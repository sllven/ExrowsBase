"""
Central configuration for UniView AI backend.

All secrets are read from environment variables (populated from .env in local
dev via python-dotenv). Nothing here is ever sent to the frontend directly;
the frontend only ever talks to our own FastAPI endpoints.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- General ---
    app_name: str = "UniView AI"
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = _bool("DEBUG", True)

    # --- Database ---
    database_url: str = os.getenv(
        "DATABASE_URL", f"sqlite:///{BASE_DIR / 'uniview.db'}"
    )

    # --- Cache ---
    redis_url: str | None = os.getenv("REDIS_URL") or None
    research_cache_ttl_seconds: int = int(
        os.getenv("RESEARCH_CACHE_TTL_SECONDS", str(60 * 60 * 6))  # 6h
    )

    # --- Optional AI enrichment keys (system works without them, in a
    # reduced / rule-based mode; every feature degrades honestly rather
    # than fabricating output when a key is missing) ---
    llm_api_key: str | None = os.getenv("LLM_API_KEY") or None
    llm_model: str = os.getenv("LLM_MODEL", "claude-sonnet-4-6")
    vision_api_key: str | None = os.getenv("VISION_API_KEY") or None
    search_api_key: str | None = os.getenv("SEARCH_API_KEY") or None
    search_api_provider: str = os.getenv("SEARCH_API_PROVIDER", "none")

    # --- Pipeline tuning ---
    max_images_per_category: int = int(os.getenv("MAX_IMAGES_PER_CATEGORY", "8"))
    max_total_images_analyzed: int = int(os.getenv("MAX_TOTAL_IMAGES_ANALYZED", "90"))
    http_timeout_seconds: float = float(os.getenv("HTTP_TIMEOUT_SECONDS", "12"))
    user_agent: str = os.getenv(
        "HTTP_USER_AGENT",
        "UniViewAI/1.0 (educational research tool; contact: admin@example.com)",
    )

    # Confidence thresholds used everywhere in the UI/API
    threshold_highly_verified: int = 90
    threshold_verified: int = 75
    threshold_limited_evidence: int = 60
    # below threshold_limited_evidence => "Unverified" and hidden by default


settings = Settings()
