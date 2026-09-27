"""Small importable API client. Dashboard reads ONLY through this module (never the DB).

Every function returns decoded JSON on success or {"error": "..."} when the
API is unreachable — callers render a clear message, never crash.
"""

from __future__ import annotations

import os

import httpx

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


def _get(path: str, params: dict | None = None, timeout: float = 15.0):
    try:
        r = httpx.get(f"{API_BASE_URL}{path}", params=params, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": f"API unreachable at {API_BASE_URL}{path}: {e}"}


def get_health() -> dict:
    return _get("/health")


def get_machines() -> dict:
    data = _get("/machines")
    return data


def get_summary(hours: float = 24.0) -> dict:
    return _get("/dashboard/summary", {"hours": hours})


def get_telemetry(machine_id: str, limit: int = 2000) -> dict:
    return _get("/telemetry", {"machine_id": machine_id, "limit": limit})
