# JouleMitra — Implementation Plan

Planning doc only. Authoritative spec: `docs/spec/MASTER_SPEC.md` §12 (build
order), §4 (repo layout). Related: `docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`,
`docs/PROJECT_AUDIT.md`.

Rule (spec §12): vertical slices — the app is runnable after each phase.
Rule (spec p.168): build data → model → analytics → decision → verification →
UI. A dashboard with fake numbers is never acceptable.

---

## Phase 1 — Simulator → API → Database → Dashboard (no ML)

**Scope:** repo skeleton, config, telemetry schema; parameterised factory
simulator (all spec §5 signals + NORMAL scenario at minimum); PostgreSQL
schema for Phase-1 tables; FastAPI ingestion endpoints; one Streamlit page
showing real stored simulator data end to end.

**Files/folders to create (file level):**

```text
pyproject.toml                      # pinned deps, ruff/pytest config (see §8)
.env.example                        # DB URL, timezone, thresholds placeholder
.gitignore                          # .env, __pycache__, data blobs, *.db
docker-compose.yml                  # backend, db (Postgres), dashboard (no mqtt — Phase 6)
README.md  LICENSE                 # LICENSE needs owner decision (AUDIT §10)
apps/backend/main.py                # FastAPI app factory, /health, /health/components
apps/backend/routers/telemetry.py   # POST /telemetry, GET /telemetry
apps/backend/routers/production.py  # POST /production, GET /production
apps/backend/routers/sites.py       # GET /sites, /machines, /machines/{id}
apps/backend/schemas.py             # Telemetry + Production Pydantic schemas (units, tz-aware ts, source tag)
apps/backend/db.py                  # engine/session, Asia/Kolkata handling
apps/simulator/factory_simulator.py # scenario engine entry point
apps/simulator/machine_models.py    # per-machine-type physics (furnace/compressor/pump/motor/generic)
apps/simulator/fault_generator.py   # anomaly-scenario injector (IDLE_WASTE etc. — stub NORMAL-only ok in P1)
apps/dashboard/app.py               # Streamlit home: real stored simulator data via API — energy (kWh), power (kW), production, machine state, per machine, source=SIMULATED visible (no SEC/cost/CO₂e, no placeholders)
apps/dashboard/pages/overview.py    # Overview section (spec §10), API-backed only
services/ingestion/validate.py      # missing/duplicate/out-of-order/impossible/stale/spike/unit checks + quality flag
database/migrations/001_phase1.sql  # Site, Machine, Sensor, Telemetry, ProductionRecord, MachineState, User, AuditEvent
database/seeds/phase1.sql           # 1 site, 3–4 machines (no tariff — Tariff table/seed is Phase 5)
data/schemas/telemetry.json         # JSON-schema mirror of the Pydantic telemetry schema
tests/api/test_ingestion.py         # invalid/missing/malformed/duplicate/zero-production cases
tests/integration/test_e2e_smoke.py # simulator → API → DB → dashboard-data smoke test
scripts/setup/init_db.py            # create db + run migrations + seeds
scripts/seed/seed_phase1.py         # load seed site/machines
```

**Phase-1 DB tables** (subset of DATA_MODEL.md; full definitions there):
`Site`, `Machine`, `Sensor`, `Telemetry` (with `source`, quality flag,
dedup key), `ProductionRecord` (with `source`), `MachineState`, `User`,
`AuditEvent`.

**Acceptance test (runnable):**

```bash
docker compose up -d db
python scripts/setup/init_db.py
python apps/simulator/factory_simulator.py --scenario NORMAL --hours 24
pytest tests/integration/test_e2e_smoke.py -q
# then: backend serves GET /telemetry rows == simulator packets sent (minus
# quarantined), and the Streamlit Overview renders energy-today/production-today
# from GET /dashboard/summary with source=SIMULATED visible.
```

**Explicitly out of scope:** baseline/SEC analytics, anomaly detection,
machine-health adapter, optimisation, recommendations, verification, cost/
carbon math, MQTT ingestion path, Modbus, auth beyond foundation tables,
React, hardware.

---

