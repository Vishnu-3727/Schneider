# JouleMitra — Validation (Phases 2–4)

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

## Phase 4 optimisation + recommendation verification (SIMULATED data)

Verified 2026-09-27. `pytest`: 211 passed, 1 skipped (the optional PBL ONNX
test, which needs PBL_TEST_ONNX_PATH), about 248 s. Every figure below is
PROJECTED from the Phase-2 baseline coefficients and an ILLUSTRATIVE tariff
(ASSUMPTION, not a real tariff order). None of it is a measured or verified
saving.

| Check | Result (SIMULATED/PROJECTED) |
|---|---|
| Test 2, TARIFF_SHIFT day (fixture), same production 3375 kg | Comparable. Energy 1482.1 → 1450.9 kWh (−2.1 %); cost INR 11716 → 9999 (−14.7 %, illustrative tariff); peak 142.6 kW both sides |
| Test-2 breakdown current → recommended (kWh) | heating 370.1 → 370.1; melting 828.2 → 828.2; holding 137.1 → 137.1; idle 113.0 → 115.5; reheat 33.6 → 0.0. The energy delta is reheat avoided by closing one cold gap. Nothing else changes. |
| Live run (Docker stack, fresh 7-day NORMAL + TARIFF_SHIFT day, seed 1) | FEASIBLE and comparable; energy 1798.9 → 1798.9 kWh (no cold gap to avoid); cost INR 13978 → 12497 (−10.6 %, from time-of-use placement only); peak 142.5 kW both sides |
| Reproducibility | Full 24 h case ×3 byte-identical (test); live run ×2 identical schedule and metrics |
| Non-comparable run (production 3375 vs 1500 kg) | comparable = false with reason. Recommendation quantities null; kWh/t shown instead |
| Recommendations (live) | 2 generated (R-IDLE: quantity null; R-RESCHEDULE: projected INR −1481, kWh 0). All PENDING_REVIEW, NOT_VERIFIED. No banned phrases. Accept → ACCEPTED but still NOT_VERIFIED; second decision → 409 |

Earlier drafts of the optimizer reported a −10 % projected energy reduction.
That figure was an artifact: the current schedule was compared at its
observed heat durations against idealised planned durations. It was
corrected before this commit, so the optimizer now moves heats in time but
never changes a heat's intrinsic durations, and reheat is decided by the same
rule on both sides. Energy can only fall by avoiding reheat, not by
shortening heats. Tariff-driven cost shifts are the main projected lever.
What the automated suite checks (no live numbers invented here):

- Optimiser acceptance (`tests/integration/test_phase4a.py`): feasible +
  independently validated schedules; tariff-shift day cheaper at equal
  production; INFEASIBLE explanations name the group; peak cap hard;
  reproducibility (small OPTIMAL case + full-horizon x3 byte-identical);
  BASELINE_UNAVAILABLE / no-tariff paths invent no price; per-state energy
  breakdown sums to the total.
- Recommendations (`tests/unit/test_recommendations.py`,
  `tests/api/test_recommendations_api.py`): complete fields per rule;
  inspection/process rows null quantity; banned-phrase scan over all text;
  idempotent generation; conflict flagged with both reasons kept;
  acknowledge 404/409; accepted stays NOT_VERIFIED with an audit row;
  generation with health unavailable or an INFEASIBLE optimiser (remaining
  sources + surfaced explanation).

ASSUMPTIONS entries: A21 (optimiser simplifications), A22 (illustrative
tariff), A23 (deterministic budget + wall-clock safety net), A24
(recommendation rules, wording, human-in-the-loop), A25 (energy breakdown
semantics).

## Phase 5 intervention verification (SIMULATED data)

Verified 2026-09-27. `pytest`: 238 passed, 1 skipped (the optional PBL
ONNX test), about 318 s. Live run through the Docker stack
(`POST /interventions` then `POST /interventions/{id}/verify`): furnace-01
with chronic powered holding for 60 % of every idle gap, 7-day baseline,
3-day measurement window, seed 1. Every number is from SIMULATED
telemetry. Cost uses the ILLUSTRATIVE tariff (ASSUMPTION). CO2 uses the CEA
v21.0 factor 0.710 kgCO2/kWh (EXTERNAL_REFERENCE, applied as
LATEST_AVAILABLE to 2026 energy, to be confirmed against the CEA table).

CO2 figures are **estimates based on provisional emission-factor data, not for external accounting**. They are CO2 only (CEA factors exclude other GHGs) and are never relabelled CO2e. The 291 kg figure must not be presented as an authoritative real-world emissions reduction until the factor has been confirmed against the CEA table.

| Case (simulated cause) | Outcome | Counterfactual kWh | Actual kWh | Saving kWh | ± U (90 %) | Cost / CO2 |
|---|---|---:|---:|---:|---:|---|
| REDUCE_IDLE, effectiveness 1.0, rebound 0.15 | SUCCESS → VERIFIED | 5941.5 | 5531.5 | 410.1 (6.9 %) | 157.2 | INR 3015 (illustrative tariff) / estimated 291.1 kg CO2, provisional factor |
| effectiveness 0.5, compliance 0.6 | NO_EFFECT → NOT_VERIFIED | 5858.6 | 5752.4 | 106.2 | 155.0 | not applicable |
| effectiveness 1.0, rebound 1.0 (reheat outweighs) | WORSE → NOT_VERIFIED | 5853.6 | 6698.6 | −845.0 (energy increased) | 154.9 | not applicable |
| production +53 % after the change | NOT_COMPARABLE | — | — | — | — | not applicable |
| 20 h telemetry outage in measurement | INSUFFICIENT_DATA (69 % complete) | — | — | — | — | not applicable |

- The baseline fit passed G14 (hourly CV(RMSE) about 10.6 %).
- Each case moved APPROVED → APPLIED → MEASURED → outcome, with an audit
  row per move.
- Re-posting the same idempotency key, or re-verifying, returned the
  stored result: no duplicate intervention, saving, cost or CO2.
- The partial fix is a real improvement, but it is smaller than what 3 days
  of data can prove, so it is correctly NOT_VERIFIED. A longer measurement
  window would narrow the uncertainty.
- Automated coverage (`tests/unit/test_verification.py`,
  `tests/unit/test_impact.py`, `tests/integration/test_interventions.py`):
  - SUCCESS and NO_EFFECT on seeds 1 and 2, REPAIR success, WORSE,
    NOT_COMPARABLE, INSUFFICIENT_DATA.
  - Idempotency, and illegal transitions (409).
  - Tariff periods, boundaries, local time, a missing or incomplete tariff,
    the illustrative label.
  - Factor units, provenance, version and effective-date selection, a
    missing factor.
  - Only a VERIFIED saving is converted to cost or CO2.
  - The state-hour counterfactual trap.