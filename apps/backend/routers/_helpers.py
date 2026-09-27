"""Shared ingest helpers (machine lookup, state tracking)."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def fetch_machines(session: Session, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = session.execute(
        text("SELECT id, site_id, name, machine_type, rated_power_kw FROM machine WHERE id = ANY(:ids)"),
        {"ids": ids},
    ).fetchall()
    return {r[0]: {"site_id": r[1], "name": r[2], "machine_type": r[3], "rated_power_kw": r[4]} for r in rows}


def fetch_latest_telemetry(session: Session, ids: list[str]) -> dict[str, dict]:
    """Latest (ts, energy_kwh) per machine."""
    if not ids:
        return {}
    rows = session.execute(
        text(
            "SELECT DISTINCT ON (machine_id) machine_id, ts, energy_kwh "
            "FROM telemetry WHERE machine_id = ANY(:ids) ORDER BY machine_id, ts DESC"
        ),
        {"ids": ids},
    ).fetchall()
    return {r[0]: {"ts": r[1], "energy_kwh": r[2]} for r in rows}


def fetch_existing_ts(session: Session, machine_id: str, lo, hi) -> set:
    rows = session.execute(
        text("SELECT ts FROM telemetry WHERE machine_id = :m AND ts >= :lo AND ts <= :hi"),
        {"m": machine_id, "lo": lo, "hi": hi},
    ).fetchall()
    return {r[0] for r in rows}


def fetch_open_states(session: Session, ids: list[str]) -> dict[str, dict]:
    if not ids:
        return {}
    rows = session.execute(
        text(
            "SELECT machine_id, id, state FROM machine_state "
            "WHERE machine_id = ANY(:ids) AND ts_end IS NULL"
        ),
        {"ids": ids},
    ).fetchall()
    return {r[0]: {"id": r[1], "state": r[2]} for r in rows}


def close_and_open_state(session: Session, open_row: dict | None, machine_id: str, new_state: str, ts, source: str) -> dict:
    """Close the open state row (if the state changed) and open the new one.

    Returns the current open row ({id, state}) so callers can track it
    without re-querying.
    """
    if open_row is not None and open_row["state"] == new_state:
        return open_row
    if open_row is not None:
        session.execute(
            text("UPDATE machine_state SET ts_end = :ts WHERE id = :id"),
            {"ts": ts, "id": open_row["id"]},
        )
    row = session.execute(
        text(
            "INSERT INTO machine_state (machine_id, state, ts_start, ts_end, source) "
            "VALUES (:m, :s, :ts, NULL, :src) RETURNING id"
        ),
        {"m": machine_id, "s": new_state, "ts": ts, "src": source},
    ).fetchone()
    return {"id": row[0], "state": new_state}


def touch_sensors(session: Session, machine_id: str, ts) -> None:
    session.execute(
        text("UPDATE sensor SET last_seen_at = :ts WHERE machine_id = :m"),
        {"ts": ts, "m": machine_id},
    )


def audit(session: Session, action: str, entity: str, entity_id: str, detail: dict) -> None:
    import json

    session.execute(
        text(
            "INSERT INTO audit_event (action, entity, entity_id, detail_json) "
            "VALUES (:a, :e, :eid, CAST(:d AS jsonb))"
        ),
        {"a": action, "e": entity, "eid": entity_id, "d": json.dumps(detail)},
    )
