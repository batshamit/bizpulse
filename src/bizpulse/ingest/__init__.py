"""Ingestion pipeline: crawl → extract → chunk → embed → upsert."""

from __future__ import annotations

from bizpulse.ingest.chunker import chunk_artifact
from bizpulse.ingest.crawler import CrawlerProtocol, PlaywrightCrawler
from bizpulse.ingest.pipeline import EmbedderProtocol, IngestionPipeline

__all__ = [
    "CrawlerProtocol",
    "EmbedderProtocol",
    "IngestionPipeline",
    "PlaywrightCrawler",
    "chunk_artifact",
]
