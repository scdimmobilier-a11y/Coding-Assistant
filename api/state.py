"""
api.state
===========

Le registre des runs en cours, et le pont thread -> asyncio (Étape 1a,
étendu en 1b aux 10 phases réelles + aux retries). Point le plus délicat de
toute la fusion, documenté en détail ici plutôt que noyé dans les
endpoints FastAPI — voir aussi README.md, section "Fusion frontend ↔
backend".

Pourquoi un thread, et pas juste `asyncio.create_task(orch.run_phase(...))` :
`Orchestrator.run_phase`/`run_node`/`run_pipeline` sont des appels Python
synchrones et BLOQUANTS — chaque nœud peut faire un subprocess (Semgrep,
Bearer...) ou un appel HTTP bloquant (LLM, Neo4j...). Un simple
`create_task` sur une coroutine qui appelle ce code bloquant ne libère PAS
la boucle d'événements pendant toute la durée du nœud ; ça bloquerait TOUTES
les autres requêtes de l'API pendant tout un run. D'où : un thread Python
dédié par run, qui fait le travail bloquant, et un pont thread-safe pour
faire remonter chaque événement dans l'`asyncio.Queue` consommée par le
générateur SSE (qui, lui, tourne bien dans la boucle asyncio).

`asyncio.Queue` n'est PAS thread-safe par elle-même ; l'API officiellement
recommandée pour appeler depuis un autre thread est
`loop.call_soon_threadsafe(...)` (doc Python, asyncio-threading) — c'est ce
que ce module utilise. Alternative plus simple mais à latence légèrement
supérieure : une `queue.Queue` standard consommée par polling côté
coroutine (patron démontré par la doc Python elle-même) — non retenue ici,
`call_soon_threadsafe` fonctionne bien et sans délai de polling (preuve :
README.md, section Étape 1a).

── Les 10 phases réelles (correction de l'hypothèse "8 phases" du prompt) ──

`nodes.json`/`NodeMeta.phase` contiennent en réalité 10 valeurs distinctes,
pas 8 : `elicit, arch, net, policy, threat, graph, codegen, audit, report,
deploy` — confirmé à la fois empiriquement (Counter sur les 169 nœuds
réels) ET par la constante canonique `_PHASE_ORDER` déjà présente dans
`Orchestrator.iter_phase_pipelines` (orchestrator.py). Le prompt de fusion
d'origine n'en listait que 8 (oubli de "report" et "deploy" lors d'une
vérification incomplète) — corrigé ici avec la liste faisant autorité.

`FULL_PIPELINE_PHASE_ORDER` ci-dessous est un miroir exact de cette
constante — pas une redécouverte indépendante — pour permettre de
pré-annoncer tous les nœuds "pending" AVANT de lancer le thread (une
`iter_phase_pipelines()` généré ne le permettrait pas : il ne "yield" un
résultat qu'APRÈS que la phase entière ait tourné, donc aucun signal
"cette phase va commencer" n'est disponible avant coup). Le mécanisme
d'exécution réel reste `orch.run_phase(...)`, appelé phase par phase dans
cet ordre — rien de la logique métier n'est dupliqué, seulement l'ORDRE
déjà documenté par l'orchestrateur lui-même.

`greenfield_pipeline()`/`run_from("LEON", ...)` (mentionnés dans le prompt
de fusion) ont été essayés et écartés pour ce endpoint : `run_from` ne
couvre que les 106 nœuds atteignables par BFS depuis "LEON" (sur 169 au
total) et mélange les phases dans un seul tri topologique global — moins
adapté à un affichage groupé par phase que `iter_phase_pipelines`/son
équivalent phase-par-phase ci-dessous, qui couvre bien les 169 nœuds.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from nexus_compose import build_graph
from nexus_compose.graph import ComposabilityGraph
from nexus_compose.orchestrator import Orchestrator, StepRecord

logger = logging.getLogger("nexus_assistant.api")

# Miroir exact de Orchestrator.iter_phase_pipelines._PHASE_ORDER — voir
# docstring du module pour pourquoi ce n'est pas appelé directement.
FULL_PIPELINE_PHASE_ORDER: list[str] = [
    "elicit", "arch", "net", "policy",
    "threat", "graph", "codegen", "audit", "report", "deploy",
]

# ── graphe partagé, construit une fois (mesuré : ~120 ms pour 169 nœuds) ───
_graph: Optional[ComposabilityGraph] = None
_graph_lock = threading.Lock()


def get_graph() -> ComposabilityGraph:
    global _graph
    with _graph_lock:
        if _graph is None:
            _graph = build_graph()
        return _graph


def known_phases() -> list[str]:
    return FULL_PIPELINE_PHASE_ORDER


@dataclass
class Run:
    run_id: str
    kind: str  # "phase" | "full" | "node-retry" | "phase-retry"
    queue: "asyncio.Queue[dict[str, Any]]"
    order: list[str] = field(default_factory=list)
    finished: bool = False


RUNS: dict[str, Run] = {}


def _emit(loop: asyncio.AbstractEventLoop, queue: "asyncio.Queue[dict]", event: dict) -> None:
    loop.call_soon_threadsafe(queue.put_nowait, event)


def _build_flat_order(graph: ComposabilityGraph, phases: list[str]) -> list[tuple[str, str]]:
    """(phase, node_id) dans l'ordre exact où `on_step_done` sera appelé
    pendant l'exécution phase-par-phase ci-dessous — une concaténation des
    tris topologiques PAR PHASE, exactement ce que fait `run_phase` en
    interne pour chaque phase prise séparément."""
    flat: list[tuple[str, str]] = []
    for ph in phases:
        node_ids = graph.list_nodes(phase=ph)
        if not node_ids:
            continue
        for nid in graph.topological_sort(node_ids):
            flat.append((ph, nid))
    return flat


def _run_pipeline_in_thread(
    run_id: str,
    phases: list[str],
    ctx: dict[str, Any],
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Tourne dans un thread dédié. `phases` est soit une seule phase
    (Étape 1a, rétro-compatible), soit FULL_PIPELINE_PHASE_ORDER en entier
    (Étape 1b)."""
    run = RUNS[run_id]
    queue = run.queue
    graph = get_graph()

    flat_order = _build_flat_order(graph, phases)
    run.order = [nid for _, nid in flat_order]

    if not flat_order:
        _emit(loop, queue, {"type": "error", "message": f"Aucun nœud pour les phases {phases!r}"})
        _emit(loop, queue, {"type": "done"})
        run.finished = True
        return

    node_phase = {nid: ph for ph, nid in flat_order}  # node_id -> phase
    node_sequence = [nid for _, nid in flat_order]

    for ph, nid in flat_order:
        _emit(loop, queue, {"type": "node", "phaseId": ph, "nodeId": nid, "status": "pending"})

    def on_step_done(rec: StepRecord) -> None:
        # rec.node_id == NodeMeta.id (ex. "bearer.bearer_scan") — jamais
        # NodeMeta.tag (ex. "audit.analyze", partagé par plusieurs nœuds :
        # piège documenté dans le prompt de fusion, déjà correct ici car
        # StepRecord.node_id vient de NodeMeta.id).
        phase_id = node_phase.get(rec.node_id, "unknown")
        event: dict[str, Any] = {
            "type": "node",
            "phaseId": phase_id,
            "nodeId": rec.node_id,
            "status": "done" if rec.success else "failed",
        }
        if not rec.success and rec.error:
            event["error"] = rec.error
        _emit(loop, queue, event)

        try:
            idx = node_sequence.index(rec.node_id)
        except ValueError:
            return
        if idx + 1 < len(node_sequence):
            next_phase, next_nid = flat_order[idx + 1]
            _emit(loop, queue, {"type": "node", "phaseId": next_phase, "nodeId": next_nid, "status": "running"})

    try:
        orch = Orchestrator(graph, on_step_done=on_step_done)
        first_phase, first_nid = flat_order[0]
        _emit(loop, queue, {"type": "node", "phaseId": first_phase, "nodeId": first_nid, "status": "running"})

        shared_ctx = dict(ctx)
        for ph in phases:
            if not graph.list_nodes(phase=ph):
                continue  # miroir du `except ValueError: continue` de iter_phase_pipelines
            try:
                pr = orch.run_phase(ph, shared_ctx)
                shared_ctx.update(pr.context)
            except ValueError:
                continue
    except Exception as exc:
        logger.exception("Pipeline run %s failed", run_id)
        _emit(loop, queue, {"type": "error", "message": str(exc)})
    finally:
        _emit(loop, queue, {"type": "done"})
        run.finished = True


