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
## Phase 6 industrial connectivity verification (SIMULATED devices)

Verified 2026-09-27. `pytest`: 268 passed, 1 skipped (the optional PBL
ONNX test), about 338 s. The edge tests use a real Mosquitto broker
(docker compose), the real Modbus TCP protocol (pymodbus client against the
independent stdlib server) and the real backend on the test database.

| Requirement | How it was checked | Result |
|---|---|---|
| MQTT → same pipeline as direct HTTP | identical records via both paths | stored rows identical (analytics cannot tell them apart) |
| Malformed payload / unknown machine | broken JSON; topic for `ghost-99` | both dead-lettered with reason (malformed; API 404), others delivered |
| Duplicate message | same reading published twice | one row |
| Stale message | reading 2 h old on the live path | stored SUSPECT (not dropped, not BAD) |
| Retained / replayed message | new gateway subscription receives retained value | counted as retained, not re-sent |
| Broker unavailable | gateway pointed at a closed port | keeps running, `connected=false` |
| Broker restart / reconnect | `docker compose restart mqtt` mid-session | disconnect seen, reconnected, next message delivered |
| Modbus mapping, unit conversion, word order | known IEEE-754 vector 123.456 as ABCD / CDAB / BADC; int16/int32/uint32 | decoded exactly; wrong word order gives a different value |
| Invalid register | 0xFFFF sentinel, PF 1.5, float NaN, register not read | field null plus an issue, never a number |
| Timeout / device unavailable / reconnect | slow server, server stopped, server restarted | TIMEOUT / UNAVAILABLE with backoff, then CONNECTED |
| API unavailable | backend unreachable, gateway restarted mid-outage | nothing discarded; delivered in order when the API returned |

Live demo (processes, Docker stack): simulated Modbus meter
(compressor-01) → gateway ← MQTT device simulator (furnace-01, pump-01).

- The backend was stopped for about 26 s mid-run. The gateway reported
  `API_UNAVAILABLE` and buffered 5 readings, then delivered them when the
  API returned.
- Final: 68 records delivered (48 MQTT telemetry, 2 production, 18 Modbus),
  0 pending, 0 dead-letter, all GOOD, all tagged SIMULATED.

Defects found and fixed during Phase 6:

1. The backend marked a late-arriving older reading BAD (see ASSUMPTIONS
   A31).
2. The gateway status file could be read half-written; it is now written
   atomically.
3. docker-compose still set `NON_PRODUCTION_TYPES: pump`, so the compressor
   showed NO_PRODUCTION inside Docker; it is now `pump,compressor`.

## Final integration (2026-09-28)

Verified 2026-09-28. `pytest`: 268 passed, 1 skipped (the optional PBL
ONNX test), about 333 s, with the test-database Postgres and Mosquitto up
from docker compose. End-to-end demo driver `scripts/demo/run_demo.py`
against the local backend on the dev database (every figure from an API
response, all data SIMULATED):

Default run (`run_demo.py`, REDUCE_IDLE, seed 1):

- `[2] baseline fitted (1 OK fits); anomaly detection -> created 0,
  already_existing 0, stored 0 events (rules: none). 0 is expected: the
  chronic idle waste runs inside the reference window, so the baseline
  treats it as normal.`
- `[3] health scored; insights: 0 (categories: none). Empty follows from
  [2]: no energy events to correlate.`
- `outcome VERIFIED`, `result class SUCCESS`; counterfactual kWh
  (expected without change) 5,941.5; actual kWh (measured after change)
  5,531.5; saving kWh 410.1; uncertainty kWh (90 %) 157.2; verified
  saving kWh 410.1; cost INR 3,282 (ILLUSTRATIVE tariff); CO2 kg 291.1
  (provisional CEA v21.0 factor, CO2 only, not CO2e).
- The energy and CO2 figures repeat exactly on every run. The cost does
  not: the demo window ends at the current hour, so the saving falls into
  different time-of-day tariff periods (a later run printed INR 3,026).
  Quote the cost as "about INR 3,000, illustrative tariff".

Shifted run (`run_demo.py --shifted`, operating conditions shift after
the change):

- Same [2]/[3] lines as the default run (0 events, 0 insights, expected
  for the same reason: the waste is inside the reference window).
- `outcome NOT_COMPARABLE`, `result class NOT_COMPARABLE`; counterfactual,
  actual, saving, uncertainty and verified saving all `-` (no saving
  reported); reasons: `mean production changed +57.3 % (tolerance ±15 %)`.
