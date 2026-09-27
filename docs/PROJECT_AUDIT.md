# JouleMitra — Project Audit

Planning doc only. No application code. Authoritative spec: `docs/spec/MASTER_SPEC.md`
(spec wins over `docs/spec/CHALLENGE_README.md` on any conflict).
Audit date: 2026-09-27. All unify-rul paths are relative to
`C:\Users\vishn\Projects\unify-rul` (READ-ONLY — nothing there was modified).
Joulemitra repo: `C:\Users\vishn\Projects\joulemitra` (contains only `docs/spec/`
plus `.git/` with no commits yet).

Evidence rule (spec §2) applies to this doc: every quantitative value below that
came from a unify-rul file cites the file. Anything else is marked ASSUMPTION.

---

## 1. Existing components

### 1.1 JouleMitra repo (new, empty)

`C:\Users\vishn\Projects\joulemitra` contains only:

- `docs/spec/MASTER_SPEC.md` — authoritative spec (168 lines, read fully).
- `docs/spec/CHALLENGE_README.md` — original challenge brief / background.
- `.git/` — initialised, no commits yet (`git status` shows only `?? docs/`).

There is no code, no `pyproject.toml`, no `requirements.txt`, no
`docker-compose.yml`, no database schema, no dashboard. Everything in §5
(Missing components) has to be built.

### 1.2 unify-rul repo contents (PBL project, read-only audit)

Top-level layout (directory listing, 2026-09-27):

| Path | What it is |
|---|---|
| `unify/` | Training + model Python package (`common/`, `datasets/`, `models/`, `train/`, `deploy/`) |
| `edge/` | Raspberry Pi runtime: FastAPI service, ONNX inference, SQLite, static dashboard, benchmark, fake sensor node |
| `firmware/esp32/` | ESP32 sensor-node firmware (PlatformIO, Arduino) |
| `config/` | Training config, dataset paths, sensor vocabulary, live channel maps |
| `deploy/` | systemd unit + desktop file + Pi setup notes |
| `data/` | `raw/` + `interim/` (datasets; blobs not opened — see §9) |
| `results/` | `metrics.json`, `baseline_rf.json`, `best.pt` (binary, not opened), per-run subdirs |
| `tests/` | 6 test files (see §6) |
| `docs/` | 14 mentor-curriculum notes (`00-index.md` … `13-defense-and-industry.md`) |
| `site/` | Static browser demo (`index.html`, `results.html`, `vendor/`, `figures/`, `assets/`) |
| `scripts/` | `build_demo_site.py`, `eval_onnx.py`, `make_docx_report.py`, `make_report_figures.py` |
| `reports/` | `full-test-2026-08-28.md`, `ccp-report-unify-rul.md`, `UNIFY-RUL_Project_Report.docx` (not opened), `figures/`, `assets/`, `pi/` (bench JSON, `unify.db` — not opened) |
| `requirements-train.txt` | Laptop/training dependencies |
| `Makefile` | `install / data / smoke / train / baseline / export / verify / bench / test / serve / node / deploy / clean` targets |
| `edge/requirements-pi.txt` | Pi-only dependencies |
| `.gitignore` | Excludes `data/raw/`, `data/interim/`, `data/processed/`, `edge/*.db*`, `*.pt`, `*.onnx`, `.venv/` |
| No `LICENSE*`, no `pyproject.toml`, no `.python-version` | Confirmed by filename search at repo root |

Skipped without opening (large / binary, listed only): `.venv/`, `data/raw/*`,
`data/interim/*` (file counts noted in §6), `results/best.pt`,
`edge/artifacts/*.onnx`, `reports/pi/unify.db`,
`reports/UNIFY-RUL_Project_Report.docx`, `site/vendor/` (~12 MB per
`site/README.md`), `__pycache__/`.

---

## 2. Reusable components (PBL → JouleMitra)

Each entry: path, purpose, input schema, output schema, dependencies, model
format, training data, limitations, license, `MachineHealthModel`
(predict/score/explain) compatibility.

