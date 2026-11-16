"""
tests.test_integration_loop
==============================

End-to-end smoke test for `ObjectiveRunner` (deliverable #3): drives
`NexusFunctor.step()`/`on_feedback()` continuously, Nexus Exec genuinely
invoked, multiple concurrent objectives each with their own state.
"""

import _pathfix  # noqa: F401
import unittest

from nexus_functor.types import Objective

from nexus_brain.adapters.exec_adapter import NexusExecAdapter
from nexus_brain.adapters.harness_adapter import NexusHarnessAdapter
from nexus_brain.adapters.planner_adapter import NexusPlannerAdapter
from nexus_brain.adapters.proactive_adapter import NexusProactiveAdapter
from nexus_brain.integration.loop import ObjectiveRunner


class TestObjectiveRunnerEndToEnd(unittest.TestCase):

    def _runner(self) -> ObjectiveRunner:
        return ObjectiveRunner(
            planner=NexusPlannerAdapter(),
            executor=NexusExecAdapter(),
            harness=NexusHarnessAdapter(),
            proactive=NexusProactiveAdapter(),
        )

    def test_single_objective_runs_to_completion(self):
        runner = self._runner()
        objective = Objective(goal_id="single", description="ship it")
        context = {"planning_problem": {
            "init": ["at_start"], "goal": ["task_done"],
            "actions": [{"name": "just_do_it", "precond": ["at_start"], "add": ["task_done"],
                         "del": [], "cost": 1, "expected_reward": 0.5}],
        }}
        runner.add_objective(objective, context)

        history = runner.run_forever(max_ticks=5)
        self.assertNotIn("single", runner.active_goal_ids)  # completed and removed
        statuses = [tick["single"].status for tick in history if "single" in tick]
        self.assertEqual(statuses[-1], "complete")
        self.assertEqual(statuses[0], "ticked")

    def test_get_completed_retains_the_final_summary_after_removal(self):
        """D2 (MISSION_couple_leon_nexusbrain.md, 'Delivery callback'):
        the whole point of `get_completed` is that the result is still
        there *after* the objective has vanished from `active_goal_ids`."""
        runner = self._runner()
        objective = Objective(goal_id="deliverable", description="ship it")
        context = {"planning_problem": {
            "init": ["at_start"], "goal": ["task_done"],
            "actions": [{"name": "just_do_it", "precond": ["at_start"], "add": ["task_done"],
                         "del": [], "cost": 1, "expected_reward": 0.5}],
        }}
        runner.add_objective(objective, context)
        runner.run_forever(max_ticks=5)

        self.assertIsNone(runner.get_completed("no-such-goal"))
        completed = runner.get_completed("deliverable")
        self.assertIsNotNone(completed)
        self.assertEqual(completed.status, "complete")
        self.assertEqual(completed.goal_id, "deliverable")

    def test_ticked_and_complete_summaries_carry_the_executor_notes(self):
        """Needed for a delivery callback to show anything meaningful —
        see TickSummary.notes' own docstring."""
        runner = self._runner()
        objective = Objective(goal_id="notes-check", description="ship it")
        context = {"planning_problem": {
            "init": ["at_start"], "goal": ["task_done"],
            "actions": [{"name": "just_do_it", "precond": ["at_start"], "add": ["task_done"],
                         "del": [], "cost": 1, "expected_reward": 0.5}],
        }}
        runner.add_objective(objective, context)
        history = runner.run_forever(max_ticks=5)

        ticked = next(tick["notes-check"] for tick in history if "notes-check" in tick and tick["notes-check"].status == "ticked")
        self.assertIsNotNone(ticked.notes)

        completed = runner.get_completed("notes-check")
        self.assertIsNotNone(completed.notes)  # carried from the last FeedbackEvent

    def test_multiple_concurrent_objectives_have_independent_state(self):
        runner = self._runner()
        ctx_a = {"planning_problem": {
            "init": ["a0"], "goal": ["a1"],
            "actions": [{"name": "finish_a", "precond": ["a0"], "add": ["a1"], "del": [], "cost": 1, "expected_reward": 0.5}],
        }}
        ctx_b = {"planning_problem": {
            "init": ["b0"], "goal": ["b2"],
            "actions": [
                {"name": "b_step1", "precond": ["b0"], "add": ["b1"], "del": [], "cost": 1, "expected_reward": 0.4},
                {"name": "b_step2", "precond": ["b1"], "add": ["b2"], "del": [], "cost": 1, "expected_reward": 0.4},
            ],
        }}
        runner.add_objective(Objective(goal_id="obj_a", description="A"), ctx_a)
        runner.add_objective(Objective(goal_id="obj_b", description="B"), ctx_b)
        self.assertEqual(set(runner.active_goal_ids), {"obj_a", "obj_b"})

        # obj_a (1 step) should complete before obj_b (2 steps) — proves
        # each objective's ExecutionState/tick progress is independent.
        tick1 = runner.tick_all()
        self.assertEqual(tick1["obj_a"].status, "ticked")
        self.assertEqual(tick1["obj_b"].status, "ticked")

        tick2 = runner.tick_all()
        self.assertEqual(tick2["obj_a"].status, "complete")
        self.assertEqual(tick2["obj_b"].status, "ticked")  # obj_b still has one step left
        self.assertNotIn("obj_a", runner.active_goal_ids)
        self.assertIn("obj_b", runner.active_goal_ids)

        tick3 = runner.tick_all()
        self.assertEqual(tick3["obj_b"].status, "complete")
        self.assertEqual(runner.active_goal_ids, [])

    def test_feedback_is_actually_routed_to_harness_slow_loop(self):
        """After enough successful outcomes, the harness prior for this
        objective should shift away from uniform — proves feedback really
        reaches Nexus Harness's `record_outcome`, not just F2 locally."""
        harness = NexusHarnessAdapter()
        runner = ObjectiveRunner(
            planner=NexusPlannerAdapter(), executor=NexusExecAdapter(), harness=harness,
        )
        objective = Objective(goal_id="learning-demo", description="repeat success")
        context = {"planning_problem": {
            "init": ["s0"], "goal": ["s1"],
            "actions": [{"name": "reliable_step", "precond": ["s0"], "add": ["s1"], "del": [], "cost": 1, "expected_reward": 0.6}],
        }}
        prior_before = harness.get_policy_prior(objective, context)
        self.assertEqual(len(set(prior_before.values())), 1)  # uniform, no history yet

        runner.add_objective(objective, context)
        runner.run_forever(max_ticks=3)

        prior_after = harness.get_policy_prior(objective, context)
        self.assertNotEqual(prior_before, prior_after, "harness prior must shift once real feedback lands")


if __name__ == "__main__":
    unittest.main()
