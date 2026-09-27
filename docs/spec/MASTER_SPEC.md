# JouleMitra — Master Specification (authoritative)

Condensed from the project owner's master development prompt. `CHALLENGE_README.md`
in this folder is the original challenge brief. When the two differ, this file wins.

Challenge: Schneider Electric Challenge 04 — Smart Manufacturing, Industrial Energy &
Process Efficiency. Target: Indian SME manufacturing. First demo target: SME foundry /
induction furnace, but the architecture must also cover compressors, pumps, motors,
textiles, ceramics, food processing. Do not hard-code foundry assumptions.

Core principle: **Measure → Understand → Detect → Recommend → Act → Verify → Learn**

End-to-end chain the final demo must show:
factory data → acquisition → edge processing → validation → storage → energy analytics
→ machine-health analytics → production analytics → optimization → recommendation →
dashboard → simulated/real intervention → savings verification.

## 1. Objectives
Monitor energy; relate energy to production; compute SEC; build expected-energy baseline;
detect abnormal energy; detect abnormal equipment behaviour; use machine health to help
explain energy anomalies; analyse process inefficiency; optimise schedules; explainable
recommendations; cost and emissions impact; verify interventions; preserve throughput;
track quality where data exists; local edge operation; optional cloud sync; extensible to
real sensors.

## 2. Evidence rule (non-negotiable)
Every important quantitative value carries a source class:
MEASURED | SIMULATED | DERIVED | EXTERNAL_REFERENCE | PROJECTED | ASSUMPTION.
Never present simulated savings as real, projected ROI as guaranteed, PBL dataset
performance as foundry performance, external datasets as factory measurements, or
assumptions as measurements. Label "Simulation", "Prototype estimate" or
"Requires plant validation". Simulated data must be replaceable by real sensor data
without rewriting analytics.

## 3. Layers
1. Physical/factory: energy meter, CT, voltage, power, PF, vibration, temperature, motor
   current, RPM/runtime, machine state, production qty, batch/heat, process, quality.
   Simulator emulates all of these first.
2. Edge: ESP32 sensor-node + Raspberry Pi gateway abstractions. Receive, timestamp,
   validate, normalise, buffer offline, local metrics, light anomaly inference, publish
   MQTT, optional Modbus read, health/status. Must run in simulated mode on a normal PC;
   no physical hardware required.
3. Communication: MQTT, Modbus RTU/TCP (OPC UA optional). Sensor → Modbus/local → edge →
   MQTT → backend. Hardware drivers must not leak into business logic.
4. Backend: Python + FastAPI. Sites, machines, telemetry/production ingestion, anomalies,
   recommendations, optimisation jobs, verification, dashboard/report APIs, auth foundation.
5. Data: PostgreSQL, schema TimescaleDB-ready. Modular monolith, not microservices.
6. Analytics: baseline, SEC, energy anomaly, equipment health, process efficiency,
   carbon, cost, optimisation, recommendation, savings verification.
7. Application: Streamlit + Plotly dashboard; backend API independent so a React
   frontend can replace it later.

## 4. Suggested repo layout (logical separation must be preserved)
apps/{backend,dashboard,simulator}; services/{ingestion,energy,machine_health,
optimization,recommendations,verification,carbon}; edge/{gateway,mqtt,modbus,
device_simulator}; ml/{anomaly_detection,machine_health,baseline,models};
data/{raw,simulated,processed,schemas}; database/{migrations,seeds};
tests/{unit,integration,simulation,api}; docs/{architecture,api,data-model,deployment,
decisions}; scripts/{setup,seed,demo}. Root: README, LICENSE, .gitignore, .env.example,
docker-compose.yml, pyproject.toml. Deviate only with justification.

## 5. Simulator (core component, not throwaway)
Energy: V, I, kW, kVAr, PF, cumulative kWh, demand, state. Production: qty, good,
rejected, batch/heat, operating time, cycle time, throughput. Equipment: vibration,
temperature, current, runtime, RPM, health state. Process: furnace heating / melting /
holding / idle / shutdown / auxiliary. Commercial: tariff, ToU period, cost.
Environmental: emission factor, kgCO2e.
Scenarios (parameterised, not a fixed dataset): NORMAL, IDLE_WASTE,
EQUIPMENT_DEGRADATION, HIGH_LOAD, PRODUCTION_SURGE (baseline must tell legitimate
higher energy from waste), TARIFF_SHIFT, COMBINED_ANOMALY.
Interventions must change physical cause and effect consistently (no magic energy drop).

## 6. Analytics requirements
- Baseline: Expected = f(production, machine state, operating time, process conditions).
  Not a global average. Start interpretable (e.g. linear regression). Expose actual,
  expected, deviation, deviation %, SEC.
- SEC = energy / good production (foundry: kWh/tonne). Handle zero / missing / rejected
  production, idle, incomplete batches; return explicit "not computable" states, never inf.
- Anomaly: L1 rules (power threshold, idle energy, PF, deviation, runtime); L2 rolling
  median + MAD / z-score, optional Isolation Forest. Expose score, severity, timestamp,
  machine, metric, baseline comparison. Anomaly ≠ failure.
- Machine health: reuse PBL predictive-maintenance work via an adapter
  (`MachineHealthModel` with predict/score/explain). PBL datasets (C-MAPSS, FEMTO,
  XJTU-SY, …) are NOT foundry energy data; never merge them as if from one machine.