def _run_node_in_thread(run_id: str, node_id: str, ctx: dict[str, Any], loop: asyncio.AbstractEventLoop) -> None:
    """Retry d'un nœud unique — POST /api/pipeline/nodes/{node_id}/retry.

    IMPORTANT, découvert en testant (pas supposé) : `Orchestrator.run_node`
    ne déclenche PAS `on_step_done` — seul `run_pipeline` (utilisé en
    interne par `run_phase`/`run_from`) le fait, en enveloppant chaque
    `run_node` dans un `StepRecord` avant d'appeler le callback. Pour un
    retry de nœud isolé, l'événement "done"/"failed" est donc construit ici
    directement à partir du `NodeResult` renvoyé par `run_node`, sans passer
    par `on_step_done` (qui ne servirait à rien dans ce cas précis)."""
    run = RUNS[run_id]
    queue = run.queue
    graph = get_graph()

    try:
        phase_id = graph.node(node_id).meta.phase
    except KeyError:
        _emit(loop, queue, {"type": "error", "message": f"Unknown node {node_id!r}"})
        _emit(loop, queue, {"type": "done"})
        run.finished = True
        return

    run.order = [node_id]
    _emit(loop, queue, {"type": "node", "phaseId": phase_id, "nodeId": node_id, "status": "running"})

    try:
        orch = Orchestrator(graph)
        result = orch.run_node(node_id, dict(ctx))
        event: dict[str, Any] = {
            "type": "node", "phaseId": phase_id, "nodeId": node_id,
            "status": "done" if result.success else "failed",
        }
        if not result.success and result.error:
            event["error"] = result.error
        _emit(loop, queue, event)
    except Exception as exc:
        logger.exception("Node retry %s failed", node_id)
        _emit(loop, queue, {"type": "error", "message": str(exc)})
    finally:
        _emit(loop, queue, {"type": "done"})
        run.finished = True


