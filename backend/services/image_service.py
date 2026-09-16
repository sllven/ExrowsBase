"""
Orchestrates the image half of the pipeline for a single university:

    raw Commons candidates
        -> download bytes (bounded concurrency)
        -> Level 1-3 duplicate detection (deduplication_service)
        -> categorization (categorization_service)
        -> verification / confidence scoring (verification_service)
        -> final accept/reject decision

Nothing here invents an image: every candidate must have come from
search_service (Wikimedia Commons, or the optional web search adapter).
"""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from config import settings
from services import categorization_service, deduplication_service, verification_service
from services.deduplication_service import Candidate
from sources.official import domain_of

_HEADERS = {"User-Agent": settings.user_agent}
DOWNLOAD_CONCURRENCY = 8
MIN_IRRELEVANT_CATEGORY_CONFIDENCE = 20.0  # below this + "unknown" => drop as irrelevant


async def _download(client: httpx.AsyncClient, url: str) -> bytes | None:
    try:
        resp = await client.get(url)
        if resp.status_code == 200 and resp.headers.get("content-type", "").startswith("image/"):
            return resp.content
    except httpx.HTTPError:
        return None
    return None


async def process_candidates(
    university_name: str,
    official_website: str | None,
    raw_candidates: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """`raw_candidates` is {category: [commons image info dicts]} from
    search_service.collect_commons_candidates. Returns a flat list of fully
    processed image records (verified, rejected, or duplicate)."""
    official_domain = domain_of(official_website)

    flat: list[dict[str, Any]] = []
    for category, items in raw_candidates.items():
        for item in items:
            flat.append(item)
    flat = flat[: settings.max_total_images_analyzed]

    # --- download with bounded concurrency ---
    semaphore = asyncio.Semaphore(DOWNLOAD_CONCURRENCY)
    downloaded: list[dict[str, Any] | None] = [None] * len(flat)

    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        async def _worker(idx: int, item: dict[str, Any]) -> None:
            async with semaphore:
                img_bytes = await _download(client, item["image_url"])
                if img_bytes:
                    downloaded[idx] = {**item, "bytes": img_bytes}

        await asyncio.gather(*(_worker(i, item) for i, item in enumerate(flat)))

    items_with_bytes = [d for d in downloaded if d is not None]

    # --- categorize each (before dedup, since 'best of cluster' can use category too) ---
    categorized: list[dict[str, Any]] = []
    for item in items_with_bytes:
        cat_result = await categorization_service.categorize(
            title=item.get("title", ""),
            description=item.get("description"),
            commons_categories=item.get("categories"),
        )
        categorized.append({**item, "category_result": cat_result})

    # --- build dedup candidates ---
    dedup_inputs = [
        Candidate(
            ref=str(i),
            image_bytes=c["bytes"],
            is_official_source=bool(official_domain and domain_of(c["source_url"]) and
                                     domain_of(c["source_url"]).endswith(official_domain)),
            width=c.get("width"),
            height=c.get("height"),
            has_license=bool(c.get("license")),
            has_date=bool(c.get("date")),
            preliminary_score=c["category_result"]["confidence"],
        )
        for i, c in enumerate(categorized)
    ]
    dedup_results = deduplication_service.deduplicate(dedup_inputs)

    # --- verify + finalize ---
    results: list[dict[str, Any]] = []
    for i, c in enumerate(categorized):
        dedup = dedup_results[str(i)]
        cat_result = c["category_result"]
        source_text = " ".join(
            filter(None, [c.get("title", ""), c.get("description") or "", c.get("categories") or ""])
        )

        verification = verification_service.evaluate(
            verification_service.VerificationInput(
                university_name=university_name,
                official_domain=official_domain,
                source_url=c["source_url"],
                source_title=c.get("title", ""),
                source_text=source_text,
                category_confidence=cat_result["confidence"],
                has_license=bool(c.get("license")),
                has_date=bool(c.get("date")),
                width=c.get("width"),
                height=c.get("height"),
                is_duplicate=(dedup["status"] == "duplicate"),
            )
        )

        status = "candidate"
        rejection_reason = None

        if dedup["status"] == "duplicate":
            status = "rejected_duplicate"
            rejection_reason = f"Duplicate ({dedup['level']}) of another selected image"
        elif cat_result["category"] == "unknown" and cat_result["confidence"] < MIN_IRRELEVANT_CATEGORY_CONFIDENCE:
            status = "rejected_irrelevant"
            rejection_reason = "Could not confidently match any content category"
        elif verification["score"] < settings.threshold_limited_evidence:
            status = "rejected_low_confidence"
            rejection_reason = "Confidence score below the minimum display threshold"
        else:
            status = "verified"

        results.append(
            {
                "image_url": c["image_url"],
                "source_url": c["source_url"],
                "source_domain": domain_of(c["source_url"]),
                "source_title": c.get("title"),
                "is_official_source": verification["is_official_source"],
                "category": cat_result["category"],
                "category_confidence": cat_result["confidence"],
                "category_breakdown": cat_result["breakdown"],
                "width": c.get("width"),
                "height": c.get("height"),
                "license": c.get("license"),
                "publication_date": c.get("date"),
                "sha256": dedup_inputs[i].sha256,
                "phash": dedup_inputs[i].phash,
                "confidence_score": verification["score"],
                "confidence_label": verification["label"],
                "signals": verification["signals"],
                "explanation": verification["explanation"],
                "status": status,
                "rejection_reason": rejection_reason,
                "duplicate_of_ref": dedup["duplicate_of"],
            }
        )

    return results
