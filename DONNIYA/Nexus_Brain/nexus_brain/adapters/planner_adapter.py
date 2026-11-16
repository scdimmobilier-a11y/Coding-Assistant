"""
nexus_brain.adapters.planner_adapter
======================================

`PlannerPort` adapter for Nexus Planner (PDDLStream-diverse).

**License isolation** (non-negotiable per prompt_nexus_brain.md): PDDLStream
is GPLv3, so Nexus Planner must stay **out-of-process**, spoken to only
through `PlannerPort`, never imported inline here or anywhere else in Nexus
Brain / Nexus Functor. This adapter only ever shells out to
`vendor/nexus_planner/nexus_brain_bridge.py` via `subprocess` — it never
does `import nexus_planner`.

The real mechanism this preserves is *solve -> forbid its actions -> resolve
-> iterate to max_plans* (PDDLStream's `diverse_from_task`). See the bridge
script's own docstring for the three-tier backend it tries (real
PDDLStream+FastDownward, then pyperplan as a real-but-substitute GPL STRIPS
solver, then "unavailable").

`context` is expected to optionally carry a declarative STRIPS problem under
`context["planning_problem"]` (see bridge docstring for the schema: init /
goal / actions with precond+add+del+cost). Without one, this adapter falls
back to a tiny, license-free, non-PDDL diverse-plan heuristic so the rest of
Nexus Brain still has *something* to select among (documented clearly as a
fallback, not real STRIPS planning).
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from nexus_functor.types import Plan, PlanSet, PlanStep, Objective

_BRIDGE_SCRIPT = Path(__file__).resolve().parents[2] / "vendor" / "nexus_planner" / "nexus_brain_bridge.py"


class NexusPlannerAdapter:
    """`PlannerPort` implementation: subprocess bridge to Nexus Planner."""

    def __init__(self, max_plans: int = 4, timeout_s: float = 20.0):
        self._max_plans = max_plans
        self._timeout_s = timeout_s
        self.last_backend: str | None = None  # surfaced for tests/observability

    def generate_plans(self, objective: Objective, context: dict[str, Any]) -> PlanSet:
        problem = context.get("planning_problem")

        if problem is not None:
            plans = self._via_bridge(problem)
            if plans:
                return self._to_plan_set(objective, plans)
            # bridge ran but found nothing usable (or errored) — fall through

        return self._fallback_plan_set(objective, context)

    # ------------------------------------------------------------------ #

    def _via_bridge(self, problem: dict[str, Any]) -> list[dict]:
        request = json.dumps({"max_plans": self._max_plans, "problem": problem})
        try:
            proc = subprocess.run(
                [sys.executable, str(_BRIDGE_SCRIPT)],
                input=request, capture_output=True, text=True, timeout=self._timeout_s,
            )
        except (subprocess.TimeoutExpired, OSError):
            self.last_backend = "unavailable"
            return []

        if proc.returncode != 0 or not proc.stdout.strip():
            self.last_backend = "unavailable"
            return []

        try:
            response = json.loads(proc.stdout)
        except json.JSONDecodeError:
            self.last_backend = "unavailable"
            return []

        self.last_backend = response.get("backend", "unavailable")
        return response.get("plans", [])

    def _to_plan_set(self, objective: Objective, raw_plans: list[dict]) -> PlanSet:
        plans = []
        for i, rp in enumerate(raw_plans):
            steps = tuple(
                PlanStep(
                    step_id=f"{objective.goal_id}-s{j}",
                    action=s["action"],
                    params=s.get("params", {}),
                    expected_duration_s=s.get("expected_duration_s", 0.0),
                    expected_reward=s.get("expected_reward", 0.0),
                )
                for j, s in enumerate(rp["steps"])
            )
            total_reward = sum(s.expected_reward for s in steps)
            plans.append(Plan(
                plan_id=f"{objective.goal_id}-plan{i}-{uuid.uuid4().hex[:6]}",
                steps=steps,
                estimated_cost=float(rp.get("cost", len(steps))),
                estimated_reward=total_reward,
                confidence=0.7,  # a real solver found this, but no learned confidence signal yet
                novelty=float(rp.get("novelty", i / max(1, len(raw_plans) - 1) if len(raw_plans) > 1 else 0.0)),
                metadata={"backend": self.last_backend or "unknown"},
            ))
        return PlanSet(objective_id=objective.goal_id, plans=tuple(plans))

    def _fallback_plan_set(self, objective: Objective, context: dict[str, Any]) -> PlanSet:
        """License-free, non-PDDL fallback used only when no
        `planning_problem` was supplied, or the bridge is unavailable
        (no pyperplan installed and no compiled Fast Downward). Produces a
        handful of differently-ordered/-sized candidate plans from
        `context["available_actions"]` (or a single generic step if even
        that is absent), so F1 always has *something* to score — clearly
        weaker than real diverse planning, but keeps the system usable
        out of the box."""
        self.last_backend = "fallback"
        actions: list[str] = context.get("available_actions") or [f"advance:{objective.goal_id}"]

        plans = []
        variants = [actions, list(reversed(actions)), actions[:1]] if len(actions) > 1 else [actions]
        seen: set[tuple[str, ...]] = set()
        for i, variant in enumerate(variants):
            key = tuple(variant)
            if key in seen:
                continue
            seen.add(key)
            steps = tuple(
                PlanStep(step_id=f"{objective.goal_id}-fb{i}-s{j}", action=a,
                         expected_duration_s=1.0, expected_reward=0.3)
                for j, a in enumerate(variant)
            )
            plans.append(Plan(
                plan_id=f"{objective.goal_id}-fallback{i}-{uuid.uuid4().hex[:6]}",
                steps=steps,
                estimated_cost=float(len(steps)),
                estimated_reward=0.3 * len(steps),
                confidence=0.3,  # heuristic, not a real solver — deliberately low
                novelty=i / max(1, len(variants) - 1) if len(variants) > 1 else 0.0,
                metadata={"backend": "fallback"},
            ))
        return PlanSet(objective_id=objective.goal_id, plans=tuple(plans))