- Ends with `Unable to verify savings under current conditions.`

The shifted run exercises the same simulator-kwarg pattern as
`tests/integration/test_interventions.py::test_not_comparable_production_reports_no_saving`
(`post_idle_scale=0.1` alongside the REDUCE_IDLE intervention): the
production change makes the post period non-comparable, so verification
reports NOT_COMPARABLE instead of a saving.

## Simulator calibration (2026-09-29)

The demo furnace's rated power was raised from 150 kW to 200 kW (seed
`database/seeds/phase1.sql`, `DEFAULT_MACHINES`, `scripts/demo/run_demo.py`).
At 150 kW the simulated furnace ran at about 530 kWh per tonne, below the
500-560 kWh/t it physically takes to melt and superheat iron and well below
the 625-900 kWh/t reported for Indian foundry clusters (BEE/SAMEEEKSHA). At
200 kW the same heats run at a median 668 kWh/t (best heat 598, worst 715),
inside the typical band. Heat timing, charge and melt rate are unchanged.

Consequence for the demo: every energy figure scales by 4/3 and the
percentages are unchanged. `run_demo.py` now reports VERIFIED, counterfactual
7,922.1 kWh, saving 546.7 kWh +/- 209.6 kWh (90 %), -6.9 %, CO2 388.2 kg
(provisional factor). The Phase 5 table above and the final integration run
were recorded at 150 kW and are kept as history.

Two tests pinned the old number and now derive it from the rated power:
`tests/unit/test_tariff_shift.py` (melting power = 0.95 x rated) and
`tests/integration/test_phase4a.py::test_4` (peak cap just above melting
power). Full suite before those two fixes: 268 passed, 2 failed (exactly
those two), 1 skipped; both pass after the fix.

## Console features (2026-09-29)

What was checked on the new console screens (all SIMULATED data): the demo
inject test (`tests/api/test_demo.py`, 2 passed: 404 without `DEMO_MODE`;
injected air leak detected on compressor-01), a live inject of
`furnace_holding` rewriting the last 4 hours of furnace-01 as `IDLE_WASTE`
(detected as `L1_IDLE_WASTE` on furnace-01, 3 recommendations created), and
the deck screenshots under `docs/deck/screens/`. The Tamil/Hindi morning
brief wording is machine-drafted and pending native-speaker review before
any real use.

## Verification Monte Carlo (2026-09-29)

Is the saving verification skill or luck? `scripts/validation/monte_carlo_verify.py`
simulates 100 plants per scenario whose TRUE saving is known by paired runs
with common random numbers: the SAME plant twice with the same seed, once
with the intervention, once with a NO-OP intervention (same type, start_h
and compliance, but `effectiveness=0.0` and `rebound=0.0`; same
`post_idle_scale` in both runs, so the shift scenario isolates the
intervention effect under shifted conditions). The NO-OP draws the same
random numbers the fix path draws (`_plan_idle_hold` takes one
`rng.random()` per idle gap whenever `idle_hold_frac_fixed` is set), so the
two runs differ only by the physics of the fix. Effectiveness maps to
`idle_hold_frac_fixed = chronic × (1 − effectiveness)`
(`factory_simulator._apply_practice`), so effectiveness 0 leaves holding
unchanged. TRUE saving = energy(NO-OP post) − energy(intervention post).
Setup like `run_demo.py`: furnace-01 (200 kW), chronic idle holding 60 %,
7-day baseline + 3-day measurement, step 300 s, `verify` called WITHOUT the
database. Each pair also carries a `paired` flag (heat-start times identical
in both runs); coverage and false-claim are reported over all pairs and over
paired pairs only, and nothing is dropped. The per-pair assertions held for
all 500 pairs (pre-period energies identical; no_effect post-period energies
identical, TRUE exactly 0). All data SIMULATED. Thresholds were NOT tuned to
these numbers. Command (from the repo root, ~1–2 min; 74 s observed):

`.venv\Scripts\python scripts\validation\monte_carlo_verify.py --n 100 --seed0 1`

Per-run rows: `docs/validation/monte_carlo_verify.csv`. Full tables plus one
plain paragraph per scenario: `docs/validation/monte_carlo_verify.md`.
false-claim = share VERIFIED among runs with TRUE saving ≤ 0; coverage = share
of comparable runs (a saving was reported) where TRUE lies within reported ±
uncertainty (stated confidence 90 %).

