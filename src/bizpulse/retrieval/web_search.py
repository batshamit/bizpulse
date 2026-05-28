from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import urlparse

import httpx

from bizpulse.config import settings
from bizpulse.logging import get_logger

log = get_logger(__name__)


def _get_business_name_from_url(url: str) -> str:
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if "." not in netloc and netloc != "localhost" and not netloc.startswith("127."):
            return "business"
        parts = netloc.split(".")
        if len(parts) > 2 and parts[-2] in ("co", "com", "org", "net", "gov", "ac"):
            return parts[-3]
        if len(parts) > 1:
            return parts[-2]
        return parts[0]
    except Exception:
        return "business"


class GoogleSearchClient:
    def __init__(self, api_key: str | None = None, cse_id: str | None = None) -> None:
        self.api_key = api_key or settings.google_api_key
        self.cse_id = cse_id or settings.google_cse_id

    async def search(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        if not self.api_key or not self.cse_id:
            log.warning("google_search.disabled", reason="missing API key or CSE ID")
            return []

        url = "https://www.googleapis.com/customsearch/v1"
        params: dict[str, Any] = {
            "key": self.api_key,
            "cx": self.cse_id,
            "q": query,
            "num": num_results,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    log.warning(
                        "google_search.failed_status",
                        status_code=resp.status_code,
                        text=resp.text[:300],
                    )
                    return []

                data = resp.json()
                items = data.get("items", [])
                results = []
                for item in items:
                    results.append(
                        {
                            "title": item.get("title", ""),
                            "link": item.get("link", ""),
                            "snippet": item.get("snippet", ""),
                        }
                    )
                return results
        except Exception as exc:
            log.warning("google_search.failed_exception", error=str(exc))
            return []

    async def gather_all_perspectives(
        self,
        business_url: str,
        industry: str,
        country: str = "IN",
        state: str | None = None,
    ) -> list[dict[str, str]]:
        """Gathers latest deals, launches, budget news, scarcity/demand trends,

        and research publications from both regional and global perspectives.
        """
        if not self.api_key or not self.cse_id:
            log.info("google_search.skipped", reason="no credentials configured")
            return []

        biz_name = _get_business_name_from_url(business_url)
        location_str = country
        if state:
            location_str += f" {state}"

        # 1. Trade & Policy / Budget News
        # Restrict to government domains (PIB, ministry portals) and trade publications
        if country.upper() == "IN":
            gov_restrict = "site:*.gov.in OR site:pib.gov.in OR site:rbi.org.in"
            trade_restrict = "site:economictimes.indiatimes.com OR site:livemint.com"
        else:
            gov_restrict = "site:*.gov OR site:gov.uk OR site:europa.eu"
            trade_restrict = "site:reuters.com OR site:bloomberg.com"

        q_policy = f'"{industry}" policy change OR trade OR budget news ({gov_restrict} OR {trade_restrict}) {location_str}'

        # 2. Market Demand, Scarcity & War/Geopolitical events
        q_scarcity = f'"{industry}" scarcity OR supply chain OR demand OR war OR geopolitical impact {location_str}'

        # 3. Deals & Launches
        q_launches = f'"{biz_name}" OR "{industry}" launches OR latest deals OR partnerships OR acquisitions {location_str}'

        # 4. Domain Research & Innovations (Google Scholar + academic hubs)
        q_research = f'"{industry}" (latest research OR breakthrough OR study) (site:scholar.google.com OR site:nature.com OR site:arxiv.org)'

        queries = [
            ("policy", q_policy),
            ("scarcity", q_scarcity),
            ("launches", q_launches),
            ("research", q_research),
        ]

        log.info("google_search.gather_perspectives_start", url=business_url, industry=industry)

        # Execute searches concurrently
        tasks = [self.search(q, num_results=3) for _name, q in queries]
        search_outputs = await asyncio.gather(*tasks)

        all_results: list[dict[str, str]] = []
        seen_links = set()

        for (category, _q), results in zip(queries, search_outputs, strict=True):
            log.info("google_search.category_results", category=category, count=len(results))
            for r in results:
                link = r["link"]
                if link in seen_links:
                    continue
                seen_links.add(link)
                # Decorate snippet with metadata to aid in context grounding
                r["snippet"] = f"Category: {category.upper()}\n{r['snippet']}"
                all_results.append(r)

        return all_results
