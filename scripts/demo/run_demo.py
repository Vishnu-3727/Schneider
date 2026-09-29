"""End-to-end demo driver (dev DB): the full JouleMitra story through the API.

normal history -> chronic idle waste -> baseline -> detect -> health -> insights
-> optimise -> recommend -> approve -> intervene -> verify -> cost + CO2.

Usage (Postgres up, backend running on the dev DB):
  .venv\\Scripts\\python scripts\\demo\\run_demo.py            # REDUCE_IDLE, expect VERIFIED
  .venv\\Scripts\\python scripts\\demo\\run_demo.py --shifted  # operating conditions shift,
                                                             # expect NOT_COMPARABLE

Truncates every analytics table first (same set as tests/conftest.py). All data
is SIMULATED; the intervention changes simulator physics from the applied time
on (effectiveness / rebound), no outcome is injected. The compressor and pump
run on the same timeline with idle waste in the last 24 h, so the console
(/console/) has a detected anomaly, health for every machine and open
recommendations alongside the verified saving. Every printed figure is read
from an API response.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

import httpx
import psycopg

from apps.backend.config import get_settings
from apps.simulator.factory_simulator import MachineSpec, SimulatedFactory

TZ = ZoneInfo("Asia/Kolkata")
BASE_H, POST_H = 24 * 7, 24 * 3
MACHINE = "furnace-01"
TABLES = ("telemetry", "production_record", "machine_state", "audit_event",
          "anomaly_event", "energy_baseline", "machine_health",
          "machine_health_reference", "optimization_run", "recommendation",
          "intervention", "verification_result")


class DemoError(RuntimeError):
    pass


def truncate() -> None:
    url = get_settings().DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn, conn.cursor() as cur:
        for tbl in TABLES:
            cur.execute(f"TRUNCATE {tbl} CASCADE")


def call(api: httpx.Client, method: str, path: str, **kw) -> dict:
    r = api.request(method, path, **kw)
    if r.status_code != 200:
        raise DemoError(f"{method} {path} -> HTTP {r.status_code}: {r.text[:500]}")
    return r.json()


def ingest(api: httpx.Client, end: datetime, seed: int, shifted: bool) -> None:
    extra = {"post_idle_scale": 0.1} if shifted else {}
    fac = SimulatedFactory([MachineSpec(MACHINE, "furnace", 200.0)], hours=BASE_H + POST_H,
                           step_s=300, seed=seed, end=end, chronic_idle_hold_frac=0.6,
                           intervention={"type": "REDUCE_IDLE", "start_h": BASE_H,
                                         "effectiveness": 1.0, "rebound": 0.15},
                           **extra)
    tel, prod = fac.run()
    # Rest of the plant on the same timeline, so every console screen has a
    # story: compressor idle waste in the last 24 h (pump stays the control).
    rest = SimulatedFactory([MachineSpec("compressor-01", "compressor", 30.0),
                             MachineSpec("pump-01", "pump", 15.0)],
                            scenario="IDLE_WASTE", hours=BASE_H + POST_H, step_s=300, seed=seed,
                            end=end, scenario_start_h=BASE_H + POST_H - 24, scenario_duration_h=24)
    rtel, rprod = rest.run()
    tel, prod = tel + rtel, prod + rprod
    for path, recs in (("/telemetry?backfill=true", tel), ("/production?backfill=true", prod)):
        for i in range(0, len(recs), 1000):
            call(api, "POST", path, json={"records": recs[i:i + 1000]})
    print(f"[1] ingested {len(tel)} telemetry + {len(prod)} production records (SIMULATED)")


def pick_recommendation(recs: list[dict]) -> dict:
    mine = [r for r in recs if r["machine_id"] == MACHINE and r["status"] == "PENDING_REVIEW"]
    idle = [r for r in mine if "IDLE" in (r.get("rule_id") or "").upper()]
    if not (idle or mine):
        raise DemoError(f"no PENDING_REVIEW recommendation for {MACHINE}: {recs}")
    return (idle or mine)[0]


def fmt(v, nd=1) -> str:
    return "-" if v is None else (f"{v:,.{nd}f}" if isinstance(v, (int, float)) else str(v))


def report(v: dict) -> None:
    cost, co2 = v.get("cost_impact") or {}, v.get("co2_impact") or {}
    print("\n=== Verification (counterfactual, SIMULATED telemetry) ===")
    rows = [
        ("outcome", v.get("outcome")),
        ("result class", v.get("result_class")),
        ("counterfactual kWh (expected without change)", fmt(v.get("counterfactual_kwh"))),
        ("actual kWh (measured after change)", fmt(v.get("actual_kwh"))),
        ("saving kWh", fmt(v.get("saving_kwh"))),
        ("uncertainty kWh (90 %)", fmt(v.get("uncertainty_kwh"))),
        ("verified saving kWh", fmt(v.get("verified_saving_kwh"))),
    ]
    for k in ("before", "after", "delta"):
        if isinstance(v.get(k), dict):
            rows += [(f"{k} {m}", fmt(x, 3)) for m, x in v[k].items()]
    if cost.get("status") == "OK":
        rows.append(("cost INR", f"{fmt(cost['value_inr'], 0)}  [{cost['tariff_label']}]"))
    if co2.get("value_kg") is not None:
        f = co2["factor"]
        rows.append(("CO2 kg", (f"{fmt(co2['value_kg'])}  [{co2['unit']}; factor {f['value']} "
                                f"{f['version']} {f['source_class']}, "
                                f"provisional={co2['provisional']}]")))
    w = max(len(k) for k, _ in rows)
    for k, val in rows:
        print(f"  {k:<{w}}  {val}")
    if not v.get("comparable", True):
        print("  reasons:", "; ".join(map(str, v.get("comparability_reasons") or [])))
    print(" ", v.get("explanation", ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--shifted", action="store_true",
                    help="shift operating conditions after the change (expect NOT_COMPARABLE)")
    a = ap.parse_args()

    end = datetime.now(TZ).replace(second=0, microsecond=0)
    start = end - timedelta(hours=BASE_H + POST_H)
    applied = end - timedelta(hours=POST_H)
    ref_end = start + timedelta(days=5)  # reference window, then 2 pre-change days to score
    win = lambda s, e: {"start": s.isoformat(), "end": e.isoformat()}

    truncate()
    with httpx.Client(base_url=a.api, timeout=300.0) as api:
        ingest(api, end, a.seed, a.shifted)

        fit = call(api, "POST", "/energy/baseline/fit", json=win(start, ref_end))
        call(api, "POST", "/energy/anomalies/detect", json=win(ref_end, applied))
        call(api, "POST", "/energy/anomalies/detect", json=win(end - timedelta(days=1), end))
        stored = call(api, "GET", "/energy/anomalies").get("anomalies", [])
        by_m = sorted({f"{e.get('machine_id')}:{e.get('rule_id')}" for e in stored})
        n_fit = sum(1 for f in fit.get("fits", []) if f.get("status") == "OK")
        print(f"[2] baseline fitted ({n_fit} OK fits); {len(stored)} anomaly events "
              f"({by_m or 'none'}). The furnace's chronic idle waste sits inside its "
              f"reference window, so the baseline treats it as normal; the compressor's "
              f"waste in the last 24 h is new and is caught.")

        call(api, "POST", "/machine-health/fit", json=win(start, ref_end))
        call(api, "POST", "/machine-health/score", json=win(ref_end, end))
        insights = call(api, "GET", "/insights", params=win(ref_end, end)).get("insights", [])
        cats = sorted({i.get("category") for i in insights if i.get("category")})
        print(f"[3] health scored; insights: {len(insights)} (categories: {cats or 'none'})")

        opt = call(api, "POST", "/optimization/run", json={
            "machine_id": MACHINE, "date": (applied - timedelta(days=1)).date().isoformat()})
        print(f"[4] optimisation ({opt.get('source', 'PROJECTED')}): status {opt.get('status')}")

        call(api, "POST", "/recommendations/generate", json=win(ref_end, applied))
        rec = pick_recommendation(call(api, "GET", "/recommendations")["recommendations"])
        call(api, "POST", f"/recommendations/{rec['id']}/acknowledge",
             json={"decision": "APPROVED", "note": "demo operator approval"})
        print(f"[5] recommendation {rec['rule_id']}: '{rec['title']}' -> APPROVED")

        iv = call(api, "POST", "/interventions", json={
            "recommendation_id": rec["id"], "type": "REDUCE_IDLE",
            "applied_at": applied.isoformat(), "idempotency_key": f"demo-{uuid.uuid4()}",
            "parameters": {"note": "cut powered holding in idle gaps"}})["intervention"]
        v = call(api, "POST", f"/interventions/{iv['id']}/verify",
                 json=win(applied, end))["verification"]
        print(f"[6] intervention {iv['id']} applied {applied:%Y-%m-%d %H:%M}, verified")

        new = call(api, "POST", "/recommendations/generate", json=win(end - timedelta(days=1), end))
        print(f"[7] recommendations for the last 24 h: {new.get('created', new)} awaiting review")

    report(v)
    if v.get("outcome") == "NOT_COMPARABLE":
        print("\nUnable to verify savings under current conditions.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (DemoError, httpx.HTTPError) as e:
        print(f"DEMO FAILED: {e}", file=sys.stderr)
        sys.exit(1)
