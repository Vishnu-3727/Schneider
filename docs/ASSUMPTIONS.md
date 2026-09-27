# JouleMitra — Assumptions (Phases 1–2)

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

## A4 — Furnace batch heats (seeded variable schedule)
- ASSUMPTION (SIMULATED): Power fractions of rated
  0.85 / 0.95 / 0.45 / 0.08; PF 0.80 / 0.85 / 0.75 / 0.62; nominal charge
  375 kg at 500 kg/h melt rate during melting only; 2% reject fraction.
  Each heat varies (charge +/-8 %, melt duration follows charge, holding
  18-34 min, idle gaps from a 9-12 heats/day plan with lunch + shift extras).
- WHY: Seeded variability keeps NORMAL data strictly
  below the spike threshold (0.95 < 1.5×) so no false SUSPECT flags,
  while giving the baseline real heat-to-heat variation to fit.
- IMPACT: Real heats vary; baseline/SEC work in Phase 2 must fit plant data,
  never these constants.

## A5 — Compressor load/unload with time-of-day demand profile
- ASSUMPTION (SIMULATED): 9-min load/unload cycle at 0.90 / 0.25 of rated;
  loaded share 0.65 +/-0.10 sinusoidal over 24 h (peak mid-afternoon,
  trough at night, anchored to wall-clock time); always `running` in NORMAL.
- WHY: Typical load/unload behaviour with a daily demand rhythm, without
  modelling air pressure.
- IMPACT: No true demand-driven cycling (state is always running), so the
  baseline cannot separate legitimate demand growth from waste -- recorded
  as a LIMITATION in docs/ML_MODELS.md; Phase 6 edge work can replace with
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
- IMPACT: Phase 2 SEC treats these as NOT_APPLICABLE (both types are in
  `NON_PRODUCTION_TYPES=pump,compressor` — auxiliary equipment with no
  production concept), never 0 or inf. Non-productive kWh is reported for
  the furnace only.

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

## A11 — Fixed 1 h aggregation interval, 80 % coverage floor
- ASSUMPTION: `ENERGY_INTERVAL_S=3600`, `MIN_COVERAGE_PCT=80.0` (both in
  `.env.example`, configurable).
- WHY: 1 h matches the simulator production records and keeps baseline
  features interpretable; 80 % tolerates a few missed packets without
  admitting energy deltas over unobserved spans.
- IMPACT: Plants with batch cycles far from 1 h should refit the interval;
  sub-hour waste hides inside an hourly bucket.

## A12 — NNLS linear baseline; non-negativity imposed jointly
- ASSUMPTION: `E = b0 + SUM b_state.hours + b_prod.kg` via
  `scipy.optimize.nnls` (all coefficients >= 0); holdout tail 20 %
  (`BASELINE_HOLDOUT_FRACTION`); minimum 24 complete NORMAL intervals.
  Fit quality is reported as R2 (information only), CV(RMSE)% and NMBE%
  with an ASHRAE Guideline 14 hourly acceptance label
  (`G14_CV_MAX_PCT=30.0`, `G14_NMBE_MAX_PCT=10.0`); furnace features are
  `good_production_kg` + heating/holding/idle hours (melting hours excluded
  as collinear with production).
- WHY: Interpretable first (spec S6 "start simple"); joint non-negativity
  because post-hoc clipping of a least-squares fit scored R2_train = -1.9
  on NORMAL furnace data during development.
- IMPACT: Linear steady-state only (see docs/ML_MODELS.md limitations);
  simulator-constant melt rate leaves melting-hours/production collinear,
  so coefficients are not individually physical — predictions are.

## A13 — L2 anomaly rule gated on practical significance, excess only
- ASSUMPTION: L2 (rolling median + MAD, threshold 4.0, window 24) fires only for POSITIVE (excess-energy) residuals and
  only when |deviation_pct| also exceeds `DEVIATION_WARN_PCT` (15 %).
- WHY: Compressor duty-cycle beating leaves structured residuals of a few
  percent whose rolling MAD is tiny; a pure z-score test false-flagged
  NORMAL days during development. An anomaly is energy "above expected
  baseline for the production achieved" -- under-consumption (negative
  residual) is not waste and is out of Phase-2 scope; sparse sampling
  also leaves negative residuals that must never flag.
- IMPACT: L2 is an abrupt-large-jump detector; slow drifts below 15 %
  are not flagged by any rule (documented gap, not a silent pass —
  intervals still show their deviation % in /energy/summary).

## A14 — Scenario magnitudes (SIMULATED)
- ASSUMPTION: HIGH_LOAD +25 % power at same output (default magnitude
  0.25); PRODUCTION_SURGE more heats per day via shorter idle gaps
  (default magnitude 0.30, same per-kg melting physics); IDLE_WASTE
  powered holding (0.45 x rated, zero output) / compressor forced loaded.
- WHY: Magnitudes sit between detection thresholds (deviation warn 15 %)
  and data-quality limits (spike 1.5 x, power rule 1.1 x): HIGH_LOAD must
  flag, SURGE must not, all rows must stay GOOD quality.
- IMPACT: Detection margins are scenario-magnitude dependent; plant
  thresholds must be calibrated on measured data (see docs/ML_MODELS.md).

## A15 — Pump is the unaffected control in every Phase-2 scenario
- ASSUMPTION: Scenario overrides apply to furnace (+compressor for waste/
  load); pump physics never changes.
- WHY: A permanently NORMAL machine per run proves scenarios do not leak
  false positives onto unaffected equipment.
- IMPACT: Pump anomaly rules are exercised only by unit tests, not by
  scenario runs.

## A16 - Hour-boundary alignment between telemetry and production
- ASSUMPTION: The simulator stamps its first telemetry row at the run start
  (ts = start + i*step); the production hour index is derived from the same
  step counter i, so production, state shares and energy cover the same steps
  (only the cumulative-counter delta inherently spans one step less).
- WHY: A first row at start + step would put production one bucket off its
  energy and every hour would mis-score.
- IMPACT: Any new simulator or replay source must keep the same step-index
  alignment or re-derive the production join.

## A17 - IDLE_CONSECUTIVE_N persistence (default 4)
- ASSUMPTION: The L1 idle-waste rule fires only after IDLE_CONSECUTIVE_N (4)
  consecutive complete intervals with idle/holding share above
  IDLE_SHARE_THRESHOLD (0.5) at zero good production.
- WHY: Persistence -- not deviation -- is the signal. Sustained powered
  holding is predictable (the baseline identifies the holding coefficient,
  so a waste hour deviates only ~+5 %), while a single melt-free hour is
  normal inter-heat batch rhythm. The threshold (4) exceeds the longest
  legitimate melt-free span (~2.6 h: holding + plan idle + lunch + shift
  extras).
- IMPACT: Shorter real batch rhythms need a lower N; longer legitimate holds
  need a higher one -- env config, no code change.
