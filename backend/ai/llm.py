"""
LLM adapter used for two *optional* enrichment tasks:

  1. Turning sourced facts + the Wikipedia extract into a short, readable
     profile description (still grounded — the prompt forbids adding facts
     not present in the supplied context).
  2. Refining category classification for ambiguous image titles/descriptions.

If LLM_API_KEY is not set, both callers fall back to purely extractive /
rule-based logic (see profile_service.py and categorization_service.py).
The system is fully functional without this key — it just produces a
plainer, template-based description instead of an AI-written one, and
category confidence relies on keyword matching alone.
"""
from __future__ import annotations

import json

import httpx

from config import settings

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"


class LLMUnavailable(Exception):
    pass


async def _call(system: str, user: str, max_tokens: int = 600) -> str:
    if not settings.llm_api_key:
        raise LLMUnavailable("LLM_API_KEY not configured")

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds * 2) as client:
        resp = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": settings.llm_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.llm_model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            },
        )
        resp.raise_for_status()
        data = resp.json()

    parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    return "".join(parts).strip()


async def generate_grounded_description(university_name: str, facts: dict, extract: str | None) -> str:
    """Ask the model to write 2-4 sentences using ONLY the supplied facts
    and Wikipedia extract. Explicitly instructed not to add unsupported
    claims (numbers, dates, rankings) not present in the context."""
    system = (
        "You write short, factual university profile summaries. "
        "Use ONLY the facts and extract provided by the user. "
        "Do not invent statistics, rankings, dates, or claims not present "
        "in the given context. If the context is too thin, write a shorter, "
        "more general summary rather than filling gaps. 2-4 sentences, neutral tone."
    )
    user = json.dumps(
        {"university": university_name, "known_facts": facts, "wikipedia_extract": extract or ""},
        ensure_ascii=False,
    )
    return await _call(system, user, max_tokens=300)


async def classify_image_category(
    title: str, description: str | None, categories_text: str | None, allowed: list[str]
) -> dict:
    """Return {"category": str, "confidence": float 0-1, "reasoning": str}
    for one image, constrained to `allowed` category labels plus 'unknown'."""
    system = (
        "You classify a university photo into exactly one category from the "
        "provided list, based only on its title/description/Commons categories. "
        "If none clearly apply, respond with category 'unknown'. "
        'Respond ONLY with compact JSON: {"category": "...", "confidence": 0.0-1.0, "reasoning": "..."}'
    )
    user = json.dumps(
        {
            "allowed_categories": allowed + ["unknown"],
            "title": title,
            "description": description or "",
            "commons_categories": categories_text or "",
        },
        ensure_ascii=False,
    )
    raw = await _call(system, user, max_tokens=150)
    raw = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        parsed = json.loads(raw)
        return {
            "category": parsed.get("category", "unknown"),
            "confidence": float(parsed.get("confidence", 0.0)),
            "reasoning": parsed.get("reasoning", ""),
        }
    except (json.JSONDecodeError, TypeError, ValueError):
        return {"category": "unknown", "confidence": 0.0, "reasoning": "unparseable model response"}
