"""
nexus_functor.f3_stabilizer
=============================

F3 — added specifically to counter the failure mode the architecture doc
flags for the fused proactive policy: over-anticipation and temporal
oscillation. Concretely, without this layer, F1 recomputing "the best
choice right now" every tick would cause two problems:

  1. Plan thrashing: two plans with near-identical scores trade the #1
     spot every tick as noisy inputs jitter, causing constant switching
     even though neither plan is actually better.
  2. Proactive flapping: a receptivity signal hovering right at the
     threshold fires an interruption, gets it wrong, backs off, fires
     again a moment later — the "over-anticipation" the doc warns about.

F3 fixes both with the same basic tool: hysteresis + cooldown. It is
intentionally the *only* place in the stack with memory of "what did we
just commit to" — F0/F1/F2 are stateless with respect to switching
decisions (F0 has its own light dwell-time check, but F3's is the
authoritative, stricter one for the final decision).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from .config import F3Config
from .f1_plan_selector import PlanScore, ProactiveChoice
from .types import ProactiveCandidate


@dataclass
class _CommittedPlan:
    plan_id: str
    score: float
    ticks_committed: int = 0


class F3Stabilizer:
    def __init__(self, config: F3Config) -> None:
        self._config = config
        self._committed: Optional[_CommittedPlan] = None
        self._smoothed_receptivity: dict[str, float] = {}  # action -> EMA
        self._last_proactive_fire_at: float = float("-inf")

    # -- plan switching hysteresis --------------------------------------

    def force_release(self) -> None:
        """
        Drop the current commitment outright. Called when F2 escalates
        (the current plan has drifted past the point of local repair) —
        in that situation we *want* F1's top pick to win immediately,
        dwell-time and margin checks would only get in the way of leaving
        a plan that's already known to be failing.
        """
        self._committed = None

    def stabilize_plan(self, ranked: list[PlanScore]) -> tuple[str, bool]:
        """
        Given F1's ranked plan scores (best first), return
        (final_plan_id, did_switch). Applies dwell-time + margin hysteresis
        against whatever plan is currently committed.
        """
        top = ranked[0]

        if self._committed is None:
            self._committed = _CommittedPlan(plan_id=top.plan.plan_id, score=top.score)
            return self._committed.plan_id, True

        self._committed.ticks_committed += 1
        current_score = next(
            (ps.score for ps in ranked if ps.plan.plan_id == self._committed.plan_id),
            float("-inf"),  # current plan no longer even in the candidate set
        )

        dwell_ok = self._committed.ticks_committed >= self._config.plan_min_dwell_ticks
        beats_margin = top.score - current_score >= self._config.plan_switch_margin
        different_plan = top.plan.plan_id != self._committed.plan_id

        if different_plan and dwell_ok and beats_margin:
            self._committed = _CommittedPlan(plan_id=top.plan.plan_id, score=top.score)
            return self._committed.plan_id, True

        # Hold the line — either not different, not dwelled long enough,
        # or not a big enough improvement to be worth the switch cost.
        self._committed.score = current_score
        return self._committed.plan_id, False

    # -- proactive timing stabilization ----------------------------------

    def stabilize_proactive(self, choice: ProactiveChoice) -> ProactiveChoice:
        """
        Smooth the receptivity component (EMA per action) and enforce a
        cooldown after the last time something actually fired, so a
        borderline signal can't cause back-to-back interruptions.
        """
        if choice.candidate is None:
            return choice

        now = time.time()
        if now - self._last_proactive_fire_at < self._config.proactive_cooldown_s:
            return ProactiveChoice(candidate=None, joint_score=choice.joint_score)

        smoothed = self._smooth(choice.candidate)
        smoothed_j = smoothed.utility * smoothed.receptivity - smoothed.cost

        self._last_proactive_fire_at = now
        return ProactiveChoice(candidate=smoothed, joint_score=smoothed_j)

    def _smooth(self, candidate: ProactiveCandidate) -> ProactiveCandidate:
        alpha = self._config.receptivity_smoothing
        prev = self._smoothed_receptivity.get(candidate.action, candidate.receptivity)
        smoothed_value = alpha * prev + (1 - alpha) * candidate.receptivity
        self._smoothed_receptivity[candidate.action] = smoothed_value
        return ProactiveCandidate(
            action=candidate.action,
            utility=candidate.utility,
            receptivity=smoothed_value,
            cost=candidate.cost,
            tau_offset_s=candidate.tau_offset_s,
            params=candidate.params,
        )
