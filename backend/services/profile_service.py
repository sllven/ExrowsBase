"""
Orchestrates the full research pipeline end-to-end for one university and
persists results, tracking progress through the stages listed in the spec
(section 19) so the frontend can poll GET /api/research/{id} for live
percentages. Also implements the "recently researched -> serve cached"
behavior from section 21.
"""
from __future__ import annotations

import datetime as dt
import json

from sqlalchemy.orm import Session

from config import settings
from database import ResearchRun, University, UniversityFact, UniversityImage, UniversitySource
from services import image_service, search_service, university_service
from sources.official import domain_of
from ai import llm as llm_ai

STAGES = [
    ("identification", "University identification", 8),
    ("sources", "Source discovery", 20),
    ("images", "Image collection", 45),
    ("dedup", "Duplicate detection", 60),
    ("verify", "AI verification", 78),
    ("categorize", "Categorization", 88),
    ("profile", "Profile generation", 100),
]


def _set_stage(run: ResearchRun, db: Session, stage_key: str, percent: int) -> None:
    run.stage = stage_key
    run.progress_percent = percent
    db.commit()


async def get_or_create_university_from_title(db: Session, title: str, original_query: str) -> University | None:
    resolved = await university_service.resolve_title(title)
    if resolved is None or resolved.get("disambiguation"):
        return None

    existing = (
        db.query(University)
        .filter(University.canonical_name == resolved["canonical_name"])
        .first()
    )
    uni = existing or University(canonical_name=resolved["canonical_name"])
    uni.query_name = original_query
    uni.city = resolved.get("city")
    uni.country = resolved.get("country")
    uni.founded = resolved.get("founded")
    uni.official_website = resolved.get("official_website") if resolved.get("official_website_reachable") else None
    uni.wikipedia_url = resolved.get("wikipedia_url")
    uni.wikidata_id = resolved.get("wikidata_id")
    uni.latitude = resolved.get("latitude")
    uni.longitude = resolved.get("longitude")

    db.add(uni)
    db.commit()
    db.refresh(uni)

    # store the wikipedia extract transiently on the instance for description generation
    uni._extract = resolved.get("wikipedia_extract")  # type: ignore[attr-defined]
    uni._students_count = resolved.get("students_count")  # type: ignore[attr-defined]
    return uni


def get_fresh_cached_run(db: Session, university_id: str) -> ResearchRun | None:
    cutoff = dt.datetime.utcnow() - dt.timedelta(seconds=settings.research_cache_ttl_seconds)
    return (
        db.query(ResearchRun)
        .filter(
            ResearchRun.university_id == university_id,
            ResearchRun.status == "done",
            ResearchRun.finished_at.isnot(None),
            ResearchRun.finished_at >= cutoff,
        )
        .order_by(ResearchRun.finished_at.desc())
        .first()
    )


