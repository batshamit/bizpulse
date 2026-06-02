from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from bizpulse.api.runner_service import _fetch_google_search_artifacts
from bizpulse.models import Business
from bizpulse.retrieval.web_search import GoogleSearchClient, _get_business_name_from_url


def test_get_business_name_from_url() -> None:
    assert _get_business_name_from_url("https://www.dei.ac.in/dei/") == "dei"
    assert _get_business_name_from_url("https://example.com") == "example"
    assert _get_business_name_from_url("https://subdomain.example.co.uk") == "example"
    assert _get_business_name_from_url("http://localhost:8000") == "localhost"
    assert _get_business_name_from_url("not-a-valid-url") == "business"


@pytest.mark.asyncio
async def test_google_search_client_disabled() -> None:
    client = GoogleSearchClient(api_key=None, cse_id=None, allow_fallback=False)
    results = await client.search("test query")
    assert results == []

    perspectives = await client.gather_all_perspectives("https://example.com", "fintech")
    assert perspectives == []


@pytest.mark.asyncio
async def test_gather_all_perspectives_success() -> None:
    client = GoogleSearchClient(api_key="fake-key", cse_id="fake-cse-id")

    mock_search = AsyncMock()
    mock_search.side_effect = [
        [{"title": "Research Paper", "link": "https://scholar.google.com/study", "snippet": "Gartner study on AI"}],
        [{"title": "Policy News", "link": "https://gov.in/policy", "snippet": "New budget release"}],
        [{"title": "Deals News", "link": "https://reuters.com/deals", "snippet": "M&A deal announced"}],
        [{"title": "Climate News", "link": "https://esg.com/climate", "snippet": "Weather impact"}],
        [{"title": "Competitor News", "link": "https://market.com/competitor", "snippet": "Competitor pricing shift"}],
        [{"title": "Radar News", "link": "https://trend.com/radar", "snippet": "Emerging trends anomaly"}],
    ]

    with patch.object(client, "search", mock_search):
        results = await client.gather_all_perspectives(
            business_url="https://example.com",
            industry="fintech",
            country="IN",
            state="Maharashtra",
        )
        assert len(results) == 6
        assert results[0]["title"] == "Research Paper"
        assert "Category: ACADEMIC_RESEARCH" in results[0]["snippet"]
        assert results[1]["title"] == "Policy News"
        assert "Category: POLICY_AND_POLITICS" in results[1]["snippet"]
        assert results[2]["title"] == "Deals News"
        assert "Category: BUSINESS_DEALS" in results[2]["snippet"]
        assert results[3]["title"] == "Climate News"
        assert "Category: CLIMATE_AND_WEATHER" in results[3]["snippet"]
        assert results[4]["title"] == "Competitor News"
        assert "Category: COMPETITORS_AND_PRODUCTS" in results[4]["snippet"]
        assert results[5]["title"] == "Radar News"
        assert "Category: EMERGING_RADAR" in results[5]["snippet"]

        assert mock_search.call_count == 6
        call_args = [args[0][0] for args in mock_search.call_args_list]
        assert "scholar.google.com" in call_args[0]
        assert "gov.in" in call_args[1] or "pib.gov.in" in call_args[1]
        assert "mergers" in call_args[2] or "funding" in call_args[2]
        assert "climate" in call_args[3] or "weather" in call_args[3]
        assert "competitors" in call_args[4]
        assert "emerging" in call_args[5] or "anomalies" in call_args[5]


@pytest.mark.asyncio
async def test_fetch_google_search_artifacts() -> None:
    tenant_id = uuid4()
    business = Business(
        tenant_id=tenant_id,
        url="https://example.com",
        industry="fintech",
    )

    with patch("bizpulse.config.settings.google_api_key", "fake-key"), \
         patch("bizpulse.config.settings.google_cse_id", "fake-cse"), \
         patch("bizpulse.retrieval.web_search.GoogleSearchClient.gather_all_perspectives", new_callable=AsyncMock) as mock_gather:

        mock_gather.return_value = [
            {"title": "Policy", "link": "https://gov.in/policy", "snippet": "Category: POLICY\nText"}
        ]

        artifacts = await _fetch_google_search_artifacts(business, "IN", "Maharashtra")
        assert len(artifacts) == 1
        assert artifacts[0].source_url == "https://gov.in/policy"
        assert artifacts[0].source_type == "website_page"
        assert "Category: POLICY" in artifacts[0].extracted_text
        assert artifacts[0].tenant_id == tenant_id
        assert artifacts[0].business_id == business.id


def test_simplify_query() -> None:
    from bizpulse.retrieval.web_search import simplify_query
    q = '"real_estate" policy change (site:*.gov.in OR site:livemint.com) IN'
    assert simplify_query(q) == "real_estate policy change IN"

    q_research = '"industry" (latest research OR breakthrough OR study) (site:scholar.google.com OR site:nature.com OR site:arxiv.org)'
    assert simplify_query(q_research) == "industry latest research breakthrough study"


def test_relax_query() -> None:
    from bizpulse.retrieval.web_search import relax_query
    q = "real_estate policy change trade budget news IN"
    assert relax_query(q) == "real_estate policy change IN"

    q2 = "industry latest research breakthrough study"
    assert relax_query(q2) == "industry latest research"
