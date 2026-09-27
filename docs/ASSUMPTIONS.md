# JouleMitra — Assumptions (Phases 1–4B)

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

## A18 — EQUIPMENT_DEGRADATION simulator parameters (SIMULATED)
- ASSUMPTION: `magnitude` (default 1.0) scales the health-signal rise
  (vibration +5 mm/s, temperature +40 C at magnitude 1.0, ramping linearly
  from the window start) and `energy_penalty` (default 0.0) scales the
  extra-mechanical-load power uplift at unchanged output (fraction, same
  ramp). `energy_penalty = 0` is a HEALTH-ONLY anomaly: vibration and
  temperature rise while voltage, current and power stay at their NORMAL
  operating points (a voltage sag is a supply-side condition, not equipment
  wear, so the simulator never injects one — the pre-B1 sag model was
  removed for exactly this reason). `energy_penalty > 0` raises power AND
  current at nominal voltage and unchanged PF, so `P = sqrt(3)·V·I·PF`
  holds exactly and no power-factor energy rule fires on either fault type.
  `omit_health_signals=true` emits vibration/temperature/current as null
  (energy path unaffected).
- WHY: A degrading machine runs hotter and vibrates more; only a fault that
  also adds mechanical load draws more current for the same work.
  Separating the health ramp from the energy penalty lets one scenario
  cover health-only, combined, and unavailable-data cases without
  misleading later analytics with a supply-side artefact.
- IMPACT: Effect sizes are calibrated so a full-window fault scores
  WARNING/CRITICAL while NORMAL history stays NORMAL; plant data needs
  recalibration (thresholds are env config, no code change).

## A19 — Native statistical health model and thresholds
- ASSUMPTION: `statistical-v1` learns per-machine, per-exact-machine_state
  median + MAD references for vibration/temperature/current over hourly
  means; anomaly = max signal |robust z| with a 10 % MAD floor
  (`HEALTH_MAD_FLOOR_FRAC`); states at `HEALTH_WARN_Z=4.0` /
  `HEALTH_CRIT_Z=6.0`; health score `100·exp(-(a/crit)²)`.
- WHY: Exact-state conditioning (melting vs holding vs idle) keeps NORMAL
  state changes from flagging, but hourly means still blend adjacent states
  (an idle-dominant hour can contain 20 min of holding, reaching z ~ 3.5 on
  NORMAL data), so WARNING sits at 4 while true degradation scores z 8+.
  The floor desensitises load-confounded current (a healthy +25 % load
  uplift scores z ~ 1.7, silent); vibration/temperature are the primary
  degradation witnesses. Thin/unseen state buckets score OUT_OF_DOMAIN,
  never a forced verdict.
- IMPACT: The energy-only acceptance uses IDLE_WASTE rather than HIGH_LOAD:
  forced holding/loaded are NORMAL operating points (health silent), while
  HIGH_LOAD raises current draw, which a per-signal reference legitimately
  notices. Correlation text never claims causation (banned: cause/caused/
  because/due to/results from); the single sanctioned disclaimer is
  "This is a correlation, not an established cause".

## A20 — TARIFF_SHIFT simulator parameters (SIMULATED)
- ASSUMPTION: The ILLUSTRATIVE peak window (default 18:00–22:00 local,
  `TARIFF_SHIFT_PEAK_START_H/_END_H`, aligned with the seeded
  `evening_peak` tariff period) clusters furnace heats by scaling idle gaps
  only: 0.10x inside the window (heats pack in), 1.6x outside (daily heat
  count stays close to NORMAL). Per-heat physics (charge ±8 %, melt rate,
  holding 18–34 min, power fractions, PF) is untouched NORMAL physics.
- WHY: Models flexible, non-critical timing (running when power is most
  expensive) without inventing new physics; the same machine models are reused.
