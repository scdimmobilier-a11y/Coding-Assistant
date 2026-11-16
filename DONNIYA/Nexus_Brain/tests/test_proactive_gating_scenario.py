"""
tests.test_proactive_gating_scenario
=======================================

Deliverable #4 (prompt_nexus_brain.md): "un scénario proactif où WHAT
propose mais WHEN/F1 bloque sous le plancher de réceptivité."

Mechanics under test:
  - `WhatEngine` (Nexus Proactive — WHAT) proposes a genuine candidate with
    positive utility from an activity signal (error detected in the IDE).
  - `WhenEngine` (Nexus Proactive — WHEN, real vendored
    `ThresholdDecisionEngine`) says "too soon" because the simulated last
    user message was only a few seconds ago (< `min_response_interval`),
    which `NexusProactiveAdapter` maps to a low receptivity (0.15).
  - `NexusProactiveAdapter.estimate()` does **not** filter anything itself
    — WHAT and WHEN stay independent, per prompt ("Elles ne se fusionnent
    pas entre elles directement"); it hands F1 the raw `ProactiveSignal`.
  - The real fusion + gating happens in `NexusFunctor.step()` -> F1's
    `score_proactive()`: since 0.15 < `min_receptivity` (0.25 default), the
    candidate is filtered out of `eligible` and `Decision.proactive_action`
    comes back `None` — the proposal existed, but F1 blocked it.
"""

import _pathfix  # noqa: F401
import time
import unittest

from nexus_functor.config import FunctorConfig
from nexus_functor.functor import NexusFunctor
from nexus_functor.types import ExecutionState, Objective, Plan, PlanSet, PlanStep

from nexus_brain.adapters.proactive_adapter import NexusProactiveAdapter


def _trivial_plan_set(objective_id: str) -> PlanSet:
    step = PlanStep(step_id="s1", action="noop", expected_duration_s=1.0, expected_reward=0.1)
    plan = Plan(plan_id=f"{objective_id}-p0", steps=(step,), estimated_cost=1.0,
                estimated_reward=0.1, confidence=0.9, novelty=0.0)
    return PlanSet(objective_id=objective_id, plans=(plan,))


class TestProactiveGatingScenario(unittest.TestCase):

    def test_what_proposes_but_when_blocks_under_receptivity_floor(self):
        adapter = NexusProactiveAdapter()

        context = {
            "activity": {"active_window": "VS Code", "error_detected": True},  # WHAT: strong signal
            "messages": [],
            "last_user_message_time": time.time() - 5,   # WHEN: user just spoke 5s ago
            "triggered_by_user_message": False,           # -> "too soon" per ThresholdDecisionEngine
        }

        # 1. WHAT genuinely proposes something with clearly positive utility.
        raw_signal = adapter.estimate("state1", context)
        self.assertTrue(any(c.action == "offer_error_diagnosis" for c in raw_signal.candidates),
                         "WHAT should propose a candidate from a clear error signal")
        error_candidate = next(c for c in raw_signal.candidates if c.action == "offer_error_diagnosis")
        self.assertGreater(error_candidate.utility, 0.0)

        # 2. WHEN genuinely says "not yet" -> low receptivity, independently of WHAT.
        self.assertLess(error_candidate.receptivity, FunctorConfig().f1.min_receptivity,
                         "WHEN's receptivity must be genuinely below F1's floor for this scenario")

        # 3. The *fusion and gating* happen in Nexus Functor's F1, not in the adapter.
        config = FunctorConfig()
        functor = NexusFunctor(config=config, proactive=adapter)
        objective = Objective(goal_id="proactive-demo", description="do the plan")
        plan_set = _trivial_plan_set("proactive-demo")
        exec_state = ExecutionState(objective_id="proactive-demo")

        decision = functor.step(objective, plan_set, exec_state, context)

        self.assertIsNone(decision.proactive_action,
                           "F1 must block the proposal: receptivity is under min_receptivity")
        self.assertIsNone(decision.proactive_tau_offset_s)

    def test_when_receptivity_high_enough_lets_what_through(self):
        """Control case: once WHEN says 'yes, now', the same WHAT proposal
        must actually clear F1 and come back as `decision.proactive_action`
        — proves the floor in the first test is really about receptivity,
        not some unrelated adapter bug swallowing all proposals."""
        adapter = NexusProactiveAdapter()
        context = {
            "activity": {"active_window": "VS Code", "error_detected": True},
            "messages": [{"role": "user", "content": "hi"}],
            "last_user_message_time": time.time() - 1,
            "triggered_by_user_message": True,  # -> "Immediate response to user message" -> True
        }
        raw_signal = adapter.estimate("state2", context)
        error_candidate = next(c for c in raw_signal.candidates if c.action == "offer_error_diagnosis")
        self.assertGreaterEqual(error_candidate.receptivity, FunctorConfig().f1.min_receptivity)

        config = FunctorConfig()
        functor = NexusFunctor(config=config, proactive=adapter)
        objective = Objective(goal_id="proactive-control", description="do the plan")
        plan_set = _trivial_plan_set("proactive-control")
        exec_state = ExecutionState(objective_id="proactive-control")

        decision = functor.step(objective, plan_set, exec_state, context)
        self.assertEqual(decision.proactive_action, "offer_error_diagnosis")


if __name__ == "__main__":
    unittest.main()