## Phase 2 — SEC → baseline → actual-vs-expected → anomaly → alerts

**Scope:** `services/energy/` (SEC with not-computable states; interpretable
expected-energy baseline, linear regression first; actual vs expected +
deviation %); L1 rules + L2 rolling-median/MAD/z-score anomaly detection;
`AnomalyEvent` + `EnergyBaseline` persistence; Alerts dashboard section;
`GET /energy/summary /energy/baseline /energy/anomalies`, `GET /dashboard/summary`.

**Files/folders:** `services/energy/sec.py`, `services/energy/baseline.py`,
`services/energy/anomaly.py`, `ml/baseline/` (training harness: unit-level
splits, always-a-baseline, config-logged runs — PBL discipline),
`database/migrations/002_phase2.sql` (EnergyBaseline, AnomalyEvent),
`apps/dashboard/pages/energy.py`, `apps/dashboard/pages/alerts.py`,
`tests/unit/test_sec.py`, `test_baseline.py`, `test_anomaly.py`
(zero/missing/rejected production, idle, incomplete batches).

**Acceptance test:**

```bash
python apps/simulator/factory_simulator.py --scenario IDLE_WASTE --hours 48
pytest tests/unit/test_sec.py tests/unit/test_baseline.py tests/unit/test_anomaly.py -q
# then: GET /energy/anomalies returns the injected idle-waste window with
# score+severity+baseline comparison, and PRODUCTION_SURGE scenario raises no
# waste anomaly (legitimate load distinguished).
```

**Out of scope:** machine health, optimisation, recommendations, cost/carbon,
MQTT/edge, hardware.

## Phase 3 — PBL machine-health adapter → health score → energy-health correlation

**Scope:** `ml/machine_health/adapter.py` (`MachineHealthModel` with
`predict/score/explain`); ONNX Runtime loading of the 3-artifact layout;
`MachineHealth` persistence; correlation clue logic (never causation);
Equipment dashboard section; `GET /machine-health`. Adapter raises
`NotImplementedError` until a bearing/foundry checkpoint exists; C-MAPSS
turbofan weights are never loaded as foundry health (spec §6).

**Files/folders:** `ml/machine_health/adapter.py`, `ml/machine_health/model_card.md`
(purpose, I/O, training data, preprocessing, validation, limitations,
inference location, latency — spec §11), `ml/models/` registry +
manifests, `services/machine_health/correlate.py`,
`database/migrations/003_phase3.sql` (MachineHealth),
`apps/dashboard/pages/equipment.py`, `tests/unit/test_health_adapter.py`
(adapter contract incl. missing-model refusal; parity vs export when a
checkpoint lands).

**Acceptance test:**

```bash
pytest tests/unit/test_health_adapter.py -q
# then: with no checkpoint, GET /machine-health returns "model unavailable"
# (never a stub number); with a test checkpoint, predict/score/explain round-trip
# a (L,S) window and attention maps to sensor names with the usage-not-causation note.
```

**Out of scope:** retraining on foundry data (needs plant data — later),
optimisation, recommendations, cost/carbon, edge.

## Phase 4 — Process efficiency → OR-Tools scheduling → recommendations

**Scope:** `services/energy/process_efficiency.py` (idle time, excess holding,
needless runtime, start/stop cycling, state transitions); OR-Tools tariff-aware
scheduler (min cost / weighted cost+peak+delay; hard constraints per spec §6);
`services/recommendations/` (spec §6 field set + acknowledge); Recommendations
+ Optimisation dashboard sections; `POST /optimization/run`,
`GET /optimization/schedule`, `GET /recommendations`,
`POST /recommendations/{id}/acknowledge`.

**Files/folders:** `services/optimization/scheduler.py`,
`services/optimization/constraints.py`, `services/recommendations/engine.py`,
`database/migrations/004_phase4.sql` (Recommendation),
`apps/dashboard/pages/recommendations.py`,
`apps/dashboard/pages/optimization.py`, `tests/unit/test_optimizer.py`
(constraint enforcement, production preserved), `test_recommendations.py`
(rules, no fabricated money figures).

**Acceptance test:**

