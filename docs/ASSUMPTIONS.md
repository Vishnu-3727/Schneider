# JouleMitra — Assumptions (Phase 1)

Every entry: ASSUMPTION / WHY / IMPACT. All simulator numeric constants are
labelled SIMULATED/ASSUMPTION and every simulator record carries
`source=SIMULATED` — prototype data, requires plant validation.

## A1 — Machine TEXT ids (`furnace-01`, …) instead of UUIDs
- ASSUMPTION: `Site.id` / `Machine.id` are human-readable TEXT keys; all other
  tables use UUIDs as `docs/DATA_MODEL.md` prescribes.
- WHY: Keeps simulator CLI, MQTT-style topics (`joulemitra/{site}/{machine}/…`)
  and demo readable without a lookup table.
- IMPACT: A future migration could add UUID surrogate keys; API/joins use the
  same key on both sides so behaviour is unchanged.

## A2 — Plain PostgreSQL 16, no TimescaleDB extension
- ASSUMPTION: Schema is Timescale-compatible (timestamptz, `(machine_id, ts)`
  indexes) but no hypertables are created.
- WHY: Owner decision (IMPLEMENTATION_PLAN §10.6): simpler local setup.
- IMPACT: 1-minute demo data volumes are trivial for btree indexes; converting
  `telemetry` to a hypertable later needs no app-code change.

## A3 — Three-phase nominal voltage 415 V
- ASSUMPTION (SIMULATED): `NOMINAL_VOLTAGE_V = 415.0`, ±3 V Gaussian noise.
- WHY: Indian LT 3-phase nominal; noise stands in for unmeasured variation.
- IMPACT: Absolute current values shift with real plant voltage; power/energy
  relations are unaffected (current is derived from P, V, PF).

## A4 — Furnace batch cycle (heating 20 / melting 45 / holding 25 / idle 30 min)
- ASSUMPTION (SIMULATED): Fixed state durations; power fractions of rated
  0.85 / 0.95 / 0.45 / 0.08; PF 0.80 / 0.85 / 0.75 / 0.60; melt rate 500 kg/h
  during melting only; 2% reject fraction.
- WHY: Simplest defensible batch-furnace shape; keeps NORMAL data strictly
  below the spike threshold (0.95 < 1.5×) so no false SUSPECT flags.
- IMPACT: Real heats vary; baseline/SEC work in Phase 2 must fit plant data,
  never these constants.

## A5 — Compressor load/unload 6 min / 3 min at 0.90 / 0.25 of rated
- ASSUMPTION (SIMULATED): Fixed duty cycle, always `running` in NORMAL.
- WHY: Typical load/unload behaviour without modelling air demand.
- IMPACT: No demand-driven cycling; Phase 6 edge work can replace with
  measured pressure-driven states behind the same schema.

## A6 — Cooling pump at 0.70 of rated with slow sinusoidal modulation
- ASSUMPTION (SIMULATED): ±5% sine over 10 min + 1% noise, always `running`.
- WHY: Stands in for varying cooling load without a thermal model.
- IMPACT: Pump energy is smooth by construction; anomaly detection (Phase 2)
  must be validated against measured load profiles.

## A7 — Stale threshold 900 s, clock-skew tolerance 300 s, spike multiple 1.5×
- ASSUMPTION: Defaults in `.env.example` (`STALE_AFTER_S`, `CLOCK_SKEW_S`,
  `SPIKE_MULTIPLE`); configurable, never hard-coded.
- WHY: 15 min covers simulator/edge hiccups; 5 min covers clock drift; 1.5×
  rated separates genuine spikes from NORMAL noise.
- IMPACT: Plants with slower cadences should raise `STALE_AFTER_S`; thresholds
  are env-config, no code change needed.

## A8 — Compressor/pump emit zero-quantity production records
- ASSUMPTION: Hourly `ProductionRecord` rows with 0 kg for non-furnace machines.
- WHY: Keeps the energy↔production join uniform per machine in Phase 1 while
  exercising the "zero production accepted" path.
- IMPACT: Phase 2 SEC must treat these as "not computable", never 0 or inf.

## A9 — MachineState rows are derived from telemetry state transitions
- ASSUMPTION: No separate state-ingest endpoint in Phase 1; the telemetry
  ingest opens/closes `MachineState` rows when `machine_state` changes.
- WHY: Fewest endpoints for the vertical slice; state always agrees with
  stored telemetry.
- IMPACT: Direct state writes (Phase 6 edge path) will need an explicit
  endpoint; schema already supports it.

## A10 — `backfill=true` skips only the stale check on ingest
- ASSUMPTION: `POST /telemetry` and `POST /production` accept
  `?backfill=true`. When true, the stale-timestamp rule (`STALE_AFTER_S`)
  is skipped; every BAD rule (impossible values, future ts, decreasing
  energy), the out-of-order check, the spike check and duplicate handling
  stay active. Each backfill request writes one extra `audit_event` row
  (`action='backfill'`) with `machine_ids`, `row_count` and the time range.
  Live ingest default (`backfill=false`) is unchanged.
- WHY: A 24 h simulated backfill is old by construction at ingest time, so
  without the flag all of it lands as SUSPECT — later phases read
  GOOD-quality rows, and the NORMAL demo must be GOOD.
- IMPACT: Historical loads (simulator `--post`, CSV replays) must pass
  `backfill=true`; live/edge traffic must not, so genuinely stale sensor
  data is still flagged SUSPECT.
