"""Apply plain-SQL migrations in order, then seeds. No Alembic (Phase 1).

Usage:  python scripts/setup/init_db.py [--database-url URL]
Reads DATABASE_URL from .env via apps.backend.config when flag is absent.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from apps.backend.config import get_settings

MIGRATIONS_DIR = REPO_ROOT / "database" / "migrations"
SEEDS_DIR = REPO_ROOT / "database" / "seeds"


def _to_admin_params(db_url: str) -> tuple[dict, str]:
    """Split a SQLAlchemy-style URL into psycopg conn params + target db name."""
    url = db_url.replace("postgresql+psycopg://", "postgresql://")
    p = urlparse(url)
    dbname = p.path.lstrip("/") or "postgres"
    params = {
        "host": p.hostname or "localhost",
        "port": p.port or 5432,
        "user": unquote(p.username or "postgres"),
        "password": unquote(p.password or ""),
    }
    return params, dbname


def _ensure_database(params: dict, dbname: str) -> None:
    admin = psycopg.connect(dbname="postgres", autocommit=True, **params)
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
            if cur.fetchone() is None:
                cur.execute(f'CREATE DATABASE "{dbname}"')
                print(f"created database {dbname}")
            else:
                print(f"database {dbname} exists")
    finally:
        admin.close()


def _applied_versions(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        cur.execute("SELECT version FROM schema_migrations")
        return {r[0] for r in cur.fetchall()}


def _split_statements(sql: str) -> list[str]:
    # Migrations are simple DDL; split on semicolons, ignoring -- comments.
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    joined = "\n".join(lines)
    return [s.strip() for s in joined.split(";") if s.strip()]


def apply_sql_file(conn, path: Path, record_version: bool = True) -> None:
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        for stmt in _split_statements(sql):
            cur.execute(stmt)
        if record_version:
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s) ON CONFLICT DO NOTHING",
                (path.stem,),
            )
    conn.commit()
    print(f"applied {path.name}")


def init_db(db_url: str) -> None:
    params, dbname = _to_admin_params(db_url)
    _ensure_database(params, dbname)
    conn = psycopg.connect(dbname=dbname, autocommit=False, **params)
    try:
        applied = _applied_versions(conn)
        for mig in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if mig.stem in applied:
                print(f"skip {mig.name} (already applied)")
                continue
            apply_sql_file(conn, mig, record_version=True)
        for seed in sorted(SEEDS_DIR.glob("*.sql")):
            apply_sql_file(conn, seed, record_version=False)
    finally:
        conn.close()
    print("init_db done")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args()
    db_url = args.database_url or get_settings().DATABASE_URL
    # Hide password in logs.
    safe = re.sub(r"://([^:]+):[^@]+@", r"://\1:***@", db_url)
    print(f"init_db -> {safe}")
    init_db(db_url)


if __name__ == "__main__":
    main()
