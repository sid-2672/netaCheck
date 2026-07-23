# NetaCheck — Implementation Plan
### "Every Politician. Every Record. Every Source."

---

## Background

NetaCheck is a civic transparency platform for India. Its **hard architectural constraint** is that every rendered fact must be traceable to a source. This single constraint drives every design decision: schema, serializers, API, frontend rendering, and PDF generation all enforce it structurally, not by convention.

The reference products are PRS Legislative Research, GovTrack, OpenSecrets, ProPublica, and TheyWorkForYou — combined into one modern, legally defensible, publicly accessible platform.

---

## Specification Improvements (Pre-Implementation Recommendations)

Before writing code, the following weaknesses in the specification are noted with proposed resolutions:

### 1. Source Confidence Tiers
The spec says "every fact must have a source" but does not define what happens when two official sources contradict each other (e.g., EC affidavit vs. PRS record shows different asset values). **Resolution**: Introduce a `confidence` field (`OFFICIAL_PRIMARY`, `OFFICIAL_SECONDARY`, `INFERRED_DERIVED`, `USER_SUBMITTED`) and a conflict-detection flag in the ingestion pipeline.

### 2. Politician Identity Deduplication
A politician may appear in EC data as "Narendra Modi", MyNeta as "Narendra Damodardas Modi", and Lok Sabha as "Shri Narendra Modi". **Resolution**: Introduce a canonical `politician_slug` with an `alias` table and a reconciliation job. The schema must separate identity from affiliation.

### 3. Grading Engine Versioning
Grades computed today will differ from grades computed 2 years from now as grading weights evolve. Displaying the "current" grade on historical data is misleading. **Resolution**: Grades are stored as snapshots with `engine_version` and `computed_at` timestamps. The live grade always uses the latest engine version, but old grades are reproducible.

### 4. Scraper Legal/Ethical Layer
Web scraping government sites without rate limiting and `robots.txt` compliance exposes the operator to takedowns. **Resolution**: All scrapers must implement `robots.txt` checking, exponential backoff, configurable delays per domain, and User-Agent disclosure. A `ScraperPolicy` config table per source domain.

### 5. Multi-Tenancy / State-Level Isolation
MLAs from 36 states/UTs means 4,000+ legislators eventually. The schema must cleanly support state-level filtering without N+1 queries. **Resolution**: Materialized views per state for report card summaries, refreshed nightly.

### 6. Idempotency Token Strategy
The spec says ingestion should be idempotent but does not define the collision key. **Resolution**: Each ingestion artifact is keyed by `(source_url_hash, content_hash)`. If both match, skip. If URL matches but content changed, create a new `SourceSnapshot` and link new structured data to it.

### 7. Correction Workflow Due Process
If a politician's office submits a correction, the platform must not silently update data. **Resolution**: Corrections enter a `CorrectionRequest` queue, require admin review, generate a public `CorrectionHistory` entry, and notify the original source attribution. The original data is never deleted, only superseded.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                        CLIENTS                              │
│  Browser (Next.js SSR) │ PDF Download │ Public API          │
└────────────────┬────────────────────────────────────────────┘
                 │ HTTPS
┌────────────────▼────────────────────────────────────────────┐
│                   FastAPI Application                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐  │
│  │ Search   │ │Politician│ │ Report   │ │ PDF Engine   │  │
│  │ Router   │ │ Router   │ │ Card API │ │ Router       │  │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └──────┬───────┘  │
│       │            │            │               │           │
│  ┌────▼────────────▼────────────▼───────────────▼───────┐  │
│  │              Domain Services Layer                    │  │
│  │  PoliticianService │ GradingEngine │ SourceService   │  │
│  └────────────────────────────┬──────────────────────────┘  │
│                               │                              │
│  ┌────────────────────────────▼──────────────────────────┐  │
│  │              Repository Layer (SQLAlchemy)             │  │
│  └────────────────────────────┬──────────────────────────┘  │
└───────────────────────────────┼─────────────────────────────┘
                                │
        ┌───────────────────────┼──────────────────┐
        │                       │                  │
┌───────▼───────┐   ┌───────────▼──────┐  ┌───────▼──────┐
│  PostgreSQL   │   │   Redis Cache    │  │  R2 / S3     │
│  (Primary DB) │   │  (Future)        │  │  (PDFs/Docs) │
└───────────────┘   └──────────────────┘  └──────────────┘

        INGESTION (Celery Workers)
