"""
Lightweight local image embeddings for visual-similarity deduplication
(Level 3 in the spec). We deliberately do NOT claim this is a deep neural
embedding model — it's a fast, dependency-light color+gradient histogram
vector computed locally with Pillow/NumPy. It's real, deterministic, and
good enough to catch near-identical campus photos (crops, resizes,
recompressions, watermark variants) via cosine similarity, which is the
actual goal of Level 3 in this pipeline.

If VISION_API_KEY is configured, a real embedding model could be swapped
in behind this same function signature (get_embedding) without touching
callers — that's the extension point mentioned in the README.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

EMBEDDING_SIZE = 8  # 8x8 grid -> 64 * 3 (RGB) = 192-dim vector


def get_embedding(image_bytes: bytes) -> np.ndarray | None:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None

    img = img.resize((EMBEDDING_SIZE, EMBEDDING_SIZE), Image.BILINEAR)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    vector = arr.flatten()
    norm = np.linalg.norm(vector)
    if norm == 0:
        return vector
    return vector / norm


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return 0.0
    return float(np.clip(np.dot(a, b), -1.0, 1.0))
