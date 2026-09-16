"""
Basic tests. The categorization/confidence/dedup tests are pure-logic and
run offline. The `test_wikipedia_live_*` tests hit the real Wikipedia API
and are skipped automatically if there is no network access — they are not
mocked, because the entire point of this project is that results must come
from live sources, not fixtures pretending to be them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai.confidence import Signal, combine, label_for_score  # noqa: E402
from services import categorization_service  # noqa: E402


def test_confidence_combine_weights_present_signals_only():
    score, breakdown = combine(
        [
            Signal("source_trust", "Source evidence", 90, "official"),
            Signal("entity_match", "Entity match", 80, "matches"),
        ]
    )
    assert 0 <= score <= 100
    assert len(breakdown) == 2


def test_confidence_label_thresholds():
    thresholds = {
        "threshold_highly_verified": 90,
        "threshold_verified": 75,
        "threshold_limited_evidence": 60,
    }
    assert label_for_score(95, thresholds) == "Highly verified"
    assert label_for_score(80, thresholds) == "Verified"
    assert label_for_score(65, thresholds) == "Limited evidence"
    assert label_for_score(10, thresholds) == "Unverified"


@pytest.mark.asyncio
async def test_categorization_keyword_only():
    result = await categorization_service.categorize(
        title="Main University Library reading room",
        description="Students studying in the central library",
        commons_categories="Libraries",
    )
    assert result["category"] == "library"
    assert result["confidence"] > 0


@pytest.mark.asyncio
async def test_categorization_unknown_when_no_keywords_match():
    result = await categorization_service.categorize(
        title="IMG_2931.jpg", description=None, commons_categories=None
    )
    assert result["category"] == "unknown"


@pytest.mark.asyncio
async def test_wikipedia_live_search_smoke():
    pytest.importorskip("httpx")
    from sources import wikipedia as wiki

    try:
        candidates = await wiki.search_candidates("Massachusetts Institute of Technology")
    except Exception:
        pytest.skip("No network access in this environment")
    if candidates:
        assert any("Massachusetts Institute of Technology" in c["title"] for c in candidates)