### 2.1 RUL model — `unify/models/unify_rul.py` (+ `encoder.py`, `attention.py`, `losses.py`)

- **Purpose:** Universal Remaining-Useful-Life predictor. Shared 1-D CNN encoder
  per sensor → sensor + domain embeddings → masked cross-attention pool → MLP
  head. Any sensor count `S` with one weight set (~44 k parameters; `params:
  44417` in `results/metrics.json`; README states 44,417).
- **Input schema:** `x (B, S, L)` float32 z-scored windows (`L=30` per
  `config/default.yaml`), `mask (B, S)` bool, `sensor_ids (B, S)` int64 into
  `config/sensor_vocab.json`, `domain_id (B,)` int64. Source:
  `unify/models/unify_rul.py` `forward()` docstring.
- **Output schema:** normalised RUL `(B, n_outputs)` in [0,1]-ish (dimensionless;
  `n_outputs=1`, or 3 for quantile heads `[q10, q50, q90]`) plus attention
  `(B, heads, M, S)`. Physical units recovered by multiplying by `life_scale`
  (see `unify/common/schema.py` `life_scale()`).
- **Dependencies:** torch (train/export only — never on the Pi).
- **Model format:** PyTorch checkpoint `results/best.pt` (binary, not opened) +
  exported ONNX `edge/artifacts/unify_rul.onnx` (opset 17, dynamic batch +
  sensor axes) + optional `unify_rul_int8.onnx` (int8 dynamic quant). Export via
  `unify/deploy/export_onnx.py` (forced TorchScript tracing, `onnx.checker`,
  numerical parity check in `unify/deploy/verify_onnx.py`).
- **Training data:** NASA C-MAPSS turbofan run-to-failure (FD001–FD004),
  RUL cap 125 cycles absolute (`config/datasets.yaml`; Heimes 2008 standard).
  FEMTO/XJTU-SY parsers exist (`unify/datasets/femto.py`, `xjtu.py`) but those
  datasets sit behind browser downloads and were not present for the reported
  run — `results/metrics.json` `config.data.datasets` is `["cmapss"]` only.
  Synthetic generators (`unify/datasets/synthetic.py`, 8-ch + 3-ch) exist for
  smoke tests and must never appear in results (stated in the module docstring).
- **Measured performance (cited, C-MAPSS official test split, one prediction per
  engine at final cycle):** `results/metrics.json` → RMSE **14.5109** cycles,
  MAE **9.9936** cycles, NASA score **3416.715**, n=690. README rounds to
  14.51 / 9.99 / 3,417 and notes 17 of 707 test engines are shorter than the
  30-cycle window and cannot be scored. RandomForest baseline
  (`results/baseline_rf.json`) → RMSE **14.4051**, MAE **10.4966** — i.e. the
  baseline ties/wins on RMSE; the deep model wins on MAE. The README states
  this honestly; JouleMitra docs must repeat it, not the RMSE alone.
- **Limitations:** (a) turbofan sensor channels — weights are meaningless on
  foundry vibration/current data without retraining; (b) no uncertainty output
  unless the `pinball` loss head is enabled (`config/default.yaml`
  `loss.kind`); (c) attention weights are feature-usage indication, NOT causal
  explanation (`edge/inference.py` says so explicitly); (d) per-condition
  normalisation required for C-MAPSS FD002/FD004 — wrong stats give plausible
  but wrong RUL (the RUL-65.1-at-failure incident in
  `reports/full-test-2026-08-28.md` §7.1); (e) validation↔test correlation is
  weak (142 val units), so checkpoint choice is near-arbitrary — see README
  sweep table.
- **License:** none found — no `LICENSE*` at repo root. Treat as
  all-rights-reserved until the owner adds one; do not assume open source.
