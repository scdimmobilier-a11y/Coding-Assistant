"""
nexus_functor.interfaces
==========================

Abstract "ports" the functor talks to. Each port is a `typing.Protocol` —
structural typing, so any of the other five Nexus Brain modules (or a
subprocess/HTTP/CLI adapter wrapping one of them) can satisfy a port just
by having the right method signatures, with zero import-time coupling.

This is the seam that lets Nexus Planner (GPLv3) stay legally isolated as
an out-of-process service: as long as whatever sits behind PlannerPort
implements `generate_plans(...)`, the functor doesn't care whether that's
an in-process object, an HTTP call, or a subprocess pipe. Same goes for
the other four modules.

Every port also ships a trivial in-memory mock (in `testing.py`) so the
functor can be developed and unit-tested with zero external dependencies.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .types import (
    Decision,
    FeedbackEvent,
    Objective,
    PlanSet,
    ProactiveSignal,
)


@runtime_checkable
class PlannerPort(Protocol):
    """What the functor needs from Nexus Planner."""

    def generate_plans(self, objective: Objective, context: dict[str, Any]) -> PlanSet:
        """Return a diverse candidate plan set P = {P1, P2, ...} for objective."""
        ...


@runtime_checkable
class ExecutorPort(Protocol):
    """What the functor needs from Nexus Exec."""

    def execute_step(self, plan_id: str, step_id: str, params: dict[str, Any]) -> FeedbackEvent:
        """Run one plan step and report back what happened."""
        ...


@runtime_checkable
class HarnessPort(Protocol):
    """What the functor needs from Nexus Harness (the slow, learned policy loop)."""

    def get_policy_prior(self, objective: Objective, context: dict[str, Any]) -> dict[str, float]:
        """
        Return a prior over MacroStrategy names (as strings, e.g.
        {"EXPLOIT": 0.7, "EXPLORE": 0.2, "RECOVER": 0.05, "CONSERVE": 0.05})
        learned from past runs. F0 blends this with live signals.
        """
        ...

    def record_outcome(self, objective: Objective, decision: Decision, feedback: FeedbackEvent) -> None:
        """Slow-loop update: let the harness learn from what just happened."""
        ...


@runtime_checkable
class ProactivePort(Protocol):
    """What the functor needs from Nexus Proactive (fused WHAT+WHEN)."""

    def estimate(self, state_id: str, context: dict[str, Any]) -> ProactiveSignal:
        """Return candidate (action, timing) pairs worth considering right now."""
        ...
