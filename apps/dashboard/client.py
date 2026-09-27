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


def _post(path: str, payload: dict, timeout: float = 60.0):
    import httpx as _httpx

    try:
        r = _httpx.post(f"{API_BASE_URL}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": f"API unreachable at {API_BASE_URL}{path}: {e}"}


def get_baselines() -> dict:
    return _get("/energy/baseline")


def get_energy_summary(start_iso: str, end_iso: str, machine_id: str | None = None) -> dict:
    params = {"start": start_iso, "end": end_iso}
    if machine_id:
        params["machine_id"] = machine_id
    return _get("/energy/summary", params)


def detect_anomalies(start_iso: str, end_iso: str) -> dict:
    return _post("/energy/anomalies/detect", {"start": start_iso, "end": end_iso})


def get_anomalies(status: str | None = None) -> dict:
    return _get("/energy/anomalies", {"status": status} if status else None)


def acknowledge_anomaly(event_id: str) -> dict:
    return _post(f"/energy/anomalies/{event_id}/acknowledge", {})
