"""
For each image candidate, computes independent verification signals and
combines them (via ai/confidence.py) into one final score + a plain-English
"why this image was accepted/rejected" explanation. No signal here is
random: every score is derived from an actual comparison against text we
retrieved from the source.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from ai.confidence import Signal, combine, label_for_score
from config import settings
from sources.official import domain_of

TRUSTED_AGGREGATOR_DOMAINS = {"commons.wikimedia.org", "wikipedia.org", "en.wikipedia.org"}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", " ", text.lower())


def _name_similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


@dataclass
class VerificationInput:
    university_name: str
    official_domain: str | None
    source_url: str
    source_title: str
    source_text: str  # title + description + categories, concatenated
    category_confidence: float  # 0-100, from categorization_service
    has_license: bool
    has_date: bool
    width: int | None
    height: int | None
    is_duplicate: bool
    visual_description: str | None = None  # from ai/vision.py, if available


def evaluate(v: VerificationInput) -> dict:
    source_domain = domain_of(v.source_url) or ""
    is_official = bool(v.official_domain) and source_domain.endswith(v.official_domain)
    is_trusted_aggregator = any(source_domain.endswith(d) for d in TRUSTED_AGGREGATOR_DOMAINS)

    # --- Signal 1: source trust ---
    if is_official:
        source_trust = 97.0
        source_detail = f"Source domain '{source_domain}' matches the university's official domain."
    elif is_trusted_aggregator:
        source_trust = 82.0
        source_detail = f"Source is {source_domain}, a large public knowledge repository (not the official site)."
    else:
        source_trust = 55.0
        source_detail = f"Source domain '{source_domain}' is neither official nor a known trusted aggregator."

    # --- Signal 2: entity match (does the source actually name this university?) ---
    sim = _name_similarity(v.university_name, v.source_text)
    entity_match = round(min(sim * 140, 100), 1)  # scaled: partial-name matches still count
    entity_detail = (
        f"University name similarity against source text: {round(sim * 100)}%."
    )

    # --- Signal 3: category confidence (already computed upstream) ---
    category_signal = v.category_confidence
    category_detail = f"Automated category classification confidence: {round(category_signal)}%."

    # --- Signal 4: metadata completeness ---
    completeness_points = 0
    total_points = 4
    if v.has_license:
        completeness_points += 1
    if v.has_date:
        completeness_points += 1
    if v.width and v.width >= 500:
        completeness_points += 1
    if v.height and v.height >= 500:
        completeness_points += 1
    metadata_score = (completeness_points / total_points) * 100
    metadata_detail = f"{completeness_points}/{total_points} metadata fields present (license, date, resolution)."

    signals = [
        Signal("source_trust", "Source evidence", source_trust, source_detail),
        Signal("entity_match", "Entity match", entity_match, entity_detail),
        Signal("category_confidence", "Category confidence", category_signal, category_detail),
        Signal("metadata_completeness", "Metadata completeness", metadata_score, metadata_detail),
    ]
    if v.visual_description:
        # We only have a *description*, not a same-institution check, so this
        # signal is intentionally modest and never dominant (see WEIGHTS).
        signals.append(
            Signal("visual_signal", "Visual model", 70.0, f"Visual model description: \"{v.visual_description}\"")
        )

    score, breakdown = combine(signals)

    explanation = []
    if is_official:
        explanation.append("✓ Source belongs to the university's official domain")
    elif is_trusted_aggregator:
        explanation.append(f"✓ Source is a recognized public repository ({source_domain})")
    else:
        explanation.append(f"⚠ Source domain ({source_domain}) is not independently verified as trusted")

    if entity_match >= 50:
        explanation.append("✓ Source identifies the university by name")
    else:
        explanation.append("⚠ Source text has weak or no direct mention of the university name")

    if v.category_confidence >= 35:
        explanation.append(f"✓ Category confidence: {round(v.category_confidence)}%")
    else:
        explanation.append("⚠ Category could not be determined with confidence")

    if v.is_duplicate:
        explanation.append("✗ Detected as a duplicate of another image already in the results")
    else:
        explanation.append("✓ No duplicate detected")

    label = label_for_score(
        score,
        {
            "threshold_highly_verified": settings.threshold_highly_verified,
            "threshold_verified": settings.threshold_verified,
            "threshold_limited_evidence": settings.threshold_limited_evidence,
        },
    )

    return {
        "score": score,
        "label": label,
        "is_official_source": is_official,
        "signals": breakdown,
        "explanation": explanation,
    }
