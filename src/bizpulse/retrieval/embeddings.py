"""TEI (Text Embeddings Inference) client + Gemini embedder.

Wraps the OpenAI-compatible / TEI-native HTTP API for embed + rerank. Also
provides `GeminiEmbedder` for use when TEI isn't running locally — Gemini
text-embedding-004 has a free tier and 768-dim vectors.

Failure handling: tenacity retries on 5xx and transport errors. 4xx fail fast.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bizpulse.config import settings
from bizpulse.logging import get_logger

log = get_logger(__name__)


class TEIError(RuntimeError):
    """Raised when a TEI HTTP call fails after retries."""


class TEIEmbedder:
    """Async client for a TEI dense-embeddings endpoint.

    Typical use:
        async with TEIEmbedder() as embed:
            vectors = await embed.embed(["text 1", "text 2"])
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = (base_url or settings.embed_base_url).rstrip("/")
        self.model = model or settings.embed_model
        self._client: httpx.AsyncClient | None = None
        self._timeout = timeout
        self._max_retries = max_retries

    async def __aenter__(self) -> TEIEmbedder:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def health(self) -> bool:
        try:
            r = await self._http().get(f"{self.base_url}/health")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch. Returns one vector per input, in the same order."""
        if not texts:
            return []

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, max=4.0),
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.HTTPStatusError)
            ),
            reraise=True,
        ):
            with attempt:
                r = await self._http().post(
                    f"{self.base_url}/embed",
                    json={"inputs": texts},
                )
                if r.status_code >= 500:
                    r.raise_for_status()
                if r.status_code >= 400:
                    raise TEIError(
                        f"TEI {r.status_code} on /embed: {r.text[:300]}"
                    )
                return r.json()
        raise TEIError("TEI embed retries exhausted")  # pragma: no cover

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("TEIEmbedder must be used as async context manager")
        return self._client


class TEIReranker(TEIEmbedder):
    """Async client for a TEI cross-encoder reranker endpoint."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        super().__init__(
            base_url=base_url or settings.rerank_base_url,
            model=model or settings.rerank_model,
            timeout=timeout,
            max_retries=max_retries,
        )

    async def rerank(
        self, query: str, texts: list[str], top_n: int | None = None
    ) -> list[tuple[int, float]]:
        """Score (query, text_i) pairs. Returns (index, score) sorted desc."""
        if not texts:
            return []

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, max=4.0),
            retry=retry_if_exception_type(
                (httpx.TransportError, httpx.HTTPStatusError)
            ),
            reraise=True,
        ):
            with attempt:
                payload: dict[str, Any] = {"query": query, "texts": texts}
                if top_n is not None:
                    payload["top_n"] = top_n
                r = await self._http().post(
                    f"{self.base_url}/rerank", json=payload
                )
                if r.status_code >= 500:
                    r.raise_for_status()
                if r.status_code >= 400:
                    raise TEIError(
                        f"TEI {r.status_code} on /rerank: {r.text[:300]}"
                    )
                # TEI returns: [{"index": i, "score": s}, ...] sorted desc
                data = r.json()
                return [(item["index"], item["score"]) for item in data]
        raise TEIError("TEI rerank retries exhausted")  # pragma: no cover


# --- Gemini embedder ------------------------------------------------------

class GeminiEmbedder:
    """Async embedder using Google AI Studio's `gemini-embedding-001`.

    The model is Matryoshka-trained: it natively supports 768 / 1536 / 3072
    output dimensions via the `outputDimensionality` parameter. We default
    to 768 to keep Qdrant storage compact and search latency low; bump to
    1536 or 3072 if recall@10 evals show it pays off.

    Free-tier-friendly. Used when TEI isn't running locally — common for
    portfolio demos where a GPU isn't available.

    Note: the older `text-embedding-004` returns 404 on v1beta as of mid-2026.
    Override `model_name=` if Google ships a new identifier."""

    model = "gemini-embedding-001"

    def __init__(
        self,
        model_name: str = "gemini-embedding-001",
        api_key: str | None = None,
        timeout: float = 30.0,
        max_retries: int = 3,
        batch_size: int = 50,
        output_dim: int = 768,
    ) -> None:
        key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError(
                "GeminiEmbedder needs GOOGLE_API_KEY (or GEMINI_API_KEY) in env"
            )
        if output_dim not in (768, 1536, 3072):
            raise ValueError(
                f"output_dim must be 768, 1536, or 3072 (Matryoshka tiers); got {output_dim}"
            )
        self._key = key
        self._model_name = model_name
        self._timeout = timeout
        self._max_retries = max_retries
        self._batch_size = batch_size
        self._output_dim = output_dim
        self.embed_dim = output_dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            batch = texts[i : i + self._batch_size]
            out.extend(await self._embed_batch(batch))
        return out

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/"
            f"models/{self._model_name}:batchEmbedContents?key={self._key}"
        )
        payload = {
            "requests": [
                {
                    "model": f"models/{self._model_name}",
                    "content": {"parts": [{"text": t}]},
                    "outputDimensionality": self._output_dim,
                }
                for t in texts
            ]
        }

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, max=4.0),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    r = await client.post(url, json=payload)
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    r.raise_for_status()
                if r.status_code >= 400:
                    raise TEIError(
                        f"gemini embeddings {r.status_code}: {r.text[:200]}"
                    )
                data = r.json()
                return [e["values"] for e in data.get("embeddings", [])]
        raise TEIError("Gemini embed retries exhausted")  # pragma: no cover