| scenario | N | paired | VERIFIED | NOT_VERIFIED | NOT_COMPARABLE | INSUFFICIENT_DATA | false-claim all | false-claim paired | coverage all | coverage paired | mean TRUE kWh | mean reported kWh | mean \|error\| kWh |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| no_effect | 100 | 100 | 1 | 94 | 5 | 0 | 1.0% (1/100) | 1.0% (1/100) | 98.9% | 98.9% | 0.0 | −1.9 | 60.4 |
| partial | 100 | 100 | 70 | 25 | 5 | 0 | n/a (0/0) | n/a (0/0) | 100.0% | 100.0% | 305.8 | 297.1 | 60.6 |
| full | 100 | 0 | 98 | 0 | 2 | 0 | 50.0% (1/2) | n/a (0 paired) | 64.3% | n/a (0 paired) | 779.6 | 721.1 | 197.6 |
| worse | 100 | 0 | 0 | 97 | 3 | 0 | 0.0% (0/100) | n/a (0 paired) | 57.7% | n/a (0 paired) | −1,094.2 | −1,125.3 | 214.6 |
| production_shift | 100 | 100 | 0 | 0 | 100 | 0 | n/a (0/0) | n/a (0/0) | n/a | n/a | 158.3 | n/a | n/a |

Reading the results:

- **Common random numbers hold wherever rebound is 0.** Pre-period equality held for all 500
  pairs and no_effect TRUE is exactly 0.0 in all 100 runs, and the paired
  flag is 100/100 in no_effect, partial and production_shift — so those
  scenarios' coverage and false-claim numbers are valid measurements of
  `verify`, not realisation noise. (The previous harness used
  `intervention=None` for the control, which skipped the per-gap compliance
  draw and let the streams diverge.) full and worse are 0/100 paired (see
  Diagnosis below), so their band-coverage numbers are not.
- **Coverage is at/above 90 % where the paired comparison is exact.**
  no_effect 98.9 % with mean |error| 60.4 kWh, partial 100.0 % with mean
  |error| 60.6 kWh — the 90 % uncertainty band means what it says there,
  and the paired-only cuts match the all-pairs cuts exactly (100/100 paired
  in every rebound-free scenario). TRUE ranges are now tight and same-signed
  per scenario (partial +179 to +450, production_shift +68 to +246 kWh).
- **full/worse are 0/100 paired, so their coverage numbers are not
  measurements of `verify`.** Detection direction still works (full VERIFIED
  98/100, worse 0 false claims with 97 labelled WORSE), but coverage 64.3 % /
  57.7 %, mean |error| ~200 kWh, the full TRUE range (−77 to +1,631 kWh) and
  the "50 %" false-claim (1 of 2) are realisation noise from unpaired runs,
  and the paired-only cut is n/a with no valid pairs. The method and
  thresholds are unchanged — no tuning.
- **Diagnosis.** Rebound moves the idle-to-heating boundary earlier inside
  each gap-plus-heat pair: `_plan_idle_hold` banks the reheat
  (`apps/simulator/machine_models.py:262`), the idle gap is shortened by it
  (`machine_models.py:243`) and the next heating is lengthened by the same
  amount (`machine_models.py:205`), so the pair keeps its total length but
  the internal boundary shifts earlier in the intervention run only; because
  schedule segments are built lazily (`machine_models.py:265-267`) and share
  one rng stream with the per-step measurement noise, the first shifted
  boundary that crosses a 5-minute sampling step (seed 1, full: the second
  post-intervention gap, heat 70 starting one step early at step 2053)
  consumes a schedule draw in only one run and permanently offsets every
  later draw, so later heats, states and energies are different random
  realisations; with rebound 0 the pending reheat stays 0, no boundary ever
  moves, and all 300 rebound-free pairs stay bit-paired.
- **False claims are rare and counted on valid denominators.** no_effect
  1/100 (1.0 %), worse 0/100 (never VERIFIED when energy went up).
  The "50 %" on full is 1/2 on unpaired runs whose TRUE values are
  themselves realisation noise, so neither the rate nor its denominator is
  a measurement of `verify`. partial and production_shift have no TRUE ≤ 0
  runs, so false-claim is n/a.
- **The shift scenario is still refused 100/100** as NOT_COMPARABLE with
  no saving reported. Its TRUE is now +158.3 kWh (was −1,789 kWh): the
  production shift applies to both runs, so TRUE isolates the intervention
  effect under shifted conditions instead of conflating it with the shift.
