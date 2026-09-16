"""
Wikipedia / Wikidata source adapter.

This is our primary, always-available, no-API-key-required source of
verified structural facts (canonical name, location, founding date,
official website, coordinates). We never invent any of these values:
every field is either populated from the API response or left as None,
which callers must render as "Not available from verified sources."
"""
from __future__ import annotations

import httpx
from typing import Any

from config import settings

WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_REST_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"

_HEADERS = {"User-Agent": settings.user_agent}


async def search_candidates(query: str, limit: int = 6) -> list[dict[str, Any]]:
    """Search Wikipedia for pages matching `query`, filtered to plausible
    university/college/institute articles. Returns raw candidates; the
    university_service decides how to disambiguate them."""
    params = {
        "action": "query",
        "list": "search",
        "srsearch": f"{query} university OR college OR institute",
        "format": "json",
        "srlimit": str(limit * 2),
    }
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        resp = await client.get(WIKIPEDIA_API, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("query", {}).get("search", []):
        title = item.get("title", "")
        snippet = item.get("snippet", "")
        results.append({"title": title, "snippet": snippet, "pageid": item.get("pageid")})

    # Keep only entries that look like an educational institution, unless
    # nothing matches that filter (better an unfiltered list than none).
    edu_keywords = (
        "university", "college", "institute", "polytechnic", "academy",
        "school of", "conservatory",
    )
    filtered = [r for r in results if any(k in r["title"].lower() for k in edu_keywords)]
    return (filtered or results)[:limit]


async def get_summary(title: str) -> dict[str, Any] | None:
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        resp = await client.get(WIKIPEDIA_REST_SUMMARY.format(title=title.replace(" ", "_")))
        if resp.status_code != 200:
            return None
        data = resp.json()

    if data.get("type") == "disambiguation":
        return {"disambiguation": True, "title": data.get("title")}

    coords = data.get("coordinates") or {}
    return {
        "disambiguation": False,
        "title": data.get("title"),
        "description": data.get("description"),
        "extract": data.get("extract"),
        "wikipedia_url": data.get("content_urls", {}).get("desktop", {}).get("page"),
        "thumbnail": (data.get("thumbnail") or {}).get("source"),
        "latitude": coords.get("lat"),
        "longitude": coords.get("lon"),
        "pageid": data.get("pageid"),
    }


async def get_wikidata_facts(wikipedia_title: str) -> dict[str, Any]:
    """Pull structured, sourced facts from Wikidata: official website,
    inception/founding date, country, city, student count if present.
    Returns {} if the page has no linked Wikidata item — never fabricated.
    """
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        # Step 1: find the Wikidata QID linked to this Wikipedia article.
        props_resp = await client.get(
            WIKIPEDIA_API,
            params={
                "action": "query",
                "prop": "pageprops",
                "titles": wikipedia_title,
                "format": "json",
            },
        )
        props_resp.raise_for_status()
        pages = props_resp.json().get("query", {}).get("pages", {})
        qid = None
        for page in pages.values():
            qid = (page.get("pageprops") or {}).get("wikibase_item")
        if not qid:
            return {}

        # Step 2: fetch the entity and pull the properties we care about.
        entity_resp = await client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": qid,
                "format": "json",
                "props": "claims|labels",
                "languages": "en",
            },
        )
        entity_resp.raise_for_status()
        entity = entity_resp.json().get("entities", {}).get(qid, {})
        claims = entity.get("claims", {})

    def _first_value(prop: str) -> Any | None:
        vals = claims.get(prop)
        if not vals:
            return None
        try:
            return vals[0]["mainsnak"]["datavalue"]["value"]
        except (KeyError, IndexError):
            return None

    official_website = _first_value("P856")  # official website
    inception = _first_value("P571")  # inception / founding date
    students = _first_value("P2196")  # students count
    country_ref = _first_value("P17")  # country (entity reference)
    location_ref = _first_value("P131")  # administrative location (usually city)

    founded_year = None
    if isinstance(inception, dict):
        time_str = inception.get("time", "")
        # Wikidata time format: "+1209-01-01T00:00:00Z"
        digits = time_str.lstrip("+-")
        if len(digits) >= 4:
            founded_year = digits[:4]

    entity_qids = [
        ref["id"] for ref in (country_ref, location_ref) if isinstance(ref, dict) and ref.get("id")
    ]
    labels = await _fetch_labels(entity_qids) if entity_qids else {}

    return {
        "wikidata_id": qid,
        "official_website": official_website if isinstance(official_website, str) else None,
        "founded": founded_year,
        "students_count": students.get("amount", "").lstrip("+") if isinstance(students, dict) else None,
        "country": labels.get(country_ref["id"]) if isinstance(country_ref, dict) else None,
        "city": labels.get(location_ref["id"]) if isinstance(location_ref, dict) else None,
    }


async def _fetch_labels(qids: list[str]) -> dict[str, str]:
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        resp = await client.get(
            WIKIDATA_API,
            params={
                "action": "wbgetentities",
                "ids": "|".join(qids),
                "format": "json",
                "props": "labels",
                "languages": "en",
            },
        )
        resp.raise_for_status()
        entities = resp.json().get("entities", {})
    return {
        qid: (entity.get("labels", {}).get("en", {}) or {}).get("value")
        for qid, entity in entities.items()
    }
