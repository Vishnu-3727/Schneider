# UCI Steel Industry — real meter data (external dataset; MEASURED readings + DERIVED calculations)

Raw meter readings are MEASURED from an external dataset, never SIMULATED. Anything computed from them with a method or assumption is DERIVED. MEASURED here means only: annual kWh, kVAh sum, per-interval power factor, and energy by Load_Type. DERIVED means: average power factor, the kVAh-billing gap, the capacitor kVAr, the rupee figure (illustrative tariff), the non-working-hours share (stated working-hours assumption), the baseline, and every anomaly count. Dataset: 

- Citation: UCI Machine Learning Repository, Steel Industry Energy Consumption (id 851), DAEWOO Steel, Gwangyang, South Korea, 2018, 15-minute data.
- Licence: CC BY 4.0.
- Source: https://archive.ics.uci.edu/dataset/851/steel+industry+energy+consumption
- Plant: DAEWOO Steel, Gwangyang, South Korea, year 2018, 15-minute meter readings (35,040 rows = 8,760 hourly intervals).
- This is a Korean steel plant, NOT an Indian SME foundry. It is used only to show the JouleMitra pipeline runs end to end on real meter data.

Solid results first: power factor, the kVAh gap, capacitor sizing, and the light-load-outside-hours share. The baseline and anomaly counts below are DERIVED and are NOT a detection result — see the caveat above the counts table.

## Annual energy and power factor (external dataset; MEASURED + DERIVED)

| Metric | Value |
|---|---|
| Annual kWh (MEASURED) | 959,637 |
| Annual kVAh sum (MEASURED) | 1,087,756 |
| Average PF = kWh/kVAh (DERIVED) | 0.882 |
| kVAh-billing gap (DERIVED) | 128,119 kWh |
| Gap at illustrative Rs 7.5/kWh (DERIVED, illustrative tariff) | Rs 960,893 |

The plant metered about 959,637 kWh (MEASURED) and about 1,087,756 kVAh in total (MEASURED), so the average power factor is about 0.882 (DERIVED) and the kVAh-billing gap is about 128,119 kWh (DERIVED), roughly Rs 960,893 at the illustrative Rs 7.5/kWh tariff (DERIVED, illustrative only, not a real tariff order).

## Capacitor need per load type (DERIVED, external dataset)

| Load_Type (MEASURED dataset field) | N (15-min) (MEASURED) | Typical P kW (DERIVED) | Typical Q kVAr (DERIVED) | Typical PF (DERIVED) | kVAr to 0.95 (DERIVED) |
|---|---|---:|---:|---:|---:|
| Light_Load | 18,072 | 34.5 | 28.0 | 0.776 | 16.7 |
| Medium_Load | 9,696 | 153.8 | 57.6 | 0.936 | 7.1 |
| Maximum_Load | 7,272 | 237.1 | 104.8 | 0.915 | 26.8 |

Typical means mean power over 15-minute intervals of that Load_Type (DERIVED), the same mean-power method as the console Bill screen. Light-load power factor is the worst (about 0.776, needing about 16.7 kVAr), Maximum-load needs about 26.8 kVAr despite a better power factor (about 0.915) because its absolute reactive power is larger, and Medium-load needs about 7.1 kVAr (power factor about 0.936). All kVAr figures are DERIVED.

## Idle / light load in non-working hours (DERIVED, external dataset; stated assumption)

| Metric | Value |
|---|---|
| Light_Load during non-working hours (DERIVED) | 135,387 kWh |
| Share of annual kWh (DERIVED) | 14.1 % |

Non-working is a stated assumption, not a dataset field: WeekStatus == Weekend at any time, plus weekdays outside 09:00-18:00 (NSM < 32400 or NSM >= 64800). About 135,387 kWh (DERIVED), about 14.1 % of the year (DERIVED), is Light_Load energy inside those hours — the real-data counterpart of energy spent with no output. Change the working-hours assumption and this share moves.

## Baseline and anomaly detection (DERIVED, external dataset)

