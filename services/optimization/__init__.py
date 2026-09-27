"""Phase 4A tariff-aware furnace scheduling (Google OR-Tools CP-SAT)."""

from services.optimization.constraints import (
    AuxPlan,
    AuxTask,
    HeatPlan,
    HeatTemplate,
    OptConstraints,
    Schedule,
    templates_from_heats,
)
from services.optimization.evaluate import (
    EnergyModel,
    EvalResult,
    StatePowers,
    TariffPeriod,
    assign_reheat,
    evaluate,
    slots_to_heats,
)
from services.optimization.scheduler import SchedulerResult, plan
from services.optimization.validate import validate

__all__ = [
    "AuxPlan",
    "AuxTask",
    "EnergyModel",
    "EvalResult",
    "HeatPlan",
    "HeatTemplate",
    "OptConstraints",
    "Schedule",
    "SchedulerResult",
    "StatePowers",
    "TariffPeriod",
    "assign_reheat",
    "evaluate",
    "plan",
    "slots_to_heats",
    "templates_from_heats",
    "validate",
]
