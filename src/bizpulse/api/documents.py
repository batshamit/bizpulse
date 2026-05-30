"""Business reference-document upload + management endpoints.

Files (PDF/DOCX/TXT/MD/HTML, ≤20MB) are parsed to text, chunked, embedded,
and upserted into the per-tenant Qdrant collection — same collection the
URL crawler writes to. The next /analyze on this business sees them as
retrieval context alongside the crawled web pages.

Persistence:
  - `business_documents` row holds metadata (filename, size, sha256, n_chunks)
  - chunks themselves live in Qdrant, tagged with metadata.source_type='reference_doc'
    and metadata.source_url='doc://<doc_id>/<filename>' so the GUI can
    distinguish them from crawled pages in citation lists.

Dedup: (business_id, sha256) is UNIQUE — re-uploading the same file
returns 200 with the existing doc id, no re-embed.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient

from bizpulse.api.dependencies import get_store, require_tenant
from bizpulse.ingest.chunker import chunk_text
from bizpulse.ingest.document_parser import (
    MAX_DOC_BYTES,
    UnsupportedDocumentTypeError,
    detect_content_type,
    parse_document,
    sha256_bytes,
)
from bizpulse.logging import get_logger
from bizpulse.models import Chunk, ChunkMetadata, EmbeddedChunk, Tenant
from bizpulse.retrieval import TenantQdrant
from bizpulse.storage import Store

log = get_logger(__name__)

router = APIRouter(prefix="/v1/businesses/{business_id}/documents", tags=["documents"])

# Reuse runner_service's choice of embedder + qdrant dir.
_QDRANT_BASE = Path(
    os.environ.get("BIZPULSE_QDRANT_DIR", str(Path(tempfile.gettempdir()) / "bizpulse-qdrant"))
)


# --- response shapes ------------------------------------------------------

class DocumentSummary(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    n_chunks: int
    extracted_chars: int
    sha256: str
    uploaded_at: str


# --- helpers --------------------------------------------------------------

def _doc_repo_for(tenant_id, business_id: UUID) -> TenantQdrant:
    """Per-business Qdrant collection. Same path runner_service uses for the
    URL crawl — when /analyze runs for this business it'll see both."""
    qd_dir = _QDRANT_BASE / f"biz-{business_id}"
    qd_dir.mkdir(parents=True, exist_ok=True)
    return TenantQdrant(tenant_id, client=QdrantClient(path=str(qd_dir)))


def _pick_embedder():
    # Mirror runner_service's choice — Gemini if key present, else hash fallback.
    from bizpulse.api.runner_service import _pick_embedder as _live_pick_embedder
    return _live_pick_embedder()


# --- routes ---------------------------------------------------------------

@router.post(
    "",
    response_model=DocumentSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a reference document for this business",
    description=(
        "Accepts PDF / DOCX / TXT / MD / HTML up to 20 MB. The file's text "
        "is extracted, chunked, embedded, and added to the per-tenant Qdrant "
        "collection. The next /analyze for this business will see these "
        "chunks alongside the URL crawl."
    ),
)
async def upload_document(
    business_id: UUID,
    file: UploadFile = File(...),
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> DocumentSummary:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="business not found")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uploaded file is empty.",
        )
    if len(data) > MAX_DOC_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({len(data)} bytes > {MAX_DOC_BYTES} max).",
        )

    try:
        ct = detect_content_type(file.filename or "upload", file.content_type)
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))

    file_sha = sha256_bytes(data)

    # Dedup — if we've seen this exact bytes for this business, return existing.
    existing = store.find_document_by_sha(business_id, file_sha)
    if existing is not None:
        log.info("document.upload.dedup", business_id=str(business_id), sha=file_sha[:12])
        return DocumentSummary(**existing)

    try:
        text = parse_document(data=data, content_type=ct)
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Failed to parse document: {exc!s}",
        )

    extracted_chars = len(text)
    n_chunks = 0
    doc_id = uuid4()

    if text.strip():
        chunks = chunk_text(text)
        if chunks:
            embedder = _pick_embedder()
            try:
                vectors = await embedder.embed([c.text for c in chunks])
            except Exception as exc:  # noqa: BLE001
                log.warning("document.embed_failed", error=str(exc)[:200])
                vectors = []

            if vectors and len(vectors) == len(chunks):
                # Stamp metadata so retrieval / citation rendering knows
                # these came from an uploaded doc, not the URL crawl.
                stamped_chunks: list[EmbeddedChunk] = []
                source_url = f"doc://{doc_id}/{file.filename}"
                for c, v in zip(chunks, vectors):
                    meta = ChunkMetadata(
                        tenant_id=tenant.id,
                        business_id=business_id,
                        industry=biz.industry,
                        source_url=source_url,
                        source_type="reference_doc",
                        content_hash=file_sha[:32],
                    )
                    stamped = EmbeddedChunk(
                        chunk=Chunk(text=c.text, metadata=meta),
                        vector=v,
                        embed_model=getattr(embedder, "model", "unknown"),
                        embed_dim=getattr(embedder, "embed_dim", len(v)),
                    )
                    stamped_chunks.append(stamped)

                repo = _doc_repo_for(tenant.id, business_id)
                repo.ensure_collection(vector_size=stamped_chunks[0].embed_dim)
                repo.upsert(stamped_chunks)
                n_chunks = len(stamped_chunks)

    record = store.insert_document(
        id=doc_id,
        tenant_id=tenant.id,
        business_id=business_id,
        filename=file.filename or "upload",
        content_type=ct,
        size_bytes=len(data),
        n_chunks=n_chunks,
        sha256=file_sha,
        extracted_chars=extracted_chars,
    )

    log.info(
        "document.uploaded",
        business_id=str(business_id),
        doc_id=str(doc_id),
        filename=file.filename,
        n_chunks=n_chunks,
        extracted_chars=extracted_chars,
    )
    return DocumentSummary(**record)


@router.get(
    "",
    response_model=list[DocumentSummary],
    summary="List reference documents for this business",
)
def list_documents(
    business_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> list[DocumentSummary]:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="business not found")
    rows = store.list_documents(business_id)
    return [DocumentSummary(**r) for r in rows]


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a reference document and its chunks",
)
def delete_document(
    business_id: UUID,
    document_id: UUID,
    tenant: Tenant = Depends(require_tenant),
    store: Store = Depends(get_store),
) -> None:
    biz = store.get_business(business_id)
    if biz is None or biz.tenant_id != tenant.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="business not found")
    ok = store.delete_document(business_id, document_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document not found")
