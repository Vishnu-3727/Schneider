# JouleMitra — Architecture

Planning doc only. Authoritative spec: `docs/spec/MASTER_SPEC.md` §3 (layers),
§4 (repo layout), §8 (API), §9 (MQTT/edge/Modbus), §11 (engineering rules,
failure modes). Related docs: `docs/DATA_MODEL.md`, `docs/IMPLEMENTATION_PLAN.md`,
`docs/PROJECT_AUDIT.md`.

Modular monolith (spec §3.5): one Python backend + one Streamlit dashboard +
simulator + edge gateway in a single repo with strict logical separation.
Not microservices. Backend API stays frontend-independent so React can replace
Streamlit later (spec §3.7).

---

## 1. Layered architecture (spec §3) with ASCII diagram

Seven layers. Hardware drivers never leak into business logic (spec §3.3);
simulated sources swap to real ones behind interfaces (see §5).

```text
 L1  PHYSICAL / FACTORY              L2  EDGE                    L3  COMMUNICATION
 ┌──────────────────────┐   ┌─────────────────────────┐   ┌─────────────────────┐
 │ energy meter, CT     │   │ ESP32 sensor-node       │   │ Modbus RTU/TCP      │
 │ V, I, kW, kVAr, PF,  │──▶│ (sample/validate/       │──▶│ (energy meter reg   │
 │ kWh, demand          │   │  timestamp/buffer)      │   │  reads; Mock now,   │
 │ vibration, temp,     │   │ Raspberry Pi gateway    │   │  Real later)        │
 │ current, RPM/runtime │   │ (validate/normalise/    │   │ MQTT (edge→backend) │
 │ machine state, prod  │   │  local metrics/light    │   │ OPC UA optional     │
 │ qty, batch/heat      │   │  inference/offline buf) │   │ HTTP ingest (dev)   │
 └──────────────────────┘   └─────────────────────────┘   └─────────────────────┘
        │ SIMULATED first: device_simulator emulates every       │
        │ signal on a normal PC — no hardware required          │
        └────────────────────────────────────────────────────────┘
                                     │
                                     v
 L4  BACKEND (Python + FastAPI, modular monolith)
 ┌──────────────────────────────────────────────────────────────────┐
 │ ingestion → validation → storage → energy analytics →            │
 │ machine-health → production/process → optimisation →             │
 │ recommendations → verification → dashboard/report APIs + auth    │
 └──────────────────────────────────────────────────────────────────┘
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        v                            v                            v
 L5  DATA                    L6  ANALYTICS                L7  APPLICATION
 PostgreSQL                  baseline / SEC /             Streamlit + Plotly
 (TimescaleDB-ready)         anomaly (L1+L2) /            dashboard (all §10
 Modular schema,             equipment health /           sections); backend
 16 entities                 process efficiency /         API independent
 (DATA_MODEL.md)             optimisation (OR-Tools) /    → React-ready
                             recommendations / cost /
                             carbon / verification
```

End-to-end chain (spec p.13): factory data → acquisition → edge processing →
validation → storage → energy analytics → machine-health analytics →
production analytics → optimisation → recommendation → dashboard →
simulated/real intervention → savings verification. The demo must walk this
whole chain (spec §12: `python scripts/demo/run_demo.py` eventually).

---

## 2. Component map (every software component + its folder)

Folders follow spec §4. "New" = to build; "Adapted" = pattern/contract from
unify-rul (see PROJECT_AUDIT.md §2, license decision pending).

### apps/

| Component | Folder | Role |
|---|---|---|
| Backend API | `apps/backend/` | FastAPI app, routers per spec §8, Pydantic schemas, error envelope (no stack traces), auth foundation |
| Dashboard | `apps/dashboard/` | Streamlit + Plotly pages for every spec §10 section; consumes backend API only, never the DB directly |
| Factory simulator | `apps/simulator/` | Parameterised physics: energy / production / equipment / process-state / tariff-ToU / emissions signals + 7 scenarios (spec §5); interventions change physical cause→effect consistently |

### services/ (business logic; no hardware imports)

| Component | Folder | Role |
|---|---|---|
| Ingestion + validation | `services/ingestion/` | Record validation (missing/duplicate/out-of-order/impossible/stale/spike/unit-mismatch), per-record quality status, idempotency |
| Energy analytics | `services/energy/` | SEC (+ not-computable states), expected-energy baseline `f(production, state, time, process)`, L1 rules + L2 rolling-median/MAD/z-score (+ optional Isolation Forest), energy anomaly events |
| Machine health | `services/machine_health/` | `MachineHealthModel` adapter (`predict/score/explain`) over the PBL ONNX contract; energy↔health correlation as diagnostic clue only |
| Optimisation | `services/optimization/` | OR-Tools CP-SAT tariff-aware scheduling; current vs recommended schedule, cost/energy/peak/production impact |
| Recommendations | `services/recommendations/` | Rule/analytics-based recommendation records (spec §6 field set), acknowledge flow, conflict handling |
| Verification | `services/verification/` | Before/after comparison with comparability guards; "Unable to verify…" when invalid |
| Carbon + cost | `services/carbon/` | CO₂e = energy × sourced factor; cost = energy × applicable tariff/ToU/demand |

