"""
Builds category-specific search queries and fans them out to our source
adapters (Wikimedia Commons always; optional third-party web search if
configured). Deduplicates raw candidate titles/URLs before returning them
for the image_service to download and verify.
"""
from __future__ import annotations

import asyncio
from typing import Any

from config import settings
from services.categorization_service import CATEGORIES
from sources import wikimedia, search as web_search_adapter

_CATEGORY_QUERY_TERMS = {
    "campus": ["campus", "main building", "aerial view"],
    "dormitory": ["dormitory", "student residence hall"],
    "library": ["library"],
    "classroom": ["lecture hall", "classroom"],
    "laboratory": ["laboratory", "research lab"],
    "sport": ["sports facilities", "stadium"],
    "student_life": ["student life", "campus students"],
    "city": ["city view"],
}


def build_queries(university_name: str) -> dict[str, list[str]]:
    """Returns {category: [query, ...]} — e.g. '{university} official campus'."""
    queries: dict[str, list[str]] = {}
    for category in CATEGORIES:
        terms = _CATEGORY_QUERY_TERMS[category]
        queries[category] = [f"{university_name} {term}" for term in terms]
    return queries


async def collect_commons_candidates(
    university_name: str, per_category_limit: int
) -> dict[str, list[dict[str, Any]]]:
    """For each category, search Commons and fetch imageinfo. Returns raw
    candidate dicts (not yet downloaded/verified/deduped)."""
    queries = build_queries(university_name)

    async def _for_category(category: str, qlist: list[str]) -> tuple[str, list[dict[str, Any]]]:
        seen_titles: list[str] = []
        for q in qlist:
            titles = await wikimedia.search_images(q, limit=per_category_limit)
            for t in titles:
                if t not in seen_titles:
                    seen_titles.append(t)
            if len(seen_titles) >= per_category_limit:
                break
        infos = await wikimedia.get_image_info(seen_titles[:per_category_limit])
        for info in infos:
            info["query_category"] = category
        return category, infos

    tasks = [_for_category(cat, qs) for cat, qs in queries.items()]
    results = await asyncio.gather(*tasks)
    return dict(results)


async def collect_web_sources(university_name: str) -> list[dict[str, Any]]:
    """Optional supplementary web sources via the third-party search adapter.
    Returns [] (not fabricated results) if no provider is configured."""
    try:
        results = await web_search_adapter.web_search(f"{university_name} university", count=8)
        return results
    except web_search_adapter.SearchUnavailable:
        return []
