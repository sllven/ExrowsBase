# UniView AI

**See the university as a student sees it.**

Enter the name of any real university and UniView AI finds it, gathers real
information and photographs from open sources, checks where each piece of
content actually comes from, removes duplicates, and assembles a visual
profile — every fact and every image linked to a real, clickable source.

There is no list of pre-baked universities. There is no hardcoded demo mode.
The pipeline that runs for "MIT" is the same pipeline that runs for any
university nobody has ever searched for before.

---

## 1. Problem

Prospective students research universities largely through marketing
brochures and curated official photography. It's hard to find an honest,
sourced, visual sense of a campus — and even harder to trust that a photo
labeled "campus library" actually is that university's library and not a
stock photo or a different school entirely.

## 2. Solution

UniView AI runs a research pipeline per university:

1. **Identify** the canonical institution (disambiguating when needed).
2. **Gather** structured facts and photographs from real, checkable sources.
3. **Verify** every photo against multiple independent signals before it's
   shown as "verified."
4. **Deduplicate** at three levels so the same photo doesn't appear five times.
5. **Categorize** each photo (campus, dormitory, library, classroom,
   laboratory, sport, student life, city).
6. **Score confidence** algorithmically, never randomly, and show the math.
7. **Present** a sourced profile, with an honest "not available" wherever
   evidence is missing.

**The governing rule, everywhere in this codebase: NO EVIDENCE = NO
CONFIDENT CLAIM.** No source → not shown as fact. No reliable photo match →
lower confidence or exclude. Ambiguous university name → ask the user. No
data → say so, in the UI, not a fabricated placeholder.

## 3. Architecture

```
frontend/            Vanilla HTML/CSS/JS. Talks only to our own API.
backend/
  main.py            FastAPI app, mounts routers + serves the frontend.
  config.py          All configuration from environment variables.
  database.py        SQLAlchemy models (SQLite by default, Postgres-ready).
  api/                 HTTP layer — request/response shaping only.
  services/            Orchestration + business logic.
  ai/                   LLM / vision / embeddings / confidence-scoring adapters.
  sources/              Adapters for external data: Wikipedia, Wikidata,
                         Wikimedia Commons, official websites, optional
                         third-party web search.
```

Data flow for one research run (`services/profile_service.py`):

```
university_service.identify()
    -> Wikipedia search + Wikidata facts (no key required)
search_service.collect_commons_candidates()
    -> Wikimedia Commons search + imageinfo, per category
image_service.process_candidates()
    -> download -> categorization_service.categorize()
              -> deduplication_service.deduplicate()   (SHA-256 / pHash / embedding)
              -> verification_service.evaluate()        (-> ai/confidence.py)
profile_service persists everything + generates a grounded description
```

## 4. Why Wikipedia / Wikidata / Wikimedia Commons are the backbone

They are the only sources in this project that are **simultaneously**: free,
keyless, structured, globally comprehensive (covering MIT and a small
regional university alike), and individually citable (every fact and every
image links back to a real page). That directly satisfies the "works for
any university, not a hardcoded list" requirement without needing the
operator to provision a paid search API just to try the app.

Two optional adapters extend the pipeline when the operator provides keys
(see `.env.example`):

- **`SEARCH_API_KEY` / `SEARCH_API_PROVIDER`** (Brave or Bing) — pulls in
  additional web sources beyond Wikipedia/Commons.
- **`LLM_API_KEY`** (Anthropic-compatible) — writes a more natural profile
  description from the gathered facts, and helps refine ambiguous image
  categorization.
- **`VISION_API_KEY`** — enables a real per-image visual description signal
  in the confidence engine.

**None of these are required to run the app.** Without them, UniView AI
still identifies any university, gathers real Commons photography, verifies
it, deduplicates it, categorizes it by keyword evidence, and writes an
extractive (not fabricated) description straight from the Wikipedia
summary. The system never fills a missing key's gap with invented content —
it just runs the reduced, still fully honest pipeline. `GET /api/health`
reports which optional adapters are currently active.

## 5. Verification methodology

Each image is scored from independent signals in `services/verification_service.py`,
combined by `ai/confidence.py`:

| Signal | Weight | What it measures |
|---|---|---|
| Source evidence | 35% | Is the domain the university's *official* site, a trusted public repository (Wikimedia/Wikipedia), or unknown? |
| Entity match | 25% | Does the source text actually name this university (fuzzy string match)? |
| Category confidence | 20% | How strongly did keyword/LLM evidence support the assigned category? |
| Metadata completeness | 10% | Are license, date, and adequate resolution present? |
| Visual model (optional) | 10% | Only included when `VISION_API_KEY` is set. |

The weighted average is rounded to a 0–100 score and labeled:

