# NetaCheck

> **"Every Politician. Every Record. Every Source."**

NetaCheck is an open-source civic transparency platform for India. It aggregates publicly available official records for Members of Parliament and State Legislators into a single, sourced, legally defensible report card.

**Hard constraint**: Every fact displayed on NetaCheck is linked to its source. If data has no source, it does not render.

---

## Status

🚧 **Active development** — Phase 1 (Scaffolding) complete.

| Phase | Status | Description |
|-------|--------|-------------|
| 1 | ✅ Complete | Project scaffolding, Docker, CI |
| 2 | 🔜 Next | Database schema & migrations |
| 3 | ⏳ Planned | ADR / MyNeta ingestion pipeline |
| 4 | ⏳ Planned | PRS Legislative Activity pipeline |
| 5 | ⏳ Planned | Grading engine |
| 6 | ⏳ Planned | REST API |
| 7 | ⏳ Planned | Next.js frontend |
| 8 | ⏳ Planned | PDF generation |
| 9 | ⏳ Planned | Search & Compare |
| 10 | ⏳ Planned | Deployment |

---

## Architecture

```
Frontend (Next.js / Vercel)
    ↕ HTTPS
Backend (FastAPI / Railway)
    ↕
PostgreSQL (primary DB)  +  Redis (task queue)  +  R2 (PDF storage)
    ↑
Ingestion Workers (Celery/Dramatiq)
  ADR | PRS | Lok Sabha | Rajya Sabha | ECI
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+
- Node.js 22+
- `make`

### 1. Clone and configure

```bash
git clone https://github.com/your-org/netacheck.git
cd netacheck
make setup        # installs deps + copies .env.example → .env
```

Edit `.env` and set at minimum:
- `POSTGRES_PASSWORD`
- `REDIS_PASSWORD`
- `SECRET_KEY` (`openssl rand -hex 32`)
- `ADMIN_API_KEY` (`python -c "import secrets; print(secrets.token_urlsafe(32))"`)

### 2. Start services

```bash
make dev          # starts Postgres + Redis + Backend (hot reload)
```

### 3. Apply migrations

```bash
make migrate
```

### 4. Verify

```bash
curl http://localhost:8000/api/v1/health
# → {"status":"ok","app":"NetaCheck",...}
```

### 5. View API docs (development only)

Open [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Development Commands

```bash
make help         # list all commands

make test         # run all tests
make test-unit    # unit tests only
make test-cov     # tests + open coverage report

make lint         # Ruff linter
make format       # Black formatter
make typecheck    # Mypy

make migrate              # apply all migrations
make migrate-create MSG="add politician table"  # create a new migration
make migrate-down         # rollback last migration

make seed         # load development seed data
```

---

## Project Structure

```
netacheck/
├── backend/              # FastAPI application
│   ├── src/netacheck/    # Source package
│   │   ├── core/         # Config, DB, logging, exceptions
│   │   ├── models/       # SQLAlchemy ORM models (Phase 2)
│   │   ├── repositories/ # Data access layer (Phase 2)
│   │   ├── services/     # Business logic (Phase 5+)
│   │   ├── grading/      # Isolated grading engine (Phase 5)
│   │   ├── ingestion/    # Data scrapers (Phase 3+)
│   │   ├── api/          # FastAPI routers (Phase 6)
│   │   └── pdf/          # ReportLab PDF generation (Phase 8)
│   ├── alembic/          # Database migrations
│   └── tests/            # Pytest test suite
├── frontend/             # Next.js application (Phase 7)
├── docker/               # Dockerfiles + init scripts
├── .github/workflows/    # GitHub Actions CI
├── docker-compose.yml
├── Makefile
└── .env.example
```

---

## Data Sources

| Source | Data Type | Status |
|--------|-----------|--------|
| ADR / MyNeta | Affidavits, criminal cases, assets | Phase 3 |
| PRS India | Attendance, legislative activity | Phase 4 |
| Lok Sabha | Question records, debates | Phase 6+ |
| Rajya Sabha | Question records, debates | Phase 6+ |
| Election Commission of India | Candidate data, results | Phase 6+ |
| Indian Kanoon | Court records (cross-reference) | Future |

---

## Legal & Ethics

- All data is sourced from publicly available official government records.
- No speculation, inference, or editorially loaded language.
- Criminal cases are displayed exactly as declared in election affidavits, with legal status (pending / charged / convicted / acquitted) clearly labeled.
- A [correction workflow](http://localhost:3000/corrections) allows politicians and the public to flag inaccuracies.
- Full [methodology documentation](http://localhost:3000/methodology) explains how every metric is computed.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Install pre-commit hooks: `make install-hooks`
4. Make changes and run `make check` before committing
5. Open a pull request against `develop`

---

## License

MIT License — see [LICENSE](LICENSE).

---

## Disclaimer

NetaCheck aggregates and presents publicly available records. It does not express any political opinion or make any editorial judgment. The platform is not affiliated with any political party, government body, or advocacy group.
