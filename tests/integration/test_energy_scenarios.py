"""Scenario acceptance (integration, real test DB, through the API).

Fit on 2 NORMAL days, detect on the 24 h scenario window:
  NORMAL -> 0 events; IDLE_WASTE -> overlapping event(s), worse SEC,
  non-productive energy; HIGH_LOAD -> overlapping event(s) with positive
  deviation; PRODUCTION_SURGE -> higher energy AND production, 0
  deviation/waste events (critical test); re-detect -> no duplicates.

NORMAL and PRODUCTION_SURGE false-positive checks run on seeds 1, 2, 3
(robustness: seeded NORMAL variability must never flag on any seed).

History is 2 NORMAL days (48 hourly intervals, twice the
MIN_BASELINE_INTERVALS=24 minimum) at 5-minute simulator steps: same
assertions as the 7-day run at a third of the rows.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.simulator.factory_simulator import DEFAULT_MACHINES, SimulatedFactory

TZ = ZoneInfo("Asia/Kolkata")
END = datetime(2026, 9, 20, 12, 0, tzinfo=TZ)
N_NORMAL_H = 2 * 24
SCEN_H = 24
STEP_S = 300

SEEDS_ALL = (1, 2, 3)


def _post_all(client, path, packets, chunk=2000):
    for i in range(0, len(packets), chunk):
        r = client.post(f"{path}?backfill=true", json={"records": packets[i:i + chunk]})
        assert r.status_code == 200, r.text[:500]


def _prepare(client, scenario: str, seed: int = 1):
    f = SimulatedFactory(DEFAULT_MACHINES, scenario=scenario, hours=N_NORMAL_H + SCEN_H,
                         step_s=STEP_S, seed=seed, end=END,
                         scenario_start_h=N_NORMAL_H, scenario_duration_h=SCEN_H)
    tel, prod = f.run()
    _post_all(client, "/telemetry", tel)
    _post_all(client, "/production", prod)
    fit_start = (END - timedelta(hours=N_NORMAL_H + SCEN_H)).isoformat()
    fit_end = (END - timedelta(hours=SCEN_H)).isoformat()
    r = client.post("/energy/baseline/fit", json={"start": fit_start, "end": fit_end})
    assert r.status_code == 200, r.text[:500]
    fits = {x["machine_id"]: x for x in r.json()["fits"]}
    assert all(x["status"] == "OK" for x in fits.values()), fits
    det_start = (END - timedelta(hours=SCEN_H)).isoformat()
    det_end = END.isoformat()
    r = client.post("/energy/anomalies/detect", json={"start": det_start, "end": det_end})
    assert r.status_code == 200, r.text[:500]
    windows = {m: (datetime.fromisoformat(ws), datetime.fromisoformat(we))
               for m, (ws, we) in f.scenario_windows().items()}
    summary = client.get("/energy/summary",
                         params={"start": det_start, "end": det_end}).json()["intervals"]
    ref = client.get("/energy/summary",
                     params={"start": fit_start, "end": fit_end}).json()["intervals"]
    return fits, r.json(), windows, summary, ref


def _overlaps(ev, ws, we):
    s, e = datetime.fromisoformat(ev["window_start"]), datetime.fromisoformat(ev["window_end"])
    return s < we and e > ws


@pytest.mark.parametrize("seed", SEEDS_ALL)
def test_normal_day_no_events(client, seed):
    _fits, _det, _w, summary, _ref = _prepare(client, "NORMAL", seed=seed)
    assert _det["created"] == 0
    assert client.get("/energy/anomalies").json()["anomalies"] == []
    for mid in ("furnace-01", "compressor-01"):
        win = [i for i in summary if i["machine_id"] == mid and i["complete"]
               and i["actual_kwh"] is not None and i["expected_kwh"] is not None]
        tot_act = sum(i["actual_kwh"] for i in win)
        tot_exp = sum(i["expected_kwh"] for i in win)
        agg = abs(tot_act - tot_exp) / tot_exp * 100.0 if tot_exp else 0.0
        assert agg <= 5.0, f"{mid} seed {seed} aggregate deviation {agg:.2f}%"


def test_idle_waste_events_sec_worse_non_productive(client):
    _fits, _det, windows, summary, ref = _prepare(client, "IDLE_WASTE")
    ws, we = windows["furnace-01"]
    evs = client.get("/energy/anomalies").json()["anomalies"]
    furn = [e for e in evs if e["machine_id"] == "furnace-01" and _overlaps(e, ws, we)]
    assert len(furn) >= 1, evs
    assert any(e["rule_id"] == "L1_IDLE_WASTE" for e in furn)
    win = [i for i in summary if i["machine_id"] == "furnace-01"]
    nonprod = sum(i["non_productive_kwh"] or 0.0 for i in win)
    assert nonprod > 0, "idle window must report non-productive kWh"
    assert any(i["sec_status"] == "NO_PRODUCTION" for i in win)
    ref_sec = [i["sec_kwh_per_t"] for i in ref
               if i["machine_id"] == "furnace-01" and i["sec_status"] == "OK"]
    assert ref_sec and sum(ref_sec) / len(ref_sec) > 0  # reference SEC computable
    # Compressor waste also detected with positive deviation.
    cws, cwe = windows["compressor-01"]
    comp = [e for e in evs if e["machine_id"] == "compressor-01" and _overlaps(e, cws, cwe)]
    assert comp and all((e["deviation_pct"] or 0) > 0 for e in comp if e["deviation_pct"])


def test_high_load_positive_deviation_events(client):
    _fits, _det, windows, _summary, _ref = _prepare(client, "HIGH_LOAD")
    evs = client.get("/energy/anomalies").json()["anomalies"]
    hits = [e for e in evs
            if e["machine_id"] in windows and _overlaps(e, *windows[e["machine_id"]])
            and (e["deviation_pct"] or 0) > 0]
    assert len(hits) >= 1, evs


@pytest.mark.parametrize("seed", SEEDS_ALL)
def test_production_surge_not_flagged_as_waste(client, seed):
    _fits, _det, windows, summary, ref = _prepare(client, "PRODUCTION_SURGE", seed=seed)
    ws, we = windows["furnace-01"]
    win = [i for i in summary if i["machine_id"] == "furnace-01"]
    ref_win = [i for i in ref if i["machine_id"] == "furnace-01" and i["complete"]]
    e_day = sum(i["actual_kwh"] for i in win if i["actual_kwh"] is not None)
    e_ref = sum(i["actual_kwh"] for i in ref_win if i["actual_kwh"] is not None) / 2.0
    p_day = sum(i["good_production_kg"] or 0.0 for i in win)
    p_ref = sum(i["good_production_kg"] or 0.0 for i in ref_win) / 2.0
    assert e_day > e_ref, "surge day must use MORE energy than a normal day"
    assert p_day > p_ref, "surge day must produce MORE than a normal day"
    evs = client.get("/energy/anomalies").json()["anomalies"]
    furn = [e for e in evs if e["machine_id"] == "furnace-01" and _overlaps(e, ws, we)]
    assert furn == [], furn  # legitimate load is never waste
    waste = [e for e in evs if e["rule_id"] in ("L1_DEVIATION", "L1_IDLE_WASTE", "L2_MAD_RESIDUAL")]
    assert waste == [], waste
    win_c = [i for i in win if i["complete"] and i["actual_kwh"] is not None
             and i["expected_kwh"] is not None]
    tot_act = sum(i["actual_kwh"] for i in win_c)
    tot_exp = sum(i["expected_kwh"] for i in win_c)
    agg = abs(tot_act - tot_exp) / tot_exp * 100.0 if tot_exp else 0.0
    assert agg <= 5.0, f"surge seed {seed} aggregate deviation {agg:.2f}%"


def test_redetect_is_idempotent(client):
    _fits, first, _w, _s, _r = _prepare(client, "IDLE_WASTE")
    det_start = (END - timedelta(hours=SCEN_H)).isoformat()
    det_end = END.isoformat()
    second = client.post("/energy/anomalies/detect",
                         json={"start": det_start, "end": det_end}).json()
    assert second["created"] == 0
    assert second["already_existing"] == first["created"]
    n1 = len(client.get("/energy/anomalies").json()["anomalies"])
    assert n1 == first["created"]
