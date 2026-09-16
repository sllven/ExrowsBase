"""
Factual, non-judgmental comparison between two already-researched
universities. Never ranks or declares a "winner" (section 25) — only
surfaces the facts each university has on file, side by side, each with
its own source or an honest "Not available from verified sources."
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import University, get_db

router = APIRouter(prefix="/api/compare", tags=["compare"])

COMPARE_DIMENSIONS = [
    ("location", "Location"),
    ("founded", "Founded"),
    ("students", "Students"),
    ("official_website", "Official website"),
]

IMAGE_CATEGORY_DIMENSIONS = ["campus", "dormitory", "library", "sport", "student_life", "city"]


class CompareRequest(BaseModel):
    university_id_a: str
    university_id_b: str


@router.post("")
def compare_universities(payload: CompareRequest, db: Session = Depends(get_db)) -> dict:
    a = db.get(University, payload.university_id_a)
    b = db.get(University, payload.university_id_b)
    if not a or not b:
        raise HTTPException(404, "One or both universities not found")

    def fact_map(uni: University) -> dict[str, dict]:
        return {f.key: {"value": f.value, "source_url": f.source_url} for f in uni.facts}

    facts_a, facts_b = fact_map(a), fact_map(b)

    rows = []
    for key, label in COMPARE_DIMENSIONS:
        rows.append(
            {
                "dimension": label,
                "a": facts_a.get(key, {}).get("value") or "Not available from verified sources.",
                "a_source": facts_a.get(key, {}).get("source_url"),
                "b": facts_b.get(key, {}).get("value") or "Not available from verified sources.",
                "b_source": facts_b.get(key, {}).get("source_url"),
            }
        )

    image_counts_a = {c: 0 for c in IMAGE_CATEGORY_DIMENSIONS}
    image_counts_b = {c: 0 for c in IMAGE_CATEGORY_DIMENSIONS}
    for img in a.images:
        if img.status == "verified" and img.category in image_counts_a:
            image_counts_a[img.category] += 1
    for img in b.images:
        if img.status == "verified" and img.category in image_counts_b:
            image_counts_b[img.category] += 1

    for cat in IMAGE_CATEGORY_DIMENSIONS:
        rows.append(
            {
                "dimension": f"Verified {cat.replace('_', ' ')} images",
                "a": str(image_counts_a[cat]),
                "a_source": None,
                "b": str(image_counts_b[cat]),
                "b_source": None,
            }
        )

    return {
        "university_a": {"id": a.id, "name": a.canonical_name},
        "university_b": {"id": b.id, "name": b.canonical_name},
        "rows": rows,
    }
