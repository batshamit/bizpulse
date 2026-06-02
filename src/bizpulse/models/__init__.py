"""Pydantic schemas — the typed contracts every pipeline stage uses.

Importing from `bizpulse.models` re-exports the most-used types so callers
write `from bizpulse.models import Chunk, Citation, MarketingStrategy` rather
than reaching into submodules.
"""

from __future__ import annotations

from bizpulse.models.agents import (
    AgentInput,
    AgentName,
    AgentOutput,
    AgentStatus,
    AgentTrace,
)
from bizpulse.models.citations import Citation
from bizpulse.models.common import (
    SUPPORTED_INDUSTRIES,
    Business,
    BusinessId,
    ChunkId,
    RunId,
    StrictModel,
    Tenant,
    TenantId,
    slugify,
    utcnow,
)
from bizpulse.models.industry import (
    INDUSTRIES_DIR,
    IndustryOntology,
    IndustryPack,
    load_all_industries,
    load_industry,
)
from bizpulse.models.ingest import (
    Chunk,
    ChunkMetadata,
    EmbeddedChunk,
    RawArtifact,
    SourceType,
)
from bizpulse.models.research import (
    AcademicPaper,
    AcademicTrackerOutput,
    BusinessDeal,
    CompetitiveIntelligenceOutput,
    DailyResearchReport,
    EnvironmentalMonitorOutput,
    MarketScoutOutput,
    PolicyAnalystOutput,
    RadarOutput,
)
from bizpulse.models.retrieval import (
    RetrievalMethod,
    RetrievalQuery,
    RetrievalResult,
    RetrievedChunk,
)
from bizpulse.models.run import RunRecord, RunStatus
from bizpulse.models.strategy import (
    AudienceAnalysis,
    AudiencePersona,
    BrandAnalysis,
    ChannelSlug,
    CompetitiveLandscape,
    Competitor,
    ContentAudit,
    ContentAuditFinding,
    MarketingStrategy,
    Priority,
    Recommendation,
)

__all__ = [
    "INDUSTRIES_DIR",
    "SUPPORTED_INDUSTRIES",
    "AcademicTrackerOutput",
    "AgentInput",
    "AgentName",
    "AgentOutput",
    "AgentStatus",
    "AgentTrace",
    "AudienceAnalysis",
    "AudiencePersona",
    "BrandAnalysis",
    "Business",
    "BusinessId",
    "ChannelSlug",
    "Chunk",
    "ChunkId",
    "ChunkMetadata",
    "Citation",
    "CompetitiveIntelligenceOutput",
    "CompetitiveLandscape",
    "Competitor",
    "ContentAudit",
    "ContentAuditFinding",
    "DailyResearchReport",
    "EmbeddedChunk",
    "EnvironmentalMonitorOutput",
    "IndustryOntology",
    "IndustryPack",
    "MarketScoutOutput",
    "MarketingStrategy",
    "PolicyAnalystOutput",
    "Priority",
    "RadarOutput",
    "RawArtifact",
    "Recommendation",
    "RetrievalMethod",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievedChunk",
    "RunId",
    "RunRecord",
    "RunStatus",
    "SourceType",
    "StrictModel",
    "Tenant",
    "TenantId",
    "load_all_industries",
    "load_industry",
    "slugify",
    "utcnow",
]
