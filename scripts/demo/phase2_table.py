"""Phase-2 verification driver (dev DB): 7 NORMAL days + scenario, fit, detect.

Usage (backend running on the dev DB):
  .venv\\Scripts\\python scripts\\demo\\phase2_table.py

Truncates telemetry, production_record, machine_state, anomaly_event and
energy_baseline first. Prints per machine: day energy, production, SEC,
deviation %, event count — one table per scenario.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import httpx
import psycopg

from apps.backend.config import get_settings

API = "http://localhost:8000"
TZ = ZoneInfo("Asia/Kolkata")
SCENARIOS = ["NORMAL", "IDLE_WASTE", "HIGH_LOAD", "PRODUCTION_SURGE"]


def truncate() -> None:
    url = get_settings().DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    conn = psycopg.connect(url, autocommit=True)
    with conn.cursor() as cur:
        for tbl in ("telemetry", "production_record", "machine_state",
                    "anomaly_event", "energy_baseline"):
            cur.execute(f"TRUNCATE {tbl}")
    conn.close()


def main() -> int:
    end = datetime.now(TZ).replace(microsecond=0)
    fit_start = (end - timedelta(days=8)).isoformat()
    fit_end = (end - timedelta(days=1)).isoformat()
    det_end = end.isoformat()
    with httpx.Client(base_url=API, timeout=120.0) as api:
        for sc in SCENARIOS:
            truncate()
            r = subprocess.run(
                [sys.executable, "-m", "apps.simulator", "--normal-days", "7",
                 "--scenario", sc, "--hours", "24", "--post",
                 "--end", det_end],
                cwd=REPO, capture_output=True, text=True, check=False,
            )
            print(r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-500:])
            fit = api.post("/energy/baseline/fit",
                           json={"start": fit_start, "end": fit_end}).json()
            det = api.post("/energy/anomalies/detect",
                           json={"start": fit_end, "end": det_end}).json()
            body = api.get("/energy/summary",
                           params={"start": fit_end, "end": det_end}).json()
            summ = body["intervals"]
            aggs = {a["machine_id"]: a for a in body.get("aggregates", [])}
            evs = api.get("/energy/anomalies").json()["anomalies"]
            print(f"=== scenario {sc}: fits=" +
                  ",".join(f"{x['machine_id']}:{x['status']}:"
                            f"R2h={x.get('r2_holdout') and round(x['r2_holdout'], 4)}:"
                            f"CVh={x.get('cv_rmse_pct_holdout') and round(x['cv_rmse_pct_holdout'], 2)}:"
                            f"NMBEh={x.get('nmbe_pct_holdout') and round(x['nmbe_pct_holdout'], 2)}:"
                            f"{x.get('acceptance')}"
                            for x in fit["fits"]))
            print(f"=== scenario {sc}: detect created={det['created']}")
            print(f"{'machine':14} {'E_day':>9} {'prod_kg':>9} {'SEC':>9} "
                  f"{'SEC_st':>16} {'mean_dev%':>9} {'events':>6}")
            for mid in ("furnace-01", "compressor-01", "pump-01"):
                win = [i for i in summ if i["machine_id"] == mid]
                agg = aggs.get(mid, {})
                e_day = agg.get("total_actual_kwh") or sum(i["actual_kwh"] or 0.0 for i in win)
                p_day = agg.get("total_good_production_kg")
                if p_day is None:
                    p_day = sum(i["good_production_kg"] or 0.0 for i in win)
                # Window SEC = total energy / total good production (never the
                # mean of hourly SEC values), via services.energy.sec.
                sec_v = agg.get("window_sec_kwh_per_t")
                sec_s = f"{sec_v:.0f}" if sec_v is not None else "-"
                st = agg.get("window_sec_status") or "-"
                devs = [i["deviation_pct"] for i in win if i["deviation_pct"] is not None]
                md = f"{sum(devs) / len(devs):+.1f}" if devs else "-"
                ne = len([e for e in evs if e["machine_id"] == mid])
                print(f"{mid:14} {e_day:9.0f} {p_day:9.0f} {sec_s:>9} "
                      f"{st:>16} {md:>9} {ne:6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
