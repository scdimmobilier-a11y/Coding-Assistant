"""
api.pipeline
==============

POST /api/pipeline/run, GET /api/pipeline/events,
POST /api/pipeline/nodes/{node_id}/retry,
POST /api/pipeline/phases/{phase_id}/retry — Étapes 1a + 1b du prompt de
fusion. Voir state.py pour le détail du pont thread -> asyncio.

`RunRequest.phase` omis ou `None` -> pipeline complet (10 phases réelles,
voir state.FULL_PIPELINE_PHASE_ORDER) ; `phase` donné -> une seule phase
(comportement de l'Étape 1a, inchangé).

Décision sur le run_id des retries (laissée ouverte par le prompt de
fusion, "à décider et documenter") : chaque retry crée un NOUVEAU run_id
plutôt que de republier sur le run_id d'origine. Plus simple à raisonner
(pas de réouverture d'un flux SSE potentiellement déjà fermé côté client),
et cohérent avec le fait qu'un retry est, du point de vue de
l'orchestrateur, une exécution indépendante.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .state import RUNS, FULL_PIPELINE_PHASE_ORDER, get_graph, start_node_retry, start_phase_retry, start_pipeline_run

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


class RunRequest(BaseModel):
    instruction: str
    phase: str | None = None


class RunResponse(BaseModel):
    run_id: str
    phases: list[str]


class RetryResponse(BaseModel):
    run_id: str


def _sse_stream(request: Request, run_id: str):
    run = RUNS.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Unknown run_id {run_id!r}")

    async def event_stream():
        while True:
            if await request.is_disconnected():
                break
            event = await run.queue.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("type") in ("done", "error"):
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/phases")
async def list_phases() -> list[dict[str, object]]:
    """Étape 2 du prompt de fusion : les 10 id de phase réels (voir
    state.FULL_PIPELINE_PHASE_ORDER pour la correction de l'hypothèse
    "8 phases"), pour que le frontend construise son état initial sans
    dépendre de src/data/mockPipeline.ts. Volontairement SANS libellé
    FR — le mapping id -> libellé est centralisé côté frontend
    (src/lib/phaseLabels.ts), pas ici, pour rester cohérent avec la
    consigne "mapping centralisé côté frontend" de l'Étape 2."""
    graph = get_graph()
    return [{"id": ph, "nodeCount": len(graph.list_nodes(phase=ph))} for ph in FULL_PIPELINE_PHASE_ORDER]


@router.post("/run", response_model=RunResponse)
async def run_pipeline(req: RunRequest) -> RunResponse:
    graph = get_graph()
    if req.phase is not None:
        if not graph.list_nodes(phase=req.phase):
            raise HTTPException(status_code=400, detail=f"Unknown phase {req.phase!r}")
        phases = [req.phase]
    else:
        phases = FULL_PIPELINE_PHASE_ORDER

    loop = asyncio.get_running_loop()
    ctx = {"instruction": req.instruction}
    run_id = start_pipeline_run(phases, ctx, loop)
    return RunResponse(run_id=run_id, phases=phases)


@router.get("/events")
async def pipeline_events(request: Request, run_id: str):
    return _sse_stream(request, run_id)


@router.post("/nodes/{node_id}/retry", response_model=RetryResponse)
async def retry_node(node_id: str) -> RetryResponse:
    graph = get_graph()
    try:
        graph.node(node_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown node {node_id!r}")
    loop = asyncio.get_running_loop()
    run_id = start_node_retry(node_id, {}, loop)
    return RetryResponse(run_id=run_id)


@router.post("/phases/{phase_id}/retry", response_model=RetryResponse)
async def retry_phase(phase_id: str) -> RetryResponse:
    graph = get_graph()
    if not graph.list_nodes(phase=phase_id):
        raise HTTPException(status_code=404, detail=f"Unknown phase {phase_id!r}")
    loop = asyncio.get_running_loop()
    run_id = start_phase_retry(phase_id, {}, loop)
    return RetryResponse(run_id=run_id)
