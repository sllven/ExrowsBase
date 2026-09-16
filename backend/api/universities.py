from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import University, UniversityImage, UniversitySource, get_db
from services import university_service

router = APIRouter(prefix="/api/universities", tags=["universities"])


class SearchRequest(BaseModel):
    query: str


class SearchCandidate(BaseModel):
    title: str
    snippet: str | None = None


class SearchResponse(BaseModel):
    status: str  # found | ambiguous | not_found
    university: dict | None = None
    candidates: list[SearchCandidate] | None = None
    message: str | None = None


@router.post("/search", response_model=SearchResponse)
async def search_university(payload: SearchRequest) -> SearchResponse:
    result = await university_service.identify(payload.query)

    if result["status"] == "not_found":
        return SearchResponse(
            status="not_found",
            message="University not found. Try checking the spelling or entering the official university name.",
        )

    if result["status"] == "ambiguous":
        return SearchResponse(
            status="ambiguous",
            candidates=[SearchCandidate(**c) for c in result["candidates"]],
            message="Which university did you mean?",
        )

    return SearchResponse(status="found", university=result["university"])


@router.get("/{university_id}")
def get_university(university_id: str, db: Session = Depends(get_db)) -> dict:
    uni = db.get(University, university_id)
    if not uni:
        raise HTTPException(404, "University not found")
    return _serialize_university(uni)


@router.get("/{university_id}/images")
def get_university_images(
    university_id: str,
    category: str | None = Query(default=None),
    verified_only: bool = Query(default=True),
    include_uncertain: bool = Query(default=False),
    db: Session = Depends(get_db),
) -> dict:
    uni = db.get(University, university_id)
    if not uni:
        raise HTTPException(404, "University not found")

    q = db.query(UniversityImage).filter(UniversityImage.university_id == university_id)
    if category and category != "all":
        q = q.filter(UniversityImage.category == category)

    if include_uncertain:
        q = q.filter(UniversityImage.status.in_(["verified", "rejected_low_confidence"]))
    elif verified_only:
        q = q.filter(UniversityImage.status == "verified")

    images = q.order_by(UniversityImage.confidence_score.desc()).all()
    uncertain_count = (
        db.query(UniversityImage)
        .filter(UniversityImage.university_id == university_id, UniversityImage.status == "rejected_low_confidence")
        .count()
    )
    return {
        "images": [_serialize_image(img) for img in images],
        "uncertain_count": uncertain_count,
    }


@router.get("/{university_id}/sources")
def get_university_sources(university_id: str, db: Session = Depends(get_db)) -> dict:
    uni = db.get(University, university_id)
    if not uni:
        raise HTTPException(404, "University not found")
    sources = db.query(UniversitySource).filter(UniversitySource.university_id == university_id).all()
    domains = {img.source_domain for img in uni.images if img.source_domain}
    extra = [
        {"url": None, "domain": d, "title": d, "source_type": "wikimedia" if "wikimedia" in d else "other", "is_official": False}
        for d in domains
        if d not in {s.domain for s in sources}
    ]
    return {
        "sources": [
            {
                "url": s.url,
                "domain": s.domain,
                "title": s.title,
                "source_type": s.source_type,
                "is_official": s.is_official,
            }
            for s in sources
        ]
        + extra
    }


def _serialize_university(uni: University) -> dict:
    return {
        "id": uni.id,
        "canonical_name": uni.canonical_name,
        "city": uni.city,
        "country": uni.country,
        "founded": uni.founded,
        "official_website": uni.official_website,
        "wikipedia_url": uni.wikipedia_url,
        "latitude": uni.latitude,
        "longitude": uni.longitude,
        "description": uni.description,
        "description_generated_by": uni.description_generated_by,
        "facts": [
            {
                "key": f.key,
                "label": f.label,
                "value": f.value or "Not available from verified sources.",
                "source_url": f.source_url,
                "verified": f.verified,
            }
            for f in uni.facts
        ],
        "updated_at": uni.updated_at.isoformat() if uni.updated_at else None,
    }


def _serialize_image(img: UniversityImage) -> dict:
    return {
        "id": img.id,
        "image_url": img.image_url,
        "source_url": img.source_url,
        "source_domain": img.source_domain,
        "source_title": img.source_title,
        "is_official_source": img.is_official_source,
        "category": img.category,
        "category_confidence": img.category_confidence,
        "width": img.width,
        "height": img.height,
        "license": img.license or "Unknown",
        "publication_date": img.publication_date or "Information unavailable",
        "retrieved_at": img.retrieved_at.isoformat() if img.retrieved_at else None,
        "confidence_score": img.confidence_score,
        "confidence_label": img.confidence_label,
        "signals": img.signals(),
        "explanation": img.explanation(),
        "status": img.status,
    }
