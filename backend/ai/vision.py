"""
Vision adapter interface.

Real image *content* classification (rather than just title/metadata text
matching) requires a multimodal model call per image, which costs both
money and pipeline time. We expose a clean interface here so an operator
can plug in a dedicated vision/embedding provider via VISION_API_KEY.

Without a key, image content is NOT fabricated — the categorization and
verification services simply rely on textual signals (title, Commons
categories, source context) instead, and this is reflected honestly in
the confidence breakdown ("Visual model: not configured" rather than a
fake score).
"""
from __future__ import annotations

import base64

import httpx

from config import settings
from ai.llm import ANTHROPIC_API_URL, LLMUnavailable


async def describe_image(image_url: str) -> dict | None:
    """Use a multimodal LLM call to get a short visual description + a
    same-university plausibility note. Returns None if no vision key is
    configured or the request fails — callers must treat None as
    'no visual signal available', not as a negative signal."""
    if not settings.vision_api_key:
        return None

    try:
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds) as client:
            img_resp = await client.get(image_url)
            img_resp.raise_for_status()
            content_type = img_resp.headers.get("content-type", "image/jpeg").split(";")[0]
            b64 = base64.b64encode(img_resp.content).decode("ascii")

            resp = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": settings.vision_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "max_tokens": 150,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image",
                                    "source": {"type": "base64", "media_type": content_type, "data": b64},
                                },
                                {
                                    "type": "text",
                                    "text": (
                                        "In one short sentence, describe what this photo shows "
                                        "(setting, subject, indoor/outdoor). Do not guess the "
                                        "specific institution."
                                    ),
                                },
                            ],
                        }
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            parts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
            return {"description": "".join(parts).strip()}
    except (httpx.HTTPError, LLMUnavailable):
        return None
