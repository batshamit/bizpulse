"""Public industry / location metadata lookup."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from bizpulse.models.industry import load_all_industries

router = APIRouter(prefix="/v1/metadata", tags=["metadata"])

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
LOCATIONS_FILE = DATA_DIR / "locations.json"


def _load_locations():
    if not LOCATIONS_FILE.is_file():
        # Default seeds
        return {
            "countries": [
                {"code": "IN", "name": "India"},
                {"code": "EU", "name": "European Union"},
                {"code": "US", "name": "United States"},
                {"code": "GB", "name": "United Kingdom"},
            ],
            "states": {
                "IN": [
                    {"code": "maharashtra", "name": "Maharashtra"},
                    {"code": "karnataka", "name": "Karnataka"},
                    {"code": "tamil_nadu", "name": "Tamil Nadu"},
                    {"code": "delhi", "name": "Delhi"},
                    {"code": "uttar_pradesh", "name": "Uttar Pradesh"},
                ]
            },
        }
    with LOCATIONS_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/industries")
def list_industries() -> list[dict]:
    all_packs = load_all_industries()
    return [
        {"slug": p.slug, "name": p.name, "description": p.description} for p in all_packs.values()
    ]


@router.get("/locations")
def list_locations() -> dict:
    return _load_locations()
