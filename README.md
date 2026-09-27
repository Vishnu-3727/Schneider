# JouleMitra — Phase 4 (optimisation → recommendations, human-in-the-loop)

Authoritative spec: `docs/spec/MASTER_SPEC.md`. Phase 1 committed (de875e9);
Phase 2 scope: `docs/IMPLEMENTATION_PLAN.md` Phase 2 section. Simulator
constants: `docs/ASSUMPTIONS.md`. Model cards: `docs/ML_MODELS.md`
(baseline v1-linear; health `statistical-v1`; external `pbl-rul` adapter;
CP-SAT scheduler + recommendation rules). Scenarios: `docs/SIMULATION.md`.
Latest verification numbers: see docs/VALIDATION.md (Phase 2 table; Phase 3
section; Phase 4 section to be filled by manager from live run). Do not
begin Phase 5 (no intervention simulation, no savings verification).

Phase 3 status: health interface (`MachineHealthModel` + registry),
native `statistical-v1` (per-machine, state-conditioned median + MAD
reference; `POST /machine-health/fit|/score`, `GET /machine-health`,
`GET /machine-health/models`), energy + health correlation
(`GET /insights`: ENERGY_ONLY / HEALTH_ONLY / COINCIDENT /
ENERGY_ONLY_HEALTH_UNAVAILABLE, causation language banned), PBL adapter
(`pbl-rul`: UNAVAILABLE without a local artifact, always OUT_OF_DOMAIN
for factory machines — scoring them always uses `statistical-v1`),
dashboard Equipment + Insights views (API-only; state as text + symbol),
and the B1 physics fix (health-only degradation keeps voltage/current/
power NORMAL; `energy_penalty > 0` raises power AND current at nominal
voltage). 118 pre-existing tests preserved; PBL adds unit + integration
tests including an optional ONNX test (runs when `PBL_TEST_ONNX_PATH`
points at a local artifact and the `[pbl]` extra is installed).

Phase 4 status: tariff-aware CP-SAT scheduling (`POST /optimization/run`,
`GET /optimization/schedule`, current vs recommended, projected energy /
peak / cost / production + per-state breakdown, INFEASIBLE explanations,
deterministic budget with a wall-clock TIMEOUT safety net) and a pure-rule
recommendation engine (`POST /recommendations/generate`,
`GET /recommendations`, `POST /recommendations/{id}/acknowledge` with
404/409; idempotent; conflicts flagged, never dropped; accepted rows stay
NOT_VERIFIED; savings-fact wording banned) with Optimisation +
Recommendations dashboard views (API-only, PROJECTED ≠ MEASURED ≠
VERIFIED legend, illustrative tariff). All figures simulated/projected;
no intervention, no savings verification, no carbon/cost engine beyond the
projected schedule cost (Phase 5 work).

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