Method: hourly intervals with the project's own services (services.energy.baseline fit_baseline/predict/deviation and services.energy.anomaly l1_flags/l2_flags/build_events) using the defaults from apps/backend/config.py. The dataset has no production counts, so the production-normalised baseline cannot be used; instead the non-production path is used, exactly as the backend does for compressor/pump machines: machine_type "compressor" with non_production_types ["pump", "compressor"] (the NON_PRODUCTION_TYPES default), i.e. state-hours-only features. Load_Type maps to states Light->idle, Medium->holding, Maximum->running (0.25 h per 15-min record). No rated power is published, so the L1_POWER rule is disabled (rated 0 never fires); every other rule uses the config defaults.

- Fit window (MEASURED intervals): first 8 weeks (1344 hourly intervals, ending 2018-02-25T23:00:00).
- Detect window (MEASURED intervals): rest of the year (7416 hourly intervals, 2018-02-26T00:00:00 to 2018-12-31T23:00:00).
- Baseline fit (DERIVED): OK; features ['hours_heating', 'hours_melting', 'hours_holding', 'hours_idle', 'hours_running', 'hours_stopped', 'hours_shutdown', 'hours_auxiliary']; intercept 63.3; CV(RMSE) holdout 67.3 %; NMBE holdout 2.6 %; acceptance NOT_ACCEPTABLE (ASHRAE G14 hourly).

What this proves is only that the pipeline ran end to end on real meter data. The anomaly counts below are NOT a detection result, for three reasons: (1) the baseline failed its own quality check — G14 NOT_ACCEPTABLE with CV(RMSE) 67.3 %; (2) L1_IDLE_WASTE fires nightly only because this dataset has no production counts, so every sustained Light_Load stretch looks like energy with no output; (3) the largest events are all 08:00 shift starts, which the state-hours-only baseline cannot model. Lesson: for plants without production data the baseline needs a time-of-day / shift driver — listed as future work below. Counts are kept for transparency, not as findings.

| Rule (DERIVED) | Events (DERIVED, NOT a finding) |
|---|---:|
| L1_DEVIATION | 240 |
| L1_IDLE_WASTE | 313 |
| L1_POWER_FACTOR | 260 |
| L2_MAD_RESIDUAL | 166 |
| L1_POWER | 0 |
| Total (DERIVED, NOT a finding) | 979 |

Why the baseline fails: energy varies widely inside a Load_Type — for example Light_Load nights are usually about 10-15 kWh per hour but transition hours labelled Light_Load reach hundreds of kWh, and Maximum_Load labels sometimes coincide with single-digit kWh. That is the same limitation the project documents for the compressor: without a production or demand driver the baseline detects level shifts but cannot tell legitimate demand growth from waste.

### 5 largest anomaly events by |deviation| (DERIVED, NOT a finding; external dataset)

| # | Start (DERIVED) | Rule (DERIVED) | Actual kWh (MEASURED) | Expected kWh (DERIVED) | Deviation % (DERIVED) |
|---|---|---|---:|---:|---:|
| 1 | 2018-03-22T08:00:00 | L2_MAD_RESIDUAL | 314.4 | 63.3 | +397.0 % |
| 2 | 2018-08-18T08:00:00 | L2_MAD_RESIDUAL | 293.0 | 63.3 | +363.1 % |
| 3 | 2018-11-01T08:00:00 | L2_MAD_RESIDUAL | 269.2 | 63.3 | +325.6 % |
| 4 | 2018-07-31T08:00:00 | L2_MAD_RESIDUAL | 256.3 | 63.3 | +305.2 % |
| 5 | 2018-04-10T08:00:00 | L2_MAD_RESIDUAL | 247.4 | 63.3 | +291.1 % |

The largest deviations are all Light-labelled 08:00 morning shift starts consuming several hundred kWh against an expected few dozen — the Load_Type label says light while the meter says heavy. These are DERIVED artefacts of a state-hours-only baseline with no time-of-day driver, not confirmed waste. Under-consumption (Maximum label with single-digit kWh) never flags by design: only excess energy is waste.

Future work: add a time-of-day / shift driver to the baseline for plants without production data, so shift starts are expected instead of anomalous.

Per-event rows: `docs/validation/uci_steel_anomalies.csv`.
