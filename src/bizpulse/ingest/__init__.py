"""Ingestion pipeline: crawl → extract → chunk → embed → upsert."""

from __future__ import annotations

from bizpulse.ingest.chunker import chunk_artifact

__all__ = ["chunk_artifact"]
