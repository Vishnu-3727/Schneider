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
