# JouleMitra — Phase 1 (Simulator → API → Database → Dashboard, no ML)

Authoritative spec: `docs/spec/MASTER_SPEC.md`. Phase 1 scope: `docs/IMPLEMENTATION_PLAN.md`
Phase 1 section. Simulator constants: `docs/ASSUMPTIONS.md`.

## Prerequisites

- Python 3.11, Docker (running), PostgreSQL 16 via compose.

## Setup

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
Copy-Item .env.example .env
docker compose up -d db
.venv\Scripts\python scripts/setup/init_db.py
```

## Run

```powershell
# Backend API (http://localhost:8000)
.venv\Scripts\python -m uvicorn apps.backend.main:app --port 8000

# Simulator: 24h NORMAL scenario, post to API (uses ?backfill=true, see docs/ASSUMPTIONS.md A10)
.venv\Scripts\python -m apps.simulator --scenario NORMAL --hours 24 --step-s 60 --seed 1 --post
# ... or write CSVs instead:
.venv\Scripts\python -m apps.simulator --scenario NORMAL --hours 24 --seed 1 --csv data/simulated/normal_24h.csv

# Dashboard (http://localhost:8501, reads ONLY from the API)
.venv\Scripts\python -m streamlit run apps/dashboard/app.py
```

Only the `NORMAL` scenario exists in Phase 1; any other `--scenario` exits with
`NotImplementedError` (Phase 2+ work).

## Tests (real Postgres test database, nothing silently skipped)

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://joulemitra:joulemitra@localhost:5432/joulemitra_test"
.venv\Scripts\python -m pytest -q
```

## Docker (db + backend + dashboard, one shared Dockerfile)

```powershell
docker compose up -d --build
curl http://localhost:8000/health/components
curl http://localhost:8501/   # HTTP 200
```

## Layout (Phase 1 files)

`apps/backend` (FastAPI), `apps/simulator` (NORMAL scenario engine),
`apps/dashboard` (Streamlit, API-only), `services/ingestion` (validation),
`database/migrations` + `database/seeds` (plain SQL), `scripts/setup` + `scripts/seed`,
`data/schemas/telemetry.json`, `tests/{unit,api,integration}`.
