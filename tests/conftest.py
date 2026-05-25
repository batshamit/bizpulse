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
