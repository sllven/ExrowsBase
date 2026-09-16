"""
Three-level duplicate detection.

Level 1 — exact duplicate: SHA-256 of the raw image bytes.
Level 2 — near duplicate: perceptual hash (pHash) Hamming distance.
Level 3 — visual similarity: local embedding cosine similarity.

Images are compared pairwise within an already-fetched batch (bounded by
config.max_total_images_analyzed, so this stays O(n^2) on a small n).
The "best" survivor of a duplicate cluster is chosen by:
    1) is_official_source (True wins)
    2) higher resolution (width * height)
    3) more complete metadata (license + date present)
    4) higher preliminary confidence score
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

import imagehash
from PIL import Image
import io

from ai import embeddings

PHASH_NEAR_DUPLICATE_THRESHOLD = 6  # Hamming distance; lower = stricter
EMBEDDING_SIMILARITY_THRESHOLD = 0.985  # cosine similarity


@dataclass
class Candidate:
    ref: str  # opaque id supplied by caller (e.g. index or db id)
    image_bytes: bytes
    is_official_source: bool
    width: int | None
    height: int | None
    has_license: bool
    has_date: bool
    preliminary_score: float

    sha256: str = field(init=False, default="")
    phash: str | None = field(init=False, default=None)
    embedding: object = field(init=False, default=None)

    def __post_init__(self) -> None:
        self.sha256 = hashlib.sha256(self.image_bytes).hexdigest()
        try:
            img = Image.open(io.BytesIO(self.image_bytes))
            self.phash = str(imagehash.phash(img))
        except Exception:
            self.phash = None
        self.embedding = embeddings.get_embedding(self.image_bytes)

    def quality_key(self) -> tuple:
        area = (self.width or 0) * (self.height or 0)
        metadata_score = int(self.has_license) + int(self.has_date)
        return (self.is_official_source, area, metadata_score, self.preliminary_score)


def deduplicate(candidates: list[Candidate]) -> dict[str, dict]:
    """Returns {ref: {"status": "unique"|"duplicate", "duplicate_of": ref|None,
    "level": "exact"|"near"|"visual"|None}} for every candidate."""
    result: dict[str, dict] = {c.ref: {"status": "unique", "duplicate_of": None, "level": None} for c in candidates}
    n = len(candidates)

    for i in range(n):
        a = candidates[i]
        if result[a.ref]["status"] == "duplicate":
            continue
        cluster = [a]
        for j in range(i + 1, n):
            b = candidates[j]
            if result[b.ref]["status"] == "duplicate":
                continue

            level = None
            if a.sha256 == b.sha256:
                level = "exact"
            elif a.phash and b.phash:
                dist = imagehash.hex_to_hash(a.phash) - imagehash.hex_to_hash(b.phash)
                if dist <= PHASH_NEAR_DUPLICATE_THRESHOLD:
                    level = "near"
            if level is None and a.embedding is not None and b.embedding is not None:
                sim = embeddings.cosine_similarity(a.embedding, b.embedding)
                if sim >= EMBEDDING_SIMILARITY_THRESHOLD:
                    level = "visual"

            if level:
                cluster.append(b)
                result[b.ref] = {"status": "duplicate", "duplicate_of": None, "level": level}

        if len(cluster) > 1:
            best = max(cluster, key=lambda c: c.quality_key())
            for c in cluster:
                if c.ref == best.ref:
                    result[c.ref] = {"status": "unique", "duplicate_of": None, "level": None}
                else:
                    lvl = result[c.ref]["level"] or "exact"
                    result[c.ref] = {"status": "duplicate", "duplicate_of": best.ref, "level": lvl}

    return result
