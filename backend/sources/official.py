"""
Lightweight adapter for touching a university's official website.

Used to (a) confirm the domain from Wikidata actually resolves, and
(b) as an "official source" match target when scoring image/source trust.
We deliberately keep this shallow (HEAD/GET + title) rather than crawling —
deep crawling of arbitrary institutional sites is out of scope for the MVP
and would slow the pipeline well past the 30s target.
"""
from __future__ import annotations

from urllib.parse import urlparse

import httpx

from config import settings

_HEADERS = {"User-Agent": settings.user_agent}


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        netloc = urlparse(url).netloc.lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except ValueError:
        return None


async def verify_reachable(url: str | None) -> bool:
    if not url:
        return False
    try:
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds, headers=_HEADERS, follow_redirects=True
        ) as client:
            resp = await client.head(url)
            if resp.status_code >= 400:
                resp = await client.get(url)
            return resp.status_code < 400
    except httpx.HTTPError:
        return False
