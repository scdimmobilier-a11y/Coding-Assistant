"""
nexus_brain.adapters.exec_adapter
==================================

`ExecutorPort` adapter backed by the *real* Nexus Exec (OpenFugu/Fugu)
multi-turn role-routing loop — `vendor/nexus_exec/nexus_exec/mini.py`,
class `Coordinator`, imported and used unmodified.

Faithful to the source mechanism (see prompt_nexus_brain.md, "Nexus Exec"):
a router selects **one** worker + one role per turn (never fan-out/fan-in);
the loop runs role -> inject role prompt -> call worker -> repeat, up to
`max_turns`; termination is on Verifier `ACCEPT`, on `max_turns`, or on a
Thinker `<suggested_role>` override redirecting the next turn.

Two things the real `Coordinator` needs are pluggable:

1. **worker** — any `Callable[[role_name, messages, agent_id], str]`.
   Defaults to `MockWorker` (also real, vendored code, explicitly designed
   by the source project as an offline stand-in so the *loop* can be
   exercised without API keys).

2. **router** — the real `ExecRouter` needs `torch` + `transformers` + a
   trained checkpoint (hidden-state linear head over Qwen3-0.6B) that isn't
   fetchable in an offline/sandboxed environment. When those are actually
   available (real deployment), `NexusExecAdapter` uses the real, trained
   `ExecRouter`. Otherwise it falls back to `HeuristicExecRouter` below —
   a dependency-free stand-in that satisfies the *exact same* call
   contract (`.route(messages, sample, agent_mask) -> dict` with
   `agent_id`/`role_id`/`role_name`), so `Coordinator.run()`'s real control
   flow (ACCEPT / suggested_role override / max_turns) is exercised
   faithfully either way — only the role-picking policy differs.

D3 (`MISSION_couple_leon_nexusbrain.md`) extension — does NOT replace any
of the above: `ExecutorPort.execute_step(plan_id, step_id, params)`
(`nexus_functor/interfaces.py`, unmodified) never receives the plan step's
`action` name, only `step_id`. So the one piece of information this
adapter needs to know "is this step a `deliver_software` step" cannot come
from the call signature itself — it is registered *ahead of time*, by
whoever just saw the `PlanSet` a `PlannerPort` produced (typically the
`post_objective` glue in `bridge/core_factory.py`, right after
`ObjectiveRunner.add_objective()` — see that module for the orchestration
this deliberately leaves to the caller rather than duplicating here, per
Invariant #1: adapters don't reach into each other or into the planner's
output on their own). A registered step is executed by
`CodegenAdapter.deliver_software(...)` (HTTP call to `nexus_compose`'s
pipeline) *instead of* the normal `Coordinator` role-routing loop — never
both — so Invariant #6 (sequential role routing, no fan-out/fan-in) still
holds for every step that *does* go through `Coordinator`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

_VENDOR_EXEC = Path(__file__).resolve().parents[2] / "vendor" / "nexus_exec"
if str(_VENDOR_EXEC) not in sys.path:
    sys.path.insert(0, str(_VENDOR_EXEC))

from nexus_exec.mini import Coordinator, MockWorker, ROLE_NAMES, N_AGENTS  # noqa: E402  (real, vendored, unmodified)

from nexus_functor.types import FeedbackEvent, Outcome  # noqa: E402

from .codegen_adapter import CodegenAdapter, CodegenAdapterError


class HeuristicExecRouter:
    """Dependency-free stand-in for the real trained `ExecRouter`.

    Satisfies the exact call contract `Coordinator` expects:
        .route(messages, sample=False, agent_mask=None) -> dict

    Role policy: Worker once (get an initial answer), Thinker once
    (demonstrate the `<suggested_role>` override path), then Verifier for
    all remaining turns (demonstrates genuine ACCEPT-based termination —
    `MockWorker` accepts on the 2nd verification, matching its own
    docstring: "lets the loop demonstrably terminate via ACCEPT rather than
    only by max-turns"). None of this is a source of correctness for the
    run: every real decision point (ACCEPT, override-consumption,
    max_turns) lives inside `Coordinator.run()`, untouched here.
    """

    def __init__(self, agent_count: int = N_AGENTS, role_plan: Optional[list[str]] = None):
        self._agent_count = max(1, agent_count)
        # Worker once, Thinker once, then Verifier padding out any max_turns
        # we're likely to be configured with.
        self._role_plan = role_plan or (["Worker", "Thinker"] + ["Verifier"] * 32)
        self._turn = 0

    def route(self, messages: list, sample: bool = False, agent_mask=None) -> dict:
        idx = min(self._turn, len(self._role_plan) - 1)
        role_name = self._role_plan[idx]
        role_id = ROLE_NAMES.index(role_name)

        agent_id = self._turn % self._agent_count
        if agent_mask:
            allowed = [a for a, ok in enumerate(agent_mask) if ok]
            if allowed:
                agent_id = allowed[self._turn % len(allowed)]

        self._turn += 1
        return {"agent_id": agent_id, "role_id": role_id, "role_name": role_name}

    def reset(self) -> None:
        """Start a fresh role sequence (call between independent `execute_step`s)."""
        self._turn = 0


def _try_real_router(model_dir: Optional[str], vector_path: Optional[str]):
    """Attempt to construct the real trained `ExecRouter`; `None` if unavailable
    (missing torch/transformers, missing checkpoint files, etc.) — this keeps
    the adapter usable both in a full deployment and in this offline sandbox."""
    if not (model_dir and vector_path):
        return None
    try:
        from nexus_exec.mini import ExecRouter  # imports torch/transformers lazily
        return ExecRouter(model_dir, vector_path)
    except Exception:
        return None


class NexusExecAdapter:
    """`ExecutorPort` implementation backed by Nexus Exec's real `Coordinator`.

    One `Coordinator` instance (fresh role-router state) is used per
    `execute_step` call, matching the source semantics: routing state is
    per-run (per plan-step), not shared across unrelated steps.
    """

    def __init__(
        self,
        worker: Optional[Callable[[str, list, int], str]] = None,
        model_dir: Optional[str] = None,
        vector_path: Optional[str] = None,
        max_turns: int = 5,
        sample: bool = False,
        codegen_adapter: Optional[CodegenAdapter] = None,
    ):
        self._worker = worker or MockWorker()
        self._model_dir = model_dir
        self._vector_path = vector_path
        self._real_router = _try_real_router(model_dir, vector_path)
        self._using_real_router = self._real_router is not None
        self._max_turns = max_turns
        self._sample = sample
        self._codegen_adapter = codegen_adapter or CodegenAdapter()
        # step_id -> (instruction, goal_id) — see module docstring, D3.
        self._deliver_software_steps: dict[str, tuple[str, Optional[str]]] = {}

    @property
    def using_real_router(self) -> bool:
        """True iff the real trained `ExecRouter` is active (vs. the heuristic
        stand-in) — surfaced so callers/tests can assert which path ran."""
        return self._using_real_router

    def register_deliver_software_step(
        self, step_id: str, instruction: str, goal_id: Optional[str] = None
    ) -> None:
        """Mark `step_id` as a `deliver_software` step (D3): the next
        `execute_step(_, step_id, _)` call for it will go to
        `CodegenAdapter.deliver_software(instruction)` instead of the
        normal `Coordinator` loop. See module docstring for why this
        registration happens ahead of time rather than being derived
        inside `execute_step` itself."""
        self._deliver_software_steps[step_id] = (instruction, goal_id)

    def execute_step(self, plan_id: str, step_id: str, params: dict[str, Any]) -> FeedbackEvent:
        registered = self._deliver_software_steps.pop(step_id, None)
        if registered is not None:
            return self._execute_deliver_software(plan_id, step_id, *registered)

        query = self._render_query(plan_id, step_id, params)
        router = self._real_router or HeuristicExecRouter()

        coordinator = Coordinator(
            router=router,
            worker=self._worker,
            max_turns=self._max_turns,
            sample=self._sample,
        )
        t0 = time.time()
        result = coordinator.run(query)
        elapsed = time.time() - t0

        if result.terminated_by == "verifier_accept":
            outcome, deviation, reward = Outcome.SUCCESS, 0.0, 1.0
        elif result.terminated_by == "max_turns":
            outcome, deviation, reward = Outcome.PARTIAL, 0.5, 0.3
        else:  # "verifier_no_response" or anything unforeseen
            outcome, deviation, reward = Outcome.FAILURE, 1.0, 0.0

        return FeedbackEvent(
            plan_id=plan_id,
            step_id=step_id,
            outcome=outcome,
            observed_reward=reward,
            deviation=deviation,
            notes=(
                f"terminated_by={result.terminated_by} turns={len(result.turns)} "
                f"elapsed_s={elapsed:.3f} final={result.final[:160]!r}"
            ),
        )

    def _execute_deliver_software(
        self, plan_id: str, step_id: str, instruction: str, goal_id: Optional[str]
    ) -> FeedbackEvent:
        """D3: run a `deliver_software` step by calling `nexus_compose`'s
        real pipeline instead of the `Coordinator` loop — see module
        docstring. `nexus_compose` remains the sole source of truth for
        what actually happens; this only starts the run and reports
        SUCCESS/FAILURE of *starting* it (the pipeline's own SSE/dashboard
        is the source of truth for how the run itself proceeds — this
        adapter does not poll or block on it, per Invariant #2's
        fire-and-forget spirit one layer up)."""
        try:
            result = self._codegen_adapter.deliver_software(instruction, goal_id=goal_id)
        except CodegenAdapterError as e:
            return FeedbackEvent(
                plan_id=plan_id, step_id=step_id, outcome=Outcome.FAILURE,
                observed_reward=0.0, deviation=1.0, notes=f"deliver_software failed: {e}",
            )
        run_id = result.get("run_id", "?")
        return FeedbackEvent(
            plan_id=plan_id, step_id=step_id, outcome=Outcome.SUCCESS,
            observed_reward=1.0, deviation=0.0,
            notes=f"deliver_software started nexus_compose run_id={run_id} for: {instruction!r}",
        )

    @staticmethod
    def _render_query(plan_id: str, step_id: str, params: dict[str, Any]) -> str:
        return (
            "Execute one plan step.\n"
            f"plan_id={plan_id}\nstep_id={step_id}\nparams={params!r}\n"
            "Solve this step, verify the result, and report ACCEPT when correct."
        )
