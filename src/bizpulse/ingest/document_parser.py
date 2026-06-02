"""Parse uploaded reference documents into plain text.

Supported types (auto-detected from content_type, with filename extension
as a fallback):
  text/plain         .txt, .log, .csv
  text/markdown      .md
  text/html          .html, .htm    (trafilatura extracts main content)
  application/pdf    .pdf            (pypdf reads page by page)
  application/vnd.openxmlformats-officedocument.wordprocessingml.document
                     .docx           (docx2txt extracts text)
"""

from __future__ import annotations

import hashlib
import re
from io import BytesIO
from pathlib import Path

from bizpulse.logging import get_logger

log = get_logger(__name__)


class UnsupportedDocumentTypeError(ValueError):
    """Raised when an upload's content_type / filename isn't one we can parse."""


# Map content_type → parser fn name (resolved at parse time so optional deps
# don't break imports). Filename extension fallbacks below.
_CONTENT_TYPE_PARSERS = {
    "text/plain": "_parse_plain",
    "text/csv": "_parse_plain",
    "text/markdown": "_parse_plain",
    "text/html": "_parse_html",
    "application/xhtml+xml": "_parse_html",
    "application/pdf": "_parse_pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "_parse_docx",
}
_EXT_FALLBACK = {
    ".txt": "text/plain",
    ".log": "text/plain",
    ".csv": "text/plain",
    ".md":  "text/markdown",
    ".markdown": "text/markdown",
    ".html": "text/html",
    ".htm":  "text/html",
    ".pdf":  "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}

MAX_DOC_BYTES = 100 * 1024 * 1024  # 100 MB — covers larger PDFs and documents


def detect_content_type(filename: str, declared: str | None) -> str:
    """Pick a content_type for the upload. Prefer the declared type if it's
    one we support; fall back to the filename extension; else raise."""
    if declared and declared.lower() in _CONTENT_TYPE_PARSERS:
        return declared.lower()
    ext = Path(filename).suffix.lower()
    if ext in _EXT_FALLBACK:
        return _EXT_FALLBACK[ext]
    raise UnsupportedDocumentTypeError(
        f"Unsupported document type: declared={declared!r}, filename={filename!r}. "
        f"Supported: {sorted(_EXT_FALLBACK.keys())}"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_document(*, data: bytes, content_type: str) -> str:
    """Parse the bytes into plain text. Returns empty string for empty docs."""
    if not data:
        return ""
    if len(data) > MAX_DOC_BYTES:
        raise ValueError(f"Document too large: {len(data)} bytes (max {MAX_DOC_BYTES})")
    fn_name = _CONTENT_TYPE_PARSERS.get(content_type)
    if fn_name is None:
        raise UnsupportedDocumentTypeError(f"No parser for content_type={content_type!r}")
    fn = globals()[fn_name]
    return fn(data)


# ---- per-type parsers ---------------------------------------------------

def _parse_plain(data: bytes) -> str:
    """Plain text / markdown / CSV — UTF-8 with utf-8-sig fallback."""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(enc).strip()
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace").strip()


def _parse_html(data: bytes) -> str:
    text = _parse_plain(data)
    try:
        import trafilatura  # type: ignore[import-not-found]
        out = trafilatura.extract(text, include_comments=False, include_tables=True)
        if out and out.strip():
            return out.strip()
    except ImportError:
        pass
    # Fallback strip
    txt = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    txt = re.sub(r"<style.*?</style>",  " ", txt,  flags=re.S | re.I)
    txt = re.sub(r"<[^>]+>", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def _parse_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]
    except ImportError as exc:
        raise UnsupportedDocumentTypeError(
            "PDF parsing requires `pypdf`; install via `uv pip install pypdf` "
            "or `pip install pypdf`."
        ) from exc
    reader = PdfReader(BytesIO(data))
    pages_text: list[str] = []
    for i, page in enumerate(reader.pages):
        try:
            t = page.extract_text() or ""
        except Exception as exc:
            log.warning("pdf.page_parse_failed", page=i, error=str(exc)[:200])
            continue
        if t.strip():
            pages_text.append(t.strip())
    return "\n\n".join(pages_text)


def _parse_docx(data: bytes) -> str:
    try:
        import docx2txt  # type: ignore[import-not-found]
    except ImportError as exc:
        raise UnsupportedDocumentTypeError(
            "DOCX parsing requires `docx2txt`; install via `uv pip install docx2txt`."
        ) from exc
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
        tf.write(data)
        tmp_path = tf.name
    try:
        return (docx2txt.process(tmp_path) or "").strip()
    finally:
        try:
            Path(tmp_path).unlink()
        except Exception:
            pass
