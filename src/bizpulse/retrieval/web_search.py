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


def simplify_query(query: str) -> str:
    import re
    # Remove parenthesized site blocks like (site:*.gov.in OR site:livemint.com)
    q = re.sub(r'\(site:[^)]+\)', '', query)
    # Remove individual site filters
    q = re.sub(r'site:\S+', '', q)
    # Remove OR operators
    q = q.replace(' OR ', ' ')
    # Remove quotes and parentheses
    q = q.replace('"', '').replace('(', '').replace(')', '')
    # Remove multiple spaces
    q = re.sub(r'\s+', ' ', q).strip()
    return q


def relax_query(query: str) -> str:
    # Relax a query to make it very broad if more specific forms yield 0 results.
    q = simplify_query(query)
    words = q.split()
    if len(words) <= 4:
        return q
    # Keep the first 3 words of the query
    relaxed_words = words[:3]
    # Keep country/location specifier if it was there at the end
    if words[-1] in ("IN", "US", "UK", "global") and words[-1] not in relaxed_words:
        relaxed_words.append(words[-1])
    return " ".join(relaxed_words)


class GoogleSearchClient:
    def __init__(self, api_key: str | None = None, cse_id: str | None = None, allow_fallback: bool = True) -> None:
        self.api_key = api_key or settings.google_api_key
        self.cse_id = cse_id or settings.google_cse_id
        self.allow_fallback = allow_fallback

    async def search(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        results = []
        if self.api_key and self.cse_id:
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
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("items", [])
                        for item in items:
                            results.append(
                                {
                                    "title": item.get("title", ""),
                                    "link": item.get("link", ""),
                                    "snippet": item.get("snippet", ""),
                                }
                            )
                        if results:
                            log.info("google_search.success", count=len(results))
                            return results
                    else:
                        log.warning(
                            "google_search.failed_status",
                            status_code=resp.status_code,
                            text=resp.text[:300],
                        )
            except Exception as exc:
                log.warning("google_search.failed_exception", error=str(exc))

        # Layered fallbacks if Google search is disabled, failed, or returned empty results
        if not self.allow_fallback:
            log.info("google_search.fallback_disabled")
            return []
        log.info("google_search.trigger_fallback", query=query)
        
        # 1. Try Yahoo first (highly stable and unblocked)
        results = await self._yahoo_search_fallback(query, num_results)
        if results:
            return results
            
        # 2. Try DuckDuckGo second as secondary fallback
        results = await self._duckduckgo_search_fallback(query, num_results)
        if results:
            return results

        # 3. Defensive query relaxation retry (ensures we collect data under all conditions)
        relaxed = relax_query(query)
        if relaxed != simplify_query(query):
            log.info("google_search.relaxing_query", original=query, relaxed=relaxed)
            results = await self._yahoo_search_fallback(relaxed, num_results)
            if results:
                return results
            return await self._duckduckgo_search_fallback(relaxed, num_results)

        return []

    async def _yahoo_search_fallback(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        import re
        from urllib.parse import unquote
        simplified = simplify_query(query)
        log.info("yahoo_search_fallback.start", query=simplified)
        url = "https://search.yahoo.com/search"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        params = {"q": simplified}
        try:
            from bs4 import BeautifulSoup
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code != 200:
                    log.warning("yahoo_search_fallback.failed_status", status_code=resp.status_code)
                    return []
                
                soup = BeautifulSoup(resp.text, "html.parser")
                results = []
                algos = soup.find_all("div", class_="algo")
                for algo in algos:
                    if len(results) >= num_results:
                        break
                    comp_title = algo.find("div", class_="compTitle")
                    if not comp_title:
                        continue
                    a = comp_title.find("a")
                    if not a:
                        continue
                    href = a.get("href")
                    
                    # Extract title from h3 to get clean text
                    h3 = a.find("h3")
                    if h3:
                        title = h3.get_text(strip=True)
                    else:
                        title = a.get_text(strip=True)
                    
                    # Extract original URL from RU parameter
                    link = href
                    if href and "/RU=" in href:
                        match = re.search(r'/RU=([^/]+)', href)
                        if match:
                            link = unquote(match.group(1))
                    
                    snippet = ""
                    comp_text = algo.find("div", class_="compText")
                    if comp_text:
                        snippet = comp_text.get_text(strip=True)
                    
                    if link:
                        results.append({
                            "title": title,
                            "link": link,
                            "snippet": snippet
                        })
                log.info("yahoo_search_fallback.success", count=len(results))
                return results
        except Exception as exc:
            log.warning("yahoo_search_fallback.failed_exception", error=str(exc))
            return []

    async def _duckduckgo_search_fallback(self, query: str, num_results: int = 5) -> list[dict[str, str]]:
        simplified = simplify_query(query)
        url = "https://html.duckduckgo.com/html/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        params = {"q": simplified}
        try:
            from bs4 import BeautifulSoup
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code != 200:
                    log.warning("ddg_search_fallback.failed_status", status_code=resp.status_code)
                    return []
                
                soup = BeautifulSoup(resp.text, "html.parser")
                results = []
                for result_div in soup.find_all("div", class_="result"):
                    if len(results) >= num_results:
                        break
                    title_a = result_div.find("a", class_="result__a")
                    snippet_a = result_div.find("a", class_="result__snippet")
                    if title_a:
                        title = title_a.get_text(strip=True)
                        link = title_a.get("href")
                        # Parse DDG proxy links if present
                        if link and link.startswith("/l/?"):
                            from urllib.parse import parse_qs
                            parsed_link = parse_qs(urlparse(link).query)
                            if "uddg" in parsed_link:
                                link = parsed_link["uddg"][0]
                        
                        snippet = snippet_a.get_text(strip=True) if snippet_a else ""
                        if link:
                            results.append({
                                "title": title,
                                "link": link,
                                "snippet": snippet
                            })
                log.info("ddg_search_fallback.success", count=len(results))
                return results
        except Exception as exc:
            log.warning("ddg_search_fallback.failed_exception", error=str(exc))
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
            if not self.allow_fallback:
                log.info("google_search.skipped", reason="no credentials configured")
                return []

        biz_name = _get_business_name_from_url(business_url)
        location_str = country
        if state:
            location_str += f" {state}"

        # Trade & Policy / Budget News restrictors
        if country.upper() == "IN":
            gov_restrict = "site:*.gov.in OR site:pib.gov.in OR site:rbi.org.in"
            trade_restrict = "site:economictimes.indiatimes.com OR site:livemint.com"
        else:
            gov_restrict = "site:*.gov OR site:gov.uk OR site:europa.eu"
            trade_restrict = "site:reuters.com OR site:bloomberg.com"

        # Construct 6 distinct queries aligned with the 6 reasoning subagents
        q_academic = f'"{industry}" (latest research OR breakthrough OR study OR innovation OR patent) (site:scholar.google.com OR site:nature.com OR site:arxiv.org)'
        q_policy = f'"{industry}" (policy change OR regulation OR tax reform OR budget news) ({gov_restrict} OR {trade_restrict}) {location_str}'
        q_deals = f'"{industry}" (mergers OR acquisitions OR funding round OR joint venture OR partnership OR investment) {location_str}'
        q_climate = f'"{industry}" (climate risk OR weather disruption OR ESG mandate OR sustainability OR carbon tax OR green tech) {location_str}'
        q_competitors = f'"{biz_name}" (competitors OR competitor pricing OR product launch OR product pivot OR client sentiment) {location_str}'
        q_radar = f'"{industry}" (emerging trends OR market anomalies OR disruptive signal OR localized shock) {location_str}'

        queries = [
            ("academic_research", q_academic),
            ("policy_and_politics", q_policy),
            ("business_deals", q_deals),
            ("climate_and_weather", q_climate),
            ("competitors_and_products", q_competitors),
            ("emerging_radar", q_radar),
        ]

        log.info("google_search.gather_perspectives_start", url=business_url, industry=industry)

        # Execute searches concurrently
        tasks = [self.search(q, num_results=3) for _name, q in queries]
        search_outputs = await asyncio.gather(*tasks, return_exceptions=True)

        all_results: list[dict[str, str]] = []
        seen_links = set()

        for (category, _q), results in zip(queries, search_outputs, strict=True):
            if isinstance(results, Exception):
                log.warning("google_search.perspective_failed", category=category, error=str(results))
                continue
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
