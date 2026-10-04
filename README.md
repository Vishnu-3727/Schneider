<div align="center">

# JouleMitra

Find the energy your factory wastes, fix it, and prove the saving.

Energy and process-efficiency intelligence for Indian SME foundries · Schneider Electric Challenge 04 · Team Tap to Tap

[![live demo](https://img.shields.io/static/v1?label=live&message=demo&color=brightgreen&style=flat-square)](https://vishnu-3727.github.io/Schneider/)
[![python 3.11](https://img.shields.io/static/v1?label=python&message=3.11&color=blue&style=flat-square)](docs/DEVELOPMENT_NOTES.md)
[![tests 278 passed](https://img.shields.io/static/v1?label=tests&message=278%20passed&color=brightgreen&style=flat-square)](docs/DEVELOPMENT_NOTES.md)
[![data simulated](https://img.shields.io/static/v1?label=data&message=simulated&color=orange&style=flat-square)](docs/ASSUMPTIONS.md)
[![FastAPI](https://img.shields.io/static/v1?label=backend&message=FastAPI&color=teal&style=flat-square)](docs/ARCHITECTURE.md)
[![PostgreSQL 16](https://img.shields.io/static/v1?label=database&message=PostgreSQL%2016&color=blueviolet&style=flat-square)](docs/DATA_MODEL.md)

[**Live demo**](https://vishnu-3727.github.io/Schneider/) ·
[**How it works**](#how-it-works) ·
[**Quick start**](#quick-start) ·
[**Results**](#results-simulated-plant-data) ·
[**Docs**](#documentation)

<img src="docs/readme/cover.png" width="100%" alt="JouleMitra console cover screen">

</div>

## The problem

Indian SME foundries get one bill a month, with no per-machine view.
A busy day and a wasteful day look exactly the same on that bill.
Savings are guessed, never proven.

## What JouleMitra does

| Step | What happens |
| ---- | ------------ |
| Measure | Reads existing panel meters over RS-485 Modbus, per machine, per hour. |
| Detect | Compares actual energy with a baseline learned from each machine's own history, for the output it actually produced (kWh per tonne). |
| Plan | A CP-SAT optimiser moves furnace heats out of peak-tariff hours, same heats and same output. |
| Act | Ranked actions in a morning brief (English, Tamil, Hindi); a supervisor approves; nothing is switched automatically. |
| Verify | Counterfactual measurement with ASHRAE Guideline 14 uncertainty; a saving is claimed only when it beats the error band. |

## Results (simulated plant data)

| Result | What it means |
|---|---|
| **−6.9 %** | less energy on furnace-01 after the idle-holding fix (VERIFIED on simulated data) |
| **546.7 ± 209.6 kWh** | saved in 70 measured hours; the saving is 2.6× its 90 % error band |
| **1 in 100** | false claims across 100 runs where the fix did nothing |
| **≈ 2.2 months** | projected payback on a ₹75,000 kit |

All plant figures come from the simulator. The pipeline was also run on a year of real steel-plant meter data (UCI #851). Details: [docs/VALIDATION.md](docs/VALIDATION.md).

## See it

<table>
<tr>
<td><img src="docs/readme/plant.png" alt="Plant overview"><br><b>Plant overview</b></td>
<td><img src="docs/readme/detect.png" alt="Waste caught early"><br><b>Waste caught early</b></td>
</tr>
<tr>
<td><img src="docs/readme/optimise.png" alt="Plan tomorrow"><br><b>Plan tomorrow</b></td>
<td><img src="docs/readme/brief.png" alt="Morning brief"><br><b>Morning brief</b></td>
</tr>
</table>

<img src="docs/readme/impact.png" width="100%" alt="Savings proven against the counterfactual">

*Savings, proven against what would have happened anyway.*

Open the [live console](https://vishnu-3727.github.io/Schneider/) (read-only snapshot; run locally for live actions).

## How it works

```mermaid
flowchart LR
    CT["CT clamps"] --> METER["Energy meter (Modbus RTU)"] --> CONV["RS-485 to TCP converter"] --> EDGE["Edge gateway (Raspberry Pi, store-and-forward)"] --> SRV
    subgraph SRV["JouleMitra server (FastAPI + PostgreSQL)"]
        direction TB
        BASE["Baseline (NNLS)"] --> ANOM["Anomaly detection"] --> HEALTH["Machine health"] --> OPT["Optimiser (CP-SAT)"] --> REC["Recommendations"] --> VER["Verification (ASHRAE G14)"]
    end
    SRV --> CONSOLE["Web console"] & BRIEF["Morning brief"] & ERP["ERP-MES export"]
```

| Layer | Technology |
| ----- | ---------- |
| Backend | Python 3.11, FastAPI, Pydantic, SQLAlchemy |
| Data | PostgreSQL 16, SQLite edge buffer |
| Analytics | NumPy, Pandas, SciPy, Google OR-Tools CP-SAT |
| Industrial IoT | MQTT/Mosquitto, Modbus TCP/pymodbus, RS-485 |
| Frontend | Web console with three.js, Streamlit + Plotly |
| Quality | pytest, Ruff, Docker Compose |

## Quick start

The live link above is a read-only snapshot; to run the full interactive site (Try a fault, approve, re-plan) on your own machine, you only need Docker Desktop.

### Get the code

```bash
git clone https://github.com/Vishnu-3727/Schneider.git
cd Schneider
```

No git? Use Code → Download ZIP on GitHub, unzip it, and open the folder.

### One click

Requires Docker Desktop (Windows, macOS) or Docker Engine with the compose plugin (Linux).

Windows: double-click `start-demo.bat`. macOS / Linux:

```bash
./start-demo.sh
```

First run builds the image and loads the simulated plant (about 3–5 minutes); later runs are faster. It opens `http://localhost:8000/console/` when ready. Stop with `docker compose down`.

### Same thing, step by step

```bash
docker compose up -d --build db mqtt backend
docker compose exec -T backend python scripts/setup/init_db.py
docker compose exec -T backend python scripts/demo/run_demo.py
# then open http://localhost:8000/console/
```

They work the same in PowerShell.

### What you get

| URL | What it is |
| --- | ---------- |
| `http://localhost:8000/console/` | The web console, all 11 screens, live |
| `http://localhost:8000/docs` | The API, Swagger UI |
| `http://localhost:8501` | Streamlit dashboard; start it with `docker compose up -d dashboard` |

### Troubleshooting

- Port 8000 or 5432 already in use: stop the other program or run `docker compose down` first.
- Docker is not running: start Docker Desktop, wait until it says Running, then run again.
- Reset everything with `docker compose down -v` (deletes the demo database).

<details><summary>Developer setup (Python 3.11, no Docker for the app)</summary>

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
Copy-Item .env.example .env
docker compose up -d db mqtt
.venv\Scripts\python scripts/setup/init_db.py
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\demo\demo.ps1 -Console
```

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://joulemitra:joulemitra@localhost:5432/joulemitra_test"
.venv\Scripts\python -m pytest -q
```

</details>

More commands (simulator, dashboard, Docker, API): [docs/DEVELOPMENT_NOTES.md](docs/DEVELOPMENT_NOTES.md).

## Repository layout

```text
apps/backend      # FastAPI server: telemetry, baselines, alerts, scheduling, verification
apps/console      # Web console served at /console/ (live API only)
apps/dashboard    # Streamlit dashboard (API-only views)
apps/simulator    # SimulatedFactory: physics engine producing SIMULATED telemetry
services/         # Analytics services: energy, health, optimisation, verification
edge/             # Raspberry Pi gateway: MQTT/Modbus adapters + SQLite store-and-forward
database/         # Plain-SQL migrations and seeds
scripts/          # Setup helpers and one-click end-to-end demo
site/             # Static snapshot published to GitHub Pages
docs/             # Architecture, data model, validation, deployment references
tests/            # Unit, API and integration tests (real Postgres, nothing skipped)
```

## Documentation

| Doc | What it covers |
| --- | -------------- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Layered modular-monolith design and repo layout |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Entity model, units, timestamps and source classes |
| [docs/ML_MODELS.md](docs/ML_MODELS.md) | Model cards: baseline, machine health, RUL adapter, optimiser |
| [docs/VALIDATION.md](docs/VALIDATION.md) | Validation results on simulated data plus real steel-plant meter data (UCI #851) |
| [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) | Every simulator constant, labelled SIMULATED/ASSUMPTION |
| [docs/SIMULATION.md](docs/SIMULATION.md) | Scenario engine and the implemented waste scenarios |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Edge gateway: protocol adapters and store-and-forward buffer |
| [docs/deployment/](docs/deployment/) | Reference plant wiring for a future install (docs only) |
| [docs/DEVELOPMENT_NOTES.md](docs/DEVELOPMENT_NOTES.md) | Phase notes, API list and commands moved out of this README |

## Scope and honesty

- All plant data is simulated; every figure is labelled SIMULATED, DERIVED or PROJECTED.
- Decision support only: it never switches a furnace, motor or safety system.
- Physical hardware and ESP32/Raspberry Pi deployment are the next step (wiring docs ready).

## Team Tap to Tap

Chennai Institute of Technology, Department of ECE: Vishnu Vardhan K S (team lead), Varshini R, Yugawathi E, V Paresh Kumar.
Schneider Electric Challenge 04: Smart Manufacturing.
