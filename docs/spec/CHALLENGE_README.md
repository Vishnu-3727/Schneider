# Smart Manufacturing — Industrial Energy & Process Efficiency

## Project Overview

We are building a software prototype for the Smart Manufacturing challenge.

The goal is to help a small/medium manufacturing factory:

- Monitor machine-level energy consumption
- Detect abnormal energy usage
- Identify whether abnormal consumption may be related to machine degradation or process inefficiency
- Optimize production scheduling where possible
- Estimate energy, financial, and CO₂ savings
- Verify whether an intervention actually produced the expected improvement

The core idea is:

> **Measure → Understand → Predict → Optimize → Act → Verify**

This is NOT intended to be just another IoT dashboard or just a predictive-maintenance system.

The important part is connecting:

**Energy + Machine Health + Production**

into one decision-support system.

---

# 1. Problem

A typical SME manufacturing factory may have machines such as:

- Motors
- Compressors
- Pumps
- Furnaces
- CNC/process machines
- Conveyors

The factory knows its overall electricity bill but may not know:

- Which machine is consuming excessive energy
- When energy consumption becomes abnormal
- Whether increased consumption is caused by production or equipment degradation
- Whether production scheduling is creating unnecessary energy peaks
- How much money and CO₂ could be saved by changing operations

The system should help answer:

> **Where is energy being wasted, why is it being wasted, and what should the factory do about it?**

while maintaining required production and quality.

---

# 2. Proposed Architecture

```text
                         FACTORY
                            |
              +-------------+-------------+
              |             |             |
          Energy Data   Machine Data   Production Data
              |             |             |
              +-------------+-------------+
                            |
                            v
                    DATA / EDGE LAYER
                            |
                            v
                 ENERGY BASELINE ENGINE
                            |
                            v
                 ANOMALY DETECTION ENGINE
                            |
                 +----------+----------+
                 |                     |
                 v                     v
          MACHINE HEALTH         PROCESS ANALYSIS
                 |                     |
                 +----------+----------+
                            |
                            v
                  OPTIMIZATION ENGINE
                            |
                            v
                 RECOMMENDATION ENGINE
                            |
                            v
                       DASHBOARD
                            |
                            v
                  ACTION / INTERVENTION
                            |
                            v
                  MEASURE ACTUAL RESULT
                            |
                            +------> FEEDBACK
```

---

# 3. Core Software Components

## A. Factory Data Simulator

Because we initially do not have access to a real industrial factory, we will generate realistic synthetic data.

The simulator should generate:

### Electrical data

- Voltage
- Current
- Power
- Energy/kWh
- Power factor

### Machine data

- Temperature
- Vibration
- Machine load
- Operating state
- RPM where relevant

### Production data

- Production quantity
- Production rate
- Machine operating time
- Product/batch information

### External data

- Electricity tariff
- Time of day
- Renewable availability if used

The simulator must also generate abnormal scenarios.

Example:

```text
Normal:

Production = 100 units/hour
Power = 50 kW
Vibration = normal

Fault/degradation:

Production = 100 units/hour
Power = 65 kW
Vibration = increasing
Temperature = increasing
```

This allows us to demonstrate that the system can detect an energy-efficiency problem.

---

# 4. Energy Baseline Engine

The system should determine how much energy a machine/process SHOULD consume under its current operating conditions.

Example:

```text
Production = 100 units/hour
Machine load = 70%
Operating time = 8 hours

Expected energy = 500 kWh
Actual energy   = 620 kWh

Energy anomaly = +120 kWh
```

The important concept is **production-normalized energy**.

We should not simply say:

> "The machine consumed more energy."

We should ask:

> "Did the machine consume more energy than expected for the amount of production it performed?"

Possible models:

- Linear Regression
- Random Forest
- XGBoost

Start simple. Only use more complex ML if it provides a measurable benefit.

---

# 5. Anomaly Detection

