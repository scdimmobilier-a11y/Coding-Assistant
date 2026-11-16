"""
bridge.core_factory
======================

Builds the single `NexusCore` instance the bridge server serves, plus (D1,
`MISSION_couple_leon_nexusbrain.md`) the `ObjectiveRunner` that actually
drives Nexus Functor. Kept separate from `server.py` so tests can
construct a core (and, since D1, a runner) with fakes without spinning up
FastAPI.

`pulse=None` remains unchanged (see `docs/DECISIONS.md`, "Pulse") — Leon's
own `pulse-manager.ts` is a strict superset of Nexus Core's `PulseManager`
and is already wired into Leon's own ReAct/tool internals; running Nexus
Core's pulse loop on the same territory would be exactly the double-run
the original mission's point #6 warned against. This mission's own §6
confirms: not something D1–D6 asks to revisit.

D1 — real `post_objective`, no longer `None` by default
---------------------------------------------------------
`_make_post_objective()` builds the callback `NexusCore(post_objective=...)`
fires into: `ObjectiveRunner.add_objective(objective, context)`, returning
immediately with `{"posted": True, "goal_id": ...}` — fire-and-forget, per
Invariant #2 (`docs/INVARIANTS.md`): Nexus Core never loops on
`functor.step()` itself; that's the background tick task's job (see
`server.py`'s lifespan). `runner.tick_all()` runs there, not here.

D3 — reaching `nexus_compose` through a plan step, not a bypass
-------------------------------------------------------------------
"Turn a spoken request into a full STRIPS `planning_problem`" is still
real, separate NLU work this integration does not attempt to fake — same
boundary the previous version of this file already drew, still correct.
What D1+D3 add is a narrow, explicit, OPT-IN escape hatch for callers who
*do* already know they want the production pipeline: if `context` (the
same `context` dict `handle_turn`/`resume_paused` receive from Leon's
request body) carries a `"deliver_software"` key — a string instruction,
or simply `True` to reuse the objective's own description — the resulting
plan is seeded with a single `deliver_software` action
(`NexusPlannerAdapter`'s own license-free fallback path, given
`available_actions=["deliver_software"]`, unmodified — see
`planner_adapter.py`), and that step is registered with
`NexusExecAdapter.register_deliver_software_step()` so it runs through
`CodegenAdapter` (HTTP call to `nexus_compose`'s pipeline) instead of the
generic `Coordinator` loop. Without that key, agent-mode delegation
behaves exactly as before: a generic single-step objective, handled by
whatever `NexusPlannerAdapter`/`NexusExecAdapter` already do for any other
goal. See `docs/DECISIONS.md`, "Post-objective wiring (D1-D3)".

D6 — `evolve_harness_tool`, now wired (previously silently absent)
---------------------------------------------------------------------
Passed straight through from the same `NexusHarnessAdapter` instance the
`ObjectiveRunner` uses for `HarnessPort` — see `docs/DECISIONS.md`,
"Harness evolution (D6)" for the two-separate-data-flows note (this does
not make F0's learned prior and Nexus Core's own prompt/skill/memory CRUD
interact; see `docs/INVARIANTS.md` #8).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from nexus_brain.adapters.codegen_adapter import CodegenAdapter
from nexus_brain.adapters.exec_adapter import NexusExecAdapter
from nexus_brain.adapters.harness_adapter import NexusHarnessAdapter
from nexus_brain.adapters.planner_adapter import NexusPlannerAdapter
from nexus_brain.adapters.proactive_adapter import NexusProactiveAdapter
from nexus_brain.core.brain import NexusCore
from nexus_brain.core.memory import LayeredMemory
from nexus_brain.core.react import ReactLoop, ReactStep
from nexus_brain.integration.loop import ObjectiveRunner
from nexus_functor.types import Objective

from .leon_client import LeonClient
from .memory_bridge import DEFAULT_STORE_PATH, bridge_persist_fn, load_bookkeeping_into
from .skills import make_leon_bridged_skills
from . import registry_aggregator

PostObjectiveFn = Callable[[Objective, dict], Any]

_UNSET = object()  # sentinel: lets build_nexus_core() tell "post_objective not
                    # passed at all" (use the real D1 wiring) apart from
                    # "post_objective=None passed explicitly" (deliberate override).


def _default_agent_planner(goal: str, ctx: dict[str, Any]) -> list[ReactStep]:
    """Single-step plan for anything a native skill can't handle: ask for
    human-in-the-loop confirmation before delegating to Nexus Functor. This
    is deliverable #4's PAUSED state — Leon maps it to a spoken/visual
    confirmation, see leon_patch/server/src/core/nexus-bridge-client.ts.

    D5.3 (Mission 2, Meta Framework/Nexus Studio) adds a second, narrower
    branch ABOVE this default: `context["query_registry"]` is the same
    opt-in convention as `context["deliver_software"]` above — a caller
    that already knows it wants a registry lookup sets it explicitly (a
    capability string, or `True` for "no filter"), rather than this
    planner trying to guess intent from `goal`'s natural-language text
    ("un simple filtre, pas un NL-to-query complet" — the mission's own
    words). Absent, behaviour is byte-for-byte the pre-D5 plan below."""
    query = ctx.get("query_registry")
    if query is not None:
        capability = query if isinstance(query, str) else None
        return [
            ReactStep(
                step_id="query-registry",
                tool="query_registry",
                args={"capability": capability},
                # Read-only introspection, nothing changes state — unlike
                # pose_objective below, there is nothing here for a human
                # to approve.
                requires_approval=False,
            )
        ]

    return [
        ReactStep(
            step_id="confirm-delegation",
            tool="pose_objective",
            args={"description": goal},
            requires_approval=True,
        )
    ]


def _execute_query_registry_step(step: ReactStep) -> dict[str, Any]:
    """D5.3 — 'the Brain can query its own system', literally: calls
    `registry_aggregator.query_registry()` — the exact same function
    `GET /registry/full` calls — in-process rather than looping back over
    HTTP to itself (see that function's own docstring for why). The raw
    `nodes`/`edges` are kept in the returned dict (folded into
    `ReactTrace.history` by `_execute_current`, see core/react.py) for
    anything downstream that wants the structured data; `output` is a
    short spoken-style summary, never the full JSON — nobody wants 183
    node dicts read out loud as a turn's response."""
    capability = step.args.get("capability")
    try:
        full = registry_aggregator.query_registry(capability)
    except registry_aggregator.RegistryAggregatorError as exc:
        return {"success": False, "output": f"Registry query failed: {exc}"}

    nodes = full["nodes"]
    if capability:
        output = (
            f"{len(nodes)} node(s) with capability {capability!r}: " + ", ".join(n["id"] for n in nodes)
            if nodes
            else f"No node currently declares capability {capability!r}."
        )
    else:
        output = f"The full registry has {len(nodes)} nodes and {len(full['edges'])} edges."
    return {"success": True, "output": output, "nodes": nodes, "edges": full["edges"]}


def _make_agent_executor(core_holder: dict[str, NexusCore]):
    def executor(step: ReactStep, ctx: dict[str, Any]) -> dict[str, Any]:
        if step.tool == "query_registry":  # D5.3 — read-only, needs no core at all
            return _execute_query_registry_step(step)

        core = core_holder["core"]
        result = core.pose_objective(step.args["description"], ctx)
        if isinstance(result, dict) and result.get("posted") is False:
            objective = result["objective"]
            output = (
                "I can't delegate that to Nexus Functor yet — no ObjectiveRunner "
                "is wired into this bridge (this only happens if `post_objective` "
                "was explicitly overridden to None — see build_nexus_core_and_runner). "
                f"For reference, the objective I would have posted is: {objective.description!r}."
            )
        else:
            output = f"Delegated to Nexus Functor: {result}"
        return {"success": True, "output": output}

    return executor


def _make_post_objective(runner: ObjectiveRunner, executor: NexusExecAdapter) -> PostObjectiveFn:
    """D1+D3: fire-and-forget sink for `NexusCore.pose_objective()`. See
    module docstring for the `context["deliver_software"]` opt-in."""

    def post_objective(objective: Objective, context: dict[str, Any]) -> dict[str, Any]:
        run_context = dict(context)
        deliver = run_context.pop("deliver_software", None)
        if deliver:
            run_context.setdefault("available_actions", ["deliver_software"])

        runner.add_objective(objective, run_context)

        if deliver:
            instruction = deliver if isinstance(deliver, str) else objective.description
            ao = runner.get(objective.goal_id)
            if ao is not None:
                for plan in ao.plan_set.plans:
                    for step in plan.steps:
                        if step.action == "deliver_software":
                            executor.register_deliver_software_step(
                                step.step_id, instruction, goal_id=objective.goal_id
                            )

        return {"posted": True, "goal_id": objective.goal_id}

    return post_objective


def build_nexus_core_and_runner(
    leon_client: Optional[LeonClient] = None,
    memory_store_path: Optional[Path] = None,
    planner: Optional[NexusPlannerAdapter] = None,
    executor: Optional[NexusExecAdapter] = None,
    harness: Optional[NexusHarnessAdapter] = None,
    proactive: Optional[NexusProactiveAdapter] = None,
    codegen_adapter: Optional[CodegenAdapter] = None,
) -> tuple[NexusCore, ObjectiveRunner]:
    """D1: like `build_nexus_core()`, but also returns the `ObjectiveRunner`
    driving it — needed by `server.py`'s background tick task and by the
    `/objective/{goal_id}/status` and `/objective/{goal_id}/deliver`
    endpoints (D1/D2). Every adapter is individually injectable so tests
    can exercise the wiring with fakes (see `tests/test_post_objective_wiring.py`),
    exactly like `leon_client` already was."""
    leon_client = leon_client or LeonClient()
    planner = planner or NexusPlannerAdapter()
    executor = executor or NexusExecAdapter(codegen_adapter=codegen_adapter or CodegenAdapter())
    harness = harness or NexusHarnessAdapter()
    runner = ObjectiveRunner(planner=planner, executor=executor, harness=harness, proactive=proactive)

    store_path = memory_store_path or DEFAULT_STORE_PATH
    memory = LayeredMemory(persist_fn=lambda layer, entry: bridge_persist_fn(layer, entry, store_path))
    load_bookkeeping_into(memory, store_path)

    core_holder: dict[str, NexusCore] = {}
    react_loop = ReactLoop(
        planner_fn=_default_agent_planner,
        executor_fn=_make_agent_executor(core_holder),
    )

    core = NexusCore(
        skills=make_leon_bridged_skills(leon_client),
        react_loop=react_loop,
        memory=memory,
        pulse=None,  # unchanged — see docs/DECISIONS.md, "Pulse"
        evolve_harness_tool=harness.evolve_harness,  # D6
        post_objective=_make_post_objective(runner, executor),  # D1+D3
        diagnostics_report_fn=registry_aggregator.fetch_compose_spoken_report,  # D5.2 (Mission 2)
    )
    core_holder["core"] = core
    return core, runner


def build_nexus_core(
    leon_client: Optional[LeonClient] = None,
    post_objective: Any = _UNSET,
    memory_store_path: Optional[Path] = None,
    **adapter_overrides: Any,
) -> NexusCore:
    """Backward-compatible single-value factory: every pre-D1 call site
    (`build_nexus_core(leon_client=...)`, all of this package's existing
    tests) keeps working unchanged. `post_objective`, if given explicitly
    (including `post_objective=None`), overrides the real D1 wiring — e.g.
    `post_objective=None` still fully reproduces the pre-D1 "no sink
    configured" behaviour on purpose, see `_make_agent_executor`'s
    `posted is False` branch and its own tests. Use
    `build_nexus_core_and_runner()` directly when the `ObjectiveRunner`
    itself is also needed (background ticking, `/objective/*` endpoints)."""
    core, _runner = build_nexus_core_and_runner(
        leon_client=leon_client, memory_store_path=memory_store_path, **adapter_overrides
    )
    if post_objective is not _UNSET:
        core._post_objective = post_objective  # deliberate override, see docstring
    return core