┌──────────────────────────────────────────────────────────────┐
│  ADRScraper │ PRSScraper │ LokSabhaScraper │ ECIScraper      │
│  Each: download → validate → parse → normalize → store       │
└──────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
netacheck/
├── backend/
│   ├── pyproject.toml
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   ├── src/
│   │   └── netacheck/
│   │       ├── __init__.py
│   │       ├── core/                    # App-wide concerns
│   │       │   ├── config.py            # Pydantic Settings
│   │       │   ├── database.py          # Engine + session factory
│   │       │   ├── dependencies.py      # FastAPI DI providers
│   │       │   ├── exceptions.py        # Domain exceptions
│   │       │   └── logging.py           # Structured logging
│   │       ├── domain/                  # Pure domain models (no DB)
│   │       │   ├── politician.py
│   │       │   ├── source.py
│   │       │   └── grading.py
│   │       ├── models/                  # SQLAlchemy ORM models
│   │       │   ├── base.py
│   │       │   ├── politician.py
│   │       │   ├── geography.py
│   │       │   ├── legislature.py
│   │       │   ├── source.py
│   │       │   ├── criminal.py
│   │       │   ├── assets.py
│   │       │   ├── attendance.py
│   │       │   ├── legislative.py
│   │       │   ├── election.py
│   │       │   ├── affidavit.py
│   │       │   ├── correction.py
│   │       │   └── audit.py
│   │       ├── repositories/            # Data access layer
│   │       │   ├── base.py
│   │       │   ├── politician.py
│   │       │   ├── source.py
│   │       │   └── report_card.py
│   │       ├── services/                # Business logic
│   │       │   ├── politician_service.py
│   │       │   ├── report_card_service.py
│   │       │   ├── search_service.py
│   │       │   └── pdf_service.py
│   │       ├── grading/                 # Isolated grading engine
│   │       │   ├── __init__.py
│   │       │   ├── engine.py
│   │       │   ├── metrics/
│   │       │   │   ├── attendance.py
│   │       │   │   ├── criminal.py
│   │       │   │   ├── assets.py
│   │       │   │   └── legislative.py
│   │       │   └── tests/
│   │       ├── ingestion/               # One module per provider
│   │       │   ├── base.py              # Abstract scraper
│   │       │   ├── policy.py            # robots.txt + rate limit
│   │       │   ├── adr/
│   │       │   │   ├── scraper.py
│   │       │   │   ├── parser.py
│   │       │   │   └── normalizer.py
│   │       │   ├── prs/
│   │       │   ├── lok_sabha/
│   │       │   ├── rajya_sabha/
│   │       │   └── eci/
│   │       ├── api/                     # FastAPI routers
│   │       │   ├── v1/
│   │       │   │   ├── router.py
│   │       │   │   ├── politicians.py
│   │       │   │   ├── search.py
│   │       │   │   ├── report_card.py
│   │       │   │   ├── compare.py
│   │       │   │   ├── pdf.py
│   │       │   │   ├── sources.py
│   │       │   │   ├── methodology.py
│   │       │   │   ├── corrections.py
│   │       │   │   └── admin.py
│   │       │   └── middleware/
│   │       │       ├── rate_limit.py
│   │       │       └── logging.py
│   │       └── pdf/                     # ReportLab PDF generation
│   │           ├── generator.py
│   │           ├── templates/
│   │           └── assets/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── fixtures/
├── frontend/
│   ├── package.json
│   ├── next.config.ts
│   ├── tailwind.config.ts
│   └── src/
│       ├── app/                         # Next.js App Router
│       │   ├── layout.tsx
│       │   ├── page.tsx                 # Landing
│       │   ├── search/
│       │   ├── politician/[slug]/
│       │   ├── compare/
│       │   ├── party/[slug]/
│       │   ├── state/[slug]/
│       │   ├── methodology/
│       │   ├── corrections/
│       │   └── about/
│       ├── components/
│       │   ├── ui/                      # Design system primitives
│       │   ├── politician/              # Politician-specific components
│       │   ├── report-card/
│       │   ├── source/                  # Source citation components
│       │   └── layout/
│       ├── lib/
│       │   ├── api.ts                   # API client
│       │   ├── types.ts                 # Shared TypeScript types
│       │   └── utils.ts
│       └── hooks/
├── docker/
│   ├── backend.Dockerfile
│   └── frontend.Dockerfile
├── docker-compose.yml
├── docker-compose.prod.yml
├── Makefile
├── .env.example
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── .pre-commit-config.yaml
└── README.md
```

---

## Database Schema

### Core Design Principles
1. **Every data value row links to a `SourceSnapshot`** — this is a FK constraint, not optional.
2. **Soft deletes** only on `Politician`, `CorrectionRequest`. Hard deletes never allowed on source or audit tables.
3. **Immutable history** — `SourceSnapshot`, `AffidavitEntry`, `CriminalCase`, `AssetDeclaration` rows are never updated. New ingestions create new rows with newer `effective_from` dates.
4. **Slug-based public identity** — `politician.slug` is the stable public key, never PK integers.

### Entity Relationship Summary

```
State ──< Constituency ──< Election ──< ElectionResult
                                              │