- **Adapter compatibility:** HIGH, with retraining. The `(B,S,L)` + mask +
  `sensor_ids` contract already supports variable foundry sensor sets (e.g.
  vibration RMS/kurtosis, temperature, motor current) by extending
  `sensor_vocab.json` and retraining. `edge/inference.py::Predictor.predict()`
  already has the exact shape JouleMitra's `MachineHealthModel.predict()`
  needs: `window (L, S) → {rul, health, rul_lo, rul_hi, latency_ms,
  attention}`. `score()` maps to EWMA-smoothed health (`Smoother` class);
  `explain()` maps to mean-over-heads attention + sensor-ID names, with the
  mandatory caveat that it is usage, not causation.

### 2.2 Preprocessing — `unify/common/` (`schema.py`, `normalize.py`, `windowing.py`, `features.py`)

- **Purpose:** `Unit` dataclass (one machine, healthy→failure; `(T,S)` signals
  + `sensor_ids` + native-unit RUL + `life_total` + `unit_of_time`); train-only
  z-score keyed by (dataset, sensor-ID) with optional per-operating-condition
  tables; sliding windows (`L=30`, label = RUL at window right edge, never
  spanning two units); time-domain vibration features
  (rms/kurt/skew/crest/p2p; ESP32 computes the rms/kurt/crest subset).
- **Input → output:** raw waveforms / CSV rows → `Unit` → normalised `(N,S,L)`
  windows + `[0,1]` capped RUL labels (absolute cap for C-MAPSS, fractional
  cap for bearings — `Unit.capped_rul()`).
- **Dependencies:** numpy only (deliberately — shared verbatim with the Pi; see
  `edge/inference.py` sys.path comment and `Makefile deploy` copying
  `unify/common` to the Pi).
- **Model format / training data:** n/a (code + `data/interim/*.npz` cache).
- **Limitations:** vibration-feature code assumes 25.6 kHz bearing snapshots for
  FEMTO/XJTU; foundry signals (kW, current, temperature) need new feature
  functions, not reuse of kurtosis-style features. DC-removal assumption is
  vibration-specific.
- **License:** none found (see §2.1).
- **Adapter compatibility:** HIGH for the *pattern* (ID-keyed stats shipped
  with the model; train-only fitting; `norm_stats.json` refusal to start when
  stale). JouleMitra should copy this module's discipline into its own energy
  preprocessing, not its vibration constants.

### 2.3 Dataset harness — `unify/datasets/` (`build.py`, `joint.py`, `cmapss.py`, `femto.py`, `xjtu.py`, `synthetic.py`)

- **Purpose:** one-parser-per-dataset → common `Unit`; unit-level (never
  window-level) train/val split; official-test holdout keyed on `unit_id`;
  mask-padded collate for mixed-sensor-count batches; one-shot parse → cache.
- **Input → output:** `data/raw/<ds>/` → `data/interim/<ds>/*.npz` (1,416 files
  counted in `data/interim/cmapss`; `synthetic` + `synthetic_small` cached too).
- **Dependencies:** pandas, numpy, pyyaml.
- **Limitations:** FEMTO/XJTU require manual browser download
  (`config/datasets.yaml` documents layouts); C-MAPSS is simulated turbofan
  data, NOT measured factory data — spec §6 forbids presenting it as foundry
  performance.
- **Adapter compatibility:** MEDIUM. The `Unit` + registry pattern is a good
  template for JouleMitra's multi-machine-type ingestion (furnace, compressor,
  pump, motor), but JouleMitra deals with live energy/production streams, not
  run-to-failure files, so only the discipline (unit-level splits, no leakage,
  cached parses) transfers.

### 2.4 Edge service — `edge/app.py`, `edge/inference.py`, `edge/fake_node.py`, `edge/bench.py`

- **Purpose:** FastAPI ingest + ONNX Runtime predictions + EWMA alarm +
  SQLite logging + static dashboard + latency benchmark; `fake_node.py` is the
  ESP32 stand-in (synthetic packets, `--degrade` ramp, `--replay` of real
  cached units).
- **Input schema:** `POST /ingest` JSON `{node: str≤32, seq: int, ts_ms: int,
  feat: [float × S], clip: int, jitter_us: int}` (Pydantic `Packet` in
  `edge/app.py`). Endpoints: `POST /ingest`; `GET /health /metrics
  /api/recent /` (no MQTT, no Modbus, no auth — see §5).
