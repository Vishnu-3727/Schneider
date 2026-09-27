"""GET /dashboard/summary — per-machine rollup over a trailing window.

Phase 1 only: energy (kWh from cumulative-counter deltas), latest power (kW),
production (kg), latest state, source tag, quality counts. No SEC/cost/CO2e.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.db import get_db
from services.ingestion.validate import now_utc

router = APIRouter()


@router.get("/dashboard/summary")
def dashboard_summary(hours: float = Query(default=24.0, gt=0, le=24 * 31), db: Session = Depends(get_db)):
    now = now_utc()
    start = now - timedelta(hours=hours)
    machines = db.execute(text("SELECT id, name, machine_type FROM machine ORDER BY id")).fetchall()
    out = []
    for mid, name, mtype in machines:
        erow = db.execute(
            text(
                "SELECT MIN(energy_kwh), MAX(energy_kwh), COUNT(*) FROM telemetry "
                "WHERE machine_id = :m AND ts >= :start"
            ),
            {"m": mid, "start": start},
        ).fetchone()
        emin, emax, tcount = erow[0], erow[1], erow[2]
        energy_kwh = (emax - emin) if (emin is not None and emax is not None) else 0.0

        lrow = db.execute(
            text(
                "SELECT power_kw, machine_state, source, ts FROM telemetry "
                "WHERE machine_id = :m ORDER BY ts DESC LIMIT 1"
            ),
            {"m": mid},
        ).fetchone()

        prow = db.execute(
            text(
                "SELECT COALESCE(SUM(qty_good_kg), 0), COALESCE(SUM(qty_total_kg), 0) "
                "FROM production_record WHERE machine_id = :m AND window_start >= :start"
            ),
            {"m": mid, "start": start},
        ).fetchone()

        qrows = db.execute(
            text(
                "SELECT quality, COUNT(*) FROM telemetry "
                "WHERE machine_id = :m AND ts >= :start GROUP BY quality"
            ),
            {"m": mid, "start": start},
        ).fetchall()
        quality_counts = {q: c for q, c in qrows}

        out.append(
            {
                "machine_id": mid,
                "machine_name": name,
                "machine_type": mtype,
                "window_hours": hours,
                "energy_kwh": energy_kwh,
                "telemetry_rows": tcount,
                "latest_power_kw": lrow[0] if lrow else None,
                "latest_state": lrow[1] if lrow else None,
                "source": lrow[2] if lrow else None,
                "latest_ts": lrow[3] if lrow else None,
                "production_good_kg": prow[0],
                "production_total_kg": prow[1],
                "quality_counts": quality_counts,
            }
        )
    return {"machines": out, "window_hours": hours}
