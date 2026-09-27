# JouleMitra — ML Models (Phase 2: expected-energy baseline; Phase 3: machine health)

All numbers below are MEASURED on SIMULATED data (prototype, requires plant
validation). Nothing here transfers to real plant performance. Model code:
`services/energy/baseline.py`. Training harness: `POST /energy/baseline/fit`.
History: `energy_baseline` table (one row per fit, `source=DERIVED`).

## 1. Expected-energy baseline v1-linear

- **Purpose.** Answer "did this machine use more energy than expected FOR THE
  PRODUCTION IT ACHIEVED?" — the production-normalised alternative to a naive
  global average, which would flag legitimate high-output operation as waste.
- **Inputs (per machine, per fixed 1 h interval).** Furnace (production
  type): `good_production_kg` + `hours_heating` + `hours_holding` +
  `hours_idle`. Melting energy is carried by the production term (energy =
  fixed + variable × production, ISO 50006 style); heating, holding and idle
  hours capture time-based losses. Melting hours are deliberately EXCLUDED:
  the simulator's near-constant melt rate makes melting-hours and production
  near-perfectly collinear, so including both lets the fit split one physical
  effect arbitrarily across two coefficients. Compressor/pump (config
  `NON_PRODUCTION_TYPES=pump,compressor`, auxiliary types with no production
  records) use state hours only — the simulator provides no load/throughput
  variable, so none exists in the model.
- **Model.** `E = b0 + Σ b_state·hours + b_prod·kg`, fitted with non-negative
  least squares (`scipy.optimize.nnls`, all coefficients ≥ 0). The
  non-negativity is imposed JOINTLY during optimisation: post-hoc clipping of
  a least-squares fit was tried and gave R²_train = −1.9 on NORMAL furnace
  data (clipping one coefficient of a collinear set destroys predictions).
- **Outputs.** `expected_kwh`, `deviation_kwh = actual − expected`,
  `deviation_pct` (null with status `EXPECTED_NEAR_ZERO` when
  expected ≤ `EXPECTED_EPSILON_KWH`, never inf/NaN).
- **Training data.** Reference window of NORMAL, complete intervals only
  (incomplete intervals — BAD rows or coverage < `MIN_COVERAGE_PCT` — are
  excluded and reported, never silently dropped). Minimum
  `MIN_BASELINE_INTERVALS` (24) complete intervals or the fit refuses with
  `INSUFFICIENT_BASELINE_HISTORY` and no numbers are produced.
- **Preprocessing.** Aggregation (`services/energy/aggregate.py`): energy from
  cumulative-counter deltas of GOOD rows; state hours by row share;
  production joined on interval start (GOOD records only). No imputation.
- **Validation.** Time-ordered tail holdout (`BASELINE_HOLDOUT_FRACTION`
  = 0.2). The fit stores train AND holdout R² / CV(RMSE)% / NMBE%, plus an
  acceptance label from ASHRAE Guideline 14 hourly criteria (config
  `G14_CV_MAX_PCT=30.0`, `G14_NMBE_MAX_PCT=10.0`): CV(RMSE) ≤ 30 % and
  |NMBE| ≤ 10 % → ACCEPTABLE, else NOT_ACCEPTABLE. R² is reported for
  information only and plays no part in the decision: it is not meaningful
  when the target variance is near zero (the pump's near-constant load makes
  the denominator of R² ~0, so R² swings negative even for a model whose
  CV(RMSE) is a fraction of a percent). Only the holdout numbers below may
  be quoted.
- **Window aggregates.** `GET /energy/summary` returns per-machine window
  aggregates next to the hourly intervals: Σactual, Σexpected, aggregate
  deviation %, window SEC + status, non-productive kWh. Window SEC is
  Σenergy / Σgood-production over the window (via
  `services.energy.sec.compute_sec`) — never the mean of hourly SEC values,
  which over-weights low-production hours. The dashboard Energy view shows
  the window SEC; the hourly SEC series remains visible but is labelled
  hourly.
- **Inference location / latency.** In-API scoring (`GET /energy/summary`,
  `POST /energy/anomalies/detect` loads the latest fit per machine);
  microseconds per interval (closed-form dot product).

## 2. Measured held-out quality (SIMULATED)

Latest verification numbers: see docs/VALIDATION.md.

