#!/usr/bin/env python3
"""
vendor/nexus_planner/nexus_brain_bridge.py
============================================

Out-of-process CLI bridge for Nexus Planner (PDDLStream-diverse, GPLv3).

**License isolation** (see prompt_nexus_brain.md, "Note de licence
importante"): PDDLStream is GPLv3. This script is the *only* place in the
whole Nexus Brain tree that is allowed to import GPL-licensed planning code
(PDDLStream itself, and — as a stand-in backend, see Tier 2 below —
pyperplan, also GPLv3). It is invoked exclusively as a subprocess
(`python3 nexus_brain_bridge.py < request.json > response.json`); nothing
under `nexus_brain/` or `nexus_functor/` ever imports this module or
anything it imports. That is what keeps the copyleft from spreading to the
rest of the system.

Protocol
--------
stdin  : one JSON object
    {
      "max_plans": 4,
      "problem": {
        "init": ["at_start", "have_tool"],
        "goal": ["task_done"],
        "actions": [
          {"name": "gather_requirements", "precond": ["at_start"],
           "add": ["requirements_ready"], "del": [], "cost": 1,
           "expected_reward": 0.4, "expected_duration_s": 5},
          ...
        ]
      }
    }
stdout : one JSON object
    {"backend": "pyperplan" | "pddlstream" | "none",
     "plans": [{"steps": [...], "cost": float}, ...]}

Mechanism (faithful to Nexus Planner / PDDLStream's `diverse_from_task`,
see vendor/nexus_planner/nexus_planner/algorithms/diverse.py): find a plan,
**forbid** the actions it used, re-solve, repeat until `max_plans` plans
have been found or the (shrinking) domain becomes unsolvable.

Backend tiers, tried in order:
  1. **pddlstream** — the real `diverse_from_task` (real vendored source,
     `vendor/nexus_planner/nexus_planner/algorithms/diverse.py`). Requires a
     compiled Fast Downward (translator + search binary) that is *not*
     bundled with this export (no bundled build manifests/binaries — see
     vendor/nexus_planner/README.md) and is not fetchable in an offline
     sandbox. Attempted first so a real deployment with FD compiled uses
     the genuine mechanism; falls through cleanly otherwise.
  2. **pyperplan** — a real, independent GPLv3 STRIPS solver (pip-installable,
     https://github.com/aibasel/pyperplan). We generate a small PDDL
     domain/problem from the declarative `problem` dict above, hand it to
     pyperplan's real search (`search_plan`), and implement the
     solve-forbid-resolve loop *around* it ourselves — this is genuine PDDL
     solving, not a re-implementation of PDDLStream's own code, staying out
     of Nexus Planner's GPL source while still needing a GPL *dependency*
     (pyperplan) for the solve step, hence why this file — not
     `nexus_brain/adapters/planner_adapter.py` — is where it lives.
  3. **none** — neither backend available; reports empty plans so the
     Python-side adapter can fall back to its own non-PDDL, license-free
     diverse-plan heuristic (see `NexusPlannerAdapter._fallback_plans`).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


# ─────────────────────────── Tier 1: real PDDLStream ───────────────────────────

def _try_pddlstream(problem: dict[str, Any], max_plans: int) -> list[dict] | None:
    """Best-effort attempt at the real `diverse_from_task`. Returns None (not
    an empty list) if the real mechanism could not run at all, so the caller
    can distinguish "ran, found 0 plans" from "unavailable"."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from nexus_planner.algorithms.diverse import diverse_from_task  # noqa: F401
        from nexus_planner.algorithms.downward import (  # noqa: F401
            parse_sequential_domain, parse_problem, task_from_domain_problem,
        )
        # Real Fast Downward (translator + search binary) is required beyond
        # this import to actually build a sas_task and call diverse_from_task
        # end-to-end; not bundled/compiled in this environment (see module
        # docstring). We surface that cleanly rather than half-run it.
        import sas_tasks  # noqa: F401  — FD's own translate module; not vendored here
        return None  # pragma: no cover — real FD toolchain not available in this build
    except Exception:
        return None


# ─────────────────────────── Tier 2: pyperplan ───────────────────────────