- **Small effects are honestly borderline.** partial (effectiveness 0.5,
  compliance 0.6) verifies in 70/100 weeks and correctly returns NO_EFFECT in
  25 — whether it proves depends on how much idle waste that week's seed
  happened to contain, exactly as the Phase 5 single-seed table suggested.
- **The comparability gate fires on 2–5 % of ordinary weeks** (natural
  production variation beyond ±15 %), refusing instead of reporting. That is
  the gate doing its job, at the cost of occasionally discarding a fine week.

## Real meter data: UCI Steel Industry (2026-09-29)

Raw meter readings are MEASURED from an external dataset, never
SIMULATED. Anything computed from them with a method or assumption is
DERIVED. MEASURED here means only: annual kWh, kVAh sum, per-interval
power factor, and energy by Load_Type. DERIVED means: average power
factor, the kVAh-billing gap, the capacitor kVAr, the rupee figure
(illustrative tariff), the non-working-hours share (stated
working-hours assumption), the baseline, and every anomaly count.
Dataset: UCI ML Repository id 851, Steel Industry Energy
Consumption — DAEWOO Steel, Gwangyang, South Korea, 2018, 15-minute data,
licence CC BY 4.0
(https://archive.ics.uci.edu/dataset/851/steel+industry+energy+consumption).
This is a Korean steel plant, NOT an Indian SME foundry; it is used only to
show the JouleMitra pipeline runs end to end on real meter data.

Command: `.venv\Scripts\python scripts\validation\uci_steel.py` (downloads the
zip with urllib into `data/external/uci_steel/`, git-ignored). Full tables
plus one plain paragraph per finding: `docs/validation/uci_steel.md`;
per-event rows: `docs/validation/uci_steel_anomalies.csv`.

Solid results first (power factor / kVAh gap / capacitor sizing /
light-load-outside-hours share):

- Annual 959,637 kWh (MEASURED), 1,087,756 kVAh sum (MEASURED); average PF
  0.882 (DERIVED); kVAh-billing gap 128,119 kWh (DERIVED), about Rs 960,893
  at the illustrative Rs 7.5/kWh tariff (DERIVED, illustrative only, not a
  real tariff order).
- Capacitor to 0.95 (DERIVED, mean-power method as the console Bill screen):
  Light_Load PF 0.776 → 16.7 kVAr; Medium_Load 0.936 → 7.1 kVAr;
  Maximum_Load 0.915 → 26.8 kVAr.
- Light_Load during non-working hours (DERIVED, stated assumption: Weekend
  any time plus weekdays outside 09:00–18:00): 135,387 kWh, 14.1 % of the
  year. Change the working-hours assumption and this share moves.

Baseline and anomaly counts (DERIVED, NOT a detection result):

- Baseline (DERIVED; project services, non-production path: machine_type
  "compressor" with non_production_types ["pump", "compressor"],
  state-hours-only features; Load_Type Light->idle, Medium->holding,
  Maximum->running; L1_POWER disabled, all other rules at config defaults;
  fit first 8 weeks, detect rest): fit OK but G14 NOT_ACCEPTABLE (CV(RMSE)
  holdout 67.3 %, NMBE 2.6 %) — energy varies widely inside a Load_Type,
  the documented compressor limitation without a production/demand driver.
- What this proves is only that the pipeline ran end to end on real meter
  data. The anomaly counts below are NOT a detection result, for three
  reasons: (1) the baseline failed its own quality check — G14
  NOT_ACCEPTABLE with CV(RMSE) 67.3 %; (2) L1_IDLE_WASTE fires nightly
  only because this dataset has no production counts, so every sustained
  Light_Load stretch looks like energy with no output; (3) the largest
  events are all 08:00 shift starts, which the state-hours-only baseline
  cannot model. Lesson: for plants without production data the baseline
  needs a time-of-day / shift driver (future work). Counts are kept for
  transparency, not as findings.
- Anomaly events (DERIVED, NOT a finding; 7,416 hourly intervals): 979
  total — L1_DEVIATION 240, L1_IDLE_WASTE 313, L1_POWER_FACTOR 260,
  L2_MAD_RESIDUAL 166, L1_POWER 0. Five largest by |deviation| are
  Light-labelled 08:00 morning shift starts at +291 to +397 % (e.g.
  2018-03-22 08:00, actual 314.4 kWh vs expected 63.3 kWh) — DERIVED
  artefacts of a baseline with no time-of-day driver, not confirmed waste.