- IMPACT: Clustering strengths are illustrative, not measured behaviour;
  the 4 h window cannot hold a full NORMAL day of heats, so total production
  drops slightly vs NORMAL. Optimiser tests derive the requirement from the
  day actually produced, so the comparison stays fair.

## A21 — Optimizer model simplifications (PROJECTED)
- ASSUMPTION: Nominal planning uses a fixed charge per heat
  (`OPT_HEAT_CHARGE_KG=375`, melt time = charge / `OPT_MELT_RATE_KG_H`);
  heating fixed (`OPT_HEATING_H`); holding bounded [`OPT_HOLD_MIN_H`,
  `OPT_HOLD_MAX_H`] = [0.25, 0.75] h (illustrative metallurgical limits,
  plant to confirm). Re-optimising an observed day instead keeps each
  heat's own observed base heating / melting / holding durations on BOTH
  sides (current and recommended); holding is fixed at observed because the
  model does not represent schedule-induced waiting inside holding, so the
  optimiser cannot shorten it. One furnace, ordered non-overlap; operating
  windows default to the full horizon; the first heat of a horizon never
  incurs reheat (`first_heat_cold=false`); cold threshold
  (`OPT_COLD_THRESHOLD_H=2.0` h) and reheat extra (`OPT_REHEAT_EXTRA_H`)
  are rounded to whole slots and applied by one shared rule to both
  schedules; reheat is carved OUT of observed heating slots (total heating
  slots unchanged; if observed heating is shorter than the rule's reheat,
  the shortfall is recorded rather than extending the heat); energy = stored
  Phase-2 baseline coefficients (never invented); peak = per-state NORMAL
  median powers (DERIVED); demand charge (when a tariff carries one) = peak
  × max demand rate; missing tariff → cost term omitted, reported
  "unavailable (no tariff)". Determinism = fixed `random_seed` + 1 worker +
  time limit (identical schedules on identical inputs/config on the same
  build; short limits may return FEASIBLE instead of proven OPTIMAL).
- WHY: Keeps the CP-SAT model linear, small and auditable; every number the
  optimiser outputs is labelled PROJECTED and needs plant validation. Fair
  sides (same intrinsic durations, symmetric reheat carved from observed
  heating) keep projected deltas to genuine gap effects (reheat avoided,
  idle vs holding) and time-of-use placement.
- IMPACT: Real heats vary charge; real reheat depends on thermal state, not
  a clock threshold; demand billing here is a simplification. Short solver
  limits trade optimality proofs for speed — acceptance asserts FEASIBLE-or-
  better plus the independent validate() on every output.

## A22 — Illustrative tariff seed (ASSUMPTION, not a tariff order)
- ASSUMPTION: `database/seeds/phase4_tariff.sql` holds ONE time-of-use
  tariff for the demo site (night 6.0 / day 7.5 / evening-peak 18–22 10.5
  INR/kWh, no demand charge), `source_class=ASSUMPTION`, every row stamped
  "ILLUSTRATIVE - not a real tariff order - replace with the plant DISCOM
  tariff". Prices live only in the seed, never in code; a period with
  end <= start wraps past midnight. Re-seeding only overwrites rows still
  labelled ASSUMPTION, never a real DISCOM tariff entered later.
- WHY: The optimiser needs a price signal to demonstrate tariff-aware
  scheduling before the plant shares its tariff order.
