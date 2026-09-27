"""Load the Phase 1 seed file into the configured database."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import psycopg

from apps.backend.config import get_settings
from scripts.setup.init_db import SEEDS_DIR, _to_admin_params, apply_sql_file


def main() -> None:
    params, dbname = _to_admin_params(get_settings().DATABASE_URL)
    conn = psycopg.connect(dbname=dbname, autocommit=False, **params)
    try:
        apply_sql_file(conn, SEEDS_DIR / "phase1.sql", record_version=False)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