### edge/

| Component | Folder | Role |
|---|---|---|
| Pi gateway (simulated on PC first) | `edge/gateway/` | Receive → validate → timestamp → SQLite buffer → MQTT publish; survives network loss, resyncs (adapted from PBL `edge/app.py` skeleton) |
| MQTT layer | `edge/mqtt/` | Topic helpers + paho-mqtt client wrapper for `joulemitra/{site}/{machine}/telemetry\|health\|state` and `joulemitra/{site}/production` |
| Modbus abstraction | `edge/modbus/` | `read_energy_meter/voltage/current/power/power_factor` interface; `MockModbusDevice` now, `RealModbusDevice` later |
| Device simulator | `edge/device_simulator/` | Software stand-in for ESP32 nodes (adapted from PBL `edge/fake_node.py`, incl. `--replay` of simulator output) |

### ml/

| Component | Folder | Role |
|---|---|---|
| Classical baselines | `ml/baseline/` | Linear regression expected-energy model + unit-level train/val splits + always-a-baseline harness (PBL discipline) |
| Anomaly models | `ml/anomaly_detection/` | L2 statistics + optional Isolation Forest training/eval, documented per spec §11 ML rule |
| Health adapter + weights | `ml/machine_health/` | Adapter code + `models/` checkpoint layout (`model.onnx`, `norm_stats.json`, `sensor_vocab.json`, `live_map.json`); C-MAPSS weights NEVER shipped as foundry health |
| Model registry | `ml/models/` | Versioned artifact store + `model.sha256` manifests (PBL `export_onnx.py` pattern) |

### data / database / tests / scripts / docs

| Component | Folder | Role |
|---|---|---|
| Schemas + samples | `data/schemas/` (+ `raw/`, `simulated/`, `processed/`) | Pydantic/JSON schemas; sample + simulated datasets (never presented as measured) |
| Migrations + seeds | `database/migrations/`, `database/seeds/` | DDL for the 16 entities; tariff/emission-factor/site/machine seed data (all illustrative values labelled) |
| Tests | `tests/{unit,integration,simulation,api}/` | SEC/baseline/anomaly/cost/carbon/optimiser/recommendation/verification units; API invalid-missing-malformed-duplicate-zero-production cases; MQTT/DB-down failure cases (spec §11) |
| Setup/seed/demo | `scripts/{setup,seed,demo}/` | Env setup, DB seeding, `run_demo.py` full-chain demo |
| Docs | `docs/{architecture,api,data-model,deployment,decisions}/` | This file + API/ML_MODELS/SIMULATION/DEPLOYMENT/DEMO/ASSUMPTIONS/VALIDATION + `decisions/ADR-*` |

---

## 3. Data flow (one telemetry record, happy path)

```text
sensor/simulator → (Modbus read | HTTP POST) → gateway validate/timestamp
 → MQTT joulemitra/{site}/{machine}/telemetry → backend POST /telemetry
 → record validation + quality flag → PostgreSQL Telemetry row
 → energy service: actual vs EnergyBaseline → SEC → AnomalyEvent?
 → machine_health: health score → correlation clue
 → recommendations (+ optimisation job on schedule)
 → dashboard (Overview/Energy/Equipment/Alerts/Recommendations/Optimisation/Verification)
 → operator acknowledges → Intervention recorded
 → verification: before/after energy, SEC, cost, CO₂e, production, quality
 → VerificationResult (or "Unable to verify…")
```

Production records flow on `joulemitra/{site}/production` → `POST /production`
→ `ProductionRecord` rows, joined to telemetry by (site, machine, time bucket)
for SEC and baseline features. Tariff/ToU and emission factors are reference
data (`Tariff`, `EmissionFactor` rows with source/geography/year), never
hard-coded.

---

## 4. Evidence-source tagging (spec §2, non-negotiable)

Every important quantitative value carries one source class, stored alongside
the value and shown in UI/API:

- **MEASURED** — from a real sensor through the gateway (Phase 7 wiring/CAD
  reference docs exist; no firmware/hardware yet, so nothing is MEASURED).
- **SIMULATED** — from `apps/simulator/` or `edge/device_simulator/`.
  Dashboard/API labels it "Simulation".
- **DERIVED** — computed from stored values (SEC, deviations, smoothed
  health, correlations). The formula/reference must be traceable.
- **EXTERNAL_REFERENCE** — PBL dataset metrics (C-MAPSS RMSE etc.), grid
  emission-factor publications, tariff orders. Always cited, never presented
  as factory measurements.
- **PROJECTED** — optimiser/expected-impact figures ("Prototype estimate",
  "Requires plant validation"). Never presented as guaranteed savings.
