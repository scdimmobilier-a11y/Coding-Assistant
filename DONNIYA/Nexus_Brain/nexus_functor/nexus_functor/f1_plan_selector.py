"""
nexus_functor.f1_plan_selector
================================

F1 — the level that actually chooses things: which candidate plan P_i to
run, and (fused into the same pass) which proactive (action, timing) pair
— if any — is worth surfacing right now.

Two independent scoring problems, both conditioned on F0's macro-strategy:

1. Plan scoring: multi-criteria weighted sum over each Plan in the
   PlanSet, weights taken from F1Config.plan_weights[macro_strategy].

2. Proactive joint scoring: for each ProactiveCandidate (a, tau) coming
   out of Nexus Proactive's fused WHAT+WHEN estimate,
       J(a, tau) = utility(a) * receptivity(tau) - lambda * cost(a, tau)
   and we take argmax over candidates that clear the minimum-receptivity
   floor. This mirrors the joint optimization the architecture doc
   describes for pi(s_t, h_t) -> (a, tau) — F1 is where WHAT and WHEN
   actually get combined into one decision, rather than resolved
   separately by two competing heuristics.

Note: F1 proposes; it does not commit. F3 is the layer that decides
whether to actually act on F1's proposal or hold the previous choice
(hysteresis). This separation is deliberate — F1 should be free to
compute "what looks best right now" without worrying about oscillation;
that's F3's one job.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .config import F1Config
from .types import MacroStrategy, Plan, PlanSet, ProactiveCandidate, ProactiveSignal


@dataclass(frozen=True)
class PlanScore:
    plan: Plan
    score: float


@dataclass(frozen=True)
class ProactiveChoice:
    candidate: Optional[ProactiveCandidate]
    joint_score: float


class F1PlanSelector:
    def __init__(self, config: F1Config) -> None:
        self._config = config

    # -- plan selection -----------------------------------------------

    def score_plans(self, plan_set: PlanSet, macro_strategy: MacroStrategy) -> list[PlanScore]:
        weights = self._config.plan_weights[macro_strategy.name]
        plans = plan_set.plans

        max_reward = max((p.estimated_reward for p in plans), default=1.0) or 1.0
        max_cost = max((p.estimated_cost for p in plans), default=1.0) or 1.0

        scored = []
        for plan in plans:
            reward_norm = plan.estimated_reward / max_reward
            cost_norm = plan.estimated_cost / max_cost
            score = (
                weights["reward"] * reward_norm
                + weights["confidence"] * plan.confidence
                + weights["novelty"] * plan.novelty
                - weights["cost"] * cost_norm
            )
            scored.append(PlanScore(plan=plan, score=score))

        scored.sort(key=lambda ps: ps.score, reverse=True)
        return scored

    def best_plan(self, plan_set: PlanSet, macro_strategy: MacroStrategy) -> PlanScore:
        return self.score_plans(plan_set, macro_strategy)[0]

    # -- joint proactive (a*, tau*) selection --------------------------

    def score_proactive(self, signal: Optional[ProactiveSignal]) -> ProactiveChoice:
        if signal is None or not signal.candidates:
            return ProactiveChoice(candidate=None, joint_score=0.0)

        eligible = [c for c in signal.candidates if c.receptivity >= self._config.min_receptivity]
        if not eligible:
            return ProactiveChoice(candidate=None, joint_score=0.0)

        best: Optional[ProactiveCandidate] = None
        best_score = float("-inf")
        for c in eligible:
            j = c.utility * c.receptivity - self._config.proactive_cost_lambda * c.cost
            if j > best_score:
                best, best_score = c, j

        # Only worth surfacing if the joint score is actually positive —
        # a technically-best-of-a-bad-lot candidate with negative J means
        # "better to do nothing right now".
        if best_score <= 0.0:
            return ProactiveChoice(candidate=None, joint_score=best_score)

        return ProactiveChoice(candidate=best, joint_score=best_score)