```bash
python -m pytest tests/unit/test_optimizer.py tests/unit/test_recommendations.py -q
# then: POST /optimization/run on seeded TARIFF_SHIFT data returns a recommended
# schedule with lower cost, same required production, and every expected-impact
# figure tagged PROJECTED with confidence.
```

**Out of scope:** intervention execution, verification, carbon/cost engines
(Phase 5), MQTT/edge, hardware. No autonomous control — decision support only.

## Phase 5 — Intervention → verification → cost → carbon → before/after

**Scope:** `Intervention` recording (simulated action changes simulator physics
— no magic drops); `services/verification/` comparability guards
(energy↓? production≈? SEC↓? quality kept? conditions comparable?);
`services/carbon/` (factor as data: unit, source, geography, year) + tariff
cost math; Verification dashboard section; `POST /interventions`,
`GET /verification`.

**Files/folders:** `services/verification/compare.py`,
`services/carbon/carbon.py`, `services/carbon/cost.py`,
`database/migrations/005_phase5.sql`
(Intervention, VerificationResult, Tariff, EmissionFactor),
`database/seeds/tariffs.sql`, `database/seeds/emission_factors.sql`
(sourced, labelled), `apps/dashboard/pages/verification.py`,
`tests/unit/test_verification.py`, `test_cost_carbon.py`
(missing-tariff/factor, incomparable-conditions cases).

**Acceptance test:**

```bash
python scripts/demo/run_demo.py
# then: full story — normal data → degradation + idle → detect → recommend →
# intervene → verify — ends with a VerificationResult showing before/after
# energy, SEC, cost, CO₂e, production, quality + deltas, all source-tagged;
# rerunning the demo against shifted operating conditions yields
# "Unable to verify savings under current conditions."
```

**Out of scope:** MQTT/edge swap, Modbus, hardware, React.

## Phase 6 — MQTT → simulated edge gateway → Modbus abstraction → buffering/offline

**Scope:** Mosquitto via compose; `edge/mqtt/` topic layer; `edge/gateway/`
simulated RPi gateway (validate/timestamp/SQLite buffer/publish/resync,
per-machine window state, PBL `edge/app.py` skeleton); `edge/modbus/`
interface + `MockModbusDevice`; HTTP ingest retained for dev; gateway latency
percentiles via PBL `bench.py` pattern; `/health/components` full wiring.

**Files/folders:** `edge/gateway/app.py`, `edge/gateway/buffer.py`,
`edge/mqtt/client.py`, `edge/mqtt/topics.py`, `edge/modbus/device.py`,
`edge/modbus/mock_device.py`, `edge/device_simulator/node.py`
(PBL `fake_node.py` pattern incl. replay), `tests/simulation/` (drop-MQTT /
drop-DB / corrupt / stale packet cases), `docker-compose.yml` (mqtt service).

**Acceptance test:**

```bash
docker compose up -d db mqtt backend dashboard
python edge/device_simulator/node.py --degrade &
docker compose stop mqtt && sleep 30 && docker compose start mqtt
pytest tests/simulation/ -q
# then: zero record loss across the outage (SQLite buffer resynced), gaps
# counted in /health, dashboard streams resume.
```

**Out of scope:** physical ESP32/RPi, real Modbus hardware, AutoCAD/Fusion
artifacts.

## Phase 7 — Hardware + supporting artifacts (never delay software)

**Scope:** ESP32 energy-meter node firmware (Modbus reads via Phase-6
abstraction; PBL dual-core timing architecture); RPi gateway deployment
(systemd unit per PBL `deploy/` pattern); AutoCAD Electrical schematic (power/
signal/protection) + Fusion 360 enclosure as supporting artifacts.

**Files/folders:** `edge/firmware/esp32/` (new energy node; keep vibration
node as health complement), `deploy/` (service units, Pi setup notes),
`docs/deployment/` (wiring, provisioning — no committed secrets),
`cad/electrical/`, `cad/enclosure/` (references/exports only).

**Acceptance test:**

```bash
pio run -t upload -t monitor   # from edge/firmware/esp32
# then: live MEASURED packets flow ESP32 → gateway → backend → dashboard with
# source=MEASURED, and unplugging a sensor yields a stale badge (not silent zeros).
```

