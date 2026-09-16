"""
SQLAlchemy models + session management.

Uses SQLite by default (file-based, zero setup). Because we go through
SQLAlchemy's engine abstraction and never write raw SQLite-specific SQL,
switching to PostgreSQL later is just a DATABASE_URL change (see README).
"""
from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any, Generator

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from config import settings


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class University(Base):
    __tablename__ = "universities"

    id = Column(String, primary_key=True, default=_uuid)
    canonical_name = Column(String, nullable=False, index=True)
    query_name = Column(String, nullable=True)
    city = Column(String, nullable=True)
    country = Column(String, nullable=True)
    founded = Column(String, nullable=True)
    official_website = Column(String, nullable=True)
    wikipedia_url = Column(String, nullable=True)
    wikidata_id = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    description_generated_by = Column(String, nullable=True)  # "llm" | "extractive" | None
    created_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    facts = relationship("UniversityFact", back_populates="university", cascade="all, delete-orphan")
    images = relationship("UniversityImage", back_populates="university", cascade="all, delete-orphan")
    sources = relationship("UniversitySource", back_populates="university", cascade="all, delete-orphan")
    research_runs = relationship("ResearchRun", back_populates="university", cascade="all, delete-orphan")


class UniversityFact(Base):
    """A single sourced factual claim, e.g. 'Founded: 1209' -> [source]."""

    __tablename__ = "university_facts"

    id = Column(String, primary_key=True, default=_uuid)
    university_id = Column(String, ForeignKey("universities.id"), nullable=False)
    key = Column(String, nullable=False)  # e.g. "founded", "students", "cost_of_living"
    label = Column(String, nullable=False)  # human readable label
    value = Column(Text, nullable=True)  # None/empty => not available
    source_url = Column(String, nullable=True)
    source_title = Column(String, nullable=True)
    verified = Column(Boolean, default=False)

    university = relationship("University", back_populates="facts")


class UniversitySource(Base):
    __tablename__ = "university_sources"

    id = Column(String, primary_key=True, default=_uuid)
    university_id = Column(String, ForeignKey("universities.id"), nullable=False)
    url = Column(String, nullable=False)
    domain = Column(String, nullable=False)
    title = Column(String, nullable=True)
    source_type = Column(String, nullable=False)  # official | wikipedia | wikimedia | other
    is_official = Column(Boolean, default=False)
    retrieved_at = Column(DateTime, default=dt.datetime.utcnow)

    university = relationship("University", back_populates="sources")


class UniversityImage(Base):
    __tablename__ = "university_images"

    id = Column(String, primary_key=True, default=_uuid)
    university_id = Column(String, ForeignKey("universities.id"), nullable=False)

    image_url = Column(String, nullable=False)
    thumb_url = Column(String, nullable=True)
    source_url = Column(String, nullable=False)
    source_domain = Column(String, nullable=False)
    source_title = Column(String, nullable=True)
    is_official_source = Column(Boolean, default=False)

    category = Column(String, nullable=False, default="unknown")
    category_confidence = Column(Float, default=0.0)
    category_breakdown_json = Column(Text, nullable=True)  # json dict of all category scores

    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)

    license = Column(String, nullable=True)
    publication_date = Column(String, nullable=True)
    retrieved_at = Column(DateTime, default=dt.datetime.utcnow)

    sha256 = Column(String, nullable=True, index=True)
    phash = Column(String, nullable=True, index=True)

    confidence_score = Column(Integer, default=0)
    confidence_label = Column(String, default="Unverified")
    verification_signals_json = Column(Text, nullable=True)  # json list of {signal, score}
    verification_explanation_json = Column(Text, nullable=True)  # json list of strings

    status = Column(String, default="candidate")
    # candidate | verified | rejected_duplicate | rejected_low_confidence | rejected_irrelevant
    rejection_reason = Column(String, nullable=True)
    duplicate_of_id = Column(String, nullable=True)

    university = relationship("University", back_populates="images")

    def signals(self) -> list[dict[str, Any]]:
        return json.loads(self.verification_signals_json or "[]")

    def explanation(self) -> list[str]:
        return json.loads(self.verification_explanation_json or "[]")

    def category_breakdown(self) -> dict[str, float]:
        return json.loads(self.category_breakdown_json or "{}")


class ResearchRun(Base):
    """One research pipeline execution for a university (supports caching/refresh)."""

    __tablename__ = "research_runs"

    id = Column(String, primary_key=True, default=_uuid)
    university_id = Column(String, ForeignKey("universities.id"), nullable=False)

    status = Column(String, default="pending")  # pending|running|done|failed|not_found|ambiguous
    stage = Column(String, nullable=True)
    progress_percent = Column(Integer, default=0)
    error_message = Column(String, nullable=True)

    confidence = Column(Integer, nullable=True)
    sources_count = Column(Integer, default=0)
    images_analyzed = Column(Integer, default=0)
    verified_images = Column(Integer, default=0)
    rejected_images = Column(Integer, default=0)
    duplicate_images = Column(Integer, default=0)

    started_at = Column(DateTime, default=dt.datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)

    university = relationship("University", back_populates="research_runs")


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