The system should detect abnormal behavior.

Possible methods:

- Statistical thresholds
- Rolling averages
- Z-score
- Isolation Forest
- ML-based anomaly detection

Example:

```text
Expected power = 50 kW
Actual power   = 65 kW
Production     = unchanged

             ↓

Energy anomaly detected
```

The system should then investigate possible causes.

---

# 6. Energy + Machine Health Correlation

This is an important differentiating component.

Instead of treating machine health and energy as separate systems, correlate them.

Example:

```text
Production = unchanged
Motor current = increasing
Vibration = increasing
Temperature = increasing
Energy = increasing

                ↓

Possible equipment degradation
```

The system should distinguish between:

### Production-driven energy increase

```text
Production ↑
Energy ↑
Machine condition normal
```

This is likely normal.

### Equipment-driven energy increase

```text
Production → same
Energy ↑
Vibration ↑
Temperature ↑
Current ↑
```

This is potentially abnormal.

The system should report this as a likely cause, not claim certainty unless the evidence supports it.

---

# 7. Optimization Engine

The optimizer should consider:

- Production requirements
- Machine availability
- Machine operating constraints
- Energy consumption
- Electricity tariff
- Operating schedule

Objective:

Reduce energy/cost/CO₂ while maintaining production requirements.

Example:

```text
Current:

Machine A + Machine B + Machine C
running simultaneously

Peak = 450 kW
```

Possible optimized schedule:

```text
Machine A
    ↓
Machine B
    ↓
Machine C

Peak = 300 kW
```

Production must remain within the required target.

Use:

**Google OR-Tools**

for the initial optimization prototype.

---

# 8. Recommendation Engine

The system should convert analysis into actionable recommendations.

Examples:

```text
WARNING

Compressor 2 is consuming 18% more energy
than its production-normalized baseline.

Possible cause:
Equipment inefficiency / degradation.

Recommended action:
Inspect compressor and check operating condition.

Estimated saving:
₹X/day
```

Another example:

```text
OPTIMIZATION OPPORTUNITY

Process B can be shifted from 2 PM to 10 PM.

Expected result:
Peak demand ↓
Energy cost ↓
CO₂ ↓

Production target:
Maintained
```

---

# 9. Savings & Carbon Engine

Every recommendation should be translated into measurable impact.

## Energy

```text
Before = 10,000 kWh/day
After  = 8,700 kWh/day

Energy saved = 1,300 kWh/day
```

## Cost

```text
Cost saving = Energy saved × applicable tariff
```

## CO₂

```text
CO₂e avoided =
Energy saved × applicable emission factor
```

Emission factors must be configurable and sourced appropriately rather than hard-coded arbitrarily.

## Production

Always show whether production was maintained.

Example:

```text
Production before = 5,000 units/day
Production after  = 5,000 units/day
```

The key KPI is therefore not simply:

> "Energy decreased."

It is:

> **Energy decreased while required production was maintained.**

---

# 10. Savings Verification

The system should not stop at making a prediction.

It should compare predicted savings with actual savings.

```text
Recommendation
      |
      v
Intervention
      |
      v
New measurements
      |
      v
Compare with baseline
      |
      v
Actual savings
```

Example:

```text
Predicted saving = ₹5,000/day
Actual saving    = ₹4,600/day
```

This creates a feedback loop and makes the system more useful than a static dashboard.

---

# 11. Dashboard

The final prototype should have a dashboard showing:

```text
+------------------------------------------------+
|       SMART FACTORY ENERGY INTELLIGENCE        |
+------------------------------------------------+
| Energy       | Cost          | CO2e             |
| 8,700 kWh    | ₹XX,XXX       | XXX kg           |
+------------------------------------------------+
|                                                |
|       Actual vs Expected Energy                |
|                                                |
+------------------------------------------------+
| MACHINE HEALTH                                 |
|                                                |
| Motor 1        NORMAL                          |
| Motor 2        WARNING                         |
| Compressor     ABNORMAL                        |
+------------------------------------------------+
| RECOMMENDATIONS                                |
|                                                |
| Compressor 2: 18% above baseline               |
| Action: Inspect compressor                    |
| Estimated saving: ₹X/day                       |
|                                                |
| Scheduling opportunity detected                |
| Estimated saving: ₹X/day                       |
+------------------------------------------------+
```

