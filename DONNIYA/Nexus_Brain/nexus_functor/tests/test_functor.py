"""
Run with:  python -m unittest discover -s tests -v
(from the nexus-functor/ root, with nexus_functor/ importable — i.e. run
from the repo root, or `pip install -e .`)
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_functor.config import F0Config, F1Config, F2Config, F3Config, FunctorConfig
from nexus_functor.f0_macro_strategy import F0MacroStrategySelector
from nexus_functor.f1_plan_selector import F1PlanSelector
from nexus_functor.f2_local_adapter import AdaptationAction, F2LocalAdapter
from nexus_functor.f3_stabilizer import F3Stabilizer
from nexus_functor.functor import NexusFunctor
from nexus_functor.testing import MockExecutor, MockHarness, MockPlanner, MockProactive
from nexus_functor.types import (
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


def _make_plan(plan_id: str, reward: float, cost: float, confidence: float, novelty: float = 0.0, n_steps: int = 3) -> Plan:
    steps = tuple(
        PlanStep(step_id=f"{plan_id}-s{i}", action=f"a{i}", expected_reward=reward / n_steps)
        for i in range(n_steps)
    )
    return Plan(plan_id=plan_id, steps=steps, estimated_cost=cost, estimated_reward=reward,
                confidence=confidence, novelty=novelty)


class TestTypes(unittest.TestCase):
    def test_empty_plan_set_rejected(self) -> None:
        with self.assertRaises(ValueError):
            PlanSet(objective_id="o1", plans=())

    def test_plan_set_lookup(self) -> None:
        p = _make_plan("p1", 1.0, 1.0, 0.5)
        ps = PlanSet(objective_id="o1", plans=(p,))
        self.assertIs(ps.by_id("p1"), p)
        self.assertIsNone(ps.by_id("missing"))


class TestF0MacroStrategy(unittest.TestCase):
    def test_safety_valve_forces_recover(self) -> None:
        f0 = F0MacroStrategySelector(F0Config(min_dwell_ticks=0))
        state = ExecutionState(objective_id="o1", cumulative_deviation=0.9)
        result = f0.select({"EXPLOIT": 1.0}, state)
        self.assertEqual(result, MacroStrategy.RECOVER)

    def test_min_dwell_blocks_immediate_change(self) -> None:
        f0 = F0MacroStrategySelector(F0Config(min_dwell_ticks=5))
        state = ExecutionState(objective_id="o1", cumulative_deviation=0.0)
        first = f0.select({"EXPLORE": 1.0}, state)
        # still within dwell window -> unchanged from the initial EXPLOIT default
        second = f0.select({"EXPLORE": 1.0}, state)
        self.assertEqual(first, second)

    def test_harness_trust_zero_uses_only_live_signal(self) -> None:
        f0 = F0MacroStrategySelector(F0Config(harness_trust=0.0, min_dwell_ticks=0))
        state = ExecutionState(objective_id="o1", cumulative_deviation=0.5)  # mid-range -> biases RECOVER-ish
        result = f0.select({"EXPLOIT": 1.0}, state)  # prior says EXPLOIT but trust=0 ignores it
        self.assertEqual(result, MacroStrategy.RECOVER)


class TestF1PlanSelector(unittest.TestCase):
    def test_exploit_prefers_high_confidence(self) -> None:
        f1 = F1PlanSelector(F1Config())
        safe = _make_plan("safe", reward=5.0, cost=2.0, confidence=0.95, novelty=0.0)
        risky = _make_plan("risky", reward=5.0, cost=2.0, confidence=0.2, novelty=0.9)
        ps = PlanSet(objective_id="o1", plans=(safe, risky))
        best = f1.best_plan(ps, MacroStrategy.EXPLOIT)
        self.assertEqual(best.plan.plan_id, "safe")

    def test_explore_prefers_novelty(self) -> None:
        f1 = F1PlanSelector(F1Config())
        safe = _make_plan("safe", reward=5.0, cost=2.0, confidence=0.95, novelty=0.0)
        risky = _make_plan("risky", reward=5.0, cost=2.0, confidence=0.2, novelty=0.9)
        ps = PlanSet(objective_id="o1", plans=(safe, risky))
        best = f1.best_plan(ps, MacroStrategy.EXPLORE)
        self.assertEqual(best.plan.plan_id, "risky")

    def test_proactive_below_receptivity_floor_ignored(self) -> None:
        f1 = F1PlanSelector(F1Config(min_receptivity=0.5))
        sig = ProactiveSignal(
            state_id="s1",
            candidates=(ProactiveCandidate(action="a", utility=1.0, receptivity=0.1, cost=0.0, tau_offset_s=0.0),),
        )
        choice = f1.score_proactive(sig)
        self.assertIsNone(choice.candidate)

    def test_proactive_negative_joint_score_ignored(self) -> None:
        f1 = F1PlanSelector(F1Config(proactive_cost_lambda=10.0))
        sig = ProactiveSignal(
            state_id="s1",
            candidates=(ProactiveCandidate(action="a", utility=0.5, receptivity=0.9, cost=1.0, tau_offset_s=0.0),),
        )
        choice = f1.score_proactive(sig)
        self.assertIsNone(choice.candidate)  # utility*recept (0.45) - 10*1.0 << 0

    def test_proactive_picks_best_joint_score(self) -> None:
        f1 = F1PlanSelector(F1Config(min_receptivity=0.0, proactive_cost_lambda=0.1))
        low = ProactiveCandidate(action="low", utility=0.3, receptivity=0.5, cost=0.0, tau_offset_s=0.0)
        high = ProactiveCandidate(action="high", utility=0.9, receptivity=0.8, cost=0.0, tau_offset_s=0.0)
        sig = ProactiveSignal(state_id="s1", candidates=(low, high))
        choice = f1.score_proactive(sig)
        self.assertEqual(choice.candidate.action, "high")


class TestF2LocalAdapter(unittest.TestCase):
    def test_on_track_continues(self) -> None:
        f2 = F2LocalAdapter(F2Config())
        plan = _make_plan("p", 3.0, 1.0, 0.8, n_steps=3)
        state = ExecutionState(objective_id="o1", committed_plan_id="p", step_index=0)
        fb = FeedbackEvent(plan_id="p", step_id="p-s0", outcome=Outcome.SUCCESS, deviation=0.02)
        result = f2.adapt(plan, state, fb)
        self.assertEqual(result.action, AdaptationAction.CONTINUE)
        self.assertEqual(result.next_step_index, 1)

    def test_moderate_deviation_patches(self) -> None:
        f2 = F2LocalAdapter(F2Config(local_patch_threshold=0.2, escalate_threshold=0.9))
        plan = _make_plan("p", 3.0, 1.0, 0.8, n_steps=3)
        state = ExecutionState(objective_id="o1", committed_plan_id="p", step_index=0, cumulative_deviation=0.0)
        fb = FeedbackEvent(plan_id="p", step_id="p-s0", outcome=Outcome.PARTIAL, deviation=0.5)
        result = f2.adapt(plan, state, fb)
        self.assertEqual(result.action, AdaptationAction.PATCH)
        self.assertTrue(result.next_step.params.get("_retry"))

    def test_severe_deviation_escalates(self) -> None:
        f2 = F2LocalAdapter(F2Config(escalate_threshold=0.5))
        plan = _make_plan("p", 3.0, 1.0, 0.8, n_steps=3)
        state = ExecutionState(objective_id="o1", committed_plan_id="p", step_index=0, cumulative_deviation=0.4)
        fb = FeedbackEvent(plan_id="p", step_id="p-s0", outcome=Outcome.FAILURE, deviation=0.5)
        result = f2.adapt(plan, state, fb)
        self.assertEqual(result.action, AdaptationAction.ESCALATE)

    def test_failure_does_not_advance_index(self) -> None:
        f2 = F2LocalAdapter(F2Config(escalate_threshold=0.99, local_patch_threshold=0.99))
        plan = _make_plan("p", 3.0, 1.0, 0.8, n_steps=3)
        state = ExecutionState(objective_id="o1", committed_plan_id="p", step_index=1, cumulative_deviation=0.0)
        fb = FeedbackEvent(plan_id="p", step_id="p-s1", outcome=Outcome.FAILURE, deviation=0.1)
        result = f2.adapt(plan, state, fb)
        self.assertEqual(result.next_step_index, 1)  # stayed, didn't advance to 2


class TestF3Stabilizer(unittest.TestCase):
    def test_first_call_commits_top_plan(self) -> None:
        f3 = F3Stabilizer(F3Config())
        from nexus_functor.f1_plan_selector import PlanScore
        ranked = [PlanScore(plan=_make_plan("p1", 1, 1, 1), score=0.9)]
        plan_id, switched = f3.stabilize_plan(ranked)
        self.assertEqual(plan_id, "p1")
        self.assertTrue(switched)

    def test_small_margin_does_not_switch(self) -> None:
        f3 = F3Stabilizer(F3Config(plan_switch_margin=0.5, plan_min_dwell_ticks=0))
        from nexus_functor.f1_plan_selector import PlanScore
        p1, p2 = _make_plan("p1", 1, 1, 1), _make_plan("p2", 1, 1, 1)
        f3.stabilize_plan([PlanScore(plan=p1, score=0.9)])
        # p2 barely better -> below margin -> should NOT switch
        plan_id, switched = f3.stabilize_plan([PlanScore(plan=p2, score=1.0), PlanScore(plan=p1, score=0.9)])
        self.assertEqual(plan_id, "p1")
        self.assertFalse(switched)

    def test_large_margin_after_dwell_switches(self) -> None:
        f3 = F3Stabilizer(F3Config(plan_switch_margin=0.05, plan_min_dwell_ticks=1))
        from nexus_functor.f1_plan_selector import PlanScore
        p1, p2 = _make_plan("p1", 1, 1, 1), _make_plan("p2", 1, 1, 1)
        f3.stabilize_plan([PlanScore(plan=p1, score=0.5)])  # tick 0: commits p1
        plan_id, switched = f3.stabilize_plan(
            [PlanScore(plan=p2, score=0.9), PlanScore(plan=p1, score=0.5)]
        )  # tick 1: dwell satisfied, margin cleared
        self.assertEqual(plan_id, "p2")
        self.assertTrue(switched)

    def test_force_release_allows_immediate_switch(self) -> None:
        f3 = F3Stabilizer(F3Config(plan_switch_margin=0.9, plan_min_dwell_ticks=99))
        from nexus_functor.f1_plan_selector import PlanScore
        p1, p2 = _make_plan("p1", 1, 1, 1), _make_plan("p2", 1, 1, 1)
        f3.stabilize_plan([PlanScore(plan=p1, score=0.5)])
        f3.force_release()
        plan_id, switched = f3.stabilize_plan([PlanScore(plan=p2, score=0.51), PlanScore(plan=p1, score=0.5)])
        self.assertEqual(plan_id, "p2")
        self.assertTrue(switched)

    def test_proactive_cooldown_blocks_rapid_refire(self) -> None:
        from nexus_functor.f1_plan_selector import ProactiveChoice
        f3 = F3Stabilizer(F3Config(proactive_cooldown_s=3600))  # effectively "never again in this test"
        cand = ProactiveCandidate(action="a", utility=1.0, receptivity=1.0, cost=0.0, tau_offset_s=0.0)
        first = f3.stabilize_proactive(ProactiveChoice(candidate=cand, joint_score=1.0))
        self.assertIsNotNone(first.candidate)
        second = f3.stabilize_proactive(ProactiveChoice(candidate=cand, joint_score=1.0))
        self.assertIsNone(second.candidate)  # cooldown blocks the immediate re-fire


class TestNexusFunctorIntegration(unittest.TestCase):
    def test_full_loop_runs_without_error_and_completes_plans(self) -> None:
        functor = NexusFunctor(
            harness=MockHarness(),
            planner=MockPlanner(n_plans=3, steps_per_plan=3, seed=42),
            proactive=MockProactive(seed=42),
        )
        executor = MockExecutor(failure_rate=0.15, seed=42)
        objective = Objective(goal_id="obj-1", description="integration test objective")
        state = ExecutionState(objective_id=objective.goal_id)

        decisions = []
        for _ in range(30):
            decision = functor.step(objective, plan_set=None, execution_state=state)
            decisions.append(decision)
            self.assertIn(decision.macro_strategy, list(MacroStrategy))
            self.assertIsInstance(decision.confidence, float)
            self.assertGreaterEqual(decision.confidence, 0.0)
            self.assertLessEqual(decision.confidence, 1.0)

            if decision.next_step is not None:
                event = executor.execute_step(
                    decision.selected_plan_id, decision.next_step.step_id, decision.next_step.params
                )
                functor.on_feedback(objective, decision, state, event)

        functor.flush_learning()
        # At least one plan switch should have happened across 30 noisy ticks.
        self.assertTrue(any(d.plan_switched for d in decisions))
        # Every decision must reference a real, known macro strategy and plan id.
        self.assertTrue(all(d.selected_plan_id for d in decisions))

    def test_step_without_plan_set_or_planner_raises(self) -> None:
        functor = NexusFunctor()  # no planner wired in
        objective = Objective(goal_id="obj-2", description="no planner")
        state = ExecutionState(objective_id=objective.goal_id)
        with self.assertRaises(ValueError):
            functor.step(objective, plan_set=None, execution_state=state)


if __name__ == "__main__":
    unittest.main()
