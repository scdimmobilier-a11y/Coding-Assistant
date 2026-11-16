"""
nexus_functor.functor
=======================

NexusFunctor — the public entry point. This is "the foncteur dynamique
hiérarchique" from the architecture doc: the component that sits between
Nexus Planner's candidate plans / Nexus Proactive's candidate
(action, timing) pairs on one side, and Nexus Exec's execution on the
other, continuously selecting and re-selecting what to do.

Call shape, once per tick:

    decision = functor.step(objective, plan_set, execution_state, context)
    # ... hand decision.next_step off to Nexus Exec ...
    feedback = exec_port.execute_step(decision.selected_plan_id, step.step_id, step.params)
    functor.on_feedback(objective, decision, execution_state, feedback)

Everything upstream (F0-F3) is exercised on every `step()` call; the
functor itself holds no state beyond what F0/F3 need to detect
oscillation — all "real" state (whose plan is committed, how far along,
deviation history) lives in the caller-owned `ExecutionState`, so a
caller can run many concurrent objectives through their own functor
instances, or serialize/inspect ExecutionState freely.
"""

from __future__ import annotations

from typing import Any, Optional

from .config import FunctorConfig
from .f0_macro_strategy import F0MacroStrategySelector
from .f1_plan_selector import F1PlanSelector
from .f2_local_adapter import AdaptationAction, F2LocalAdapter
from .f3_stabilizer import F3Stabilizer
from .feedback import FeedbackLoopManager
from .interfaces import HarnessPort, PlannerPort, ProactivePort
from .types import (
    Decision,
    ExecutionState,
    FeedbackEvent,
    Objective,
    PlanSet,
)


class NexusFunctor:
    def __init__(
        self,
        config: Optional[FunctorConfig] = None,
        harness: Optional[HarnessPort] = None,
        planner: Optional[PlannerPort] = None,
        proactive: Optional[ProactivePort] = None,
    ) -> None:
        self._config = config or FunctorConfig()
        self._harness = harness
        self._planner = planner
        self._proactive = proactive

        self._f0 = F0MacroStrategySelector(self._config.f0)
        self._f1 = F1PlanSelector(self._config.f1)
        self._f2 = F2LocalAdapter(self._config.f2)
        self._f3 = F3Stabilizer(self._config.f3)
        self._feedback = FeedbackLoopManager(harness=harness)

    # ----------------------------------------------------------------

    def step(
        self,
        objective: Objective,
        plan_set: Optional[PlanSet],
        execution_state: ExecutionState,
        context: Optional[dict[str, Any]] = None,
    ) -> Decision:
        """
        Advance the run by one tick. Pulls a fresh plan_set from
        Nexus Planner if none was supplied and a planner port is wired in
        (typical first-tick case); otherwise re-uses the plan_set the
        caller already has generated for this objective.
        """
        context = context or {}
        execution_state.tick += 1

        if plan_set is None:
            if self._planner is None:
                raise ValueError(
                    "step() needs a PlanSet: either pass one explicitly, "
                    "or construct NexusFunctor with a `planner` port."
                )
            plan_set = self._planner.generate_plans(objective, context)

        # -- F2: react to the outcome of the *previous* tick, first ------
        current_plan = (
            plan_set.by_id(execution_state.committed_plan_id)
            if execution_state.committed_plan_id
            else None
        )
        adaptation = None
        if current_plan is not None:
            adaptation = self._f2.adapt(current_plan, execution_state, execution_state.last_step_result)
            execution_state.cumulative_deviation = adaptation.updated_cumulative_deviation
            if adaptation.action is AdaptationAction.ESCALATE:
                self._f3.force_release()

        # -- F0: pick macro-strategy for this tick ------------------------
        harness_prior = (
            self._harness.get_policy_prior(objective, context) if self._harness else {}
        )
        macro_strategy = self._f0.select(harness_prior, execution_state)

        # -- F1: rank candidate plans under that strategy ------------------
        ranked = self._f1.score_plans(plan_set, macro_strategy)

        # -- F3: decide whether to actually switch ------------------------
        final_plan_id, switched = self._f3.stabilize_plan(ranked)
        execution_state.committed_plan_id = final_plan_id
        final_plan = plan_set.by_id(final_plan_id)
        assert final_plan is not None  # stabilize_plan only returns ids from `ranked`

        if switched:
            execution_state.step_index = 0
            execution_state.cumulative_deviation = 0.0  # fresh plan, no drift yet
            next_step = final_plan.steps[0] if final_plan.length else None
            rationale = f"switched to {final_plan_id} (top-ranked under {macro_strategy.name})"
        elif adaptation is not None and adaptation.action is not AdaptationAction.ESCALATE:
            if adaptation.next_step_index is not None:
                execution_state.step_index = adaptation.next_step_index
            next_step = adaptation.next_step
            rationale = f"held {final_plan_id}: {adaptation.reason}"
        else:
            # No prior commitment and F3 didn't flag a switch (first tick,
            # single-plan set) — just start the plan.
            next_step = final_plan.steps[0] if final_plan.length else None
            rationale = f"starting {final_plan_id}"

        best_score = ranked[0].score
        confidence = _squash(best_score)

        # -- Proactive: fused (a*, tau*), independently of plan progress --
        proactive_signal = (
            self._proactive.estimate(execution_state.objective_id, context)
            if self._proactive
            else None
        )
        proactive_choice = self._f1.score_proactive(proactive_signal)
        proactive_choice = self._f3.stabilize_proactive(proactive_choice)

        return Decision(
            objective_id=objective.goal_id,
            macro_strategy=macro_strategy,
            selected_plan_id=final_plan_id,
            next_step=next_step,
            proactive_action=(
                proactive_choice.candidate.action if proactive_choice.candidate else None
            ),
            proactive_tau_offset_s=(
                proactive_choice.candidate.tau_offset_s if proactive_choice.candidate else None
            ),
            plan_switched=switched,
            confidence=confidence,
            rationale=rationale,
        )

    # ----------------------------------------------------------------

    def on_feedback(
        self,
        objective: Objective,
        decision: Decision,
        execution_state: ExecutionState,
        event: FeedbackEvent,
    ) -> None:
        """Route one FeedbackEvent through both the fast and slow loops."""
        self._feedback.on_feedback(objective, decision, execution_state, event)

    def flush_learning(self) -> None:
        """Force the slow loop to push any buffered outcomes to Nexus Harness now."""
        self._feedback.flush_slow_loop()


def _squash(score: float) -> float:
    """Map an unbounded score to a rough [0, 1] confidence via a soft squash."""
    # Simple, dependency-free logistic squash — good enough for a
    # human-readable confidence field, not meant to be a calibrated
    # probability.
    import math

    return 1.0 / (1.0 + math.exp(-score))
