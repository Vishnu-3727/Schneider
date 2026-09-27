# JouleMitra — Data Model

Planning doc only. Authoritative spec: `docs/spec/MASTER_SPEC.md` §7 (16
entities minimum). Related: `docs/ARCHITECTURE.md` (§4 evidence tagging),
`docs/IMPLEMENTATION_PLAN.md` (migrations per phase).

Conventions: timezone-aware timestamps everywhere, displayed Asia/Kolkata
(spec §11). Explicit units on every physical field. Every quantitative table
carries a `source` column (MEASURED | SIMULATED | DERIVED |
EXTERNAL_REFERENCE | PROJECTED | ASSUMPTION — spec §2). IDs are UUIDs unless
noted. Migrations: `database/migrations/001_phase1.sql` … `005_phase5.sql`
(see IMPLEMENTATION_PLAN.md).

---

## 1. Entities (key fields with units)

**Site** (Phase 1) — `id, name, location, timezone (default Asia/Kolkata),
industry_type, created_at`.

**Machine** (Phase 1) — `id, site_id → Site, name, machine_type
(furnace | compressor | pump | motor | textile | ceramics | food | generic —
never hard-coded to foundry), rated_power_kW, installed_at`.

**Sensor** (Phase 1) — `id, machine_id → Machine, channel
(V | I | kW | kVAr | PF | kWh | vibration | temperature | current | rpm |
state …), unit (V | A | kW | kVAr | kWh | °C | mm/s | rpm …),
source (MEASURED | SIMULATED), last_seen_at`.

**Telemetry** (Phase 1) — `id, sensor_id → Sensor, ts (timestamptz),
value (in Sensor.unit), quality (ok | quarantined | stale),
source, dedup_key (site, machine, ts, seq) UNIQUE`.
One row per sensor reading; high-volume, Timescale-hypertable candidate.

**ProductionRecord** (Phase 1) — `id, machine_id → Machine,
window_start, window_end (timestamptz), qty_units, good_units,
rejected_units, batch_heat_id, operating_time_s, cycle_time_s,
throughput_units_per_h, source`. Energy joins to production on
(machine, time bucket) for SEC/baseline.

**MachineState** (Phase 1) — `id, machine_id → Machine, state
(heating | melting | holding | idle | shutdown | auxiliary | running | stopped),
ts_start, ts_end (timestamptz, nullable = ongoing), source`.
Answers "what consumes energy without useful production?".

**User** (Phase 1, auth foundation) — `id, name, role
(operator | maintenance_engineer | factory_manager), created_at`.
MVP uses role selector, not full auth (spec §10).

**AuditEvent** (Phase 1) — `id, user_id → User (nullable), action,
entity, entity_id, at (timestamptz), detail_json`.

**EnergyBaseline** (Phase 2) — `id, machine_id → Machine, valid_from,
valid_to (timestamptz), model_kind (linear_regression | …),
expected_kWh, actual_kWh, deviation_kWh, deviation_pct, sec_kWh_per_unit
(nullable = not computable), history_days, confidence, source (DERIVED)`.
Expected = f(production, machine state, operating time, process conditions) —
never a global average (spec §6).

**AnomalyEvent** (Phase 2) — `id, machine_id → Machine, ts (timestamptz),
metric (power | idle_energy | pf | deviation | runtime …),
actual, expected (nullable), score, severity (NORMAL | WARNING | CRITICAL —
never colour-only), level (L1_rule | L2_statistical), baseline_id →
EnergyBaseline (nullable), acknowledged (bool), source (DERIVED)`.
Anomaly ≠ failure (spec §6).

**MachineHealth** (Phase 3) — `id, machine_id → Machine, ts (timestamptz),
health_score [0,1], rul_value (nullable, native time unit in `rul_unit`),
rul_lo, rul_hi (nullable — only with quantile head), attention_json
(sensor → weight, usage-not-causation), model_version (sha),
source (DERIVED | SIMULATED)`. Written only by the `MachineHealthModel`
adapter; adapter absent → no rows, "model unavailable".

**Recommendation** (Phase 4) — `id, machine_id → Machine (nullable for
plant-wide), title, severity, reason, evidence_json, action,
expected_impact_json (energy_kWh, cost_INR, co2e_kg, all PROJECTED),
confidence, created_at, acknowledged_by → User (nullable),
source_module, source (DERIVED | PROJECTED)`. No fabricated money figures
(spec §6).

**Intervention** (Phase 5) — `id, recommendation_id → Recommendation
(nullable), machine_id → Machine, action_taken, at (timestamptz),
params_json, simulated (bool), source`. Simulated interventions must change
simulator physics consistently (spec §5).

**VerificationResult** (Phase 5) — `id, intervention_id → Intervention,
window_before_start/end, window_after_start/end (timestamptz),
energy_before_kWh, energy_after_kWh, sec_before, sec_after
(kWh per good unit), cost_before_INR, cost_after_INR, co2e_before_kg,
co2e_after_kg, production_before/after (units), quality_kept (bool),
conditions_comparable (bool), verdict (verified | unable_to_verify),
source (DERIVED)`. If `conditions_comparable` is false → verdict forced to
`unable_to_verify` with reason (spec §6).

**Tariff** (Phase 5) — `id, site_id → Site, valid_from, valid_to,
period (peak | off_peak | normal), energy_rate_INR_per_kWh,
demand_rate_INR_per_kW (nullable), source (EXTERNAL_REFERENCE |
ASSUMPTION), source_ref (order/publication citation)`.

**EmissionFactor** (Phase 5) — `id, geography, year, factor_kgCO2e_per_kWh,
source (EXTERNAL_REFERENCE | ASSUMPTION), source_ref (publication citation)`.
Never invented silently (spec §6).

---

## 2. Relationships (text ER diagram)

```text
Site 1──* Machine 1──* Sensor 1──* Telemetry
  │           │            (dedup_key UNIQUE; hypertable candidate)
  │           ├──* ProductionRecord
  │           ├──* MachineState
  │           ├──* EnergyBaseline 1──* AnomalyEvent (baseline_id, nullable)
  │           ├──* MachineHealth
  │           ├──* Recommendation ──* Intervention ──1 VerificationResult
  │           │         │  (recommendation_id nullable; simulated flag)
  │           │         └── acknowledged_by ──* User (role)
  ├──* Tariff
  │
  └── (EmissionFactor is geography+year keyed, not site keyed)

User 1──* AuditEvent (user_id nullable; entity+entity_id polymorphic ref)
MachineHealth ──? AnomalyEvent   (correlation clue, no FK — diagnostic only,
                                  never causation; see ARCHITECTURE §2)
Intervention ──? ProductionRecord / Telemetry (before/after windows reference
                                  time ranges, not FKs — comparability guards
                                  in VerificationResult decide validity)
```

Join rules: energy↔production on (machine_id, time bucket); baseline lookup
on (machine_id, ts ∈ [valid_from, valid_to]); tariff lookup on
(site_id, ts ∈ validity, ToU period); factor lookup on (geography, year).
Missing tariff/factor rows → cost/CO₂e skipped with explicit reason, never
defaulted (ARCHITECTURE §6).
