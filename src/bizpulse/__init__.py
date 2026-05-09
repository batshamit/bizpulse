"""BizPulse — multi-agent RAG marketing-strategy platform."""

from __future__ import annotations

# Load .env into os.environ as early as possible. Pydantic Settings reads
# .env into its own fields, but anything that calls os.environ.get() directly
# (e.g., bizpulse.storage's BIZPULSE_STORE backend selector, vendor SDKs that
# look up their API keys via os.environ) needs the values process-wide.
# `override=False` means real env vars (Bitvise/systemd) win over .env.
from dotenv import load_dotenv as _load_dotenv

_load_dotenv(override=False)

__version__ = "0.1.0"

__all__ = ["__version__"]