- Energy + health correlation: diagnostic clue, never guaranteed causation; always explain why.
- Process efficiency: idle time, excess holding, needless runtime, start/stop cycling,
  state transitions — "what consumes energy without useful production?"
- Optimisation: Google OR-Tools. Min cost or weighted cost + peak penalty + delay penalty.
  Hard constraints: required production, availability, process constraints, hours. Output
  current vs recommended schedule, cost, energy, peak, production impact.
- Recommendations: rule/analytics based first. Fields: title, machine/process, severity,
  reason, evidence, action, expected impact, confidence, timestamp, source module.
  No fabricated money figures.
- Human-in-the-loop decision support only. No direct control of furnaces, motors,
  actuators, safety systems.
- Intervention simulation: before/after energy, SEC, cost, CO2e, production, quality, with
  deltas.
- Verification: energy lower? production comparable? SEC lower? quality kept? conditions
  comparable? If not valid → "Unable to verify savings under current conditions."
- Carbon: CO2e = energy × factor; factor stored as data with unit, source, geography,
  year. Never invent factors silently.
- Cost: energy × applicable tariff (time/period/demand). Tariff stored as data; actual vs
  illustrative clearly marked.

## 7. Data model (minimum entities)
Site, Machine, Sensor, Telemetry, ProductionRecord, MachineState, EnergyBaseline,
AnomalyEvent, MachineHealth, Recommendation, Intervention, VerificationResult, Tariff,
EmissionFactor, User, AuditEvent. Document relationships in docs/DATA_MODEL.md.

## 8. API (FastAPI, validated schemas, useful errors, no stack traces)
GET /health, /health/components, /sites, /machines, /machines/{id}, /telemetry,
/production, /energy/summary, /energy/baseline, /energy/anomalies, /machine-health,
/recommendations, /verification, /dashboard/summary, /optimization/schedule;
POST /telemetry, /production, /recommendations/{id}/acknowledge, /interventions,
/optimization/run.

## 9. MQTT / edge / Modbus
Topics: joulemitra/{site_id}/{machine_id}/telemetry|health|state,
joulemitra/{site_id}/production. HTTP ingestion also supported for dev.
Simulated RPi gateway: receive, validate, timestamp, SQLite buffer, publish, survive
network loss, resync. Modbus interface (read_energy_meter/voltage/current/power/
power_factor) with MockModbusDevice now, RealModbusDevice later.

## 10. Dashboard
Sections: Overview (SEC, energy today, production today, cost, CO2e, health), Energy
(actual vs expected, SEC trend, by machine, by state), Equipment (health, anomaly score,
temp, vibration, current, runtime, trend), Alerts, Recommendations, Optimisation
(current vs recommended), Verification (before/after). Industrial UX: clear numbers, no
gimmicks, NORMAL/WARNING/CRITICAL not colour-only. Roles: Operator, Maintenance
Engineer, Factory Manager (role selector, not full auth, in MVP).

## 11. Engineering rules
ML must be useful and documented (purpose, I/O, training data, preprocessing,
validation, limitations, inference location, latency); simple → statistical → ML.
Tests mandatory: unit (SEC, baseline, anomaly, cost, carbon, optimiser constraints,
recommendation rules, verification), integration, API (invalid/missing/malformed/
duplicate/zero production), failure (MQTT/DB down, missing sensor, corrupt, stale).
Data validation for missing, duplicate, out-of-order, impossible, stale, spikes, unit
mismatch; per-record quality status. Logging + /health/components. Config via .env
(+ .env.example), no secrets committed, no hard-coded tariffs/factors/thresholds/URLs.
docker-compose for backend, DB, MQTT broker, dashboard. Timezone-aware timestamps,
Asia/Kolkata display. Explicit units everywhere (kWh, kW, kg/t, kWh/t, °C, A, V,
kgCO2e, INR). Type hints, Pydantic, no giant files, no fake implementations — mocks are
named Mock*/Simulated*; unimplemented = NotImplementedError/TODO.
Docs: README, ARCHITECTURE, DATA_MODEL, API, ML_MODELS, SIMULATION, DEPLOYMENT, DEMO,
ASSUMPTIONS, VALIDATION, docs/decisions/ADR-*.
Ambiguity → write ASSUMPTION / WHY / IMPACT, choose simplest defensible option.
Failure modes to plan for: no internet, MQTT down, DB down, sensor disconnected, bad
readings, missing/zero production, model unavailable, infeasible optimisation,
conflicting recommendations, duplicate telemetry, clock/timezone, unit errors, missing
emission factor, missing tariff, insufficient baseline history.

## 12. Build order (vertical slices; app runnable after each)
1. Simulator → API → Database → Dashboard (plus repo, config, telemetry schema). No ML.
2. SEC → energy baseline → actual vs expected → anomaly detection → alerts.
3. PBL machine-health adapter → health score → energy-health correlation.
4. Process efficiency → OR-Tools tariff-aware scheduling → recommendations.
5. Intervention → savings verification → cost → carbon → before/after.
6. MQTT → simulated edge gateway → Modbus abstraction → buffering/offline.
7. Hardware (ESP32, RPi) + AutoCAD Electrical schematic + Fusion 360 enclosure
   (supporting artifacts only; never delay software).

Demo command (eventually): `python scripts/demo/run_demo.py` — seed, normal data,
trigger compressor degradation + idle, detect, recommend, intervene, verify, show
before/after.

Rule: build data → model → analytics → decision → verification → UI. A dashboard with
fake numbers is not acceptable.