**Out of scope:** everything software (must already work); cloud sync
(optional, later); any direct control of furnaces/motors/actuators/safety
systems (forbidden by spec §6 — human-in-the-loop only).

---

## 8. Dependency list

**Python packages** (`pyproject.toml`, pinned; floor versions from PBL pins
where shared): `fastapi==0.115.6`, `uvicorn[standard]==0.34.0`,
`pydantic==2.10.4`, `pydantic-settings`, `sqlalchemy`, `psycopg[binary]`,
`alembic` (or plain SQL migrations), `numpy==2.2.1`, `pandas>=2.2`,
`scipy>=1.14`, `scikit-learn>=1.5`, `or-tools`, `paho-mqtt`, `pymodbus`,
`streamlit`, `plotly`, `onnxruntime>=1.19` (edge/gateway + adapter),
`torch>=2.4` (training only, never on Pi), `onnx>=1.17` (export only),
`pytest>=8.0`, `httpx>=0.27`, `ruff`, `tzdata`. `xgboost` deferred (only if
linear baseline is measurably insufficient — spec §6 "start simple").

**External services:** PostgreSQL 16 (TimescaleDB-ready extension when
available), Mosquitto MQTT broker, all via `docker-compose.yml`
(backend, db, mqtt, dashboard services). No cloud dependency; offline-first
per spec §11 failure modes.

---

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Simulator tuned to look good (validates nothing) | M | H | Document irreducibility floor per scenario (PBL synthetic-docstring pattern); acceptance tests assert detection, not accuracy figures |
| Simulated savings presented as real | M | H | Evidence-source tags enforced at schema level (§ARCHITECTURE §4); demo/figures generated from tagged artifacts |
| C-MAPSS metrics mistaken for foundry performance | M | H | Adapter refuses turbofan weights; ML_MODELS doc repeats the boundary; spec §2 labels |
| Baseline confounds legitimate load with waste | H | M | PRODUCTION_SURGE negative-test in Phase 2 acceptance; production-normalised baseline required (no global averages) |
| Optimiser infeasible / ignored constraints | M | M | Hard-constraint tests; infeasibility returns binding constraints, never a partial schedule |
| MQTT/DB outage loses data | M | H | SQLite buffer + resync (Phase 6 sim test kills broker mid-stream); idempotency keys |
| Scope creep (ERP/SCADA/generic IoT/deep learning) | H | M | Spec §"What We Are NOT Building" enforced per-phase out-of-scope lists above |
| unify-rul license blocks code reuse | M | M | Owner decision pre-Phase 3; fallback is clean-room re-implementation from AUDIT contracts |
| No plant data for validation | H | H | Simulator + honesty labels carry the prototype; every PROJECTED figure says "Requires plant validation" |
| Timezone/unit bugs in energy math | M | H | tz-aware timestamps + Asia/Kolkata display from Phase 1; explicit units on every schema field; quarantine on mismatch |

---

## 10. Decisions needed from owner

1. **PostgreSQL-in-Docker vs SQLite for local dev** — spec §3.5 says
   PostgreSQL (TimescaleDB-ready); SQLite would simplify Phase 1 but breaks
   the Timescale path. Default if no answer: PostgreSQL in compose (spec wins).
2. **Python version** — 3.11 (challenge background) vs 3.12+. Default: 3.11
   (matches background stack; PBL pins install cleanly).
3. **unify-rul license** — add a LICENSE file permitting reuse, or direct
   clean-room implementation (blocks any Phase 3+/6 copying — see AUDIT §10).
4. **Tariff + emission-factor sources for seeds** — actual plant tariff order
   / published grid factor vs illustrative placeholders (placeholders ship
   ASSUMPTION-tagged either way; real sources preferred).
5. **Machine types for the first demo** — foundry/induction-furnace-first per
   spec, or compressor-first (demo script currently assumes compressor
   degradation + idle; confirm).
6. **TimescaleDB from day one vs plain Postgres with Timescale-ready schema** —
   default: plain Postgres, hypertable-compatible schema (simpler local setup).