Party ──< PartyMembership ──< Politician >──┘
                                   │
                     ┌─────────────┼──────────────────┐
                     │             │                  │
              LegislativeTerm   Affidavit          AuditLog
                     │             │
              ┌──────┴──────┐      └──< AffidavitEntry >── SourceSnapshot
              │             │
     AttendanceRecord  LegislativeActivity >── SourceSnapshot
              │
         SourceSnapshot

CriminalCase >── SourceSnapshot
AssetDeclaration >── SourceSnapshot
GradeSnapshot >── (computed, no source FK — grades reference metrics which have sources)
CorrectionRequest >── CorrectionHistory
```

### Key Schema Tables (abbreviated)

| Table | Purpose | Notable Constraints |
|---|---|---|
| `state` | Indian states & UTs | Unique `iso_code` |
| `constituency` | Lok Sabha / Vidhan Sabha seats | FK to `state` |
| `political_party` | Parties with ECI registration | Unique `eci_id` |
| `politician` | Canonical politician identity | Unique `slug`, soft-delete |
| `politician_alias` | Name variants for dedup | FK to `politician` |
| `party_membership` | Time-bounded party affiliations | Overlapping ranges prevented via constraint |
| `election` | Election events | FK to `constituency` |
| `election_result` | Results per candidate | FK to `election`, `politician` |
| `legislative_term` | Sitting periods in parliament/assembly | FK to `politician`, `constituency` |
| `source_provider` | Registered data sources (ADR, PRS, etc.) | |
| `source_snapshot` | Immutable crawl records | Hash, URL, timestamp, parser version |
| `affidavit` | Nomination affidavit filing | FK to `election_result`, `source_snapshot` |
| `affidavit_entry` | Individual fields from affidavit | FK to `affidavit`, `source_snapshot` — **source required** |
| `criminal_case` | Criminal cases from affidavit | FK to `affidavit_entry`, legal status enum |
| `asset_declaration` | Asset line items | FK to `affidavit_entry` |
| `attendance_record` | Session attendance | FK to `legislative_term`, `source_snapshot` |
| `legislative_activity` | Questions, bills, debates | FK to `legislative_term`, `source_snapshot` |
| `grade_snapshot` | Computed grades per politician per version | Immutable after creation |
| `grade_metric_result` | Individual metric scores in a grade | FK to `grade_snapshot` |
| `correction_request` | Public correction submissions | Status workflow |
| `correction_history` | Audit trail of corrections applied | Immutable |
| `user_feedback` | General public feedback | |
| `audit_log` | Admin actions | Immutable |

---

## Phased Delivery Plan

### Phase 1 — Scaffolding & Infrastructure (Week 1)
**Goal**: Running skeleton with CI, Docker, linting, and an importable Python package.

Files to create:
- `backend/pyproject.toml` — dependencies, tool config (Black, Ruff, Mypy, Pytest)
- `backend/src/netacheck/core/config.py` — Pydantic Settings with env var support
- `backend/src/netacheck/core/database.py` — async SQLAlchemy engine + session factory
- `backend/src/netacheck/core/logging.py` — structlog JSON logger
- `backend/src/netacheck/core/exceptions.py` — domain exception hierarchy
- `backend/alembic/env.py` — Alembic with async support
- `docker-compose.yml` — postgres + backend + frontend services
- `docker/backend.Dockerfile`
- `docker/frontend.Dockerfile`
- `.env.example`
- `Makefile` — `make dev`, `make test`, `make migrate`, `make lint`
- `.github/workflows/ci.yml`
- `.pre-commit-config.yaml`

**Verification**: `make dev` starts postgres + backend with health endpoint returning 200.

---

### Phase 2 — Database Schema & Migrations (Week 1–2)
**Goal**: Complete normalized schema, all migrations, seed data for testing.

Files to create:
- All `backend/src/netacheck/models/*.py` — SQLAlchemy 2.x models
- `alembic/versions/0001_initial_schema.py`
- `backend/src/netacheck/repositories/base.py` — generic async repository
- `backend/src/netacheck/repositories/politician.py`
- `backend/src/netacheck/repositories/source.py`
- `backend/tests/fixtures/seed.py` — seed data (5 test politicians)

**Verification**: `make migrate` applies cleanly. `make seed` populates test data. All FK constraints enforced.

---

### Phase 3 — ADR Ingestion Pipeline (Week 2–3)
**Goal**: Scrape MyNeta/ADR affidavit data for 20 Lok Sabha MPs (pilot batch).

Files to create:
- `backend/src/netacheck/ingestion/base.py` — `AbstractScraper` protocol
- `backend/src/netacheck/ingestion/policy.py` — robots.txt checker, rate limiter
- `backend/src/netacheck/ingestion/adr/scraper.py` — HTTP + pagination
- `backend/src/netacheck/ingestion/adr/parser.py` — HTML → raw dict
- `backend/src/netacheck/ingestion/adr/normalizer.py` — raw dict → domain entities

**Verification**: Running the ADR scraper for 20 pilot MPs populates `affidavit`, `affidavit_entry`, `criminal_case`, `asset_declaration` with source references. Re-running is idempotent.

---

### Phase 4 — PRS Legislative Activity Pipeline (Week 3)
**Goal**: Scrape PRS India for attendance and legislative activity.

Files to create:
- `backend/src/netacheck/ingestion/prs/scraper.py`
- `backend/src/netacheck/ingestion/prs/parser.py`
- `backend/src/netacheck/ingestion/prs/normalizer.py`

---

### Phase 5 — Grading Engine (Week 3–4)
**Goal**: Isolated, fully-tested grading engine.

Files to create:
- `backend/src/netacheck/grading/engine.py` — `GradingEngine` with version
- `backend/src/netacheck/grading/metrics/attendance.py` — pure function
- `backend/src/netacheck/grading/metrics/criminal.py` — pure function
- `backend/src/netacheck/grading/metrics/assets.py` — pure function
- `backend/src/netacheck/grading/metrics/legislative.py` — pure function
- `backend/src/netacheck/grading/tests/` — 100% coverage target

Grading Output Contract:
```python
@dataclass
class MetricResult:
    metric_name: str
    raw_value: str | int | float
    grade: Literal["A", "B", "C", "D", "F", "N/A"]
    reason: str                    # factual, no editorial
    source_references: list[str]   # source_snapshot IDs
    confidence: Confidence         # enum
    engine_version: str

@dataclass  
class ReportCardGrade:
    politician_slug: str
    overall_grade: str
    metrics: list[MetricResult]
    computed_at: datetime
    engine_version: str
    data_as_of: datetime           # oldest source timestamp in computation
```

---

### Phase 6 — REST API (Week 4–5)
**Goal**: Full documented API with pagination, filtering, rate limiting.

Key endpoints:
```
GET  /api/v1/politicians                    # paginated list
GET  /api/v1/politicians/{slug}             # canonical politician
GET  /api/v1/politicians/{slug}/report-card # computed report card
GET  /api/v1/politicians/{slug}/sources     # all source citations
GET  /api/v1/politicians/{slug}/criminal-cases
GET  /api/v1/politicians/{slug}/assets
GET  /api/v1/politicians/{slug}/attendance
GET  /api/v1/politicians/{slug}/legislative-activity
GET  /api/v1/search?q=&state=&party=
GET  /api/v1/compare?slugs=slug1,slug2
GET  /api/v1/parties/{slug}
GET  /api/v1/states/{slug}
GET  /api/v1/methodology
POST /api/v1/corrections
GET  /api/v1/corrections/{id}
GET  /api/v1/pdf/{slug}                     # triggers PDF generation
GET  /api/v1/health
POST /admin/v1/ingestion/trigger
GET  /admin/v1/ingestion/status
```

---

### Phase 7 — Frontend (Week 5–7)
**Goal**: Next.js App Router frontend with SSR, SEO, accessibility.

Design Language: **"Government Dossier"**
- Off-white/cream base: `#FAF7F2`
- Dark ink text: `#1C1917`
- Grade stamp red: `#C0392B` (used ONLY for grade stamps, never sentiment)
- Accent teal: `#0D6E6E`
- Monospace for all numbers
- Paper texture via CSS `noise` filter
- No animations except subtle page transitions

Pages:
1. **Landing** — tagline, search bar, methodology link, latest updates
2. **Search** — filters by state, party, constituency, election year
3. **Politician** — full report card with source citations on every datum
4. **Compare** — side-by-side for up to 3 politicians
5. **Party** — aggregated stats per party
6. **State** — aggregated stats per state
7. **Methodology** — how every grade is computed, with formula
8. **Corrections** — submit / view correction requests
9. **About** — mission, legal disclaimer, privacy

Frontend Source Citation Pattern:
Every metric component receives a `sources` prop containing `SourceCitation[]`. If `sources.length === 0`, the component renders `[DATA UNAVAILABLE]` instead of a value. This is enforced at the TypeScript type level — the value field is `string | null` and the component is typed to only render when value is non-null with sources present.

---

### Phase 8 — PDF Generation (Week 7)
**Goal**: Server-side ReportLab PDF that matches the web UI design.

Features:
- Grade stamp (circle with letter, generated as PDF vector)
- Full citation footnotes
- QR code linking to live politician page
- Generation timestamp + engine version footer
- Page numbers
- Methodology note on last page

---

### Phase 9 — Search & Compare (Week 7–8)
**Goal**: Full-text search with Postgres, comparison engine.

- `tsvector` columns on `politician.name`, `constituency.name`, `party.name`
- GIN index
- Weighted ranking (name > party > state)
- Compare endpoint supports 2–3 politicians, returns aligned metric matrices

---

### Phase 10 — Deployment (Week 8–9)
**Goal**: Production-ready deployment.

- Backend → Railway (Docker)
- Frontend → Vercel
- DB → Supabase (managed Postgres) or Railway Postgres
- R2 → Cloudflare for PDF storage
- GitHub Actions deploy pipeline

---

### Phase 11 — Scaling (Ongoing)
- 543 Lok Sabha MPs fully ingested
- Rajya Sabha
- State-level MLAs
- RTI import API
- Redis caching layer
- Materialized views for state/party summaries

---

## Open Questions for User Review

> [!IMPORTANT]
> **Q1: Ingestion Scheduling**
> Should the ingestion workers be Celery (heavyweight, well-known) or Dramatiq (lighter, simpler)? For the MVP scope, Dramatiq with Redis backend is simpler to operate. Celery is better if we need complex DAGs later. Which do you prefer?

> [!IMPORTANT]
> **Q2: Authentication for Admin**
> The spec says "admin dashboard secured" but doesn't define the mechanism. Options: (a) API key header only, (b) JWT with a simple admin user table, (c) OAuth via GitHub/Google. For MVP, API key is simplest. Preference?

> [!IMPORTANT]
> **Q3: Frontend: TailwindCSS Confirmation**
> The spec explicitly says TailwindCSS. Which version? v3 (stable, widely documented) or v4 (alpha, JIT-only, breaking changes)? Recommend **v3** for a production platform.

> [!IMPORTANT]
> **Q4: Pilot Batch Politicians**
> The spec says 20–50 MPs for the ADR pilot. Should I pick a representative cross-section (by party, by state), or do you have a specific list to start with?

> [!IMPORTANT]
> **Q5: Grading Weights**
> The grading engine needs weights for each metric. Until there is a policy committee to set these, the weights should be community-configurable (stored in DB, not hardcoded). Default weights are proposed as:
> - Attendance: 25%
> - Criminal Cases (pending): 20%
> - Asset Growth (election-over-election): 15%
> - Legislative Activity: 25%
> - Affidavit Completeness: 15%
> Does this distribution align with your vision?

> [!WARNING]
> **Q6: PDF Storage**
> PDFs can be generated on-demand (no storage needed, but slow) or pre-generated and cached on R2 (fast, but needs invalidation logic when data updates). Which approach for MVP?

> [!NOTE]
> **Q7: Monorepo vs Separate Repos**
> The plan assumes a monorepo (`netacheck/backend`, `netacheck/frontend`). This simplifies CI and shared type generation. Acceptable?

---

## Verification Plan

### Automated Tests
```bash
# Backend
pytest backend/tests/ --cov=netacheck --cov-report=term-missing

# Grading engine (isolated)
pytest backend/src/netacheck/grading/tests/ -v

# Frontend type checking
npx tsc --noEmit

# Frontend linting
npx eslint src/

# API integration tests
pytest backend/tests/integration/ -v
```

### Manual Verification
- Health endpoint returns 200 with version info
- Scraper pilot run populates 20 MPs with full source citations
- Politician page renders with no unsourced data
- Source links resolve to live government URLs
- PDF downloads and contains QR code, citations, and methodology footer
- Correction submission creates a `CorrectionRequest` record in pending state
- Re-running scraper produces no duplicate `SourceSnapshot` records

---

## Execution Order

I will implement Phase 1 first and await your confirmation before proceeding to Phase 2.

Each phase will be delivered as a series of focused, PR-sized tasks with:
1. Explanation of why the file/change exists
2. Full production-quality code
3. Architectural decision notes
4. Test suggestions

**Ready to begin Phase 1 upon your approval.**