- **Output schema:** `{status, rul, health, alarm}` per packet; SQLite
  `predictions(ts, seq, rul, rul_lo, rul_hi, health, alarm, latency_ms, feat,
  attn, model)`; `/health` reports model SHA, staleness, gaps, rejects.
- **Dependencies (pinned, `edge/requirements-pi.txt`):** fastapi==0.115.6,
  uvicorn[standard]==0.34.0, pydantic==2.10.4, numpy==2.2.1,
  onnxruntime==1.20.1. Nothing importing torch (enforced by design).
- **Model format:** consumes the 3 deploy artifacts (`unify_rul.onnx`,
  `norm_stats.json`, `sensor_vocab.json`) + `model.sha256` + `manifest.json`,
  selected by `config/live_map*.json`.
- **Measured performance (cited):** `reports/pi/bench_pi.json` (Pi 5,
  onnxruntime 1.20.1, 15 sensors, window 30) → p50 **0.654 ms** @ 4 threads
  (0.886 / 0.723 / 0.662 ms @ 1/2/3 threads). NOTE: README headline claims
  0.423/0.441/0.446 ms p50/p95/p99 — different run from the bench JSON on
  file; JouleMitra must cite the JSON file's numbers, not the README's, until
  re-measured. End-to-end service p50 1.19 ms per
  `reports/full-test-2026-08-28.md` §1.
- **Limitations:** HTTP POST, not MQTT; single shared deque (one machine per
  process); stub mode returns `rul: 42.0` when artifacts are missing (must
  never reach JouleMitra); no offline store-and-forward beyond SQLite log;
  no multi-tenancy/sites.
- **Adapter compatibility:** HIGH. `edge/inference.py::Predictor` +
  `Smoother` is the reference implementation for JouleMitra's
  `MachineHealthModel` adapter and the simulated edge gateway (Phase 6).
  `fake_node.py --replay` is the template for JouleMitra's device simulator
  feeding the gateway. Requires adding MQTT publish, site/machine routing,
  and multi-window state.

### 2.5 Firmware — `firmware/esp32/src/main.cpp` (263 lines), `config.h`, `platformio.ini`

- **Purpose:** ESP32 DevKit V1 sensor node: 1 kHz hardware-timer ISR → I2C
  burst read of MPU-6050 → ring buffer → per-1,000-sample feature window
  (rms/kurt/crest × 3 axes, order pinned in a comment that must match the
  server) → queue → core-0 network task HTTP POSTs JSON to the Pi; on-board
  LED shows alarm/offline.
- **Input → output:** 3-axis acceleration @ 1 kHz → 1 feature packet/s
  `{node, seq, ts_ms, feat[9], clip, jitter_us}`.
- **Dependencies:** Arduino framework, espressif32@6.5.0 (pinned — timer API
  breaks on 7.x), MPU-6050 @ SDA→GPIO21/SCL→GPIO22, L298N motor driver
  (ENA→25, IN1→26, IN2→27, separate 12 V supply, common ground).
- **Limitations:** MPU-6050 caps at 1 kHz vs 25.6 kHz bearing datasets — cannot
  see kHz-region bearing resonances (README §"What this is not"); Wi-Fi creds
  + Pi IP hard-coded in `config.h` (`CHANGE_ME` placeholders); HTTP only;
  no TLS, no MQTT, no OTA.
- **Adapter compatibility:** MEDIUM (Phase 7 reference). Timing architecture
  (sampling core vs network core) and feature-order contract transfer
  directly; JouleMitra needs energy-meter firmware (voltage/current/PF via
  Modbus or CT front-end), which this firmware does not implement.

### 2.6 Training entry points — `unify/train/train.py`, `evaluate.py`, `baseline_rf.py`

- **Purpose:** joint mixed-dataset training (cosine schedule, warmup, early
  stopping, `--overfit` capacity check); per-dataset RMSE/MAE/NASA evaluation;
  RandomForest-on-summaries baseline that pads to widest feature layout.
