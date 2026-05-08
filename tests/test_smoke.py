"""Smoke tests — repo wires together, FastAPI returns 200, settings load."""

from __future__ import annotations

from fastapi.testclient import TestClient

from bizpulse import __version__
from bizpulse.api.main import app
from bizpulse.config import settings


def test_version_set() -> None:
    assert __version__ == "0.1.0"


def test_settings_load_with_defaults() -> None:
    assert settings.env in {"dev", "staging", "prod"}
    assert settings.embed_dim == 1024


def test_healthz_returns_ok() -> None:
    with TestClient(app) as client:
        r = client.get("/healthz")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
