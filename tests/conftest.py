"""Pytest session setup: real Postgres test database, clean tables per test."""

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

TEST_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://joulemitra:joulemitra@localhost:5432/joulemitra_test",
)
os.environ["DATABASE_URL"] = TEST_URL

from apps.backend import db as dbmod
from apps.backend.main import create_app
from scripts.setup.init_db import init_db


@pytest.fixture(scope="session")
def _test_db():
    dbmod.reset_engine()
    init_db(TEST_URL)
    yield TEST_URL
    dbmod.reset_engine()


@pytest.fixture()
def client(_test_db):
    dbmod.reset_engine()
    app = create_app()
    with TestClient(app) as c:
        eng = dbmod.get_engine()
        with eng.begin() as conn:
            for tbl in ("telemetry", "production_record", "machine_state", "audit_event",
                        "anomaly_event", "energy_baseline",
                        "machine_health", "machine_health_reference",
                        "optimization_run", "recommendation"):
                conn.execute(text(f"TRUNCATE {tbl}"))
        yield c
