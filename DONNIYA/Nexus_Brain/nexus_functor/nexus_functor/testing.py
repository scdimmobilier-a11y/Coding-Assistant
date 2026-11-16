"""
nexus_functor.testing
=======================

Zero-dependency mock implementations of the four ports, so the functor
can be developed, demoed, and unit-tested without any of the other five
Nexus Brain modules present. Swap these for real adapters (in-process,
subprocess, or HTTP) once Nexus Planner / Nexus Exec / Nexus Harness /
Nexus Proactive are wired up for real.
"""

from __future__ import annotations

import random
from typing import Any, Optional

from .types import (
    Decision,
    FeedbackEvent,
    Objective,
    Outcome,
    Plan,
    PlanSet,
    PlanStep,
    ProactiveCandidate,
    ProactiveSignal,
)


class MockPlanner:
    """Stands in for Nexus Planner: hands back a small diverse plan set."""

    def __init__(self, n_plans: int = 3, steps_per_plan: int = 4, seed: int = 0) -> None:
        self._n_plans = n_plans
        self._steps_per_plan = steps_per_plan
        self._rng = random.Random(seed)

    def generate_plans(self, objective: Objective, context: dict[str, Any]) -> PlanSet:
        plans = []
        for i in range(self._n_plans):
            steps = tuple(
                PlanStep(
                    step_id=f"{objective.goal_id}-p{i}-s{j}",
                    action=f"action_{j}",
                    expected_duration_s=self._rng.uniform(1, 5),
                    expected_reward=self._rng.uniform(0.3, 1.0),
                )
                for j in range(self._steps_per_plan)
            )
            plans.append(
                Plan(
                    plan_id=f"{objective.goal_id}-plan{i}",
                    steps=steps,
                    estimated_cost=self._rng.uniform(1, 10),
                    estimated_reward=sum(s.expected_reward for s in steps),
                    confidence=self._rng.uniform(0.4, 0.95),
                    novelty=self._rng.uniform(0.0, 1.0),
                )
            )
        return PlanSet(objective_id=objective.goal_id, plans=tuple(plans))


class MockExecutor:
    """Stands in for Nexus Exec: 'runs' a step and reports a plausible outcome."""

    def __init__(self, failure_rate: float = 0.1, seed: int = 0) -> None:
        self._failure_rate = failure_rate
        self._rng = random.Random(seed)

    def execute_step(self, plan_id: str, step_id: str, params: dict[str, Any]) -> FeedbackEvent:
        roll = self._rng.random()
        if roll < self._failure_rate:
            outcome, deviation, reward = Outcome.FAILURE, self._rng.uniform(0.4, 0.9), 0.0
        elif roll < self._failure_rate + 0.2:
            outcome, deviation, reward = Outcome.PARTIAL, self._rng.uniform(0.1, 0.4), self._rng.uniform(0.2, 0.6)
        else:
            outcome, deviation, reward = Outcome.SUCCESS, self._rng.uniform(0.0, 0.1), self._rng.uniform(0.6, 1.0)
        return FeedbackEvent(
            plan_id=plan_id,
            step_id=step_id,
            outcome=outcome,
            observed_reward=reward,
            deviation=deviation,
        )


class MockHarness:
    """Stands in for Nexus Harness: a trivial learned prior that nudges toward EXPLOIT."""

    def __init__(self) -> None:
        self.recorded: list[tuple[Objective, Decision, FeedbackEvent]] = []

    def get_policy_prior(self, objective: Objective, context: dict[str, Any]) -> dict[str, float]:
        return {"EXPLOIT": 0.55, "EXPLORE": 0.25, "RECOVER": 0.1, "CONSERVE": 0.1}

    def record_outcome(self, objective: Objective, decision: Decision, feedback: FeedbackEvent) -> None:
        self.recorded.append((objective, decision, feedback))


class MockProactive:
    """Stands in for Nexus Proactive: occasionally suggests an interruption."""

    def __init__(self, seed: int = 0) -> None:
        self._rng = random.Random(seed)

    def estimate(self, state_id: str, context: dict[str, Any]) -> ProactiveSignal:
        candidates = tuple(
            ProactiveCandidate(
                action=f"suggest_{i}",
                utility=self._rng.uniform(0.2, 1.0),
                receptivity=self._rng.uniform(0.0, 1.0),
                cost=self._rng.uniform(0.0, 0.3),
                tau_offset_s=self._rng.uniform(0.0, 10.0),
            )
            for i in range(2)
        )
        return ProactiveSignal(state_id=state_id, candidates=candidates)
