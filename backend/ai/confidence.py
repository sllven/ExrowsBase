"""
Confidence scoring engine.

Combines several independently-computed signals into one final score via a
fixed, documented weighted average — never a random or LLM-guessed number.
Each signal is 0-100; missing signals are excluded from the average (rather
than assumed to be zero or full marks) and the explanation always states
which signals were actually evaluated.

Weights (documented in README methodology section too):
    source_trust        0.35   domain reputation (official > wikimedia/wikipedia > other)
    entity_match         0.25   does the source text actually name this university?
    category_confidence  0.20   how confidently was the image categorized
    metadata_completeness 0.10  license / date / resolution present
    visual_signal        0.10   only included if a vision/embedding signal exists
"""
from __future__ import annotations

from dataclasses import dataclass

WEIGHTS = {
    "source_trust": 0.35,
    "entity_match": 0.25,
    "category_confidence": 0.20,
    "metadata_completeness": 0.10,
    "visual_signal": 0.10,
}


@dataclass
class Signal:
    name: str
    label: str
    score: float  # 0-100
    detail: str


def combine(signals: list[Signal]) -> tuple[int, list[dict]]:
    present = {s.name: s for s in signals if s.score is not None}
    if not present:
        return 0, []

    total_weight = sum(WEIGHTS.get(name, 0.0) for name in present)
    if total_weight == 0:
        # Signals with no configured weight: simple average fallback.
        avg = sum(s.score for s in present.values()) / len(present)
        final = round(avg)
    else:
        weighted = sum(WEIGHTS.get(name, 0.0) * s.score for name, s in present.items())
        final = round(weighted / total_weight)

    breakdown = [
        {"signal": s.label, "score": round(s.score), "detail": s.detail} for s in present.values()
    ]
    return max(0, min(100, final)), breakdown


def label_for_score(score: int, thresholds: dict) -> str:
    if score >= thresholds["threshold_highly_verified"]:
        return "Highly verified"
    if score >= thresholds["threshold_verified"]:
        return "Verified"
    if score >= thresholds["threshold_limited_evidence"]:
        return "Limited evidence"
    return "Unverified"
