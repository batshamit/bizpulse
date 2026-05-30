"""Pytest configuration and global fixtures."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_run_analysis_background():
    """Automatically mock the background run_analysis_background task
    to prevent real external API calls/crawling during test runs.
    """
    with patch(
        "bizpulse.api.businesses.run_analysis_background", new_callable=AsyncMock
    ) as mock_run:
        yield mock_run


@pytest.fixture(autouse=True)
def mock_local_services():
    """Prevent tests from hitting live local model servers (ports 8800-8803, 11434)"""
    import httpx
    original_get = httpx.get
    
    def mocked_get(url, *args, **kwargs):
        url_str = str(url)
        if any(p in url_str for p in ["8800", "8801", "8802", "8803", "11434"]):
            raise httpx.ConnectError("Simulated offline for tests")
        return original_get(url, *args, **kwargs)
        
    with patch("httpx.get", side_effect=mocked_get):
        yield
