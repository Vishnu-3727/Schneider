"""Phase 2+ scenario injector — stub for Phase 1.

Only NORMAL exists in Phase 1. Every other scenario name raises
NotImplementedError with a Phase 2+ message (never a fake implementation).
"""

from apps.simulator.factory_simulator import Scenario


def apply_fault(packets: list[dict], scenario: Scenario) -> list[dict]:
    if scenario == Scenario.NORMAL:
        return packets
    raise NotImplementedError(
        f"Scenario {scenario.value} is Phase 2+ work (IDLE_WASTE etc.); "
        "only NORMAL is implemented in Phase 1."
    )
