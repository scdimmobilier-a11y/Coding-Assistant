"""
Nexus Functor — the hierarchical dynamic functor (F0-F3) at the center of
Nexus Brain. See README.md for the architecture and a runnable example.

    from nexus_functor import NexusFunctor, FunctorConfig
    from nexus_functor.types import Objective, ExecutionState

Independent of every other Nexus Brain module: stdlib only.
"""

from .config import F0Config, F1Config, F2Config, F3Config, FunctorConfig
from .functor import NexusFunctor
from .types import (
    Decision,
    ExecutionState,
    FeedbackEvent,
    MacroStrategy,
    Objective,
    Outcome,
    Plan,
    PlanSet,
    PlanStep,
    ProactiveCandidate,
    ProactiveSignal,
)

__all__ = [
    "NexusFunctor",
    "FunctorConfig",
    "F0Config",
    "F1Config",
    "F2Config",
    "F3Config",
    "Objective",
    "Plan",
    "PlanSet",
    "PlanStep",
    "ExecutionState",
    "FeedbackEvent",
    "Outcome",
    "MacroStrategy",
    "Decision",
    "ProactiveCandidate",
    "ProactiveSignal",
]

__version__ = "0.1.0"
