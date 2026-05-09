"""TEI (Text Embeddings Inference) client.

Wraps the OpenAI-compatible / TEI-native HTTP API. The same wrapper is used in
two places: the embedder calls `/embed`, the reranker calls `/rerank`.

Failure handling: tenacity retries on 5xx and transport errors. 4xx fail fast.
"""

from __future__ import annotations

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