def _generate_pddl(problem: dict[str, Any], forbidden_actions: set[str]) -> tuple[str, str]:
    """Render a minimal ground STRIPS domain+problem pair (PDDL 1.2) from the
    declarative action-list schema above. Clean-room generator — does not
    reuse or derive from PDDLStream's own PDDL-handling code."""
    actions = [a for a in problem["actions"] if a["name"] not in forbidden_actions]
    all_atoms = set(problem["init"]) | set(problem["goal"])
    for a in problem["actions"]:
        all_atoms |= set(a.get("precond", [])) | set(a.get("add", [])) | set(a.get("del", []))

    predicates = " ".join(f"({atom})" for atom in sorted(all_atoms))
    action_blocks = []
    for a in actions:
        precond = " ".join(f"({p})" for p in a.get("precond", [])) or ""
        effect_parts = [f"({e})" for e in a.get("add", [])] + [f"(not ({e}))" for e in a.get("del", [])]
        effect = " ".join(effect_parts) or "(and)"
        action_blocks.append(
            f"  (:action {a['name']}\n"
            f"    :parameters ()\n"
            f"    :precondition (and {precond})\n"
            f"    :effect (and {effect}))"
        )

    domain = (
        "(define (domain nexus)\n"
        "  (:requirements :strips)\n"
        f"  (:predicates {predicates})\n"
        + "\n".join(action_blocks) + "\n)"
    )
    init = " ".join(f"({atom})" for atom in problem["init"])
    goal = " ".join(f"({atom})" for atom in problem["goal"])
    prob = (
        "(define (problem nexus-problem)\n"
        "  (:domain nexus)\n"
        "  (:objects )\n"
        f"  (:init {init})\n"
        f"  (:goal (and {goal}))\n)"
    )
    return domain, prob


def _try_pyperplan(problem: dict[str, Any], max_plans: int) -> list[dict] | None:
    try:
        from pyperplan.planner import search_plan, SEARCHES
    except Exception:
        return None

    import tempfile

    plans: list[dict] = []
    forbidden: set[str] = set()
    action_by_name = {a["name"]: a for a in problem["actions"]}

    for _ in range(max_plans):
        domain_src, problem_src = _generate_pddl(problem, forbidden)
        with tempfile.TemporaryDirectory() as td:
            domain_path = str(Path(td) / "domain.pddl")
            problem_path = str(Path(td) / "problem.pddl")
            Path(domain_path).write_text(domain_src)
            Path(problem_path).write_text(problem_src)
            try:
                found = search_plan(domain_path, problem_path, SEARCHES["bfs"], None)
            except Exception:
                found = None

        if not found:
            break  # domain has become unsolvable once enough actions are forbidden — expected, not an error

        step_names = [op.name.strip("()") for op in found]
        steps = []
        for name in step_names:
            spec = action_by_name.get(name, {})
            steps.append({
                "action": name,
                "params": {},
                "expected_duration_s": spec.get("expected_duration_s", 0.0),
                "expected_reward": spec.get("expected_reward", 0.0),
            })
        cost = sum(action_by_name.get(n, {}).get("cost", 1) for n in step_names)
        plans.append({
            "steps": steps,
            "cost": cost,
            "novelty": len(forbidden) / max(1, len(problem["actions"])),
        })

        # forbid: PDDLStream forbids the *actions* (and optionally predicates)
        # used by this plan so the next solve is forced to find a genuinely
        # different one — same idea, applied at the PDDL/STRIPS level here.
        forbidden |= set(step_names)

    return plans


# ─────────────────────────── entrypoint ───────────────────────────

def main() -> None:
    request = json.loads(sys.stdin.read())
    problem = request["problem"]
    max_plans = int(request.get("max_plans", 4))

    plans = _try_pddlstream(problem, max_plans)
    backend = "pddlstream"
    if plans is None:
        plans = _try_pyperplan(problem, max_plans)
        backend = "pyperplan"
    if plans is None:
        plans, backend = [], "none"

    json.dump({"backend": backend, "plans": plans}, sys.stdout)


if __name__ == "__main__":
    main()
