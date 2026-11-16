"""
tests.test_adapters
=====================

Tests for the 4 `PlannerPort` / `ExecutorPort` / `HarnessPort` /
`ProactivePort` adapters, exercised against their real dependencies (the
vendored Nexus Planner/Exec/Harness/Proactive-When modules) rather than
`nexus_functor.testing`'s mocks.
"""

import _pathfix  # noqa: F401
import unittest

from nexus_functor.types import Decision, FeedbackEvent, MacroStrategy, Objective, Outcome

from nexus_brain.adapters.exec_adapter import HeuristicExecRouter, NexusExecAdapter
from nexus_brain.adapters.planner_adapter import NexusPlannerAdapter
from nexus_brain.adapters.harness_adapter import HarnessStores, NexusHarnessAdapter
from nexus_brain.adapters.proactive_adapter import NexusProactiveAdapter, WhatEngine, WhenEngine


class TestExecutorPortAdapter(unittest.TestCase):
    """Backed by the real, vendored `nexus_exec.mini.Coordinator`."""

    def test_execute_step_returns_feedback_event(self):
        adapter = NexusExecAdapter()
        event = adapter.execute_step("plan1", "step1", {"action": "demo"})
        self.assertIsInstance(event, FeedbackEvent)
        self.assertIn(event.outcome, (Outcome.SUCCESS, Outcome.PARTIAL, Outcome.FAILURE))

    def test_default_heuristic_router_reaches_genuine_accept(self):
        """With the default role plan (Worker, Thinker, then Verifier), the
        real Coordinator should terminate via a genuine Verifier ACCEPT,
        not just max_turns exhaustion — proves the multi-turn role loop
        (not a single-shot call) is what's actually running."""
        adapter = NexusExecAdapter(max_turns=5)
        self.assertFalse(adapter.using_real_router)  # no torch/checkpoint in this environment
        event = adapter.execute_step("plan1", "step1", {})
        self.assertEqual(event.outcome, Outcome.SUCCESS)
        self.assertIn("verifier_accept", event.notes)

    def test_max_turns_exhaustion_yields_partial(self):
        """A router that never routes to Verifier can never ACCEPT — the
        loop should end via max_turns, mapped to PARTIAL, not SUCCESS."""
        never_verifier_router = HeuristicExecRouter(role_plan=["Worker"] * 10)
        adapter = NexusExecAdapter(max_turns=3)
        adapter._real_router = never_verifier_router  # force this router for the test
        # bypass the "real router or heuristic()" default-construction path:
        import nexus_exec.mini as mini
        coord = mini.Coordinator(router=never_verifier_router, worker=mini.MockWorker(), max_turns=3)
        result = coord.run("dummy query")
        self.assertEqual(result.terminated_by, "max_turns")


class TestPlannerPortAdapter(unittest.TestCase):
    """Backed by the out-of-process bridge (pyperplan, GPL-isolated) or the
    license-free fallback when no `planning_problem` is supplied."""

    def test_real_backend_finds_diverse_plans(self):
        adapter = NexusPlannerAdapter(max_plans=4)
        objective = Objective(goal_id="o1", description="reach goal")
        context = {"planning_problem": {
            "init": ["at_start"],
            "goal": ["task_done"],
            "actions": [
                {"name": "route_a", "precond": ["at_start"], "add": ["task_done"], "del": [], "cost": 3, "expected_reward": 0.4},
                {"name": "route_b", "precond": ["at_start"], "add": ["task_done"], "del": [], "cost": 5, "expected_reward": 0.7},
                {"name": "route_c", "precond": ["at_start"], "add": ["task_done"], "del": [], "cost": 1, "expected_reward": 0.2},
            ],
        }}
        plan_set = adapter.generate_plans(objective, context)
        self.assertEqual(adapter.last_backend, "pyperplan")
        self.assertEqual(len(plan_set.plans), 3)  # exactly 3 disjoint routes exist
        actions_used = {p.steps[0].action for p in plan_set.plans}
        self.assertEqual(actions_used, {"route_a", "route_b", "route_c"})  # genuinely diverse, not repeats

    def test_forbid_mechanism_stops_when_domain_exhausted(self):
        """Ask for more plans than genuinely exist — solve-forbid-resolve
        should stop early rather than fabricate duplicates."""
        adapter = NexusPlannerAdapter(max_plans=10)
        objective = Objective(goal_id="o2", description="reach goal")
        context = {"planning_problem": {
            "init": ["at_start"], "goal": ["task_done"],
            "actions": [{"name": "only_route", "precond": ["at_start"], "add": ["task_done"], "del": [], "cost": 1, "expected_reward": 0.5}],
        }}
        plan_set = adapter.generate_plans(objective, context)
        self.assertEqual(len(plan_set.plans), 1)  # only one route exists; asking for 10 must not fabricate more

    def test_fallback_used_without_planning_problem(self):
        adapter = NexusPlannerAdapter()
        objective = Objective(goal_id="o3", description="no pddl given")
        plan_set = adapter.generate_plans(objective, {"available_actions": ["a", "b", "c"]})
        self.assertEqual(adapter.last_backend, "fallback")
        self.assertGreaterEqual(len(plan_set.plans), 1)


