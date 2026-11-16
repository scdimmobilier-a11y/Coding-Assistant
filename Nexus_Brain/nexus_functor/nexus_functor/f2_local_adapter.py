"""
nexus_functor.f2_local_adapter
================================

F2 — the fast, cheap layer that reacts to what just happened on the
*current* plan without going all the way back up to F1/F0. Most execution
noise should be absorbed here; F1 re-selection is for when F2 gives up.

Three outcomes per tick, in increasing order of severity:
  - CONTINUE:  step went fine (or close enough), advance to the next step.
  - PATCH:     step drifted enough to need a local fix (retry / substitute
               params) but the plan overall is still worth continuing.
  - ESCALATE:  cumulative deviation on this plan has crossed the point
               where patching isn't enough — hand back to F1 to pick a
               (possibly different) plan.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

from .config import F2Config
from .types import ExecutionState, FeedbackEvent, Outcome, Plan, PlanStep


class AdaptationAction(Enum):
    CONTINUE = auto()
    PATCH = auto()
    ESCALATE = auto()


@dataclass(frozen=True)
class AdaptationResult:
    action: AdaptationAction
    next_step: Optional[PlanStep]
    next_step_index: Optional[int]
    updated_cumulative_deviation: float
    reason: str


class F2LocalAdapter:
    def __init__(self, config: F2Config) -> None:
        self._config = config

    def adapt(
        self,
        plan: Plan,
        execution_state: ExecutionState,
        last_feedback: Optional[FeedbackEvent],
    ) -> AdaptationResult:
        # Decay old deviation so a run that recovers isn't punished forever.
        decayed = execution_state.cumulative_deviation * self._config.deviation_decay
        step_deviation = last_feedback.deviation if last_feedback else 0.0
        updated = decayed + step_deviation

        if updated >= self._config.escalate_threshold:
            return AdaptationResult(
                action=AdaptationAction.ESCALATE,
                next_step=None,
                next_step_index=None,
                updated_cumulative_deviation=updated,
                reason=(
                    f"cumulative deviation {updated:.2f} >= escalate threshold "
                    f"{self._config.escalate_threshold:.2f}"
                ),
            )

        next_index = execution_state.step_index
        if last_feedback is not None and last_feedback.outcome != Outcome.FAILURE:
            next_index += 1

        if next_index >= plan.length:
            return AdaptationResult(
                action=AdaptationAction.CONTINUE,
                next_step=None,  # plan complete
                next_step_index=next_index,
                updated_cumulative_deviation=updated,
                reason="plan complete",
            )

        next_step = plan.steps[next_index]

        if step_deviation >= self._config.local_patch_threshold:
            patched = self._patch_step(next_step, last_feedback)
            return AdaptationResult(
                action=AdaptationAction.PATCH,
                next_step=patched,
                next_step_index=next_index,
                updated_cumulative_deviation=updated,
                reason=(
                    f"step deviation {step_deviation:.2f} >= local patch threshold "
                    f"{self._config.local_patch_threshold:.2f}"
                ),
            )

        return AdaptationResult(
            action=AdaptationAction.CONTINUE,
            next_step=next_step,
            next_step_index=next_index,
            updated_cumulative_deviation=updated,
            reason="on track",
        )

    @staticmethod
    def _patch_step(step: PlanStep, last_feedback: Optional[FeedbackEvent]) -> PlanStep:
        """
        Minimal local repair: retry the same action with a note attached.
        A real implementation would branch on `last_feedback.notes` /
        `outcome` to pick retry vs. parameter substitution vs. skip; this
        default keeps the mechanism obviously extensible without
        hardcoding domain-specific repair logic into the functor itself.
        """
        patched_params = dict(step.params)
        patched_params["_retry"] = True
        if last_feedback is not None:
            patched_params["_prior_outcome"] = last_feedback.outcome.name
        return PlanStep(
            step_id=f"{step.step_id}-patched",
            action=step.action,
            params=patched_params,
            expected_duration_s=step.expected_duration_s,
            expected_reward=step.expected_reward,
        )