- IMPACT: All cost figures are PROJECTED illustrative estimates ("Requires
  plant validation"); replace the seed with the DISCOM order before any
  commercial decision.

## A23 — Deterministic solver budget with a wall-clock safety net (PROJECTED)
- ASSUMPTION: The primary CP-SAT budget is deterministic
  (`max_deterministic_time` from `OPT_DETERMINISTIC_TIME`, per-run
  overridable via `deterministic_time_s`); the effective wall-clock safety
  net is `max(time_limit_s, deterministic_time + OPT_WALL_SLACK_S)`, always
  larger than the deterministic budget on any machine speed. A FEASIBLE stop
  at the wall-clock limit is machine-load-dependent, so it returns TIMEOUT
  instead of a plan.
- WHY: Full-horizon solves stop at FEASIBLE under a wall-clock limit, so
  identical inputs could return different schedules depending on machine
  load. The deterministic budget makes repeat solves byte-identical;
  refusing wall-clock FEASIBLE plans keeps a load-dependent artefact out of
  the decision chain.
- IMPACT: A heavily loaded machine may report TIMEOUT where a wall-clock
  FEASIBLE plan would previously (non-reproducibly) appear; re-run with a
  larger deterministic budget. Determinism holds for identical
  inputs/config on the same OR-Tools build.

## A24 — Recommendation rules, wording, human-in-the-loop (Phase 4B)
- ASSUMPTION: Pure rules first (`services/recommendations/engine.py`):
  R-IDLE / R-PROCESS / R-INSPECT / R-RESCHEDULE / R-SEQUENCE / R-PRIORITISE /
  R-NOPLAN over open anomalies, correlated insights, process findings and
  the latest overlapping optimisation run. Quantities appear only as
  projected optimiser deltas (`evidence_class=PROJECTED`, cost only with a
  tariff labelled ILLUSTRATIVE/ASSUMPTION); inspection-style rows carry a
  null effect, never a guessed number. A CRITICAL inspection overlapping an
  optimiser action flags both rows CONFLICT with both reasons shown — never
  silently dropped. Generation is idempotent (`dedup_key`); every
  acknowledge writes an `audit_event` row; status stays NOT_VERIFIED until
  Phase 5. Wording is projected/estimated; fact-stating savings language is
  banned and unit-tested.
- WHY: Phase 4 is decision support, not control: a human reviews every
  proposal, and unverifiable savings must not be stated as fact.
- IMPACT: Guidance only — no actuation, no verification claims; conflicting
  rows need explicit human resolution.

## A26 — Recommendation comparability (Phase 4B)
- ASSUMPTION: Every optimiser-backed recommendation (R-RESCHEDULE, R-SEQUENCE)
  computes `comparable: bool` and `comparability_reason`. Comparable requires
  same production (within `PRODUCTION_TOLERANCE = 1%`) AND same auxiliary
  tasks (same aux energy in breakdown). When not comparable, all projected
  quantities (kWh, peak, INR) are null; the reason text shows "NOT
  COMPARABLE: <reason>" and never claims "same production". Per-kg projected
  energy (kWh/t) is shown for both sides labelled PROJECTED. R-SEQUENCE gap
  delta uses holding + idle + reheat (not just holding + idle), and the
  components are stated in the evidence.
- WHY: Prevents false equivalence claims (e.g. 1500 kg current vs 1125 kg
  recommended presented as "same production"); makes it explicit when
  projected deltas are not apples-to-apples.
- IMPACT: Dashboard Optimization view and API response show comparability
  flag prominently; non-comparable rows carry no quantified effect, only
  per-kg projections for reference.

## A25 — Energy breakdown semantics (PROJECTED)
- ASSUMPTION: `evaluate()` reports heating / melting / holding / idle /
  reheat / intercept / aux kWh, which sum to the total. Melting carries the
  production-term energy; reheat is the cold-gap subset of heating slots
  (`HeatPlan.reheat_slots`); intercept is spread uniformly; aux is extra.
  Reheat is carved OUT of observed heating slots (base = observed - reheat,
  floored at 0; total heating slots preserved).
- WHY: Makes the source of projected differences (e.g. the TARIFF_SHIFT
  day's lower energy) visible instead of a single opaque total.
- IMPACT: Breakdowns compare model structure, not measurements; reheat is
  assigned symmetrically — the shared gap rule splits reconstructed
  observed heating into base + reheat by carving the rule's reheat out of
  the observed heating (total heating slots unchanged), exactly as it does
  for the recommended schedule.