- **90–100** Highly verified
- **75–89** Verified
- **60–74** Limited evidence
- **0–59** Unverified (excluded from the main grid; available via "Show
  uncertain results")

This is a fixed formula, not a per-request LLM guess — the same inputs
always produce the same score, and the full signal breakdown is shown on
every image's detail view under "Why this image was accepted."

## 6. How we prevent unsupported images from being presented as verified

This is the most important design constraint in the project, so it's worth
spelling out exactly where it's enforced:

1. **Every image candidate has a real, retrieved source URL** before it
   ever reaches the verification step — candidates come only from
   `sources/wikimedia.py` (Wikimedia Commons search results) or the
   optional web search adapter. Nothing is ever synthesized.
2. **Nothing is shown until it clears three separate filters**
   (`services/image_service.py`): it must not be a detected duplicate, it
   must have a category confidently assigned (or it's dropped as
   irrelevant), and its combined confidence score must clear
   `threshold_limited_evidence` (60).
3. **Low-confidence images are never silently hidden as if they didn't
   exist** — they're counted and surfaced via "N additional images could
   not be reliably verified" with an explicit opt-in to view them.
4. **Every fact on a university profile carries its own source URL** or
   renders literally as "Not available from verified sources." — see
   `services/profile_service.py`'s `fact_defs` and the frontend's
   `renderFacts()`. There is no code path that inserts a plausible-looking
   number, date, or address that wasn't retrieved from a source.
5. **An ambiguous or unmatched university name never resolves silently.**
   `services/university_service.py` returns `ambiguous` unless the top
   Wikipedia match is an exact title match or the only candidate returned.
6. **The AI-written description is explicitly instructed not to add facts**
   beyond the ones it's given (`ai/llm.py::generate_grounded_description`),
   and falls back to an extractive summary of the Wikipedia article (not a
   model-generated one) when no LLM key is configured.

## 7. Duplicate detection

Three independent levels, run in that order, in
`services/deduplication_service.py`:

- **Level 1 — exact**: SHA-256 of the downloaded image bytes.
- **Level 2 — near duplicate**: perceptual hash (`imagehash.phash`),
  Hamming distance ≤ 6.
- **Level 3 — visual similarity**: a lightweight local 8×8 RGB embedding
  (`ai/embeddings.py`) compared via cosine similarity ≥ 0.985. This is
  deliberately described as a fast local heuristic, not a deep neural
  embedding model — it catches crops/recompressions/resizes, which is the
  actual goal of "Level 3" here. A real vision embedding model can be
  swapped in behind the same `get_embedding()` function signature.

Within a detected duplicate cluster, the surviving image is chosen by:
official source > higher resolution > more complete metadata > higher
preliminary confidence.

## 8. Confidence scoring — algorithmic, not random

See section 5. The formula and weights live in `ai/confidence.py` as plain
Python, not a model call — this was a specific project requirement, and
it's why the same photo scored twice (e.g. on refresh) gets a stable score
unless its underlying evidence actually changed.

## 9. Sources

For every university: its Wikipedia article, its official website (when
Wikidata's P856 property resolves and the site responds), and Wikimedia
Commons for every image. The `/api/universities/{id}/sources` endpoint and
the profile page's "Sources" section list exactly what was used for that
specific run — never a generic boilerplate list.

## 10. API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/universities/search` | Identify a university from free text; returns `found` / `ambiguous` / `not_found` |
| POST | `/api/research` | Start (or serve cached) research for a university |
| GET | `/api/research/{id}` | Poll pipeline progress; full result once `status == "done"` |
| GET | `/api/universities/{id}` | University record + sourced facts |
| GET | `/api/universities/{id}/images` | Filterable image list |
| GET | `/api/images/{id}` | Full detail + verification breakdown for one image |
| GET | `/api/universities/{id}/sources` | Sources used for this university |
| POST | `/api/compare` | Factual, non-judgmental side-by-side comparison |
| GET | `/api/health` | Reports which optional AI adapters are active |

## 11. Installation

```bash
git clone <this repo>
cd uniview-ai
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

## 12. Environment variables

See `.env.example` for the full, commented list. Nothing is required to get
a working app — `DATABASE_URL` defaults to a local SQLite file, and every
`*_API_KEY` is optional (see section 4 above for exactly what each one
unlocks).

## 13. Running locally

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Open **http://localhost:8000** — the FastAPI app serves the frontend
directly, so there's nothing else to start.

## 14. Docker

```bash
docker compose up --build
```

This builds the backend image (which also bundles and serves the frontend)
and persists the SQLite database in a named volume. Redis is scaffolded in
`docker-compose.yml` (commented out) as documented in section 15 below.

## 15. Cache

Research results are cached at the database level: a university researched
within the last `RESEARCH_CACHE_TTL_SECONDS` (default 6h) is served
instantly with an "Updated recently" note instead of re-running the full
pipeline, and a "Refresh research" button forces a new run. This works with
zero extra infrastructure (the "simple fallback" required by the spec).
`REDIS_URL` is present in configuration as an extension point — an operator
who wants shared cross-instance caching can wire a Redis-backed cache
layer behind the same `get_fresh_cached_run()` call without changing any
calling code.

## 16. Known limitations

- **Image coverage depends on Wikimedia Commons.** Very small or
  lesser-known institutions may have few or zero Commons photographs — in
  that case UniView AI honestly reports "Not enough verified information
  was found" rather than reaching for lower-quality sources.
- **"Official source" detection depends on Wikidata's P856 property being
  set and the site responding.** If Wikidata lacks an official-website
  link, images can still be verified via Wikimedia/Wikipedia trust, but
  never receive the "official domain" boost.
- **The default visual-similarity check (Level 3 dedup) is a lightweight
  local color/gradient embedding**, not a deep vision model — see section
  7. It's intentionally conservative (high similarity threshold) to avoid
  merging genuinely different photos.
- **Category confidence is keyword-based by default**; it improves with an
  `LLM_API_KEY` but is never fabricated either way — an image with no
  textual evidence for any category is labeled `unknown` and, below a
  minimum threshold, dropped as irrelevant rather than guessed at.
- **The map feature (spec section 24)** is intentionally omitted from this
  MVP's UI — coordinates are already captured (`University.latitude/longitude`
  from Wikidata) and returned in the university API response, so a map
  view can be added on the frontend without backend changes; it isn't
  wired into `index.html` yet.
- **Research time** depends on Wikimedia Commons/Wikipedia response times
  and how many categories return results; typical runs are well under 30s,
  but a very poorly-documented university may take longer due to more
  near-empty searches before the pipeline concludes there's nothing more
  to find.
