"""SQLAlchemy engine/session + FastAPI DB dependency with 503-on-down behaviour."""

from collections.abc import Iterator

from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.backend.config import get_settings, reset_settings

_engine: Engine | None = None
_session_factory: sessionmaker | None = None
_engine_url: str | None = None


def get_engine(url: str | None = None) -> Engine:
    global _engine, _session_factory, _engine_url
    db_url = url or get_settings().DATABASE_URL
    if _engine is None or _engine_url != db_url:
        _engine = create_engine(db_url, pool_pre_ping=True)
        _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
        _engine_url = db_url
    return _engine


def reset_engine() -> None:
    global _engine, _session_factory, _engine_url
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
    _engine_url = None
    reset_settings()


def get_session() -> Session:
    get_engine()
    assert _session_factory is not None
    return _session_factory()


def db_is_up() -> bool:
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db() -> Iterator[Session]:
    """FastAPI dependency. DB down -> 503 JSON {detail}, never a traceback."""
    try:
        session = get_session()
        session.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        yield session
    finally:
        session.close()
