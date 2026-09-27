"""POST /telemetry (batch) + GET /telemetry."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.backend.routers._helpers import (
    audit,
    close_and_open_state,
    fetch_existing_ts,
    fetch_latest_telemetry,
    fetch_machines,
    fetch_open_states,
    touch_sensors,
)
from apps.backend.schemas import IngestResult, TelemetryBatch
from services.ingestion.validate import now_utc, validate_telemetry

router = APIRouter()


@router.post("/telemetry", response_model=IngestResult)
def post_telemetry(
    batch: TelemetryBatch,
    db: Session = Depends(get_db),
    backfill: bool = Query(default=False),
):
    settings = get_settings()
    records = batch.records
    if not records:
        return IngestResult(accepted=0, suspect=0, bad=0, duplicate=0)

    ids = sorted({r.machine_id for r in records})
    machines = fetch_machines(db, ids)
    unknown = [m for m in ids if m not in machines]
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown machine_id(s): {', '.join(unknown)}")

    latest = fetch_latest_telemetry(db, ids)
    last_ts = {m: (latest[m]["ts"] if m in latest else None) for m in ids}
    last_energy = {m: (latest[m]["energy_kwh"] if m in latest else None) for m in ids}
    seen: dict[str, set] = {}
    for m in ids:
        ts_list = [r.ts for r in records if r.machine_id == m]
        seen[m] = fetch_existing_ts(db, m, min(ts_list), max(ts_list))
    open_states = fetch_open_states(db, ids)

    now = now_utc()
    accepted = suspect = bad = duplicate = 0
    for r in records:
        m = r.machine_id
        if r.ts in seen[m]:
            duplicate += 1
            continue
        seen[m].add(r.ts)
        verdict = validate_telemetry(
            ts=r.ts,
            now=now,
            voltage_v=r.voltage_v,
            current_a=r.current_a,
            power_kw=r.power_kw,
            power_factor=r.power_factor,
            energy_kwh=r.energy_kwh,
            last_ts=last_ts[m],
            last_energy_kwh=last_energy[m],
            rated_power_kw=machines[m]["rated_power_kw"],
            stale_after_s=settings.STALE_AFTER_S,
            clock_skew_s=settings.CLOCK_SKEW_S,
            spike_multiple=settings.SPIKE_MULTIPLE,
            skip_stale=backfill,
        )
        result = db.execute(
            text(
                "INSERT INTO telemetry (machine_id, ts, voltage_v, current_a, power_kw, "
                "reactive_power_kvar, power_factor, energy_kwh, vibration_mm_s, "
                "temperature_c, rpm, runtime_h, machine_state, source, quality, "
                "quality_reasons) VALUES (:m, :ts, :v, :i, :p, :q, :pf, :e, :vib, "
                    ":t, :rpm, :rt, :st, :src, :qual, CAST(:reasons AS jsonb)) "
                "ON CONFLICT (machine_id, ts) DO NOTHING"
            ),
            {
                "m": m,
                "ts": r.ts,
                "v": r.voltage_v,
                "i": r.current_a,
                "p": r.power_kw,
                "q": r.reactive_power_kvar,
                "pf": r.power_factor,
                "e": r.energy_kwh,
                "vib": r.vibration_mm_s,
                "t": r.temperature_c,
                "rpm": r.rpm,
                "rt": r.runtime_h,
                "st": r.machine_state.value if r.machine_state else None,
                "src": r.source.value,
                "qual": verdict.quality,
                "reasons": json.dumps(verdict.reasons),
            },
        )
        if result.rowcount == 0:
            # Lost a race with a concurrent insert of the same key.
            duplicate += 1
            continue
        if last_ts[m] is None or r.ts > last_ts[m]:
            last_ts[m] = r.ts
            if r.energy_kwh is not None:
                last_energy[m] = r.energy_kwh if last_energy[m] is None else max(last_energy[m], r.energy_kwh)
        if r.machine_state is not None:
            close_and_open_state(db, open_states.get(m), m, r.machine_state.value, r.ts, r.source.value)
            open_states.update(fetch_open_states(db, [m]))
        touch_sensors(db, m, r.ts)
        if verdict.quality == "GOOD":
            accepted += 1
        elif verdict.quality == "SUSPECT":
            suspect += 1
        else:
            bad += 1

    audit(db, "ingest", "telemetry", "batch",
          {"accepted": accepted, "suspect": suspect, "bad": bad, "duplicate": duplicate})
    if backfill:
        ts_list = sorted(r.ts for r in records)
        audit(db, "backfill", "telemetry", "batch",
              {"machine_ids": ids,
               "row_count": len(records),
               "start": ts_list[0].isoformat(),
               "end": ts_list[-1].isoformat()})
    db.commit()
    return IngestResult(accepted=accepted, suspect=suspect, bad=bad, duplicate=duplicate)


@router.get("/telemetry")
def get_telemetry(
    machine_id: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    limit: int = Query(default=1000, le=10000),
    db: Session = Depends(get_db),
):
    q = ("SELECT machine_id, ts, voltage_v, current_a, power_kw, reactive_power_kvar, "
         "power_factor, energy_kwh, vibration_mm_s, temperature_c, rpm, runtime_h, "
         "machine_state, source, quality, quality_reasons FROM telemetry")
    conds, params = [], {}
    if machine_id:
        conds.append("machine_id = :m")
        params["m"] = machine_id
    if start:
        conds.append("ts >= :start")
        params["start"] = start
    if end:
        conds.append("ts <= :end")
        params["end"] = end
    if conds:
        q += " WHERE " + " AND ".join(conds)
    q += " ORDER BY ts DESC LIMIT :lim"
    params["lim"] = limit
    rows = db.execute(text(q), params).fetchall()
    cols = ["machine_id", "ts", "voltage_v", "current_a", "power_kw", "reactive_power_kvar",
            "power_factor", "energy_kwh", "vibration_mm_s", "temperature_c", "rpm",
            "runtime_h", "machine_state", "source", "quality", "quality_reasons"]
    return [dict(zip(cols, r, strict=True)) for r in rows]
