"""
api.registry
────────────
Mission 2 (Meta Framework / Nexus Studio) — livrable D2.

Le registre de nœuds (`nexus_compose.graph.ComposabilityGraph`, 164 nœuds
réels + 5 virtuels, 218 arêtes) et le centre de diagnostic
(`NodeAvailabilityChecker`) existent déjà en mémoire process depuis la
Mission 1. Le seul chaînon manquant : rien de tout ça n'était exposé en
HTTP — `pipeline.py::GET /api/pipeline/phases` ne renvoie que `{id,
nodeCount}` par phase, jamais la métadonnée complète d'un nœud.

Ce module ne réimplémente rien : il sérialise ce qui existe déjà. Voir
`docs/registry_schema.md` pour le contrat JSON exact (c'est le même contrat
que respecte le registre statique de Nexus_Brain, cf. Mission 2 §D1).
"""
from __future__ import annotations

import asyncio
import dataclasses
from typing import Any

from fastapi import APIRouter

from .state import get_graph
from nexus_compose import NodeAvailabilityChecker
from nexus_compose.graph import Edge, NodeMeta

router = APIRouter(prefix="/api/registry", tags=["registry"])


# ── Sérialisation ────────────────────────────────────────────────────────────
# Explicite plutôt qu'implicite : on ne compte pas sur le jsonable_encoder de
# FastAPI pour deviner comment aplatir un NodeMeta/Edge. dataclasses.asdict()
# suffit pour NodeMeta (aucun champ Enum), mais Edge.type est un EdgeType
# (Enum) — on extrait sa `.value` à la main pour ne dépendre d'aucun
# comportement implicite de sérialisation d'Enum.

def _node_meta_to_dict(meta: NodeMeta) -> dict[str, Any]:
    return dataclasses.asdict(meta)


def _edge_to_dict(edge: Edge) -> dict[str, Any]:
    return {
        "source": edge.source,
        "target": edge.target,
        "label":  edge.label,
        "type":   edge.type.value,
    }


# ── D2.1 — GET /api/registry/nodes ───────────────────────────────────────────

@router.get("/nodes")
async def list_registry_nodes() -> dict[str, Any]:
    """
    Le registre complet : tous les champs `NodeMeta` de tous les nœuds
    (pas seulement phase+count comme `/api/pipeline/phases`), plus les
    arêtes typées. Lecture pure du graphe déjà construit en mémoire
    (`get_graph()` est `@lru_cache`-équivalent via `state._graph`) — aucune
    I/O, donc pas besoin de `asyncio.to_thread` ici (contrairement à
    `/diagnostics` ci-dessous).
    """
    graph = get_graph()
    return {
        "nodes": [_node_meta_to_dict(node.meta) for node in graph.nodes()],
        "edges": [_edge_to_dict(edge) for edge in graph.edges()],
    }


# ── D2.2 — GET /api/registry/diagnostics ─────────────────────────────────────

@router.get("/diagnostics")
async def registry_diagnostics() -> dict[str, list[dict[str, Any]]]:
    """
    Réexpose `NodeAvailabilityChecker.full_report()`, déjà écrit en
    Mission 1/avant — on ne fait ici que le brancher sur HTTP.

    `full_report()` fait de l'I/O bloquante par outil (`shutil.which`,
    `subprocess.run(..., timeout=5)`, `importlib.import_module`) pour
    jusqu'à ~15 outils : mêmes raisons que `security.py` de le passer par
    `asyncio.to_thread` plutôt que de bloquer la boucle événementielle.
    """
    checker = NodeAvailabilityChecker()
    report = await asyncio.to_thread(checker.full_report)
    return {
        category: [dataclasses.asdict(status) for status in statuses]
        for category, statuses in report.items()
    }


# ── D5.2 (Mission 2) — GET /api/registry/diagnostics/spoken ─────────────────
# leon_spoken_report() existait déjà (une phrase TTS-friendly résumant la
# disponibilité des outils) mais n'était atteignable que depuis CE process
# Python — ce endpoint est le seul chaînon manquant pour que le pont (D4/D5,
# nexus_core_leon_bridge/bridge/registry_aggregator.py::fetch_compose_spoken_report)
# puisse le lire et l'offrir à Nexus Core comme phrase de fin de tour
# optionnelle (nexus_brain.core.brain.NexusCore._maybe_append_diagnostics_report).
# Zéro nouvelle logique : `leon_spoken_report()` lui-même n'est pas modifié.

@router.get("/diagnostics/spoken")
async def registry_diagnostics_spoken() -> dict[str, str]:
    checker = NodeAvailabilityChecker()
    summary = await asyncio.to_thread(checker.leon_spoken_report)
    return {"summary": summary}
