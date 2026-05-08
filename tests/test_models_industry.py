"""Tests for IndustryPack loader: every shipped YAML must validate."""

from __future__ import annotations

import pytest

from bizpulse.models import (
    SUPPORTED_INDUSTRIES,
    IndustryPack,
    load_all_industries,
    load_industry,
)


@pytest.mark.parametrize("slug", SUPPORTED_INDUSTRIES)
def test_each_shipped_industry_loads(slug: str) -> None:
    pack = load_industry(slug)
    assert isinstance(pack, IndustryPack)
    assert pack.slug == slug
    assert pack.name
    assert pack.ontology.entities, "ontology.entities cannot be empty"
    # Every shipped pack ships at least one competitor seed and one channel weight.
    assert pack.competitor_seeds, f"{slug}: competitor_seeds is empty"
    assert pack.channel_weights, f"{slug}: channel_weights is empty"


def test_load_all_industries_returns_dict() -> None:
    packs = load_all_industries()
    assert set(packs) == set(SUPPORTED_INDUSTRIES)


def test_unsupported_slug_rejected() -> None:
    with pytest.raises(FileNotFoundError):
        load_industry("does_not_exist")


def test_channel_weights_in_unit_range() -> None:
    pack = load_industry("fintech")
    for ch, w in pack.channel_weights.items():
        assert 0.0 <= w <= 1.0, f"weight out of range: {ch}={w}"