- **Input → output:** `data/interim/*.npz` + `config/default.yaml` →
  `results/best.pt` + `results/metrics.json`.
- **Dependencies:** torch>=2.4 (CPU wheel noted; CUDA build documented in
  comments), scikit-learn>=1.5, pyyaml, matplotlib.
- **Limitations:** RF baseline cannot do variable-S (pads + retrains per
  layout) — the documented reason the deep model earns its keep.
- **Adapter compatibility:** MEDIUM. JouleMitra's baseline/SEC/anomaly
  training (Phase 2) should copy the harness discipline (overfit check first,
  always-a-baseline, config logged into checkpoint + metrics).

### 2.7 Deployment + demo artefacts — `deploy/`, `site/`, `scripts/`, `edge/static/`, `edge/bench.py`

- `deploy/unify-rul.service` + `.desktop` + `deploy/README.md`: user-level
  systemd unit running the Pi service on :8000 with `Conflicts=` against a
  sibling demo; `Makefile deploy` target copies artifacts + `unify/common` +
  `config/` over SSH. Directly reusable as the template for JouleMitra's
  `docker-compose` + Pi gateway deployment (Phase 6/7).
- `site/index.html` + `results.html` (+ `scripts/build_demo_site.py`): static
  page running the real exported ONNX in-browser (WASM) over held-out
  C-MAPSS engines, with per-condition normalisation verified to 0.05 cycles
  (worst case 0.0018). Reusable pattern for JouleMitra's "prove the demo is
  live, not replayed" story — but JouleMitra's dashboard is Streamlit+Plotly
  per spec §3.7, so this is a pattern reference, not code to copy.
- `edge/static/index.html`: the live Pi dashboard served at `GET /`.
  JouleMitra replaces it with the Streamlit app; keep the `/api/recent`-style
  JSON API it consumes.
- `scripts/eval_onnx.py`, `make_report_figures.py`, `make_docx_report.py`:
  post-quantisation accuracy + figure generation. Reusable approach for
  JouleMitra's validation reporting (spec: docs VALIDATION).

---

## 3. Existing Python environments and dependency files

| File | Environment | Key packages (as pinned/ranged in file) |
|---|---|---|
| `requirements-train.txt` | Laptop / training (`.venv/`, not opened) | numpy>=2.0, pandas>=2.2, scipy>=1.14, scikit-learn>=1.5, pyyaml>=6.0, matplotlib>=3.9, torch>=2.4 (CPU; CUDA build documented in comments), onnx>=1.17, onnxscript>=0.1, onnxruntime>=1.19, pytest>=8.0, httpx>=0.27 |
| `edge/requirements-pi.txt` | Raspberry Pi 5, 64-bit Pi OS (aarch64 wheels) | fastapi==0.115.6, uvicorn[standard]==0.34.0, pydantic==2.10.4, numpy==2.2.1, onnxruntime==1.20.1 |
| `firmware/esp32/platformio.ini` | ESP32 (not Python) | espressif32@6.5.0, arduino, esp32dev board |

- **Python version:** NOT pinned anywhere in unify-rul (no `.python-version`,
  no `pyproject.toml`). `requirements-train.txt` implies 3.x with numpy 2.x
  support. Measured hosts cited in `reports/full-test-2026-08-28.md`:
  training on Windows 11 / torch 2.13.0+cu130; edge on Pi 5 / onnxruntime
  1.20.1. JouleMitra must pin its own version (decision needed — see
  IMPLEMENTATION_PLAN.md; spec background suggests Python 3.11).
- **JouleMitra needs beyond these:** fastapi/uvicorn/pydantic (reuse Pi pins
  as floor), sqlalchemy/psycopg, `paho-mqtt`, `pymodbus`, `streamlit`,
  `plotly`, `or-tools`, `xgboost` (optional later), `pytest` + `httpx`,
  `pydantic-settings`, `tzdata`. Full list in IMPLEMENTATION_PLAN.md.

---