def start_pipeline_run(phases: list[str], ctx: dict[str, Any], loop: asyncio.AbstractEventLoop) -> str:
    run_id = str(uuid.uuid4())
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    kind = "full" if phases == FULL_PIPELINE_PHASE_ORDER else "phase"
    RUNS[run_id] = Run(run_id=run_id, kind=kind, queue=queue)
    threading.Thread(
        target=_run_pipeline_in_thread, args=(run_id, phases, ctx, loop),
        daemon=True, name=f"nexus-run-{run_id[:8]}",
    ).start()
    return run_id


def start_node_retry(node_id: str, ctx: dict[str, Any], loop: asyncio.AbstractEventLoop) -> str:
    run_id = str(uuid.uuid4())
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    RUNS[run_id] = Run(run_id=run_id, kind="node-retry", queue=queue)
    threading.Thread(
        target=_run_node_in_thread, args=(run_id, node_id, ctx, loop),
        daemon=True, name=f"nexus-retry-{run_id[:8]}",
    ).start()
    return run_id


def start_phase_retry(phase_id: str, ctx: dict[str, Any], loop: asyncio.AbstractEventLoop) -> str:
    run_id = str(uuid.uuid4())
    queue: "asyncio.Queue[dict]" = asyncio.Queue()
    RUNS[run_id] = Run(run_id=run_id, kind="phase-retry", queue=queue)
    threading.Thread(
        target=_run_pipeline_in_thread, args=(run_id, [phase_id], ctx, loop),
        daemon=True, name=f"nexus-retry-{run_id[:8]}",
    ).start()
    return run_id
