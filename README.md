# JouleMitra — Phase 2 (baseline → SEC → anomaly → alerts)

Authoritative spec: `docs/spec/MASTER_SPEC.md`. Phase 1 committed (de875e9);
Phase 2 scope: `docs/IMPLEMENTATION_PLAN.md` Phase 2 section. Simulator
constants: `docs/ASSUMPTIONS.md`. Baseline model card: `docs/ML_MODELS.md`
(furnace: `good_production_kg` + heating/holding/idle hours, NNLS;
NMBE% + ASHRAE G14 acceptance; R² info-only).
Scenarios: `docs/SIMULATION.md`. Latest verification numbers:
see docs/VALIDATION.md. Do not begin Phase 3.

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
# Energy + Alerts pages: actual vs expected, SEC trend, baseline quality,
# anomaly list with acknowledge (all DERIVED from SIMULATED data)
```

Scenarios `NORMAL`, `IDLE_WASTE`, `HIGH_LOAD`, `PRODUCTION_SURGE` are
implemented (others raise `NotImplementedError`, Phase 3+). Reference +
scenario run, e.g. 7 NORMAL days then 24 h waste:
`.venv\Scripts\python -m apps.simulator --normal-days 7 --scenario IDLE_WASTE --hours 24 --post`

Phase-2 API: `POST /energy/baseline/fit`, `GET /energy/baseline`,
`GET /energy/summary` (hourly intervals + per-machine window aggregates:
Σactual, Σexpected, aggregate deviation %, window SEC + status,
non-productive kWh), `POST /energy/anomalies/detect`,
`GET /energy/anomalies`, `POST /energy/anomalies/{id}/acknowledge`;
`GET /dashboard/summary` now includes SEC + open-alert count.

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
