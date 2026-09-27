"""Phase 4A acceptance tests 1-7 (integration, real test DB, through the API).

One module-scoped fixture ingests 2 NORMAL days + 1 TARIFF_SHIFT day once
(10-minute steps) and fits the furnace-01 baseline on the NORMAL window;
all tests share it. Solver time limits are short to keep the suite fast.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from apps.backend.config import get_settings
from apps.backend.db import get_db
from apps.simulator.factory_simulator import DEFAULT_MACHINES, SimulatedFactory
from services.optimization.constraints import (
    AuxTask,
    HeatTemplate,
    OptConstraints,
    Schedule,
)
from services.optimization.validate import validate

TZ = ZoneInfo("Asia/Kolkata")
END = datetime(2026, 9, 20, 0, 0, tzinfo=TZ)  # TARIFF day = Sep 19 (local)
N_NORMAL_H = 48
SCEN_H = 24
STEP_S = 600
NORMAL_DAY = "2026-09-18"
SHIFT_DAY = "2026-09-19"


def _post_all(client, path, packets, chunk=2000):
    for i in range(0, len(packets), chunk):
        r = client.post(f"{path}?backfill=true", json={"records": packets[i:i + chunk]})
        assert r.status_code == 200, r.text[:500]


@pytest.fixture(scope="module")
def p4a(_test_db):
    from apps.backend import db as dbmod
    from apps.backend.main import create_app

    dbmod.reset_engine()
    app = create_app()
    with TestClient(app) as c:
        eng = dbmod.get_engine()
        with eng.begin() as conn:
            for tbl in ("telemetry", "production_record", "machine_state",
                        "audit_event", "anomaly_event", "energy_baseline",
                        "machine_health", "machine_health_reference",
                        "optimization_run", "recommendation"):
                conn.execute(text(f"TRUNCATE {tbl}"))
        f = SimulatedFactory(DEFAULT_MACHINES, scenario="TARIFF_SHIFT",
                             hours=N_NORMAL_H + SCEN_H, step_s=STEP_S, seed=7,
                             end=END, scenario_start_h=N_NORMAL_H,
                             scenario_duration_h=SCEN_H,
                             tariff_peak_start_h=18.0, tariff_peak_end_h=22.0)
        tel, prod = f.run()
        _post_all(c, "/telemetry", tel)
        _post_all(c, "/production", prod)
        fit_start = (END - timedelta(hours=N_NORMAL_H + SCEN_H)).isoformat()
        fit_end = (END - timedelta(hours=SCEN_H)).isoformat()
        r = c.post("/energy/baseline/fit",
                   json={"machine_id": "furnace-01",
                         "start": fit_start, "end": fit_end})
        assert r.status_code == 200, r.text[:500]
        fit = r.json()["fits"][0]
        assert fit["status"] == "OK", fit
        assert fit["acceptance"] == "ACCEPTABLE", fit
        yield {"client": c, "fit": fit, "engine": eng}


def _stored_constraints(run: dict) -> OptConstraints:
    cd = run["constraints"]["constraints"]
    h = cd["heat"]
    hts = cd.get("heat_templates")
    return OptConstraints(
        n_slots=cd["n_slots"], slot_min=cd["slot_min"],
        horizon_start_iso=cd["horizon_start"], n_heats=cd["n_heats"],
        heat=HeatTemplate(charge_kg=h["charge_kg"],
                          heating_slots=h["heating_slots"],
                          melting_slots=h["melting_slots"],
                          min_hold_slots=h["min_hold_slots"],
                          max_hold_slots=h["max_hold_slots"]),
        heat_templates=(
            None if hts is None else [
                HeatTemplate(charge_kg=t["charge_kg"],
                             heating_slots=t["heating_slots"],
                             melting_slots=t["melting_slots"],
                             min_hold_slots=t["min_hold_slots"],
                             max_hold_slots=t["max_hold_slots"])
                for t in hts]),
        operating_windows=[tuple(w) for w in cd["operating_windows"]],
        maintenance_windows=[tuple(w) for w in cd["maintenance_windows"]],
        peak_cap_kw=cd["peak_cap_kw"],
        cold_threshold_slots=cd["cold_threshold_slots"],
        reheat_extra_slots=cd["reheat_extra_slots"],
        first_heat_cold=cd["first_heat_cold"],
        aux_tasks=[AuxTask(**a) for a in cd.get("aux_tasks", [])])


def _state_median_powers(p4a) -> dict:
    fit = p4a["fit"]
    with p4a["engine"].connect() as conn:
        rows = conn.execute(text(
            "SELECT machine_state, percentile_cont(0.5) WITHIN GROUP "
            "(ORDER BY power_kw) FROM telemetry WHERE machine_id = 'furnace-01' "
            "AND ts >= CAST(:s AS timestamptz) AND ts < CAST(:e AS timestamptz) "
            "AND quality = 'GOOD' AND power_kw IS NOT NULL GROUP BY 1"),
            {"s": fit["train_start"], "e": fit["train_end"]}).fetchall()
    return {r[0]: float(r[1]) for r in rows}


def test_1_valid_constraints_feasible_and_valid(p4a):
    c = p4a["client"]
    r = c.post("/optimization/run", json={
        "machine_id": "furnace-01", "date": NORMAL_DAY,
        "constraints": {"required_heats": 6, "time_limit_s": 2.0}})
    assert r.status_code == 200, r.text[:500]
    run = r.json()
    assert run["status"] in ("OPTIMAL", "FEASIBLE"), run["explanation"]
    rec = Schedule.from_dict(run["recommended"])
    assert validate(rec, _stored_constraints(run)) == []
    # Full independent re-validation with real state powers is done in
    # test_4 (peak) and the pure suite; here check production + shape.
    assert run["metrics"]["recommended"]["production_kg"]["value"] == \
        pytest.approx(6 * 375.0)
    assert run["metrics"]["recommended"]["energy_kwh"]["source"] == "PROJECTED"
    # GET latest returns this run.
    g = c.get("/optimization/schedule", params={"machine_id": "furnace-01"})
    assert g.status_code == 200 and g.json()["id"] == run["id"]
    g2 = c.get("/optimization/schedule", params={"id": run["id"]})
    assert g2.status_code == 200 and g2.json()["status"] == run["status"]


def test_2_tariff_shift_recommended_cheaper(p4a):
    c = p4a["client"]
    r = c.post("/optimization/run", json={
        "machine_id": "furnace-01", "date": SHIFT_DAY,
        "constraints": {"time_limit_s": 3.0}})
    assert r.status_code == 200, r.text[:500]
    run = r.json()
    assert run["status"] in ("OPTIMAL", "FEASIBLE"), run["explanation"]
    cur = run["metrics"]["current"]
    rec = run["metrics"]["recommended"]
    print(f"\nTARIFF_SHIFT day: current cost INR {cur['cost_inr']['value']:.0f} "
          f"({cur['energy_kwh']['value']:.0f} kWh, {cur['production_kg']['value']:.0f} kg) "
          f"-> recommended INR {rec['cost_inr']['value']:.0f} "
          f"({rec['energy_kwh']['value']:.0f} kWh, {rec['production_kg']['value']:.0f} kg)")
    assert rec["cost_inr"] is not None
    assert rec["cost_inr"]["value"] < cur["cost_inr"]["value"]
    assert rec["production_kg"]["value"] == pytest.approx(cur["production_kg"]["value"])
    assert validate(Schedule.from_dict(run["recommended"]),
                    _stored_constraints(run)) == []


def test_3a_infeasible_too_few_operating_hours(p4a):
    c = p4a["client"]
    r = c.post("/optimization/run", json={
        "machine_id": "furnace-01", "date": NORMAL_DAY,
        "constraints": {"required_heats": 6,
                        "operating_windows_h": [[0, 2]],
                        "time_limit_s": 2.0}})
    assert r.status_code == 200, r.text[:500]
    run = r.json()
    assert run["status"] == "INFEASIBLE"
    assert "NO FEASIBLE PLAN" in run["explanation"]
    assert "operating-hours" in run["explanation"]
    assert run["recommended"] is None


def test_3b_infeasible_peak_cap_below_melting(p4a):
    c = p4a["client"]
    r = c.post("/optimization/run", json={
        "machine_id": "furnace-01", "date": NORMAL_DAY,
        "constraints": {"required_heats": 2, "peak_cap_kw": 10.0,
                        "time_limit_s": 2.0}})
    assert r.status_code == 200, r.text[:500]
    run = r.json()
    assert run["status"] == "INFEASIBLE"
    assert "NO FEASIBLE PLAN" in run["explanation"]
    assert "peak-cap" in run["explanation"]


def test_4_peak_cap_hard_vs_objective(p4a):
    c = p4a["client"]
    start = datetime(2026, 9, 18, 0, 0, tzinfo=TZ).isoformat()
    end = datetime(2026, 9, 18, 12, 0, tzinfo=TZ).isoformat()
    r = c.post("/optimization/run", json={
        "machine_id": "furnace-01", "start": start, "end": end,
        "constraints": {"required_heats": 3, "slot_min": 30,
                        "peak_cap_kw": 150.0,
                        "aux_tasks": [{"name": "pump-job", "duration_h": 1.0,
                                       "window_start_h": 0.0, "window_end_h": 12.0,
                                       "power_kw": 30.0}],
                        "time_limit_s": 3.0}})
    assert r.status_code == 200, r.text[:500]
    run = r.json()
    assert run["status"] in ("OPTIMAL", "FEASIBLE"), run["explanation"]
    rec = Schedule.from_dict(run["recommended"])
    cc = _stored_constraints(run)
    medians = _state_median_powers(p4a)
    assert medians["melting"] < 150.0 < medians["melting"] + 30.0  # tension setup
    assert validate(rec, cc, medians) == []
    cur = run["metrics"]["current"]
    recm = run["metrics"]["recommended"]
    print(f"\npeak-cap case: current INR {cur['cost_inr']['value']:.0f} "
          f"({cur['energy_kwh']['value']:.0f} kWh) -> recommended "
          f"INR {recm['cost_inr']['value']:.0f} ({recm['energy_kwh']['value']:.0f} kWh), "
          f"peak {recm['peak_kw']['value']:.1f} kW vs cap 150 kW")
    # Cap never exceeded on any slot (median melting ~142 + aux 30 > 150).
    assert recm["peak_kw"]["value"] <= 150.0 + 1e-9
    assert recm["production_kg"]["value"] == pytest.approx(3 * 375.0)


def test_5_reproducible(p4a):
    c = p4a["client"]
    body = {"machine_id": "furnace-01", "date": NORMAL_DAY,
            "constraints": {"required_heats": 1, "slot_min": 30,
                            "horizon_h": 6, "time_limit_s": 2.0}}
    r1 = c.post("/optimization/run", json=body).json()
    r2 = c.post("/optimization/run", json=body).json()
    assert r1["status"] == r2["status"] == "OPTIMAL"
    assert r1["recommended"] == r2["recommended"]
    assert r1["metrics"] == r2["metrics"]


def test_6a_no_baseline_unavailable(p4a):
    c = p4a["client"]
    r = c.post("/optimization/run", json={
        "machine_id": "compressor-01", "date": NORMAL_DAY,
        "constraints": {"required_heats": 1, "time_limit_s": 1.0}})
    assert r.status_code == 200, r.text[:500]
    run = r.json()
    assert run["status"] == "BASELINE_UNAVAILABLE"
    assert "baseline" in run["explanation"].lower()


def test_6b_no_tariff_cost_absent_no_invented_price(p4a):
    c = p4a["client"]
    eng = p4a["engine"]
    saved = None
    with eng.begin() as conn:
        saved = conn.execute(text(
            "SELECT site_id, period_name, start_local, end_local, "
            "energy_inr_per_kwh, demand_inr_per_kw, valid_from, source_class, "
            "reference_note FROM tariff")).fetchall()
        conn.execute(text("DELETE FROM tariff"))
    try:
        r = c.post("/optimization/run", json={
            "machine_id": "furnace-01", "date": NORMAL_DAY,
            "constraints": {"required_heats": 2, "slot_min": 30,
                            "horizon_h": 12, "time_limit_s": 2.0}})
        assert r.status_code == 200, r.text[:500]
        run = r.json()
        assert run["status"] in ("OPTIMAL", "FEASIBLE"), run["explanation"]
        assert run["metrics"]["recommended"]["cost_inr"] is None
        assert run["metrics"]["cost_status"] == "unavailable (no tariff)"
    finally:
        with eng.begin() as conn:
            for row in saved:
                conn.execute(text(
                    "INSERT INTO tariff (site_id, period_name, start_local, end_local, "
                    "energy_inr_per_kwh, demand_inr_per_kw, valid_from, source_class, "
                    "reference_note) VALUES (:s, :p, :st, :en, :e, :d, :v, :sc, :rn) "
                    "ON CONFLICT DO NOTHING"),
                    {"s": row[0], "p": row[1], "st": row[2], "en": row[3],
                     "e": row[4], "d": row[5], "v": row[6], "sc": row[7],
                     "rn": row[8]})


def test_7_process_efficiency_endpoint(p4a):
    c = p4a["client"]
    start = datetime(2026, 9, 19, 0, 0, tzinfo=TZ).isoformat()
    end = datetime(2026, 9, 20, 0, 0, tzinfo=TZ).isoformat()
    r = c.get("/process/efficiency",
              params={"start": start, "end": end, "machine_id": "furnace-01"})
    assert r.status_code == 200, r.text[:500]
    results = r.json()["results"]
    assert len(results) == 1
    day = results[0]
    assert day["source"] == "DERIVED"
    assert day["idle_hours"] >= 0 and day["holding_hours"] > 0
    assert len(day["findings"]) == 5
    for f in day["findings"]:
        for key in ("metric", "value", "reference", "evidence", "source"):
            assert key in f, f
        assert f["source"] == "DERIVED"
    refs = [f["reference"] for f in day["findings"]]
    assert any(x is not None for x in refs)  # NORMAL medians attached


def test_unknown_machine_404(p4a):
    c = p4a["client"]
    assert c.post("/optimization/run",
                  json={"machine_id": "nope", "date": NORMAL_DAY}).status_code == 404
    assert c.get("/optimization/schedule",
                 params={"machine_id": "nope"}).status_code == 404
    assert c.get("/process/efficiency",
                 params={"start": NORMAL_DAY + "T00:00:00+05:30",
                         "end": SHIFT_DAY + "T00:00:00+05:30",
                         "machine_id": "nope"}).status_code == 404


def test_8_full_horizon_deterministic_x3(p4a):
    """B0: FULL 24 h TARIFF_SHIFT case solved 3x -> byte-identical plan+metrics."""
    import json as _json

    c = p4a["client"]
    body = {"machine_id": "furnace-01", "date": SHIFT_DAY,
            "constraints": {"time_limit_s": 10.0, "deterministic_time_s": 5.0}}
    runs = [c.post("/optimization/run", json=body) for _ in range(3)]
    for r in runs:
        assert r.status_code == 200, r.text[:500]
    bodies = [r.json() for r in runs]
    assert {b["status"] for b in bodies} <= {"OPTIMAL", "FEASIBLE"}, \
        [b["explanation"] for b in bodies]
    rec_blobs = [_json.dumps(b["recommended"], sort_keys=True) for b in bodies]
    met_blobs = [_json.dumps(b["metrics"], sort_keys=True) for b in bodies]
    assert rec_blobs[0] == rec_blobs[1] == rec_blobs[2]
    assert met_blobs[0] == met_blobs[1] == met_blobs[2]


def test_9_energy_breakdown_current_vs_recommended(p4a):
    """B0: evaluate() carries a per-state breakdown summing to the total.

    Reads back the latest full-horizon run (no extra solve keeps the suite
    fast); also prints the current vs recommended breakdown for the report.
    """
    c = p4a["client"]
    g = c.get("/optimization/schedule", params={"machine_id": "furnace-01"})
    assert g.status_code == 200
    run = g.json()
    assert run["status"] in ("OPTIMAL", "FEASIBLE"), run["explanation"]
    assert run["metrics"]["recommended"] is not None
    for side in ("current", "recommended"):
        br = run["metrics"][side].get("energy_by_state_kwh")
        assert br is not None, side
        assert set(br) >= {"heating", "melting", "holding", "idle", "reheat"}, br
        total = sum(v["value"] for v in br.values())
        assert total == pytest.approx(
            run["metrics"][side]["energy_kwh"]["value"], rel=1e-6), (side, br)
        for v in br.values():
            assert v["unit"] == "kWh" and v["source"] == "PROJECTED"
    cur = {k: v["value"] for k, v in run["metrics"]["current"]["energy_by_state_kwh"].items()}
    rec = {k: v["value"] for k, v in run["metrics"]["recommended"]["energy_by_state_kwh"].items()}
    print(f"\nTARIFF_SHIFT breakdown current vs recommended (kWh): "
          f"{ {k: (round(cur[k], 1), round(rec[k], 1)) for k in cur} }")


def test_f3_current_schedule_reconstruction_matches_telemetry(p4a):
    """F3: Reconstruct the CURRENT schedule of the TARIFF_SHIFT day and verify
    
    1. validate() reports no violations (no overlap, all constraints satisfied)
    2. Reconstructed slot occupancy equals observed telemetry slot states exactly
    """
    c = p4a["client"]
    # First run the optimization for the TARIFF_SHIFT day (same as test_2)
    r = c.post("/optimization/run", json={
        "machine_id": "furnace-01", "date": SHIFT_DAY,
        "constraints": {"time_limit_s": 3.0}})
    assert r.status_code == 200, r.text[:500]
    run = r.json()
    assert run["status"] in ("OPTIMAL", "FEASIBLE"), run["explanation"]
    
    # Reconstruct the current schedule from the stored data
    current_sched = run["current"]
    assert current_sched is not None
    
    # Build Schedule object
    sched = Schedule.from_dict(current_sched)
    
    # Get the stored constraints for validation
    constraints = _stored_constraints(run)
    
    # Get state powers for peak validation
    medians = _state_median_powers(p4a)
    
    # 1. validate() reports no violations
    violations = validate(sched, constraints, medians)
    assert violations == [], f"validate() reported violations: {violations}"
    
    # 2. Reconstructed slot occupancy equals observed telemetry slot states exactly
    n_slots = current_sched["n_slots"]
    
    # Reconstruct slot states from the schedule
    reconstructed_states = ["idle"] * n_slots
    for h in sched.heats:
        t = h.start_slot
        for _ in range(h.heating_slots):
            if 0 <= t < n_slots:
                reconstructed_states[t] = "heating"
            t += 1
        for _ in range(h.melting_slots):
            if 0 <= t < n_slots:
                reconstructed_states[t] = "melting"
            t += 1
        for _ in range(h.holding_slots):
            if 0 <= t < n_slots:
                reconstructed_states[t] = "holding"
            t += 1
    
    # Aux tasks
    for a in sched.aux:
        for t in range(a.start_slot, a.end_slot):
            if 0 <= t < n_slots:
                reconstructed_states[t] = f"aux:{a.name}"
    
    # Recompute from telemetry using the same logic as the API
    s = get_settings()
    tz = ZoneInfo(s.TZ)
    start = datetime.fromisoformat(current_sched["horizon_start"])
    slot_min = current_sched["slot_min"]
    eng = p4a["engine"]
    with eng.connect() as db:
        rows = db.execute(
            text(
                "SELECT ts, machine_state FROM telemetry WHERE machine_id = :m "
                "AND ts >= :start AND ts < :end AND quality = 'GOOD' "
                "AND machine_state IS NOT NULL ORDER BY ts"
            ),
            {"m": "furnace-01", "start": start,
             "end": start + timedelta(minutes=n_slots * slot_min)},
        ).fetchall()
    buckets: list[dict[str, int]] = [{} for _ in range(n_slots)]
    for ts, st in rows:
        k = int((ts - start).total_seconds() // 60 // slot_min)
        if 0 <= k < n_slots:
            buckets[k][st] = buckets[k].get(st, 0) + 1
    stored_slot_states = [max(b, key=b.get) if b else "idle" for b in buckets]
    
    # Compare: for each slot, the dominant state should match
    # Note: aux tasks are additional load on top of furnace state
    # We compare the furnace state (heating/melting/holding/idle)
    for i in range(n_slots):
        stored = stored_slot_states[i]
        recon = reconstructed_states[i]
        # Skip aux slots for comparison (aux is additional)
        if recon.startswith("aux:"):
            continue
        assert stored == recon, (
            f"Slot {i} mismatch: telemetry={stored}, reconstructed={recon}"
        )