Fitted furnace coefficients are non-negative but NOT individually physical:
the simulator's constant melt rate leaves melting-hours/production
collinearity in the training manifold, so many coefficient splits predict
identically on operating points spanned by training while off-manifold
points (e.g. a full hour of pure holding, never seen in training)
extrapolate poorly — the IDLE_WASTE case is therefore carried by the
independent L1 idle-share rule, not by deviation alone. A plant-data refit
(melt rate varies heat to heat) separates the features; do not interpret
fitted coefficients as equipment nameplate data.

## 3. Limitations

- Linear, steady-state, hourly: no dynamics, no start-up transients, no
  grade/product-mix effects, no ambient correction.
- Compressor/pump baselines are intercept-only means (single active state);
  they detect large sustained shifts (≥ warn threshold over N intervals),
  not duty-cycle subtleties.
- LIMITATION — compressor has no air-demand/throughput driver (state is
  always running). Without air-demand/flow information, an energy increase
  cannot reliably be distinguished between legitimate demand growth and
  waste. Future compressor diagnosis inputs: power + pressure + air
  flow/demand + runtime + machine health.
- R² is not meaningful when the target variance is near zero (pump): the
  near-constant load makes the R² denominator ~0, so R² goes negative while
  CV(RMSE) stays well within acceptance. Quote CV(RMSE)/NMBE + the G14
  label, never R² alone.
- L2 (rolling median + MAD robust z on residuals) fires on excess energy
  ONLY (positive residuals): under-consumption is not waste and is out of
  Phase-2 scope. L2 additionally requires deviation_pct above the L1 warn
  threshold: duty-cycle beating leaves structured residuals of a few percent
  whose rolling MAD is tiny, so a pure z-score test false-flags NORMAL
  data. L2 is the abrupt-large-jump detector; L1_DEVIATION (N consecutive)
  catches sustained shifts.
- Anomaly ≠ failure. Wording is always "above expected baseline for the
  production achieved".

## 4. Health model card: statistical-v1 (Phase 3, native)

- **Purpose.** Answer "is this machine behaving unlike its own NORMAL
  self?" per fixed 1 h interval, as a diagnostic clue next to energy
  analytics — never a failure prediction.
- **Inputs (per machine, per interval).** Interval means of
  `vibration_mm_s`, `temperature_c`, `current_a` plus the dominant
  `machine_state` (exact-state conditioning: melting vs holding vs idle vs
  running each get their own reference bucket). Missing signals stay None
  (never zero-filled); incomplete intervals score UNAVAILABLE.
- **Outputs.** `health_score` 0–100 (`100·exp(−(a/crit)²)`),
  `anomaly_score` (max signal |robust z|), `state` NORMAL/WARNING/CRITICAL,
  `status` OK/UNAVAILABLE/INSUFFICIENT_HISTORY/OUT_OF_DOMAIN/ERROR, plus
  per-signal contributions (`explain`: signal, value, median, z,
  pct_change, weight summing to 1.0). Code:
  `services/machine_health/statistical.py`. Training harness:
  `POST /machine-health/fit`; scoring: `POST /machine-health/score`.
  History: `machine_health_reference` / `machine_health` tables
  (`source=DERIVED`).
- **Reference data.** NORMAL-operation telemetry of the SAME machine being
  scored (per-machine fit, no cross-machine transfer); complete intervals
  only. Minimum `HEALTH_MIN_REF_INTERVALS` (24) fitted intervals and
  `HEALTH_MIN_BUCKET_ROWS` (3) rows per state bucket, else
  INSUFFICIENT_HISTORY / OUT_OF_DOMAIN — never a forced verdict.
- **Thresholds (all env config).** Modified robust z
  `0.6745·(x−median)/MAD` with a relative MAD floor
  (`HEALTH_MAD_FLOOR_FRAC=0.10`, `HEALTH_MAD_EPSILON=1e-6`); WARNING at
  `HEALTH_WARN_Z=4.0`, CRITICAL at `HEALTH_CRIT_Z=6.0`.
