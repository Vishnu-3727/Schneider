"""GET /dashboard/summary — per-machine rollup over a trailing window.

Phase 1 fields: energy (kWh from cumulative-counter deltas), latest power (kW),
production (kg), latest state, source tag, quality counts. No cost/CO2e.
Phase 2 adds: SEC (kWh/t) + status over the window and open-alert count.
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from apps.backend.config import get_settings
from apps.backend.db import get_db
from services.energy.sec import compute_sec
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

        # Phase 2: SEC over the window + open-alert count (DERIVED data).
        settings = get_settings()
        non_prod = [t.strip() for t in (settings.NON_PRODUCTION_TYPES or "").split(",") if t.strip()]
        has_prod = db.execute(
            text(
                "SELECT COUNT(*) FROM production_record "
                "WHERE machine_id = :m AND window_start >= :start"
            ),
            {"m": mid, "start": start},
        ).fetchone()[0] > 0
        sec = compute_sec(energy_kwh, float(prow[0]), has_prod, mtype, non_prod, True)
        alerts = db.execute(
            text(
                "SELECT COUNT(*) FROM anomaly_event "
                "WHERE machine_id = :m AND status = 'OPEN'"
            ),
            {"m": mid},
        ).fetchone()[0]

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
                "sec_kwh_per_t": sec.sec_kwh_per_t,
                "sec_status": sec.status,
                "non_productive_kwh": sec.non_productive_kwh,
                "open_alerts": alerts,
            }
        )
    return {"machines": out, "window_hours": hours}
