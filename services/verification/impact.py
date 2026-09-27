"""Cost and CO2 impact of a VERIFIED energy saving (pure, no DB).

Only a VERIFIED saving is converted. Any other outcome returns status
NOT_APPLICABLE with value None. A projected or unverified figure never
becomes rupees or kilograms here.

Cost: saving_inr = sum over measured hours of (counterfactual_h - actual_h)
x rate(hour). The rate comes from the tariff period covering the local hour
(start inclusive, end exclusive, periods may wrap midnight). A tariff that
does not cover every hour -> UNAVAILABLE (never a guessed price). A tariff
whose rows are all ASSUMPTION is labelled ILLUSTRATIVE: it is not the
factory's bill.

CO2: kgCO2 = verified saving_kwh x factor (kgCO2/kWh). Reported as CO2 only,
never relabelled CO2e. A factor still awaiting confirmation marks the result
provisional (an estimate, not for external accounting). The factor is
data with provenance (value, unit, gas basis, source, version, fiscal year,
effective period, source class). Choice: the factor whose effective period
covers the measurement date (EFFECTIVE), else the latest one that became
effective before it (LATEST_AVAILABLE, flagged), else UNAVAILABLE.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from services.optimization.evaluate import TariffPeriod, rate_at


@dataclass
class EmissionFactor:
    id: str
    geography: str
    value_kg_per_kwh: float
    unit: str
    gas_basis: str
    source_name: str
    version: str
    fiscal_year: str
    effective_from: date
    effective_to: date | None
    source_class: str
    note: str = ""


def cost_impact(hourly: list[dict], periods: list[TariffPeriod] | None, tz: str,
                illustrative: bool) -> dict:
    if not periods:
        return {"status": "UNAVAILABLE", "value_inr": None,
                "reason": "no tariff on record; no price is invented"}
    zone = ZoneInfo(tz)
    cf_cost = act_cost = 0.0
    try:
        for h in hourly:
            ws: datetime = h["window_start"]
            local = ws.astimezone(zone)
            rate = rate_at(periods, local.hour + local.minute / 60.0)
            cf_cost += h["counterfactual_kwh"] * rate
            act_cost += h["actual_kwh"] * rate
    except ValueError as exc:
        return {"status": "UNAVAILABLE", "value_inr": None,
                "reason": f"tariff incomplete: {exc}"}
    label = "ILLUSTRATIVE (ASSUMPTION) tariff, not the plant's bill" if illustrative \
        else "plant tariff"
    return {"status": "OK", "value_inr": round(cf_cost - act_cost, 2),
            "counterfactual_cost_inr": round(cf_cost, 2), "actual_cost_inr": round(act_cost, 2),
            "tariff_label": label, "evidence_class": "DERIVED",
            "source_class": "ASSUMPTION" if illustrative else "MEASURED"}


def select_factor(factors: list[EmissionFactor], on: date) -> tuple[EmissionFactor | None, str]:
    covering = [f for f in factors
                if f.effective_from <= on and (f.effective_to is None or on <= f.effective_to)]
    if covering:
        return max(covering, key=lambda f: f.effective_from), "EFFECTIVE"
    earlier = [f for f in factors if f.effective_from <= on]
    if earlier:
        return max(earlier, key=lambda f: f.effective_from), "LATEST_AVAILABLE"
    return None, "UNAVAILABLE"


def co2_impact(saving_kwh: float, factors: list[EmissionFactor], on: date) -> dict:
    factor, status = select_factor(factors, on)
    if factor is None:
        return {"status": "UNAVAILABLE", "value_kg": None,
                "reason": "no emission factor effective on or before the measurement date; "
                          "none is invented"}
    out = {"status": status, "value_kg": round(saving_kwh * factor.value_kg_per_kwh, 3),
           "unit": "kgCO2 (CO2 only, not CO2e: CEA grid factors exclude other GHGs)",
           "evidence_class": "DERIVED",
           # Provisional until the factor is confirmed against the CEA table:
           # an estimate, never an authoritative emissions reduction.
           "provisional": factor.source_class != "MEASURED" and "confirm" in factor.note.lower(),
           "label": "Estimated CO2 impact - provisional emission-factor data; "
                    "not for external accounting",
           "factor": {"id": factor.id, "value": factor.value_kg_per_kwh, "unit": factor.unit,
                      "gas_basis": factor.gas_basis, "geography": factor.geography,
                      "source": factor.source_name, "version": factor.version,
                      "fiscal_year": factor.fiscal_year,
                      "effective_from": factor.effective_from.isoformat(),
                      "effective_to": factor.effective_to.isoformat() if factor.effective_to else None,
                      "source_class": factor.source_class, "note": factor.note}}
    if status == "LATEST_AVAILABLE":
        out["reason"] = (f"no factor published for {on.isoformat()}; latest available "
                         f"({factor.fiscal_year}, {factor.version}) applied")
    return out


def impacts(outcome_status: str, saving_kwh: float | None, hourly: list[dict],
            periods: list[TariffPeriod] | None, illustrative: bool,
            factors: list[EmissionFactor], on: date, tz: str) -> tuple[dict, dict]:
    if outcome_status != "VERIFIED" or saving_kwh is None:
        na = {"status": "NOT_APPLICABLE", "reason": f"outcome {outcome_status}: no verified "
                                                     "saving to convert"}
        return {**na, "value_inr": None}, {**na, "value_kg": None}
    return (cost_impact(hourly, periods, tz, illustrative),
            co2_impact(saving_kwh, factors, on))
