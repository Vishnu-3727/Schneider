"""Canonical JouleMitra telemetry/production records: the only thing that leaves the edge.

Every protocol adapter (MQTT payloads, Modbus registers, the simulator)
converts to these plain dicts. They match the backend ingestion schema
(apps/backend/schemas.py TelemetryRecord / ProductionRecordIn) field for
field, so the analytics never see a register, topic or protocol structure.

This module does structural checks only (known fields, types, tz-aware
timestamps, source class). Semantic quality (impossible values, stale,
out-of-order, spikes, duplicates) stays with the backend's ingestion
validation: one source of truth, identical for every path.

Deliberately no import from apps/*: the edge package deploys on its own
(e.g. a Raspberry Pi) and talks to the backend only over HTTP.
"""

from __future__ import annotations

import math
from datetime import datetime

TELEMETRY_FIELDS = {
    "voltage_v", "current_a", "power_kw", "reactive_power_kvar", "power_factor",
    "energy_kwh", "vibration_mm_s", "temperature_c", "rpm", "runtime_h",
}
MACHINE_STATES = {"heating", "melting", "holding", "idle", "shutdown", "auxiliary",
                  "running", "stopped"}
SOURCES = {"MEASURED", "SIMULATED", "DERIVED", "EXTERNAL_REFERENCE", "PROJECTED", "ASSUMPTION"}
PRODUCTION_FIELDS = {"qty_total_kg", "qty_good_kg", "qty_rejected_kg", "operating_time_h"}


class CanonicalError(ValueError):
    """Input cannot be expressed as canonical telemetry (malformed, not merely suspicious)."""


def _ts(value, name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise CanonicalError(f"{name} is not ISO-8601: {value!r}") from exc
    if not isinstance(value, datetime):
        raise CanonicalError(f"{name} missing or not a timestamp")
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise CanonicalError(f"{name} must be timezone-aware")
    return value


def _num(value, name: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalError(f"{name} must be a number, got {type(value).__name__}")
    if not math.isfinite(value):
        raise CanonicalError(f"{name} is not finite")
    return float(value)


def telemetry(machine_id, ts, source: str, fields: dict, machine_state: str | None = None) -> dict:
    """Build one canonical telemetry record; raise CanonicalError when malformed."""
    if not isinstance(machine_id, str) or not machine_id:
        raise CanonicalError("machine_id missing")
    if source not in SOURCES:
        raise CanonicalError(f"unknown source class {source!r}")
    unknown = set(fields) - TELEMETRY_FIELDS
    if unknown:
        raise CanonicalError(f"unknown field(s): {sorted(unknown)}")
    if machine_state is not None and machine_state not in MACHINE_STATES:
        raise CanonicalError(f"unknown machine_state {machine_state!r}")
    rec = {"machine_id": machine_id, "ts": _ts(ts, "ts").isoformat(), "source": source}
    rec.update({k: _num(v, k) for k, v in fields.items()})
    if machine_state is not None:
        rec["machine_state"] = machine_state
    return rec


def production(machine_id, window_start, window_end, source: str, fields: dict,
               batch_id: str = "") -> dict:
    if not isinstance(machine_id, str) or not machine_id:
        raise CanonicalError("machine_id missing")
    if source not in SOURCES:
        raise CanonicalError(f"unknown source class {source!r}")
    missing = {"qty_total_kg", "qty_good_kg", "qty_rejected_kg"} - set(fields)
    if missing or set(fields) - PRODUCTION_FIELDS:
        raise CanonicalError(f"production fields invalid (missing {sorted(missing)})")
    rec = {"machine_id": machine_id, "window_start": _ts(window_start, "window_start").isoformat(),
           "window_end": _ts(window_end, "window_end").isoformat(), "source": source,
           "batch_id": str(batch_id)}
    rec.update({k: _num(v, k) for k, v in fields.items()})
    return rec


def dedup_key(kind: str, rec: dict) -> str:
    """Stable identity used by the edge buffer (the backend dedups the same way)."""
    when = rec.get("ts") or rec.get("window_start")
    return f"{kind}|{rec['machine_id']}|{when}"
