"""
Wikimedia Commons adapter — our primary real, freely-licensed image source.

No API key is required. Every image we return carries a genuine source URL
(the Commons file page), real license/attribution metadata pulled from
`extmetadata`, and real dimensions. We never synthesize any of these.
"""
from __future__ import annotations

import httpx
from typing import Any

from config import settings

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
_HEADERS = {"User-Agent": settings.user_agent}


async def search_images(query: str, limit: int = 12) -> list[dict[str, Any]]:
    """Full-text search across Commons files for `query`, returning file
    titles only (metadata is fetched separately in bulk via `get_image_info`).
    """
    params = {
        "action": "query",
        "list": "search",
        "srnamespace": "6",  # File: namespace
        "srsearch": query,
        "srlimit": str(limit),
        "format": "json",
    }
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        resp = await client.get(COMMONS_API, params=params)
        resp.raise_for_status()
        data = resp.json()

    return [item["title"] for item in data.get("query", {}).get("search", [])]


async def get_image_info(titles: list[str]) -> list[dict[str, Any]]:
    """Fetch imageinfo (url, dimensions, extmetadata/license/date/description)
    for a batch of File: titles. Titles that no longer resolve are skipped
    rather than padded with placeholder data.
    """
    if not titles:
        return []

    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, headers=_HEADERS) as client:
        # MediaWiki API accepts up to 50 titles per request.
        for i in range(0, len(titles), 50):
            batch = titles[i : i + 50]
            params = {
                "action": "query",
                "titles": "|".join(batch),
                "prop": "imageinfo",
                "iiprop": "url|size|mime|extmetadata",
                "format": "json",
            }
            resp = await client.get(COMMONS_API, params=params)
            resp.raise_for_status()
            data = resp.json()
            pages = data.get("query", {}).get("pages", {})

            for page in pages.values():
                if "missing" in page:
                    continue
                infos = page.get("imageinfo") or []
                if not infos:
                    continue
                info = infos[0]
                if not info.get("mime", "").startswith("image/"):
                    continue  # skip non-image files (audio, pdf, etc.)

                meta = info.get("extmetadata", {}) or {}

                def _m(key: str) -> str | None:
                    return (meta.get(key) or {}).get("value")

                results.append(
                    {
                        "title": page.get("title"),
                        "image_url": info.get("url"),
                        "width": info.get("width"),
                        "height": info.get("height"),
                        "source_url": f"https://commons.wikimedia.org/wiki/{page.get('title', '').replace(' ', '_')}",
                        "license": _m("LicenseShortName"),
                        "artist": _strip_html(_m("Artist")),
                        "description": _strip_html(_m("ImageDescription")),
                        "date": _m("DateTimeOriginal") or _m("DateTime"),
                        "categories": _m("Categories"),
                    }
                )
    return results


def _strip_html(value: str | None) -> str | None:
    if not value:
        return value
    import re

    return re.sub(r"<[^>]+>", "", value).strip() or None
