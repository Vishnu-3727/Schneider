"""Phase 1 application config via pydantic-settings reading .env.

No secrets or URLs are hard-coded anywhere; everything comes from the
environment (.env locally, compose environment in Docker).
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://joulemitra:joulemitra@localhost:5432/joulemitra"
    TEST_DATABASE_URL: str = "postgresql+psycopg://joulemitra:joulemitra@localhost:5432/joulemitra_test"
    API_BASE_URL: str = "http://localhost:8000"
    TZ: str = "Asia/Kolkata"
    STALE_AFTER_S: int = 900
    CLOCK_SKEW_S: int = 300
    SPIKE_MULTIPLE: float = 1.5

    # --- Phase 2: energy analytics (all thresholds configurable, no magic numbers) ---
    # Fixed aggregation interval in seconds (default 1 h).
    ENERGY_INTERVAL_S: int = 3600
    # Minimum telemetry duration-coverage % for an interval to count as complete.
    MIN_COVERAGE_PCT: float = 80.0
    # Minimum number of NORMAL complete intervals required to fit a baseline.
    MIN_BASELINE_INTERVALS: int = 24
    # Fraction of training intervals held out for validation (time-ordered tail).
    BASELINE_HOLDOUT_FRACTION: float = 0.2
    # Expected-energy floor (kWh): expected <= this -> deviation_pct = null.
    EXPECTED_EPSILON_KWH: float = 0.5
    # L1 deviation rule: warn/critical thresholds on deviation_pct, N consecutive.
    DEVIATION_WARN_PCT: float = 15.0
    DEVIATION_CRIT_PCT: float = 30.0
    DEVIATION_CONSECUTIVE_N: int = 2
    # L1 idle-energy rule: idle/holding hour share with zero production,
    # sustained for this many consecutive intervals (exceeds the longest
    # legitimate melt-free span; see services/energy/anomaly.py).
    IDLE_SHARE_THRESHOLD: float = 0.5
    IDLE_CONSECUTIVE_N: int = 4
    # L1 power rule: max power_kw above rated * multiple.
    RATED_POWER_MULTIPLE: float = 1.1
    # L1 power-factor rule: interval mean PF below this.
    PF_MIN_THRESHOLD: float = 0.6
    # L2 statistical rule: rolling median + MAD robust z-score threshold / window.
    MAD_THRESHOLD: float = 4.0
    MAD_WINDOW: int = 24
    # Machine types with no production concept (SEC NOT_APPLICABLE, no prod features).
    NON_PRODUCTION_TYPES: str = "pump,compressor"
    # Baseline model version string stored with each fit.
    BASELINE_MODEL_VERSION: str = "v1-linear"
    # ASHRAE Guideline 14 hourly acceptance criteria: CV(RMSE) <= this % and
    # |NMBE| <= NMBE_MAX_PCT % -> ACCEPTABLE, else NOT_ACCEPTABLE.
    G14_CV_MAX_PCT: float = 30.0
    G14_NMBE_MAX_PCT: float = 10.0

    # --- Phase 3A: machine health (all thresholds configurable, no magic numbers) ---
    # Native statistical health model id stored with each fit/score row.
    HEALTH_MODEL_ID: str = "statistical-v1"
    # Minimum fitted reference intervals required before scoring (else
    # INSUFFICIENT_HISTORY); per state-bucket minimum rows for the bucket
    # reference (else OUT_OF_DOMAIN for intervals in that bucket).
    HEALTH_MIN_REF_INTERVALS: int = 24
    HEALTH_MIN_BUCKET_ROWS: int = 3
    # Robust-z thresholds mapping max signal |z| -> WARNING / CRITICAL.
    # WARNING sits at 4: hourly means blend adjacent states (e.g. an
    # idle-dominant hour containing 20 min of holding), and those blends
    # reach z ~ 3.5 on NORMAL data; true degradation (+5 mm/s, +40 C)
    # scores z 8+.
    HEALTH_WARN_Z: float = 4.0
    HEALTH_CRIT_Z: float = 6.0
    # Relative MAD floor per signal (fraction of |median|): avoids huge z
    # from near-flat reference windows and desensitises load-confounded
    # current (a healthy +25 % load uplift scores z ~ 1.7, silent).
    # Absolute epsilon guards median ~ 0.
    HEALTH_MAD_FLOOR_FRAC: float = 0.10
    HEALTH_MAD_EPSILON: float = 1e-6

    # --- Phase 3B: PBL RUL adapter (external C-MAPSS model, optional) ---
    # Local paths to your own PBL artifact; not distributed with JouleMitra.
    # Empty (default) -> the adapter reports UNAVAILABLE, never an error.
    PBL_ONNX_PATH: str = ""
    PBL_SENSOR_VOCAB_PATH: str = ""

    # --- Phase 4A: process efficiency + tariff-aware optimisation ---
    # Optimiser slot grid / horizon / solver budget (deterministic: 1 worker).
    OPT_SLOT_MIN: int = 15
    OPT_HORIZON_H: int = 24
    OPT_TIME_LIMIT_S: float = 10.0
    # Deterministic CP-SAT budget (max_deterministic_time): the primary,
    # machine-load-independent search budget. The wall-clock
    # OPT_TIME_LIMIT_S is only a safety net (must be larger); hitting it
    # returns TIMEOUT, never a silently different FEASIBLE plan.
    OPT_DETERMINISTIC_TIME: float = 5.0
    # Slack added on top of the deterministic budget to form the effective
    # wall-clock safety net: effective_wall = max(time_limit_s,
    # deterministic_time + slack). Guarantees the deterministic budget, not
    # the wall clock, bounds the search on any machine speed.
    OPT_WALL_SLACK_S: float = 10.0
    OPT_RANDOM_SEED: int = 42
    OPT_NUM_WORKERS: int = 1
    # Objective weights: w_energy * kWh + w_peak * kW + w_cost * INR.
    OPT_W_ENERGY_KWH: float = 1.0
    OPT_W_PEAK_KW: float = 10.0
    OPT_W_COST_INR: float = 1.0
    # Furnace heat template (ASSUMPTION illustrative metallurgy; plant to
    # confirm): fixed charge per heat, melt duration = charge / melt rate,
    # fixed heating phase, holding bounded by [min, max] (hard).
    OPT_HEAT_CHARGE_KG: float = 375.0
    OPT_MELT_RATE_KG_H: float = 500.0
    OPT_HEATING_H: float = 0.333
    OPT_HOLD_MIN_H: float = 0.25
    OPT_HOLD_MAX_H: float = 0.75
    # A gap longer than this between heats adds reheat extra time to the
    # next heat's heating phase (documented simplification in ASSUMPTIONS).
    OPT_COLD_THRESHOLD_H: float = 2.0
    OPT_REHEAT_EXTRA_H: float = 0.25
    # Minimum holding time needed for pouring (process-efficiency reference).
    PROCESS_MIN_HOLD_H: float = 0.25
    # TARIFF_SHIFT scenario: heats cluster inside this illustrative peak
    # window (hours of day, local). No prices here; prices live in the seed.
    TARIFF_SHIFT_PEAK_START_H: float = 18.0
    TARIFF_SHIFT_PEAK_END_H: float = 22.0
    # Production tolerance for comparability check (fraction, e.g. 0.01 = 1%).
    # When current vs recommended production differs by more than this,
    # schedules are NOT COMPARABLE and projected deltas are suppressed.
    OPT_COMPARABLE_PROD_TOL: float = 0.01


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Test hook so env changes take effect between tests."""
    global _settings
    _settings = None