async def run_pipeline(db: Session, university: University, run: ResearchRun) -> None:
    try:
        run.status = "running"
        _set_stage(run, db, "identification", 8)

        # Clear previous run's images/sources/facts for this university so a
        # "Refresh research" produces a clean, current result set.
        db.query(UniversityImage).filter(UniversityImage.university_id == university.id).delete()
        db.query(UniversitySource).filter(UniversitySource.university_id == university.id).delete()
        db.query(UniversityFact).filter(UniversityFact.university_id == university.id).delete()
        db.commit()

        _set_stage(run, db, "sources", 20)
        sources_added = 0
        if university.wikipedia_url:
            db.add(
                UniversitySource(
                    university_id=university.id,
                    url=university.wikipedia_url,
                    domain="wikipedia.org",
                    title=university.canonical_name,
                    source_type="wikipedia",
                    is_official=False,
                )
            )
            sources_added += 1
        if university.official_website:
            db.add(
                UniversitySource(
                    university_id=university.id,
                    url=university.official_website,
                    domain=domain_of(university.official_website) or university.official_website,
                    title=f"{university.canonical_name} — official website",
                    source_type="official",
                    is_official=True,
                )
            )
            sources_added += 1
        db.commit()

        # --- facts (section 17): every fact carries its own source or "Not available" ---
        extract = getattr(university, "_extract", None)
        students_count = getattr(university, "_students_count", None)
        fact_defs = [
            ("founded", "Founded", university.founded, university.wikipedia_url),
            ("location", "Location", ", ".join(filter(None, [university.city, university.country])) or None, university.wikipedia_url),
            ("official_website", "Official website", university.official_website, university.official_website),
            ("students", "Students", students_count, university.wikipedia_url),
        ]
        for key, label, value, source_url in fact_defs:
            db.add(
                UniversityFact(
                    university_id=university.id,
                    key=key,
                    label=label,
                    value=value,
                    source_url=source_url if value else None,
                    source_title="Wikipedia / Wikidata" if source_url == university.wikipedia_url else "Official website",
                    verified=bool(value),
                )
            )
        db.commit()

        _set_stage(run, db, "images", 45)
        raw_candidates = await search_service.collect_commons_candidates(
            university.canonical_name, per_category_limit=settings.max_images_per_category
        )
        images_analyzed = sum(len(v) for v in raw_candidates.values())

        _set_stage(run, db, "dedup", 60)
        # dedup happens inside process_candidates together with categorize+verify,
        # progress markers here are best-effort UX signposts, not separate passes.
        _set_stage(run, db, "verify", 78)
        processed = await image_service.process_candidates(
            university.canonical_name, university.official_website, raw_candidates
        )

        _set_stage(run, db, "categorize", 88)
        verified_count = 0
        rejected_count = 0
        duplicate_count = 0
        for item in processed:
            img = UniversityImage(
                university_id=university.id,
                image_url=item["image_url"],
                source_url=item["source_url"],
                source_domain=item["source_domain"] or "",
                source_title=item["source_title"],
                is_official_source=item["is_official_source"],
                category=item["category"],
                category_confidence=item["category_confidence"],
                category_breakdown_json=json.dumps(item["category_breakdown"]),
                width=item["width"],
                height=item["height"],
                license=item["license"],
                publication_date=item["publication_date"],
                sha256=item["sha256"],
                phash=item["phash"],
                confidence_score=item["confidence_score"],
                confidence_label=item["confidence_label"],
                verification_signals_json=json.dumps(item["signals"]),
                verification_explanation_json=json.dumps(item["explanation"]),
                status=item["status"],
                rejection_reason=item["rejection_reason"],
            )
            db.add(img)
            if item["status"] == "verified":
                verified_count += 1
            elif item["status"] == "rejected_duplicate":
                duplicate_count += 1
            else:
                rejected_count += 1
        db.commit()

        _set_stage(run, db, "profile", 95)
        description, desc_source = await _generate_description(university, extract)
        university.description = description
        university.description_generated_by = desc_source
        db.commit()

        confidences = [i.confidence_score for i in university.images if i.status == "verified"]
        overall_confidence = round(sum(confidences) / len(confidences)) if confidences else 0

        run.status = "done"
        run.stage = "profile"
        run.progress_percent = 100
        run.confidence = overall_confidence
        run.sources_count = sources_added + len({i.source_domain for i in university.images})
        run.images_analyzed = images_analyzed
        run.verified_images = verified_count
        run.rejected_images = rejected_count
        run.duplicate_images = duplicate_count
        run.finished_at = dt.datetime.utcnow()
        db.commit()

    except Exception as exc:  # pragma: no cover - defensive; surfaced honestly to the user
        run.status = "failed"
        run.error_message = str(exc)
        run.finished_at = dt.datetime.utcnow()
        db.commit()
        raise


async def _generate_description(university: University, extract: str | None) -> tuple[str, str]:
    facts = {
        "founded": university.founded,
        "city": university.city,
        "country": university.country,
        "official_website": university.official_website,
    }
    if settings.llm_api_key:
        try:
            text = await llm_ai.generate_grounded_description(university.canonical_name, facts, extract)
            if text:
                return text, "llm"
        except Exception:
            pass

    # Extractive fallback: first 1-2 sentences of the Wikipedia extract, or a
    # bare-bones templated sentence built only from confirmed facts.
    if extract:
        sentences = extract.split(". ")
        snippet = ". ".join(sentences[:2]).strip()
        if snippet and not snippet.endswith("."):
            snippet += "."
        return snippet, "extractive"

    parts = [university.canonical_name]
    if university.city or university.country:
        parts.append(f"located in {', '.join(filter(None, [university.city, university.country]))}")
    if university.founded:
        parts.append(f"founded in {university.founded}")
    return (" — ".join(parts) + ".") if len(parts) > 1 else f"{university.canonical_name}.", "template"
