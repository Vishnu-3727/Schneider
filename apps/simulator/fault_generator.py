"""Scenario injector note.

Packet-level fault injection is NOT used: the cumulative energy counter would
become inconsistent if power were edited post-hoc. Scenarios IDLE_WASTE,
HIGH_LOAD, PRODUCTION_SURGE and EQUIPMENT_DEGRADATION are implemented as
in-run physics overrides in SimulatedFactory (parameterised by start
offset, duration, magnitude; degradation adds energy_penalty and
omit_health_signals). TARIFF_SHIFT and COMBINED_ANOMALY are Phase 4+ work.
"""

from apps.simulator.factory_simulator import PHASE3_SCENARIOS, Scenario


def apply_fault(packets: list[dict], scenario: Scenario) -> list[dict]:
    if scenario == Scenario.NORMAL:
        return packets
    if scenario in PHASE3_SCENARIOS:
        raise NotImplementedError(
            f"Scenario {scenario.value} is Phase 4+ work; only NORMAL, IDLE_WASTE, "
            "HIGH_LOAD, PRODUCTION_SURGE and EQUIPMENT_DEGRADATION are implemented "
            "(see SimulatedFactory)."
        )
    raise NotImplementedError(
        f"Scenario {scenario.value} is implemented in SimulatedFactory as an in-run "
        "physics override, not as a post-hoc packet edit (energy-counter consistency)."
    )
