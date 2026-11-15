"""nexus_unified.pack — enregistre le pack unified par-dessus le graphe de base.

`register_pack(G)` ajoute les ~227 nœuds du laboratoire (GPU/RL) et leurs
arêtes typées au graphe `G` déjà peuplé des 169 nœuds de base. Les nœuds du
pack sont en mode `strict_errors` : un handler qui renvoie `{"error": ...}`
compte comme un échec explicite.
"""
from __future__ import annotations

import logging
from typing import Any

from nexus_compose.graph import ComposabilityGraph, Edge, Node, NodeMeta

from .catalog import build_catalog
from .drivers import build_handlers
from .edges import PACK_EDGES

logger = logging.getLogger(__name__)


def register_pack(G: ComposabilityGraph) -> None:
    handlers = build_handlers()
    added_nodes = 0
    for nd in build_catalog():
        if nd["id"] in G._nodes:  # type: ignore[attr-defined]
            continue
        meta = NodeMeta(
            id=nd["id"], module=nd["module"], module_name=nd["module_name"],
            function=nd["function"], description=nd["description"], tag=nd["tag"],
            phase=nd["phase"], type=nd["type"], io_in=nd["io_in"], io_out=nd["io_out"],
            ref=nd["ref"], repo=nd.get("repo", "nexus_unified"),
            virtual=False, capabilities=tuple(nd.get("capabilities", ())),
            resources=dict(nd.get("resources", {})), apex_phase=nd.get("apex_phase", ""),
        )
        handler = handlers.get(nd["id"])
        if handler is not None:
            _hid = nd["id"]
            handler = _bind_node_id(handler, _hid)
        G.register(Node(meta, handler, strict_errors=True))
        added_nodes += 1

    added_edges = 0
    skipped = 0
    for src, tgt, lbl, etype in PACK_EDGES:
        try:
            G.connect(Edge(source=src, target=tgt, label=lbl, type=etype))
            added_edges += 1
        except KeyError as exc:
            logger.warning("pack: arête ignorée %s→%s : %s", src, tgt, exc)
            skipped += 1
    logger.info("pack unified : +%d nœuds, +%d arêtes (%d ignorées)",
                added_nodes, added_edges, skipped)
    if skipped:
        raise RuntimeError(f"pack unified : {skipped} arête(s) vers des nœuds inconnus")


def _bind_node_id(handler, node_id: str):
    def _wrapped(ctx):
        ctx = dict(ctx)
        ctx.setdefault("_node_id", node_id)
        return handler(ctx)
    return _wrapped
