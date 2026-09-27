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
