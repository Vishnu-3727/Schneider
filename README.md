# JouleMitra — software complete through Phase 6 (Phase 7 = deployment/wiring documentation only)

Authoritative spec: `docs/spec/MASTER_SPEC.md`. Phase 1 committed (de875e9);
Phase 2 scope: `docs/IMPLEMENTATION_PLAN.md` Phase 2 section. Simulator
constants: `docs/ASSUMPTIONS.md`. Model cards: `docs/ML_MODELS.md`
(baseline v1-linear; health `statistical-v1`; external `pbl-rul` adapter;
CP-SAT scheduler + recommendation rules). Scenarios: `docs/SIMULATION.md`.
Latest verification numbers: see docs/VALIDATION.md (Phases 2–5, all on
SIMULATED data). Phase 7 wiring/CAD reference docs exist (docs/deployment/, cad/);
ESP32/RPi firmware, deploy units and physical hardware are not done.

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
the projected schedule cost is the only Phase 4 money figure.

Phase 5 status: explicit lifecycle (PENDING_REVIEW → APPROVED | REJECTED →
APPLIED → MEASURED → VERIFIED | NOT_VERIFIED | NOT_COMPARABLE |
INSUFFICIENT_DATA; `services/verification/lifecycle.py`, 409 on any illegal
move, audit row per move; Phase 4 `ACCEPTED` renamed `APPROVED`).
`POST /interventions` (idempotent by key), `POST /interventions/{id}/verify`
(idempotent), `GET /interventions`, `GET /verification`,
`GET /emission-factors`. Verification is a counterfactual (IPMVP/ISO 50015
style): OLS on hourly production at t-1, t, t+1 fitted before the
intervention (never on state hours, which the intervention changes), with
ASHRAE Guideline 14 savings uncertainty. Only a VERIFIED saving is turned
into cost (illustrative tariff, labelled) and CO2 (CEA grid factor with
provenance). The simulator's chronic-holding waste and the REDUCE_IDLE /
REPAIR interventions (effectiveness, compliance, rebound) produce SUCCESS,
NO_EFFECT, WORSE, NOT_COMPARABLE and INSUFFICIENT_DATA from physics, not
from labels. Dashboard: Verification view.

Phase 6 status: `edge/` gateway (docs/DEPLOYMENT.md). MQTT (paho) and
Modbus TCP (pymodbus client, register maps as data with word/byte order,
scaling, sentinels, ranges) adapters produce canonical telemetry only. A
SQLite store-and-forward buffer delivers to the unchanged `/telemetry` and
`/production` API (dead-letter for malformed or rejected records, nothing
silently dropped, survives restarts and API outages). Mosquitto is in
docker compose. The device simulator publishes the same SimulatedFactory
data over MQTT and serves a simulated Modbus meter, so the simulator path
and the device path share one pipeline and identical analytics.

## Scope

All data is SIMULATED. The architecture is frozen: physical hardware,
ESP32 firmware, Raspberry Pi service units and CAD drawings are
intentionally NOT built. `docs/deployment/` shows how the same software
connects to a real meter via RS-485 → Modbus TCP converter → edge
gateway. Monitoring and human-in-the-loop only — no control of
furnaces, motors or safety systems.

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

### End-to-end demo

```powershell
# Full story through the API: ingest SIMULATED history -> baseline -> detect ->
# health -> insights -> optimise -> recommend -> approve -> intervene -> verify
.venv\Scripts\python scripts/demo/run_demo.py            # REDUCE_IDLE, proves a real saving verifies (VERIFIED)
.venv\Scripts\python scripts/demo/run_demo.py --shifted  # shifted operating conditions, proves the guardrail holds (NOT_COMPARABLE)
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
