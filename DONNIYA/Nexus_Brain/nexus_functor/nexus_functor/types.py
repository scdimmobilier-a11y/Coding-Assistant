"""
nexus_functor.types
====================

Core data structures shared by every layer of the hierarchical dynamic
functor (F0 -> F1 -> F2 -> F3). Nothing in this module depends on any of
the other five vendored Nexus Brain components — it only depends on the
Python standard library, so it can be developed, tested, and reasoned
about in complete isolation.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# --------------------------------------------------------------------------
# Objective (output of Nexus Core's intent layer)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Objective:
    """A structured goal, as produced by Nexus Core from raw user intent."""

    goal_id: str
    description: str
    constraints: dict[str, Any] = field(default_factory=dict)
    priority: float = 1.0
    created_at: float = field(default_factory=time.time)


# --------------------------------------------------------------------------
# Plans (output of Nexus Planner / the diverse-plan-generation stage)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanStep:
    """A single atomic step inside a candidate plan."""

    step_id: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    expected_duration_s: float = 0.0
    expected_reward: float = 0.0


@dataclass(frozen=True)
class Plan:
    """
    One candidate plan P_i, as produced by Nexus Planner's diverse-planning
    branch. Nexus Planner emits a *set* of these (P = {P1, P2, ...}); F1's
    job is to choose and re-choose among them as execution unfolds.
    """

    plan_id: str
    steps: tuple[PlanStep, ...]
    estimated_cost: float
    estimated_reward: float
    confidence: float = 0.5  # planner's own confidence in this plan, [0, 1]
    novelty: float = 0.0  # how different this plan is from recently-used ones
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return len(self.steps)


@dataclass(frozen=True)
class PlanSet:
    """The full candidate set P = {P1, P2, ...} for one objective."""

    objective_id: str
    plans: tuple[Plan, ...]
    generated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.plans:
            raise ValueError("PlanSet must contain at least one plan")

    def by_id(self, plan_id: str) -> Optional[Plan]:
        return next((p for p in self.plans if p.plan_id == plan_id), None)


# --------------------------------------------------------------------------
# Execution-time state (fed back from Nexus Exec, mid-run)
# --------------------------------------------------------------------------

@dataclass
class ExecutionState:
    """
    Live state of an in-progress run: which plan is committed, how far
    along it, and how much the real trajectory has drifted from what the
    plan expected. F2 reads this every tick; F3 reads the drift history to
    decide whether a change is a blip or a real trend.
    """

    objective_id: str
    committed_plan_id: Optional[str] = None
    step_index: int = 0
    cumulative_deviation: float = 0.0  # 0 = perfectly on-plan
    last_step_result: Optional["FeedbackEvent"] = None
    history: list["FeedbackEvent"] = field(default_factory=list)
    tick: int = 0


# --------------------------------------------------------------------------
# Feedback (result reported back by Nexus Exec after running a step)
# --------------------------------------------------------------------------

class Outcome(Enum):
    SUCCESS = auto()
    PARTIAL = auto()
    FAILURE = auto()


@dataclass(frozen=True)
class FeedbackEvent:
    """One unit of feedback from execution, flowing back up the stack."""

    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    plan_id: str = ""
    step_id: str = ""
    outcome: Outcome = Outcome.SUCCESS
    observed_reward: float = 0.0
    deviation: float = 0.0  # how far this step's real result was from expected
    timestamp: float = field(default_factory=time.time)
    notes: str = ""


# --------------------------------------------------------------------------
# Proactive signal (fused WHAT + WHEN, from Nexus Proactive)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ProactiveCandidate:
    """One (action, timing) candidate the proactive layer thinks is worth considering."""

    action: str
    utility: float  # U(a, s): expected value of taking this action at all
    receptivity: float  # R(tau, s, h): how well-timed tau is right now, in [0, 1]
    cost: float  # interruption / compute / latency cost of (a, tau)
    tau_offset_s: float  # proposed timing, as an offset from "now"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProactiveSignal:
    """The candidate set handed to F1 for joint (a*, tau*) selection."""

    state_id: str
    candidates: tuple[ProactiveCandidate, ...]
    generated_at: float = field(default_factory=time.time)


# --------------------------------------------------------------------------
# Macro-strategy (F0 output)
# --------------------------------------------------------------------------

class MacroStrategy(Enum):
    """
    Broad operating regimes F0 can put the rest of the stack into. These
    bias how F1 scores plans/actions — see f1_plan_selector.PLAN_WEIGHTS
    and PROACTIVE_WEIGHTS for the concrete weight tables per regime.
    """

    EXPLOIT = auto()   # favor high-confidence, low-variance, proven plans
    EXPLORE = auto()   # favor novel/diverse plans, accept more risk
    RECOVER = auto()   # favor short, low-cost, high-certainty plans (damage control)
    CONSERVE = auto()  # favor low-cost/low-interruption options (resource/attention scarce)


# --------------------------------------------------------------------------
# Final decision (functor output, consumed by Nexus Exec)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Decision:
    """
    What the functor decided to do *right now*. This is the single object
    that crosses the boundary from Nexus Functor into Nexus Exec.
    """

    objective_id: str
    macro_strategy: MacroStrategy
    selected_plan_id: str
    next_step: Optional[PlanStep]
    proactive_action: Optional[str]
    proactive_tau_offset_s: Optional[float]
    plan_switched: bool
    confidence: float
    rationale: str
    decided_at: float = field(default_factory=time.time)