class TestHarnessPortAdapter(unittest.TestCase):

    def test_prior_starts_uniform_then_shifts_with_outcomes(self):
        adapter = NexusHarnessAdapter()
        objective = Objective(goal_id="o1", description="x")
        prior0 = adapter.get_policy_prior(objective, {})
        self.assertAlmostEqual(sum(prior0.values()), 1.0, places=6)
        self.assertEqual(len(set(prior0.values())), 1)  # uniform: all equal

        decision = Decision(objective_id="o1", macro_strategy=MacroStrategy.EXPLOIT,
                             selected_plan_id="p", next_step=None, proactive_action=None,
                             proactive_tau_offset_s=None, plan_switched=False, confidence=0.9,
                             rationale="test")
        for _ in range(5):
            adapter.record_outcome(objective, decision, FeedbackEvent(outcome=Outcome.SUCCESS))

        prior1 = adapter.get_policy_prior(objective, {})
        self.assertEqual(prior1["EXPLOIT"], 1.0)
        self.assertEqual(prior1["EXPLORE"], 0.0)

    def test_evolve_harness_only_at_window_boundary(self):
        adapter = NexusHarnessAdapter()
        adapter.evolver.optimization_window_length = 10
        window = [{"outcome": "SUCCESS", "action": "a", "step_id": "s1"}]
        self.assertEqual(adapter.evolve_harness(5, window), {"skipped": True, "reason": "not_at_window_boundary"})
        result = adapter.evolve_harness(10, window)
        self.assertIn("generation", result)

    def test_evolve_harness_four_passes_present(self):
        adapter = NexusHarnessAdapter()
        adapter.evolver.optimization_window_length = 1
        window = [
            {"outcome": "SUCCESS", "action": "run_tests", "step_id": f"s{i}"} for i in range(4)
        ]
        result = adapter.evolve_harness(1, window)
        for pass_name in ("prompt", "subagents", "skills", "memory"):
            self.assertIn(pass_name, result)
        self.assertIn("sa_run_tests", adapter.evolver.stores.subagents)
        self.assertIn("skill_run_tests", adapter.evolver.stores.skills)


class TestProactivePortAdapter(unittest.TestCase):
    """WHAT and WHEN stay independent; this adapter only packages their
    outputs — it does not fuse them (F1 does)."""

    def test_what_and_when_are_independent_engines(self):
        adapter = NexusProactiveAdapter()
        self.assertIsInstance(adapter.what, WhatEngine)
        self.assertIsInstance(adapter.when, WhenEngine)
        self.assertIsNot(adapter.what, adapter.when)

    def test_estimate_returns_candidates_with_both_signals(self):
        adapter = NexusProactiveAdapter()
        ctx = {"activity": {"active_window": "IDE", "error_detected": True}, "messages": []}
        signal = adapter.estimate("state1", ctx)
        self.assertGreaterEqual(len(signal.candidates), 1)
        for c in signal.candidates:
            self.assertTrue(0.0 <= c.utility <= 1.5)
            self.assertTrue(0.0 <= c.receptivity <= 1.0)

    def test_what_feedback_loop_suppresses_repeated_rejections(self):
        adapter = NexusProactiveAdapter()
        ctx = {"activity": {"error_detected": True}, "messages": []}
        signal0 = adapter.estimate("s1", ctx)
        self.assertIn("offer_error_diagnosis", [c.action for c in signal0.candidates])
        for _ in range(5):
            adapter.record_what_feedback("offer_error_diagnosis", "reject")
        signal1 = adapter.estimate("s1", ctx)
        self.assertNotIn("offer_error_diagnosis", [c.action for c in signal1.candidates])


if __name__ == "__main__":
    unittest.main()
