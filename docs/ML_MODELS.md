# JouleMitra — ML Models (Phase 2: expected-energy baseline)

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
  always running): the baseline detects a level shift but cannot tell
  legitimate demand growth from waste. A flow/demand input is future work.
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
