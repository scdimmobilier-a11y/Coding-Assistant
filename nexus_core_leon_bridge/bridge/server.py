"""
bridge.server
===============

Deliverable #1: the local HTTP bridge server, "consommé depuis le runtime
Node.js de Leon (`fetch`/`axios`)". Exposes exactly the three operations
Leon's patched interception point needs:

  POST /handle_turn      -> NexusCore.handle_turn
  POST /resume_paused     -> NexusCore.resume_paused
  POST /pulse_tick        -> NexusCore.pulse_tick   (exposed for completeness/
                             testing — see docs/DECISIONS.md "Pulse": Leon's
                             own scheduler does NOT call this endpoint today)
  GET  /health            -> liveness check for leon_patch's client

D1/D2 (`MISSION_couple_leon_nexusbrain.md`) add the other side of a posed
objective — status while it runs, and its result once it's done:

  GET  /objective/{goal_id}/status   -> D1, ticking/active/unknown
  POST /objective/{goal_id}/deliver  -> D2, the final TickSummary once
                                         status is "complete" (404 while
                                         still running or unknown)

`MISSION2_meta_framework_nexus_studio.md` (D3/D4) add read-only registry
introspection — never mutating anything, purely "what exists and what
does it take as input/output":

  GET  /registry/nodes   -> D3, Nexus Brain's OWN static registry
                             (nexus_brain.registry, Niveau 1 components).
                             Lives HERE rather than on Nexus_Brain itself
                             so Nexus Core stays out of the tight loop
                             (Invariant #2, docs/INVARIANTS.md) — this
                             endpoint only reads a plain module-level
                             tuple of dicts, it never touches `app.state.core`.
  GET  /registry/full     -> D4, the fused catalogue: the above PLUS
                             nexus_compose's own registry (169 nodes/218
                             edges), fetched over HTTP — see
                             bridge/registry_aggregator.py for why that
                             fetch happens per-request rather than once at
                             startup. Optional `?capability=` query filters
                             the result (Nexus_Assistant/docs/registry_schema.md §2.3).

...and the background loop that actually makes objectives progress:
`runner.tick_all()` runs on a repeating `asyncio` task started in this
app's lifespan, at `BridgeConfig.objective_tick_interval_s` (default 2.0s,
env `NEXUS_BRIDGE_TICK_INTERVAL_S`) — never inside a request handler, so
`/handle_turn`/`/resume_paused` stay fast and fire-and-forget, per
Invariant #2. See `docs/DECISIONS.md`, "Delivery callback (D2)".

Session -> paused-goal-key bookkeeping lives HERE, not inside NexusCore,
because NexusCore's own `_active_traces` are keyed by the *original
utterance string* (see `nexus_brain/core/brain.py::handle_turn`), not by a
session id — Leon only has a `session_id` to hand back on the follow-up
turn, so this server is what bridges the two. This is deliberately a
plain in-process dict: the bridge is meant to run as a single local
process next to Leon (per the mission's "pont HTTP local"), so there is
no multi-process/multi-worker deployment to keep in sync.

`create_app(core=None, runner=None)` takes an optional pre-built
`NexusCore`/`ObjectiveRunner` pair so tests can inject fakes (see
tests/) without needing a real Leon server or a real `nexus_compose`
process. Passing `core` without `runner` (every pre-D1 test in this
package does exactly that) disables the background tick task and the
`/objective/*` endpoints return 501 — there is nothing to tick or query,
and that is a deliberate, tested no-op rather than a crash.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import registry_aggregator
from .config import get_bridge_config
from .core_factory import build_nexus_core_and_runner
from .memory_bridge import apply_leon_context_digest
from nexus_brain import registry as brain_registry

logger = logging.getLogger(__name__)


class HandleTurnRequest(BaseModel):
    user_input: str
    context: dict[str, Any] = Field(default_factory=dict)
    mode: str = "smart"
    session_id: Optional[str] = None


class ResumeRequest(BaseModel):
    session_id: str
    approved: bool
    human_input: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)


class PulseTickRequest(BaseModel):
    now: Optional[float] = None


class TurnResultOut(BaseModel):
    response: Any
    mode_used: str
    paused: bool
    goal_key: Optional[str] = None


async def _tick_loop(app: FastAPI, interval_s: float) -> None:
    """D1: drives `ObjectiveRunner.tick_all()` forever, off the request
    path. `asyncio.to_thread` because `tick_all()` is synchronous and can
    block briefly (`Coordinator.run()`, `CodegenAdapter`'s HTTP call) —
    without it, one slow tick would stall every other request this
    single-process bridge is serving."""
    runner = app.state.objective_runner
    while True:
        try:
            await asyncio.to_thread(runner.tick_all)
        except Exception:  # pragma: no cover - defensive: one bad tick must
            # never kill the whole background loop, or every OTHER active
            # objective would silently stop progressing too.
            logger.exception("objective runner tick failed")
        await asyncio.sleep(interval_s)


def create_app(core=None, runner=None, tick_interval_s: Optional[float] = None) -> FastAPI:
    if core is None and runner is None:
        core, runner = build_nexus_core_and_runner()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task: Optional[asyncio.Task] = None
        if app.state.objective_runner is not None:
            interval = tick_interval_s if tick_interval_s is not None else get_bridge_config().objective_tick_interval_s
            task = asyncio.create_task(_tick_loop(app, interval))
        yield
        if task is not None:
            task.cancel()

    app = FastAPI(title="Nexus Core <-> Leon bridge", lifespan=lifespan)

    # D5.1 (Mission 2) — mêmes origines et même posture que
    # Nexus_Assistant/api/main.py (pas de wildcard "*" avec des credentials) :
    # nexus-ui (page "Registry", D5.1) appelle GET /registry/full directement
    # depuis le navigateur, une origine différente (Vite dev server) que ce
    # pont. Sans ce middleware, la requête réussirait en curl/pytest (aucune
    # des deux n'applique CORS) mais échouerait silencieusement dans un vrai
    # navigateur — c'est le genre d'écart qu'un test HTTP ne révèle jamais.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.core = core
    app.state.objective_runner = runner  # D1/D2 — may be None, see module docstring
    app.state.paused_goal_keys = {}  # session_id -> goal_key

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/handle_turn", response_model=TurnResultOut)
    def handle_turn(req: HandleTurnRequest) -> TurnResultOut:
        core = app.state.core
        context = dict(req.context)
        if req.session_id:
            context.setdefault("session_id", req.session_id)
        apply_leon_context_digest(core.memory, context)

        result = core.handle_turn(req.user_input, context, mode=req.mode)

        goal_key: Optional[str] = None
        if req.session_id:
            if result.paused:
                goal_key = req.user_input
                app.state.paused_goal_keys[req.session_id] = goal_key
            else:
                app.state.paused_goal_keys.pop(req.session_id, None)

        return TurnResultOut(
            response=result.response,
            mode_used=result.mode_used,
            paused=result.paused,
            goal_key=goal_key,
        )

    @app.post("/resume_paused", response_model=TurnResultOut)
    def resume_paused(req: ResumeRequest) -> TurnResultOut:
        core = app.state.core
        goal_key = app.state.paused_goal_keys.get(req.session_id)
        if goal_key is None:
            raise HTTPException(
                status_code=404,
                detail=f"No paused Nexus Core trace for session {req.session_id!r}.",
            )

        context = dict(req.context)
        context.setdefault("session_id", req.session_id)
        apply_leon_context_digest(core.memory, context)

        human_input = dict(req.human_input)
        human_input.setdefault("approved", req.approved)

        result = core.resume_paused(goal_key, human_input, context)

        if result.paused:
            app.state.paused_goal_keys[req.session_id] = goal_key
        else:
            app.state.paused_goal_keys.pop(req.session_id, None)

        return TurnResultOut(
            response=result.response,
            mode_used=result.mode_used,
            paused=result.paused,
            goal_key=goal_key if result.paused else None,
        )

    @app.post("/pulse_tick")
    def pulse_tick(req: PulseTickRequest) -> dict[str, Optional[str]]:
        core = app.state.core
        return {"summary": core.pulse_tick(now=req.now)}

    @app.get("/objective/{goal_id}/status")
    def objective_status(goal_id: str) -> dict[str, Any]:
        runner = app.state.objective_runner
        if runner is None:
            raise HTTPException(status_code=501, detail="No ObjectiveRunner configured on this app instance.")

        active = runner.get(goal_id)
        if active is not None:
            return {
                "goal_id": goal_id,
                "status": "active",
                "replan_count": active.replan_count,
                "last_tick": active.tick_log[-1] if active.tick_log else None,
            }

        completed = runner.get_completed(goal_id)
        if completed is not None:
            return {"goal_id": goal_id, "status": "complete", "summary": vars(completed)}

        return {"goal_id": goal_id, "status": "unknown"}

    @app.post("/objective/{goal_id}/deliver")
    def objective_deliver(goal_id: str) -> dict[str, Any]:
        """D2: the delivery callback — Leon's `nexus-bridge-client.ts`
        polls this once `GET /objective/{goal_id}/status` says
        `"complete"` (or gets a 404 back meaning "not yet, or never
        existed" and keeps waiting/gives up per its own retry policy).
        See docs/DECISIONS.md, "Delivery callback (D2)" for why this is a
        pull endpoint rather than a push/SSE — that remains a documented,
        available follow-up, not a silent gap."""
        runner = app.state.objective_runner
        if runner is None:
            raise HTTPException(status_code=501, detail="No ObjectiveRunner configured on this app instance.")

        completed = runner.get_completed(goal_id)
        if completed is None:
            raise HTTPException(
                status_code=404,
                detail=f"No completed objective {goal_id!r} (still active, or unknown).",
            )
        return {
            "goal_id": goal_id,
            "status": completed.status,
            "outcome": completed.outcome,
            "report": completed.notes,
        }

    @app.get("/registry/nodes")
    def registry_nodes() -> dict[str, Any]:
        """D3 — Nexus Brain's own static registry, re-exported HERE rather
        than served by Nexus_Brain itself (Invariant #2: Nexus Core stays
        out of the tight loop). Reads a plain static tuple of dicts — no
        `app.state.core` involved, so this never touches NexusCore even
        indirectly."""
        return {"nodes": brain_registry.list_nodes(), "edges": []}

    @app.get("/registry/full")
    def registry_full(capability: Optional[str] = None) -> dict[str, Any]:
        """D4/D5 — the fused catalogue (nexus_compose over HTTP + Nexus
        Brain's static registry above). Delegates to
        registry_aggregator.query_registry(), the SAME function NexusCore's
        own `query_registry` ReAct tool calls in-process (D5.3) — this
        HTTP route and that tool are two doors onto one function, not two
        separate implementations that could drift apart."""
        try:
            return registry_aggregator.query_registry(capability)
        except registry_aggregator.RegistryAggregatorError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return app


# Production entrypoint: `uvicorn bridge.server:app --host ... --port ...`
app = create_app()
