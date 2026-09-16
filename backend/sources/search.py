"""
Adapter interface for an optional third-party web search API (e.g. Bing,
Brave Search, SerpAPI, Google Programmable Search). This lets the research
pipeline pull in extra web sources/images beyond Wikipedia + Wikimedia
Commons when the operator provides SEARCH_API_KEY / SEARCH_API_PROVIDER.

Per project requirement: if no key is configured, this returns an empty
result set rather than fabricating search results. Callers must treat an
empty list as "this extra source was unavailable", not as "no results
exist" — Wikipedia/Wikimedia remain the guaranteed baseline sources.
"""
from __future__ import annotations

from typing import Any

import httpx

from config import settings

_HEADERS = {"User-Agent": settings.user_agent}


class SearchUnavailable(Exception):
    """Raised (and caught by callers) when no search provider is configured."""


async def web_search(query: str, count: int = 10) -> list[dict[str, Any]]:
    if not settings.search_api_key or settings.search_api_provider == "none":
        raise SearchUnavailable("No SEARCH_API_KEY / SEARCH_API_PROVIDER configured")

    provider = settings.search_api_provider.lower()
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        if provider == "brave":
            resp = await client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": count},
                headers={**_HEADERS, "X-Subscription-Token": settings.search_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"title": r.get("title"), "url": r.get("url"), "snippet": r.get("description")}
                for r in data.get("web", {}).get("results", [])
            ]

        if provider == "bing":
            resp = await client.get(
                "https://api.bing.microsoft.com/v7.0/search",
                params={"q": query, "count": count},
                headers={**_HEADERS, "Ocp-Apim-Subscription-Key": settings.search_api_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                {"title": r.get("name"), "url": r.get("url"), "snippet": r.get("snippet")}
                for r in data.get("webPages", {}).get("value", [])
            ]

        raise SearchUnavailable(f"Unknown SEARCH_API_PROVIDER '{settings.search_api_provider}'")
