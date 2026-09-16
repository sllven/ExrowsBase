"""
Resolves a free-text query ("MIT", "Oxford", "Nazarbayev University") into
a canonical university, or a disambiguation list when the query is
ambiguous. Never guesses silently among multiple plausible matches.
"""
from __future__ import annotations

from typing import Any

from sources import official, wikipedia as wiki

# A handful of very common abbreviations. This is NOT a hardcoded database of
# university profiles — it only maps an abbreviation to the search string we
# feed into the real, live Wikipedia search, exactly like a human would type
# the full name instead of the acronym. Every other field still comes from
# the live pipeline.
_KNOWN_ABBREVIATIONS = {
    "mit": "Massachusetts Institute of Technology",
    "nu": "Nazarbayev University",
    "eth": "ETH Zurich",
    "ucla": "University of California, Los Angeles",
    "nyu": "New York University",
    "lse": "London School of Economics",
    "caltech": "California Institute of Technology",
}


async def identify(query: str) -> dict[str, Any]:
    """Returns one of:
    {"status": "not_found"}
    {"status": "ambiguous", "candidates": [...]}
    {"status": "found", "university": {...}}
    """
    cleaned = query.strip()
    if not cleaned:
        return {"status": "not_found"}

    expanded = _KNOWN_ABBREVIATIONS.get(cleaned.lower(), cleaned)

    candidates = await wiki.search_candidates(expanded, limit=6)
    if not candidates:
        return {"status": "not_found"}

    # If the top result is a strong, unambiguous textual match (exact or
    # near-exact title match, or only one plausible candidate returned),
    # resolve directly. Otherwise ask the user to disambiguate.
    top = candidates[0]
    exact_match = top["title"].strip().lower() == expanded.strip().lower()
    only_one = len(candidates) == 1

    if exact_match or only_one:
        resolved = await _resolve(top["title"])
        if resolved is None:
            return {"status": "not_found"}
        if resolved.get("disambiguation"):
            return {"status": "ambiguous", "candidates": candidates}
        return {"status": "found", "university": resolved}

    return {
        "status": "ambiguous",
        "candidates": [{"title": c["title"], "snippet": c["snippet"]} for c in candidates],
    }


async def resolve_title(title: str) -> dict[str, Any] | None:
    """Used once the user picks a specific candidate from the disambiguation screen."""
    return await _resolve(title)


async def _resolve(title: str) -> dict[str, Any] | None:
    summary = await wiki.get_summary(title)
    if summary is None:
        return None
    if summary.get("disambiguation"):
        return summary

    wikidata_facts = await wiki.get_wikidata_facts(summary["title"])
    official_website = wikidata_facts.get("official_website")

    official_domain_reachable = None
    if official_website:
        official_domain_reachable = await official.verify_reachable(official_website)

    # Description text from Wikipedia summary is like "public research university
    # in Cambridge, Massachusetts" — split heuristically for city/country display.
    description = summary.get("description") or ""

    return {
        "canonical_name": summary["title"],
        "short_description": description,
        "wikipedia_url": summary.get("wikipedia_url"),
        "wikipedia_extract": summary.get("extract"),
        "latitude": summary.get("latitude"),
        "longitude": summary.get("longitude"),
        "wikidata_id": wikidata_facts.get("wikidata_id"),
        "official_website": official_website,
        "official_website_reachable": official_domain_reachable,
        "founded": wikidata_facts.get("founded"),
        "students_count": wikidata_facts.get("students_count"),
        "country": wikidata_facts.get("country"),
        "city": wikidata_facts.get("city"),
    }