## 4. Hardware-related code (ESP32 / RPi / firmware)

- `firmware/esp32/src/main.cpp` + `config.h` + `platformio.ini` — ESP32 + MPU-6050
  accelerometer node + L298N-driven 12 V DC motor rig wiring (SDA→21, SCL→22,
  ENA→25, IN1→26, IN2→27; 2.4 GHz Wi-Fi only). Flash: `pio run -t upload -t
  monitor` (README §"Flash the sensor node").
- `edge/` runs on the Raspberry Pi 5 (measured target per
  `reports/pi/bench_pi.json`: Linux aarch64, onnxruntime 1.20.1,
  CPUExecutionProvider only; thermals 43.9→48.8 °C, `throttled 0x0`).
- `docs/08-hardware.md`, `docs/09-communication.md`, `docs/11-realtime-pipeline.md`
  document the rig, I2C/Wi-Fi/HTTP path, and the honesty layer (rig = pipeline
  demonstrator, not accuracy source).
- **Nothing energy-meter related exists** — no CT/voltage/PF front-end, no
  Modbus code, no energy-meter firmware. All of that is Phase 6/7 new build
  (spec §9: `MockModbusDevice` now, `RealModbusDevice` later).

---

## 5. Existing dashboards / sites

| Path | What | Reuse for JouleMitra |
|---|---|---|
| `edge/static/index.html` | Live Pi dashboard (served by `GET /`, fed by `/api/recent`, `/metrics`, `/health`) | Pattern only — JouleMitra dashboard is Streamlit+Plotly (spec §3.7) |
| `site/index.html` | Static demo running real ONNX in-browser over held-out C-MAPSS engines | Pattern only (prove-live-not-replayed); different stack |
| `site/results.html` | Static results/figures/limitations page | Pattern for JouleMitra VALIDATION + DEMO docs |
| `site/vendor/` | onnxruntime-web 1.20.1 + Tailwind (~12 MB, offline-capable) | Not reused |

---

## 6. What is verified working (cited — nothing else claimed)

| Claim | Evidence file |
|---|---|
| 61 tests passed, 0 failed; overfit capacity check max abs err 0.00030; official C-MAPSS test RMSE 14.89 / MAE 10.19 / NASA 3841→3831, n=690; ONNX fidelity 0.000 cycles; INT8 cost +0.044 RMSE (+0.29%) for 2.4× smaller; Pi 5 inference p50 0.654 / p95 0.675 ms @ 4 threads; service p50 1.19 ms; replay RUL 0.0 at end of life, alarm 32 cycles early, 0 false alarms | `reports/full-test-2026-08-28.md` §1 |
| Thread sweep 1–4 threads p50 0.886/0.723/0.662/0.654 ms, 15 sensors, window 30, no throttling | `reports/pi/bench_pi.json` |
| C-MAPSS official-test metrics RMSE 14.5109 / MAE 9.9936 / NASA 3416.715 (checkpoint in `results/`); RF baseline RMSE 14.4051 / MAE 10.4966 | `results/metrics.json`, `results/baseline_rf.json` |
| Export contract (opset 17, window 30, scales `{cmapss: 125.0}`, sha `a80c367e…`, 194,954 bytes ≈ 190 KB) | `edge/artifacts/manifest.json` (+ `model.sha256`) |
| `data/interim/cmapss` holds 1,416 cached unit files (matches report §2: 1,416 units, 265,256 timesteps, 15 sensors); `data/raw/cmapss` present (44 MB per report §2 — size not re-verified, blobs unopened) | Directory listing + `reports/full-test-2026-08-28.md` §2 |
| Test files present: `test_shapes.py` (73 lines), `test_preprocessing.py` (169), `test_onnx_parity.py` (85 + continuation), `test_live_normalisation.py` (93), `test_ingest.py` (63), `test_datasets.py` (250) | `tests/` listing |

