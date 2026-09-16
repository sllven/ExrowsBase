from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import ResearchRun, SessionLocal, University, get_db
from services import profile_service, university_service

router = APIRouter(prefix="/api/research", tags=["research"])


class ResearchRequest(BaseModel):
    query: str | None = None          # first-time free text
    resolved_title: str | None = None  # after user picked from disambiguation
    force_refresh: bool = False


class ResearchStartResponse(BaseModel):
    status: str  # started | ambiguous | not_found | cached
    research_id: str | None = None
    university_id: str | None = None
    candidates: list[dict] | None = None
    message: str | None = None


@router.post("", response_model=ResearchStartResponse)
async def start_research(payload: ResearchRequest, db: Session = Depends(get_db)) -> ResearchStartResponse:
    title = payload.resolved_title
    original_query = payload.query or payload.resolved_title or ""

    if not title:
        result = await university_service.identify(payload.query or "")
        if result["status"] == "not_found":
            return ResearchStartResponse(
                status="not_found",
                message="University not found. Try checking the spelling or entering the official university name.",
            )
        if result["status"] == "ambiguous":
            return ResearchStartResponse(status="ambiguous", candidates=result["candidates"], message="Which university did you mean?")
        title = result["university"]["canonical_name"]

    university = await profile_service.get_or_create_university_from_title(db, title, original_query)
    if university is None:
        return ResearchStartResponse(status="not_found", message="University not found.")

    if not payload.force_refresh:
        cached = profile_service.get_fresh_cached_run(db, university.id)
        if cached:
            return ResearchStartResponse(
                status="cached",
                research_id=cached.id,
                university_id=university.id,
                message="Updated recently — showing cached results.",
            )

    run = ResearchRun(university_id=university.id, status="pending", stage="identification", progress_percent=0)
    db.add(run)
    db.commit()
    db.refresh(run)

    asyncio.create_task(_run_in_background(run.id, university.id))

    return ResearchStartResponse(status="started", research_id=run.id, university_id=university.id)


async def _run_in_background(run_id: str, university_id: str) -> None:
    # A dedicated session because this task outlives the original request.
    db = SessionLocal()
    try:
        run = db.get(ResearchRun, run_id)
        university = db.get(University, university_id)
        if run is None or university is None:
            return
        await profile_service.run_pipeline(db, university, run)
    finally:
        db.close()


@router.get("/{research_id}")
def get_research_status(research_id: str, db: Session = Depends(get_db)) -> dict:
    run = db.get(ResearchRun, research_id)
    if not run:
        raise HTTPException(404, "Research run not found")

    response = {
        "research_id": run.id,
        "university_id": run.university_id,
        "status": run.status,
        "stage": run.stage,
        "progress_percent": run.progress_percent,
        "error_message": run.error_message,
    }

    if run.status == "done":
        university = run.university
        categories: dict[str, list[str]] = {
            "campus": [], "dormitory": [], "library": [], "classroom": [],
            "laboratory": [], "sport": [], "student_life": [], "city": [],
        }
        for img in university.images:
            if img.status == "verified" and img.category in categories:
                categories[img.category].append(img.id)

        response.update(
            {
                "university": {
                    "id": university.id,
                    "name": university.canonical_name,
                    "city": university.city,
                    "country": university.country,
                    "official_website": university.official_website,
                    "description": university.description,
                },
                "confidence": run.confidence,
                "sources_count": run.sources_count,
                "images_analyzed": run.images_analyzed,
                "verified_images": run.verified_images,
                "rejected_images": run.rejected_images,
                "duplicate_images": run.duplicate_images,
                "categories": categories,
                "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            }
        )

    return response
