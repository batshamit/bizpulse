"""IndustryPack — typed YAML config that customizes the pipeline per vertical."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import yaml
from pydantic import Field, field_validator

from bizpulse.models.common import SUPPORTED_INDUSTRIES, StrictModel

INDUSTRIES_DIR = Path(__file__).resolve().parents[3] / "industries"


class IndustryOntology(StrictModel):
    entities: list[str] = Field(min_length=1)
    regulations: list[str] = Field(default_factory=list)
    metrics: list[str] = Field(default_factory=list)


class IndustryPack(StrictModel):
    """Loaded from `industries/<slug>.yaml`. The Strategist injects fields from
    this pack at prompt-build time; the loader/eval harness uses
    `golden_eval_seeds` to pick test files.
    """

    slug: Annotated[str, Field(min_length=1)]
    name: Annotated[str, Field(min_length=1)]
    description: Annotated[str, Field(min_length=1)]
    ontology: IndustryOntology
    competitor_seeds: list[str] = Field(default_factory=list)
    channel_weights: dict[str, float] = Field(default_factory=dict)
    content_pillars: list[str] = Field(default_factory=list)
    prompt_addendum: str = Field(default="")
    golden_eval_seeds: list[str] = Field(default_factory=list)

    @field_validator("slug")
    @classmethod
    def _slug_supported(cls, v: str) -> str:
        if v not in SUPPORTED_INDUSTRIES:
            msg = f"unsupported industry slug {v!r}; expected one of {SUPPORTED_INDUSTRIES}"
            raise ValueError(msg)
        return v

    @field_validator("channel_weights")
    @classmethod
    def _weights_in_unit_range(cls, v: dict[str, float]) -> dict[str, float]:
        bad = {ch: w for ch, w in v.items() if not 0.0 <= w <= 1.0}
        if bad:
            raise ValueError(f"channel_weights must be in [0,1]; got {bad}")
        return v


def load_industry(slug: str, root: Path | None = None) -> IndustryPack:
    """Load and validate an industry pack from `industries/<slug>.yaml`."""
    base = root or INDUSTRIES_DIR
    path = base / f"{slug}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"industry pack not found: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return IndustryPack.model_validate(raw)


def load_all_industries(root: Path | None = None) -> dict[str, IndustryPack]:
    return {slug: load_industry(slug, root=root) for slug in SUPPORTED_INDUSTRIES}