NOT verified (no evidence in repo or contradicts): FEMTO/XJTU accuracy (datasets
not downloaded — README says so); any foundry/furnace number (no such data);
README headline latency 0.423 ms (contradicted by the newer `bench_pi.json`
0.654 ms — cite the JSON); live-rig RUL accuracy (explicitly disclaimed in
README + `docs/00-index.md` "two truths"); INT8 numbers in README (2.6×/79 KB
claims predate the measured 2.4× in the full-test report — cite the report).

---

## 7. Missing components (everything JouleMitra needs that unify-rul has no trace of)

Per spec §§3–11, none of these exist in either repo: factory/energy simulator
(V/I/kW/kVAr/PF/kWh/demand + production + process states + tariff/ToU +
scenarios NORMAL/IDLE_WASTE/EQUIPMENT_DEGRADATION/HIGH_LOAD/PRODUCTION_SURGE/
TARIFF_SHIFT/COMBINED_ANOMALY); FastAPI backend with sites/machines/telemetry/
production/anomalies/recommendations/optimisation/verification APIs (spec §8);
PostgreSQL schema (16 entities — see DATA_MODEL.md) / TimescaleDB readiness;
SEC + energy-baseline engine; L1/L2 energy anomaly detection; process-efficiency
analytics; OR-Tools tariff-aware scheduler; recommendation engine with the
spec §6 field set; intervention + savings-verification loop; cost engine
(tariff tables) + carbon engine (sourced emission factors); Streamlit+Plotly
dashboard (all §10 sections); MQTT topics + Mosquitto + simulated RPi gateway
with SQLite buffer/resync; Modbus abstraction (`MockModbusDevice` /
`RealModbusDevice`); multi-site/multi-machine data model, auth foundation,
role selector; units/timezone handling (Asia/Kolkata); evidence-source tagging
(MEASURED/SIMULATED/DERIVED/EXTERNAL_REFERENCE/PROJECTED/ASSUMPTION);
`/health/components`; docker-compose; `.env.example`; demo script
(`scripts/demo/run_demo.py`); all JouleMitra docs
(ARCHITECTURE/DATA_MODEL/API/ML_MODELS/SIMULATION/DEPLOYMENT/DEMO/ASSUMPTIONS/
VALIDATION/decisions/ADR-*).

---

## 8. Technical debt (inherited risks if reused carelessly)

1. **No license file** — reuse of any unify-rul code into JouleMitra is legally
   unclear until the owner adds one. Decision needed before Phase 3 copies
   patterns (see §10).
2. **No pinned Python / no pyproject** — `requirements-train.txt` uses `>=`
   ranges; reproducibility rests on `results/metrics.json`-style config
   logging, which JouleMitra must adopt from day one (spec §11: config via
   `.env`, no hard-coded thresholds).
3. **Stub fallback (`rul: 42.0`)** in `edge/app.py` — a silent-fake path that
   spec §11 ("no fake implementations") forbids; JouleMitra's gateway must
   fail loudly (`NotImplementedError`/unhealthy status), never serve stub
   numbers.
4. **Single-machine global deque** in `edge/app.py` — must become per-machine
   window state for multi-machine JouleMitra.
5. **README-vs-artifact number drift** (§6 latency example) — JouleMitra docs
   must generate figures from artifacts (`scripts/make_report_figures.py`
   pattern), never hand-type.
6. **Per-condition normalisation trap** (`reports/full-test-2026-08-28.md`
   §7.1) — any JouleMitra normalisation keyed on operating regime needs the
   same refuse-to-start guard as `edge/inference.py`.
7. **Wi-Fi creds compiled into firmware** (`config.h` `CHANGE_ME`) — JouleMitra
   Phase 7 must use provisioned credentials, never committed secrets
   (spec §11).
8. **Synthetic-data floor** (`unify/datasets/synthetic.py` docstring) — a
   reminder that JouleMitra's simulator scenarios need the same honesty: a
   documented irreducibility floor, not tuned-to-look-good data.

---

## 9. Assumptions (ASSUMPTION / WHY / IMPACT)

1. **ASSUMPTION:** unify-rul `main` branch as found on 2026-09-27 is the
   version of record. **WHY:** no version tag or release note found in repo.
   **IMPACT:** if the owner later updates unify-rul, adapter work (Phase 3)
   must be re-checked against the new tree.
