"""Ollama client for LLM and Embeddings.

Ollama's /v1/chat/completions is OpenAI-compatible (handled by OpenAICompatClient),
but its /api/embeddings and /api/embed endpoints have unique schemas that
this client handles.
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

from bizpulse.llm.base import LLMError


class OllamaClient:
    """Ollama client for embeddings.

    Ollama supports two embedding endpoints:
    - /api/embed (newer, batch support)
    - /api/embeddings (older, single prompt)

    We prefer /api/embed.
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        model: str = "nomic-embed-text",
        timeout: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> OllamaClient:
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            # Fallback for non-context-manager use, though less efficient
            return httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch using Ollama's /api/embed."""
        if not texts:
            return []

        url = f"{self.base_url}/api/embed"
        payload = {
            "model": self.model,
            "input": texts,
        }

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self._max_retries),
            wait=wait_exponential(multiplier=0.5, max=4.0),
            retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
            reraise=True,
        ):
            with attempt:
                # Use internal client if available, else one-off
                client = self._http()
                r = await client.post(url, json=payload)

                # If /api/embed is not available (older Ollama), fall back to /api/embeddings loop
                if r.status_code == 404:
                    return await self._embed_legacy(texts)

                if r.status_code >= 500:
                    r.raise_for_status()
                if r.status_code >= 400:
                    raise LLMError(
                        f"Ollama {r.status_code} on /api/embed: {r.text[:300]}",
                        vendor="ollama",
                        model=self.model,
                        retryable=False,
                    )

                data = r.json()
                return data.get("embeddings", [])

        raise LLMError(
            "Ollama embed retries exhausted", vendor="ollama", model=self.model, retryable=False
        )

    async def _embed_legacy(self, texts: list[str]) -> list[list[float]]:
        """Fallback for older Ollama versions using /api/embeddings (no batch support)."""
        url = f"{self.base_url}/api/embeddings"
        results: list[list[float]] = []

        client = self._http()
        for text in texts:
            r = await client.post(url, json={"model": self.model, "prompt": text})
            r.raise_for_status()
            results.append(r.json()["embedding"])

        return results