- **Validation.** Scenario acceptance on SIMULATED data
  (`tests/integration/test_health_scenarios.py`, 5-row table — NORMAL
  silent on seeds 1–3; IDLE_WASTE → ENERGY_ONLY; EQUIPMENT_DEGRADATION
  with `energy_penalty=0` → HEALTH_ONLY via vibration/temperature;
  with `energy_penalty=0.35` → COINCIDENT; HIGH_LOAD with omitted health
  signals → ENERGY_ONLY_HEALTH_UNAVAILABLE). Latest numbers: see
  docs/VALIDATION.md (Phase 3 section).
- **Limitations.**
  - Hourly means only: sub-hour transients are smoothed away; gradual drift
    below WARNING lowers the score but never raises the state.
  - Current is load-dependent: a healthy load uplift moves current and the
    MAD floor keeps it silent (z ~ 1.7), but a HIGH_LOAD fault raises
    current draw enough that the per-signal reference legitimately flags
    it — so HIGH_LOAD shows COINCIDENT (correlation, never causation), and
    the energy-only acceptance uses IDLE_WASTE instead (see
    docs/ASSUMPTIONS.md A19).
  - A health-only fault (simulator `energy_penalty=0`) leaves voltage,
    current and power at NORMAL; detection rests on vibration/temperature
    (see docs/ASSUMPTIONS.md A18).
  - Rare/unseen state buckets score OUT_OF_DOMAIN; correlation text never
    claims causation (banned: cause/caused/because/due to/results from).

## 5. Health model card: pbl-rul (Phase 3B, external reference adapter)

- **Purpose.** Reuse-external-work reference ONLY: expose what an
  outside turbofan RUL model can and (mostly) cannot say about JouleMitra
  machines. It never scores factory machines and is not a production
  predictor. Code: `services/machine_health/pbl_adapter.py`
  (`PBLRulAdapter(MachineHealthModel)`); listed by
  `GET /machine-health/models` next to `statistical-v1`.
- **Inputs.** C-MAPSS turbofan sensor channels ONLY (in-domain
  `score_window(...)`: an (L=30, S) normalised window + sensor-vocabulary
  ids + domain id, implementing the learned ONNX contract — inputs
  `x` (batch, sensors, 30) float32, `mask` bool, `sensor_ids` int64,
  `domain_id` int64; outputs `rul` (batch, 1), `attn`
  (batch, 4, 1, sensors)). JouleMitra signals (vibration_mm_s /
  temperature_c / current_a) are OUT_OF_DOMAIN for this model.
- **Outputs.** For factory machines (furnace/compressor/pump):
  `status=OUT_OF_DOMAIN`, reason "trained on turbofan sensor channels;
  not validated for \<type\>; retraining on plant data required", and NO
  health score or RUL — by construction, whether or not the artifact
  loads. `score_window()` returns an RUL + attention for a
  caller-supplied in-domain window (demonstration/tests only).
- **Reference data.** NASA C-MAPSS turbofan run-to-failure
  (EXTERNAL_REFERENCE). Training domain is recorded as such in
  `metadata()` and shown on the dashboard PBL card.
- **Thresholds.** None — the adapter has no decision thresholds; the only
  knobs are the local artifact paths (`PBL_ONNX_PATH`,
  `PBL_SENSOR_VOCAB_PATH`, both empty by default). Empty path, missing
  file, or missing onnxruntime (optional `[pbl]` extra, never a core
  dependency) → status UNAVAILABLE with a clear reason, never a crash.
- **Validation (EXTERNAL_REFERENCE, verified from the external project's
  files).** Test RMSE 14.51 (`results/metrics.json` official-test entry)
  vs random-forest baseline RMSE 14.41 (`results/baseline_rf.json`
  official-test entry): not better than the RF baseline on this
  benchmark; not a production-grade predictor. An optional integration
  test (`tests/integration/test_pbl_models.py`) loads a local artifact
  (path via `PBL_TEST_ONNX_PATH` env var only) and checks output
  shape/finiteness on a synthetic in-domain window, skipping with an
  explicit reason when the file or onnxruntime is absent.
- **Limitations.**
  - OUT_OF_DOMAIN for all JouleMitra factory machines; scoring factory
    machines always uses `statistical-v1`.
  - Without air-demand/flow information, an energy increase cannot
    reliably be distinguished between legitimate demand growth and waste.
    Future compressor diagnosis inputs: power + pressure + air
    flow/demand + runtime + machine health.
  - The artifact is local-only (not distributed with JouleMitra;
    ownership/licence unresolved — see `.env.example`).
