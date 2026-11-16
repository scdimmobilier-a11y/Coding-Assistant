#!/usr/bin/env python3
"""
Runnable, self-contained demo of NexusFunctor driving a simulated
objective for 25 ticks, using the stdlib mocks in nexus_functor.testing
for the other four modules (Planner / Exec / Harness / Proactive).

Run:
    python3 examples/demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nexus_functor import ExecutionState, NexusFunctor, Objective
from nexus_functor.testing import MockExecutor, MockHarness, MockPlanner, MockProactive


def main() -> None:
    functor = NexusFunctor(
        harness=MockHarness(),
        planner=MockPlanner(n_plans=4, steps_per_plan=5, seed=7),
        proactive=MockProactive(seed=7),
    )
    executor = MockExecutor(failure_rate=0.12, seed=7)

    objective = Objective(
        goal_id="demo-objective",
        description="Ship a working demo of the hierarchical dynamic functor",
    )
    state = ExecutionState(objective_id=objective.goal_id)

    print(f"Objective: {objective.description}\n")
    header = f"{'tick':>4}  {'macro':<9}  {'plan':<20}  {'switch':<6}  {'conf':>5}  {'proactive':<14}  reason"
    print(header)
    print("-" * len(header))

    for _ in range(25):
        decision = functor.step(objective, plan_set=None, execution_state=state)

        proactive_str = "-"
        if decision.proactive_action:
            proactive_str = f"{decision.proactive_action}@+{decision.proactive_tau_offset_s:.1f}s"

        print(
            f"{state.tick:>4}  {decision.macro_strategy.name:<9}  "
            f"{decision.selected_plan_id:<20}  {str(decision.plan_switched):<6}  "
            f"{decision.confidence:>5.2f}  {proactive_str:<14}  {decision.rationale}"
        )

        if decision.next_step is None:
            print("\n  -> plan complete, stopping demo.\n")
            break

        event = executor.execute_step(
            decision.selected_plan_id, decision.next_step.step_id, decision.next_step.params
        )
        functor.on_feedback(objective, decision, state, event)

    functor.flush_learning()
    print(f"Final cumulative deviation: {state.cumulative_deviation:.3f}")
    print(f"Steps of history recorded: {len(state.history)}")


if __name__ == "__main__":
    main()
