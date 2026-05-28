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
    client = GoogleSearchClient(api_key=None, cse_id=None)
    results = await client.search("test query")
    assert results == []

    perspectives = await client.gather_all_perspectives("https://example.com", "fintech")
    assert perspectives == []


@pytest.mark.asyncio
async def test_gather_all_perspectives_success() -> None:
    client = GoogleSearchClient(api_key="fake-key", cse_id="fake-cse-id")

    mock_search = AsyncMock()
    mock_search.side_effect = [
        [{"title": "Policy News", "link": "https://gov.in/policy", "snippet": "New budget release"}],
        [{"title": "Scarcity News", "link": "https://reuters.com/scarcity", "snippet": "Trade issues"}],
        [{"title": "Launches News", "link": "https://economictimes.com/launches", "snippet": "Product X launched"}],
        [{"title": "Research Paper", "link": "https://scholar.google.com/study", "snippet": "Gartner study on AI"}],
    ]

    with patch.object(client, "search", mock_search):
        results = await client.gather_all_perspectives(
            business_url="https://example.com",
            industry="fintech",
            country="IN",
            state="Maharashtra",
        )
        assert len(results) == 4
        assert results[0]["title"] == "Policy News"
        assert "Category: POLICY" in results[0]["snippet"]
        assert results[1]["title"] == "Scarcity News"
        assert "Category: SCARCITY" in results[1]["snippet"]
        assert results[2]["title"] == "Launches News"
        assert "Category: LAUNCHES" in results[2]["snippet"]
        assert results[3]["title"] == "Research Paper"
        assert "Category: RESEARCH" in results[3]["snippet"]

        assert mock_search.call_count == 4
        call_args = [args[0][0] for args in mock_search.call_args_list]
        assert "gov.in" in call_args[0] or "pib.gov.in" in call_args[0]
        assert "scarcity" in call_args[1]
        assert "example" in call_args[2]
        assert "scholar.google.com" in call_args[3]


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