- **ASSUMPTION** — owner/analyst-supplied stand-ins (e.g. illustrative
  tariff). Recorded as ASSUMPTION / WHY / IMPACT.

Enforcement: `source` column on Telemetry, ProductionRecord, AnomalyEvent,
MachineHealth, Recommendation, VerificationResult; API response envelope
includes it; dashboard renders the tag next to every number; simulator output
is tagged SIMULATED at creation so it can never be mistaken downstream.

---

## 5. Simulated → real swap (no analytics rewrite)

| Seam | Simulated implementation | Real implementation | Swap mechanism |
|---|---|---|---|
| Factory signals | `apps/simulator/` scenario engine | ESP32 energy node + meter via Modbus | Same telemetry Pydantic schema + same MQTT topics; backend cannot tell the difference |
| Edge device | `edge/device_simulator/` process on PC | `edge/gateway/` on Raspberry Pi | Same `edge/mqtt/` topic contract; gateway code identical, only transport config changes |
| Meter reads | `edge/modbus/MockModbusDevice` | `edge/modbus/RealModbusDevice` (pymodbus) | One interface (`read_energy_meter/voltage/current/power/power_factor`); dependency-injected, drivers never imported by services |
| Health model | Adapter raising `NotImplementedError` / synthetic-health stub clearly named `Simulated*` | Retrained ONNX checkpoint + stats + vocab | Same `MachineHealthModel` predict/score/explain signatures; artifact swap via manifest |
| Tariff/factors | Illustrative seed rows (ASSUMPTION) | Plant tariff order / published grid factor | Same `Tariff`/`EmissionFactor` tables; only rows + source metadata change |

Rules (spec §11): mocks are named `Mock*`/`Simulated*`; unimplemented paths
raise `NotImplementedError` or `TODO`, never return plausible-looking fakes;
no hard-coded tariffs/factors/thresholds/URLs anywhere (all `.env` +
`.env.example` + DB reference rows).

---

## 6. Failure-mode handling table (spec §11 list — all 17)

| Failure mode | Detection | Handling | User-visible result |
|---|---|---|---|
| No internet | Gateway heartbeat / publish retry | SQLite buffer, keep serving local metrics; resync on reconnect | "Offline — buffering locally (N records)" |
| MQTT down | Broker watchdog, `/health/components` | Buffer to SQLite; HTTP-ingest fallback for dev | Degraded status, no data loss |
| DB down | Connection probe | Gateway keeps buffering; backend returns 503 with useful error (no stack trace) | "Storage unavailable — retrying" |
| Sensor disconnected | `last_packet_age_s > STALE_AFTER_S` (PBL pattern) | Mark stream stale; exclude from aggregates; keep last-known with age | Stale badge + age on dashboard |
| Bad readings | Validation rules (impossible values, spikes, unit mismatch) | Quarantine with per-record quality status; never silently drop | Quality flag on record + count in Overview |
| Missing/zero production | SEC guard | Return explicit "not computable" states, never inf/NaN | "SEC unavailable — no production in window" |
| Model unavailable | Artifact/manifest check at startup + `/health` | Refuse health inference; energy analytics continue; adapter raises, never stubs | "Health model unavailable" |
| Infeasible optimisation | OR-Tools solver status | Return infeasibility + binding constraints; keep current schedule | "No feasible schedule — see constraints" |
| Conflicting recommendations | Rule priority + severity ordering | Surface conflict explicitly; require human choice | Both shown, flagged as conflicting |
| Duplicate telemetry | (site, machine, ts, seq) idempotency key | Dedup on ingest (`duplicate` ack, PBL pattern) | Counter in health endpoint |
| Clock/timezone skew | ts validation vs server time; tz-aware everywhere, Asia/Kolkata display | Reject/quarantine out-of-window timestamps | Quality flag + warning |
| Unit errors | Explicit units on every field (kWh, kW, kWh/t, °C, A, V, kgCO₂e, INR) | Schema-level unit tags; mismatch → quarantine | "Unit mismatch" error, never silent conversion |
| Missing emission factor | FK lookup at carbon computation | Skip CO₂e with explicit reason; never invent factor | "CO₂e unavailable — no factor for period" |
| Missing tariff | Tariff lookup at cost computation | Skip cost with explicit reason; never invent tariff | "Cost unavailable — no tariff for period" |
| Insufficient baseline history | Coverage check before baseline fit | Fall back to labelled/simple reference; mark confidence low | "Baseline provisional — N days of history" |
| Corrupt payload | Pydantic validation (422, first errors only — PBL pattern) | Reject + `rejected` counter | 422 with useful message |
| Stale model stats | `model.sha256` vs manifest (PBL pattern) | Refuse to start inference | `/health` shows `onnx:unknown`-style unknown state |

Cross-cutting: structured logging + `/health/components` per layer; config via
`.env` (+ `.env.example`), no secrets committed; type hints + Pydantic
throughout; no giant files.
