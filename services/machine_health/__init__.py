"""Phase 3 machine-health package: model registry.

`statistical-v1` is the native model and the ONLY model that scores factory
machines. `pbl-rul` is the external-RUL adapter: always OUT_OF_DOMAIN for
factory machines (it never emits a score), with an in-domain score_window()
for demonstration/tests only.
"""

from services.machine_health.model import MachineHealthModel
from services.machine_health.pbl_adapter import PBLRulAdapter
from services.machine_health.statistical import StatisticalHealthModel

#: Model id that scores factory machines. Scoring factory machines ALWAYS
#: uses this model; requesting any other model id for factory intervals
#: yields OUT_OF_DOMAIN rows, never scores.
FACTORY_MODEL_ID = StatisticalHealthModel.model_id

REGISTRY: dict[str, type[MachineHealthModel]] = {
    StatisticalHealthModel.model_id: StatisticalHealthModel,
    PBLRulAdapter.model_id: PBLRulAdapter,
}


def make_model(model_id: str, **kwargs) -> MachineHealthModel:
    try:
        cls = REGISTRY[model_id]
    except KeyError:
        raise ValueError(f"Unknown machine-health model_id: {model_id}") from None
    return cls(**kwargs)


__all__ = [
    "FACTORY_MODEL_ID",
    "REGISTRY",
    "MachineHealthModel",
    "PBLRulAdapter",
    "StatisticalHealthModel",
    "make_model",
]
