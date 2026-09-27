"""Scenario injector note.

Packet-level fault injection is NOT used: the cumulative energy counter would
become inconsistent if power were edited post-hoc. Scenarios IDLE_WASTE,
HIGH_LOAD, PRODUCTION_SURGE, EQUIPMENT_DEGRADATION and TARIFF_SHIFT are
implemented as in-run physics overrides in SimulatedFactory (parameterised
by start offset, duration, magnitude; degradation adds energy_penalty and
omit_health_signals; TARIFF_SHIFT clusters furnace heats in the peak window
via the peak_cluster_window timing knob with NORMAL per-heat physics).
COMBINED_ANOMALY is future work.
"""

from apps.simulator.factory_simulator import NOT_IMPLEMENTED_SCENARIOS, Scenario

# Alias kept for older imports.
PHASE3_SCENARIOS = NOT_IMPLEMENTED_SCENARIOS


def apply_fault(packets: list[dict], scenario: Scenario) -> list[dict]:
    if scenario == Scenario.NORMAL:
        return packets
    if scenario in NOT_IMPLEMENTED_SCENARIOS:
        raise NotImplementedError(
            f"Scenario {scenario.value} is future work; IDLE_WASTE, HIGH_LOAD, "
            "PRODUCTION_SURGE, EQUIPMENT_DEGRADATION and TARIFF_SHIFT are "
            "implemented in SimulatedFactory (see SimulatedFactory)."
        )
    raise NotImplementedError(
        f"Scenario {scenario.value} is implemented in SimulatedFactory as an in-run "
        "physics override, not as a post-hoc packet edit (energy-counter consistency)."
    )
