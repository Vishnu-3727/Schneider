# JouleMitra — Validation (Phases 2–3)

Every number on this page comes from SIMULATED data (source class SIMULATED /
DERIVED). It is a prototype result that requires plant validation and says
nothing about real plant performance.

## Phase 2 scenario verification (SIMULATED data)

Live demo driver: `scripts/demo/phase2_table.py` (7 NORMAL days + a 24 h
scenario window at 60 s steps, seed 1; the baseline is fitted on the NORMAL
days, detection runs on the scenario window; the dev database is truncated
first). Run on 2026-09-27 against the local backend.

Per machine over the 24 h scenario window. SEC = Σenergy / Σgood production
over complete intervals. "Mean dev %" is the mean hourly deviation from the
expected baseline.

| Scenario | Machine | Energy kWh | Good prod kg | SEC kWh/t (status) | Mean dev % | Events |
|---|---|---:|---:|---|---:|---:|
| NORMAL | furnace-01 | 1771 | 3493 | 507 (OK) | −0.5 | 0 |
| NORMAL | compressor-01 | 500 | 0 | — (NOT_APPLICABLE) | +1.3 | 0 |
| NORMAL | pump-01 | 248 | 0 | — (NOT_APPLICABLE) | 0.0 | 0 |
| IDLE_WASTE | furnace-01 | 1593 | 0 | — (NO_PRODUCTION) | +4.0 | 1 |
| IDLE_WASTE | compressor-01 | 637 | 0 | — (NOT_APPLICABLE) | +29.0 | 2 |
| IDLE_WASTE | pump-01 | 248 | 0 | — (NOT_APPLICABLE) | 0.0 | 0 |
| HIGH_LOAD | furnace-01 | 2214 | 3493 | 634 (OK) | +24.4 | 7 |
| HIGH_LOAD | compressor-01 | 625 | 0 | — (NOT_APPLICABLE) | +26.6 | 3 |
| HIGH_LOAD | pump-01 | 248 | 0 | — (NOT_APPLICABLE) | 0.0 | 0 |
| PRODUCTION_SURGE | furnace-01 | 2423 | 4927 | 492 (OK) | −0.5 | 0 |
| PRODUCTION_SURGE | compressor-01 | 500 | 0 | — (NOT_APPLICABLE) | +1.3 | 0 |
| PRODUCTION_SURGE | pump-01 | 248 | 0 | — (NOT_APPLICABLE) | 0.0 | 0 |

Reading the results:

- **PRODUCTION_SURGE** (the key check): furnace energy +37 % and good
  production +41 % against the NORMAL day, with 0 events. SEC improves
  slightly (507 → 492 kWh/t) because the time-based holding and idle losses
  are spread over more tonnes.
- **IDLE_WASTE (furnace)**: the mean deviation is only +4 %. The baseline is
  conditioned on state hours, so a furnace held powered for 24 h is "expected"
  energy for those holding hours. The waste is caught by the non-productive
  energy rule (L1_IDLE_WASTE: zero production sustained for
  IDLE_CONSECUTIVE_N intervals), not by the deviation rule. The two rules
  answer different questions and both are needed.
- **HIGH_LOAD**: the same production at higher power gives a positive
  deviation on both affected machines, and SEC worsens from 507 to 634 kWh/t.
- **Pump**: the unaffected control machine. 0 events in every scenario.

## Baseline fit quality (held-out NORMAL intervals)

| Machine | R² holdout (info only) | CV(RMSE) % | NMBE % | ASHRAE G14 hourly |
|---|---:|---:|---:|---|
| furnace-01 | 0.9994 | 1.36 | 0.11 | ACCEPTABLE |
| compressor-01 | −0.09 | 7.02 | −2.03 | ACCEPTABLE |
| pump-01 | −0.11 | 0.14 | 0.04 | ACCEPTABLE |

A negative R² for the pump and compressor is expected: their hourly energy
barely varies, so R² is not meaningful and CV(RMSE)/NMBE are the criteria.
The compressor baseline has no air-demand driver. It detects a level shift
but cannot tell legitimate demand growth from waste (see docs/ML_MODELS.md,
limitations). The furnace fit is very tight because the simulator's per-kg
melting physics is linear. Expect a lower R² on real plant data.

## Automated acceptance

`pytest`: 93 passed, 0 failed (about 95 s). The scenario tests
(`tests/integration/test_energy_scenarios.py`) check:

- NORMAL and PRODUCTION_SURGE raise 0 events on seeds 1, 2 and 3, with the
  window-aggregate deviation within ±5 %.
- IDLE_WASTE and HIGH_LOAD raise events that overlap the injected window.
- Running detection again creates no duplicate events.

## Phase 3 health + correlation verification (SIMULATED data)

Verified 2026-09-27. `pytest`: 134 passed, 0 failed (about 151 s), including
the optional PBL ONNX test, which was enabled with `PBL_TEST_ONNX_PATH`.
Acceptance runs through the API against the real test database: the energy
baseline and the `statistical-v1` health reference are fitted on NORMAL
history, then the scenario window is scored.

| Scenario | Energy | Health | Expected | Result |
|---|---|---|---|---|
| NORMAL (seeds 1, 2, 3) | normal | normal | 0 energy events, 0 health WARNING/CRITICAL, 0 insights | PASS |
| IDLE_WASTE | abnormal | normal | ENERGY_ONLY insights only | PASS |
| EQUIPMENT_DEGRADATION, energy_penalty = 0 | normal | abnormal | HEALTH_ONLY, 0 energy events | PASS |
| EQUIPMENT_DEGRADATION, energy_penalty > 0 | abnormal | abnormal | COINCIDENT, both evidences, correlation wording | PASS |
| HIGH_LOAD with health signals omitted | abnormal | missing | Energy events still detected; ENERGY_ONLY_HEALTH_UNAVAILABLE; energy endpoints 200 | PASS |
| Health model raises an exception | — | error | /energy/summary, /energy/anomalies/detect and /dashboard/summary return 200; /machine-health reports ERROR with no traceback | PASS |

Notes:

- The energy-only case uses IDLE_WASTE, not HIGH_LOAD. HIGH_LOAD raises motor
  current, which the per-signal health reference flags, so HIGH_LOAD reports
  COINCIDENT. Current depends on load, so a COINCIDENT insight is a
  correlation for a human to inspect, not a health diagnosis.
- Every insight text is scanned for causal wording (cause, caused, because,
  due to, results from) by a unit test.
- `pbl-rul` (the PBL adapter) reports OUT_OF_DOMAIN for every factory machine
  and never emits a score for them. Its cited benchmark, test RMSE 14.51 vs
  RF baseline 14.41 (EXTERNAL_REFERENCE, from unify-rul `results/metrics.json`
  and `results/baseline_rf.json`), shows it is not better than the baseline.
  The artifact is loaded from a local path at runtime and is not distributed
  with JouleMitra.
- Live Docker check: the stack is healthy, the dashboard returns HTTP 200,
  and `/machine-health/models` lists `statistical-v1` and `pbl-rul`. In the
  container no artifact path is configured, so `pbl-rul` shows
  available = false.
