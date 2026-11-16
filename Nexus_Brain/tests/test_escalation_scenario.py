"""
tests.test_escalation_scenario
=================================

Deliverable #4 (prompt_nexus_brain.md): "un scénario d'escalade F2→F3
(`force_release`) déclenchant un vrai replanning via Nexus Planner."

Mechanics under test (see nexus_functor/f2_local_adapter.py — untouched,
used as-is):
  cumulative_deviation = decay * previous + step_deviation
  if cumulative_deviation >= escalate_threshold (0.6): ESCALATE, call
  `f3.force_release()` (lifts F3's anti-oscillation hysteresis for one tick).

A single `FeedbackEvent(outcome=FAILURE, deviation=1.0)` is already >=
0.6, so one bad step is enough to escalate on the *next* `step()` call
(F2 reacts to the *previous* tick's feedback at the top of `step()`).

This test drives the real `ObjectiveRunner` (nexus_brain/integration/loop.py)
against the real, pyperplan-backed `NexusPlannerAdapter` and asserts:
  1. escalation is detected by the integration loop,
  2. `PlannerPort.generate_plans` is genuinely invoked again as a result
     (not just a re-ranking of the stale PlanSet) — verified by spying on
     the adapter's real subprocess-backed `generate_plans` call count.
"""

import _pathfix  # noqa: F401
import unittest

from nexus_functor.config import FunctorConfig
from nexus_functor.types import ExecutionState, FeedbackEvent, Objective, Outcome

from nexus_brain.adapters.planner_adapter import NexusPlannerAdapter
from nexus_brain.integration.loop import ObjectiveRunner


class _AlwaysFailsThenSucceedsExecutor:
    """Deterministic ExecutorPort double: FAILUREs (deviation=1.0) for the
    first `fail_for` calls, SUCCESS after — reliably crosses
    escalate_threshold=0.6 on the very first bad step, so we can observe
    the escalation -> replan chain without depending on Nexus Exec's own
    (separately-tested) termination modes."""

    def __init__(self, fail_for: int = 1):
        self.fail_for = fail_for
        self.calls = 0

    def execute_step(self, plan_id, step_id, params):
        self.calls += 1
        if self.calls <= self.fail_for:
            return FeedbackEvent(plan_id=plan_id, step_id=step_id, outcome=Outcome.FAILURE,
                                  observed_reward=0.0, deviation=1.0, notes="forced failure for test")
        return FeedbackEvent(plan_id=plan_id, step_id=step_id, outcome=Outcome.SUCCESS,
                              observed_reward=1.0, deviation=0.0, notes="ok")


class _CountingPlannerAdapter(NexusPlannerAdapter):
    """Wraps the real adapter, counting real invocations."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.call_count = 0

    def generate_plans(self, objective, context):
        self.call_count += 1
        return super().generate_plans(objective, context)


# Two disjoint routes so F1 has a genuinely different plan to switch to once
# F3's hysteresis is lifted by force_release().
_TWO_ROUTE_PROBLEM = {
    "init": ["at_start"],
    "goal": ["task_done"],
    "actions": [
        {"name": "route_a", "precond": ["at_start"], "add": ["task_done"], "del": [], "cost": 3, "expected_reward": 0.3},
        {"name": "route_b", "precond": ["at_start"], "add": ["task_done"], "del": [], "cost": 1, "expected_reward": 0.9},
    ],
}


class TestEscalationTriggersRealReplanning(unittest.TestCase):

    def test_f2_escalation_triggers_real_planner_call(self):
        planner = _CountingPlannerAdapter(max_plans=4)
        executor = _AlwaysFailsThenSucceedsExecutor(fail_for=1)
        config = FunctorConfig()  # escalate_threshold=0.6 (default) — 1.0 deviation crosses it

        runner = ObjectiveRunner(planner=planner, executor=executor, functor_config=config)
        objective = Objective(goal_id="escalation-demo", description="reach the goal")
        context = {"planning_problem": _TWO_ROUTE_PROBLEM}

        runner.add_objective(objective, context)
        self.assertEqual(planner.call_count, 1, "add_objective should fetch the initial PlanSet exactly once")

        # Tick 1: executes step 0 of the committed plan -> FAILURE (deviation=1.0).
        tick1 = runner.tick_all()["escalation-demo"]
        self.assertEqual(tick1.outcome, "FAILURE")
        self.assertFalse(tick1.escalated, "escalation is detected reacting to *this* feedback on the NEXT tick")

        # Tick 2: F2.adapt() reacts to tick 1's FAILURE at the top of step() ->
        # cumulative_deviation (1.0) >= escalate_threshold (0.6) -> ESCALATE ->
        # force_release() -> F3's hysteresis lifted -> F1 free to switch plans.
        ao = runner.get("escalation-demo")
        tick2 = runner.tick_all()["escalation-demo"]

        self.assertTrue(tick2.escalated, "integration loop must detect the escalation-driven plan switch")
        self.assertTrue(tick2.plan_switched, "F3 must have actually switched plans once released")
        self.assertEqual(
            planner.call_count, 2,
            "escalation must trigger a genuine second call to PlannerPort.generate_plans "
            "(real replanning), not just a re-rank of the stale PlanSet",
        )
        self.assertEqual(ao.replan_count, 1)

    def test_without_failure_no_spurious_escalation(self):
        """Control case: an executor that always succeeds should never
        report an escalation, and the planner should only ever be called
        once (at add_objective time)."""
        planner = _CountingPlannerAdapter(max_plans=4)
        executor = _AlwaysFailsThenSucceedsExecutor(fail_for=0)
        runner = ObjectiveRunner(planner=planner, executor=executor)
        objective = Objective(goal_id="control", description="reach the goal")
        runner.add_objective(objective, {"planning_problem": _TWO_ROUTE_PROBLEM})

        for _ in range(3):
            summary = runner.tick_all().get("control")
            if summary is None:
                break  # objective completed
            self.assertFalse(summary.escalated)

        self.assertEqual(planner.call_count, 1)


if __name__ == "__main__":
    unittest.main()
