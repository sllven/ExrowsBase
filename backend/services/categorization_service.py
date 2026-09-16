"""
Categorizes an image into one of the fixed categories using keyword
evidence from its title / description / Commons categories. This always
runs (no key required). If LLM_API_KEY is configured, we additionally ask
the model to classify and blend the two signals — but the rule-based score
alone is enough to produce an honest, non-random category_confidence.
"""
from __future__ import annotations

from config import settings
from ai import llm as llm_ai

CATEGORIES = [
    "campus",
    "dormitory",
    "library",
    "classroom",
    "laboratory",
    "sport",
    "student_life",
    "city",
]

_KEYWORDS: dict[str, list[str]] = {
    "campus": ["campus", "quad", "quadrangle", "main building", "aerial view", "grounds", "gate", "entrance"],
    "dormitory": ["dormitory", "dorm", "hall of residence", "residence hall", "hostel", "student housing", "accommodation"],
    "library": ["library", "reading room", "archive", "stacks"],
    "classroom": ["classroom", "lecture hall", "lecture theatre", "seminar room", "auditorium"],
    "laboratory": ["laboratory", "lab ", " lab", "research facility", "experiment"],
    "sport": ["stadium", "gym", "gymnasium", "sports", "athletics", "pool", "swimming", "playing field", "rowing", "football pitch"],
    "student_life": ["students", "graduation", "commencement", "club", "festival", "orientation", "union building", "student union"],
    "city": ["street", "city", "town", "skyline", "downtown", "market square", "old town"],
}

MIN_CONFIDENCE_TO_ASSIGN = 0.35  # below this -> "unknown", per spec section 11


def _keyword_scores(text: str) -> dict[str, float]:
    text_lower = text.lower()
    raw_scores: dict[str, int] = {}
    for cat, keywords in _KEYWORDS.items():
        hits = sum(1 for kw in keywords if kw in text_lower)
        if hits:
            raw_scores[cat] = hits

    if not raw_scores:
        return {cat: 0.0 for cat in CATEGORIES}

    total_hits = sum(raw_scores.values())
    scores = {cat: raw_scores.get(cat, 0) / total_hits for cat in CATEGORIES}
    return scores


async def categorize(title: str, description: str | None, commons_categories: str | None) -> dict:
    combined_text = " ".join(filter(None, [title, description or "", commons_categories or ""]))
    keyword_scores = _keyword_scores(combined_text)

    best_cat = max(keyword_scores, key=keyword_scores.get)
    best_score = keyword_scores[best_cat]

    method = "keyword"
    if settings.llm_api_key:
        try:
            llm_result = await llm_ai.classify_image_category(
                title, description, commons_categories, CATEGORIES
            )
            if llm_result["category"] in CATEGORIES and llm_result["confidence"] > 0:
                # Blend: average keyword evidence with model confidence when they agree;
                # if they disagree, trust whichever has stronger evidence, but never
                # silently discard the disagreement — it's reflected in a lower score.
                if llm_result["category"] == best_cat:
                    best_score = (best_score + llm_result["confidence"]) / 2
                    method = "keyword+llm"
                else:
                    # Disagreement: pick the LLM's category (richer context) but
                    # penalize confidence to reflect the uncertainty.
                    best_cat = llm_result["category"]
                    best_score = llm_result["confidence"] * 0.6
                    method = "llm_override"
        except Exception:
            pass  # fall back silently to keyword-only result

    if best_score < MIN_CONFIDENCE_TO_ASSIGN or best_cat not in CATEGORIES:
        return {
            "category": "unknown",
            "confidence": round(best_score * 100, 1),
            "breakdown": {k: round(v * 100, 1) for k, v in keyword_scores.items()},
            "method": method,
        }

    return {
        "category": best_cat,
        "confidence": round(min(best_score, 1.0) * 100, 1),
        "breakdown": {k: round(v * 100, 1) for k, v in keyword_scores.items()},
        "method": method,
    }