Recommended initial technology:

**Streamlit + Plotly**

---

# 12. Proposed Technology Stack

## Core

```text
Python 3.11
NumPy
Pandas
SciPy
Scikit-learn
XGBoost
OR-Tools
Plotly
Streamlit
```

## Backend

```text
FastAPI
Uvicorn
```

## Database

```text
PostgreSQL
TimescaleDB (optional)
```

## IoT / Future Hardware

```text
MQTT
Mosquitto
Modbus
PyModbus
```

## Edge

```text
Raspberry Pi
Python
```

## Development

```text
VS Code
Git
GitHub
```

Docker can be added later if the project becomes large enough to need multiple services.

---

# 13. Suggested Repository Structure

```text
smart-factory-energy/
│
├── simulator/
│   ├── factory_simulator.py
│   ├── machine_models.py
│   └── fault_generator.py
│
├── analytics/
│   ├── energy_baseline.py
│   ├── anomaly_detection.py
│   ├── machine_health.py
│   └── carbon.py
│
├── optimizer/
│   ├── scheduler.py
│   └── constraints.py
│
├── recommendations/
│   └── recommendation_engine.py
│
├── verification/
│   └── savings_verification.py
│
├── backend/
│   └── api.py
│
├── dashboard/
│   └── app.py
│
├── database/
│   └── schema.sql
│
├── data/
│   └── sample_data.csv
│
├── tests/
│
├── requirements.txt
└── README.md
```

---

# 14. Development Order

Do NOT build everything simultaneously.

### Phase 1 — Simulator

Generate realistic factory data.

↓

### Phase 2 — Energy Baseline

Expected vs actual energy.

↓

### Phase 3 — Anomaly Detection

Detect abnormal consumption.

↓

### Phase 4 — Machine Health

Correlate vibration/temperature/current with energy.

↓

### Phase 5 — Optimization

Find better operating schedules.

↓

### Phase 6 — Savings

Calculate:

- kWh saved
- ₹ saved
- CO₂e avoided
- production maintained

↓

### Phase 7 — Verification

Compare predicted vs actual savings.

↓

### Phase 8 — Dashboard

Put everything into one interface.

↓

### Phase 9 — Hardware

If time permits, replace simulated sensor data with:

ESP32 → MQTT → Raspberry Pi → software system.

---

# 15. What We Are NOT Building

Avoid turning this into an unnecessarily large project.

We are NOT initially building:

- A complete ERP
- A complete SCADA replacement
- A generic IoT dashboard
- A standalone predictive-maintenance system
- A standalone carbon calculator
- A giant deep-learning system
- Full autonomous control of industrial machinery

The focus is:

> **Energy + Machine Health + Production → Intelligent Recommendation/Optimization → Verified Savings**

---

# 16. Final Demonstration

The final demo should tell one complete story.

Example:

```text
Factory starts operating
        ↓
System monitors machines
        ↓
Compressor begins consuming abnormal energy
        ↓
Production remains unchanged
        ↓
Vibration/current/temperature also change
        ↓
System identifies likely equipment inefficiency
        ↓
Recommendation generated
        ↓
System also identifies a scheduling opportunity
        ↓
Optimizer proposes new schedule
        ↓
Simulated intervention
        ↓
Energy consumption decreases
        ↓
Production remains maintained
        ↓
System calculates:

Energy saved
₹ saved
CO₂e avoided
Payback
        ↓
Actual savings compared against prediction
```

This is the core software prototype we should deliver for the competition.
