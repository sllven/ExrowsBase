from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api import compare, images, research, universities
from config import settings
from database import init_db

app = FastAPI(
    title=settings.app_name,
    description="See the university as a student sees it.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(universities.router)
app.include_router(research.router)
app.include_router(images.router)
app.include_router(compare.router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "llm_enabled": bool(settings.llm_api_key),
        "vision_enabled": bool(settings.vision_api_key),
        "web_search_enabled": bool(settings.search_api_key),
    }


# Serve the vanilla frontend directly from FastAPI so `docker-compose up`
# (or `uvicorn main:app`) is a single command that gets you a working app.
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