2. **ASSUMPTION:** file line-counts and listings above reflect the working
   tree, not a clean checkout. **WHY:** `.venv/`, `__pycache__/`,
   `.pytest_cache/` present; git log not inspected (read-only audit avoided
   history Writes… history reads would also be fine, but counts suffice).
   **IMPACT:** none on planning; worker must verify counts when implementing.
3. **ASSUMPTION:** C-MAPSS `data/raw` is the 44 MB S3 mirror described in the
   README (blobs unopened per instructions). **WHY:** `data/interim/cmapss`
   file count (1,416) matches `reports/full-test-2026-08-28.md` §2 exactly,
   so the cache is consistent with that report. **IMPACT:** Phase 3 can rely
   on the cached units without re-download.
4. **ASSUMPTION:** no hidden unify-rul license grant exists outside the repo
   (e.g. email from faculty). **WHY:** none found in repo. **IMPACT:** owner
   decision required before copying code (see §10).
5. **ASSUMPTION:** JouleMitra targets the same Pi 5 + ESP32 hardware the owner
   already owns. **WHY:** unify-rul is built and measured on that pair; spec
   §12 Phase 7 names ESP32/RPi. **IMPACT:** if hardware differs, Phase 6/7
   estimates change.

---

## 10. Proposed integration strategy

1. **Phase 1–2 (no PBL code):** build JouleMitra simulator → API → Postgres →
   Streamlit and SEC/baseline/anomaly natively. PBL contributes only
   *discipline* (config-logged runs, always-a-baseline, overfit-check-first,
   artifact-generated figures). No imports from unify-rul.
2. **Phase 3 (adapter, not merge):** implement JouleMitra
   `ml/machine_health/adapter.py` exposing `MachineHealthModel`
   with `predict(window) / score(series) / explain(prediction)`, backed
   initially by ONNX Runtime loading of a retrained foundry/bearing checkpoint
   in the `edge/artifacts` 3-file layout (`model.onnx`, `norm_stats.json`,
   `sensor_vocab.json` + `live_map.json`). Copy the *contract* from
   `edge/inference.py::Predictor` + `Smoother` (≈190 + 218 lines, numpy-only);
   copy zero torch code into the service. C-MAPSS turbofan weights are NEVER
   loaded as foundry health — spec §6 forbids it; the adapter ships with
   `NotImplementedError` until a bearing/foundry checkpoint exists, and all
   health outputs are tagged SIMULATED or DERIVED per the evidence rule.
3. **Phase 6 (gateway):** fork the `edge/app.py` request-validation →
   window → predict → smooth → SQLite-log → `/health` skeleton into
   `edge/gateway/`, replacing HTTP-ingest-only with MQTT subscribe
   (`paho-mqtt`), per-machine window state, site/machine topic routing
   (`joulemitra/{site}/{machine}/telemetry|health|state`), and offline
   buffering with resync. Reuse `edge/bench.py` percentile-reporting for gateway latency validation.
4. **Phase 7 (firmware):** reuse the dual-core timing architecture and
   feature-order contract from `firmware/esp32/src/main.cpp`, but write a new
   energy-meter node (Modbus reads via the Phase 6 abstraction); keep the
   MPU-6050 vibration node only as the health-sensor complement.
5. **Legal gate:** resolve the missing-license decision (below) before any
   line of unify-rul code is copied. If unresolved, re-implement contracts
   from this audit's descriptions (clean-room) rather than copying files.

**Decisions needed from owner (pre-Phase 3):** (a) license for unify-rul reuse
(add LICENSE file — blocks any copying); (b) confirm Python version for
JouleMitra (3.11 per challenge background vs newer); (c) PostgreSQL-in-Docker
vs SQLite for local dev (spec §3.5 says PostgreSQL, TimescaleDB-ready);
(d) whether the C-MAPSS cache may be used for adapter *interface* tests only
(never as foundry evidence).
