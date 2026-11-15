"""
api.security
==============

GET /api/security/findings, POST /api/security/findings/{id}/ignore,
POST /api/security/findings/{id}/unignore — Étape 1b du prompt de fusion.

Le calcul d'accessibilité (`reachableFromEntry`) suit exactement les trois
cas documentés dans le prompt de fusion, PAS un seul fallback générique :
  a) finding sans `relatedNodeId`      -> null, requête JAMAIS lancée
  b) `relatedNodeId` + Neo4j répond    -> booléen réel
  c) `relatedNodeId` + Neo4j down      -> null + log, distinct du cas (a)
     même si la valeur JSON renvoyée est identique.

Requête Cypher en `EXISTS { ... }`, pas `MATCH p = (...) RETURN
count(p) > 0` : la forme EXISTS s'arrête au premier chemin trouvé au lieu
de matérialiser tous les chemins — recommandation de performance Cypher
actuelle pour un pattern à longueur variable (`*1..8`).

Les findings eux-mêmes (table `findings`, voir db.py) sont amorcés avec des
données de démonstration réalistes au démarrage — parser la sortie réelle
de Bearer/Semgrep/CodeQL en SecurityFinding est une fonctionnalité séparée,
plus substantielle, non couverte ici (voir db.py::seed_if_empty).

Le driver `neo4j` étant synchrone/bloquant (comme sqlite3, comme
Orchestrator), chaque requête passe par `asyncio.to_thread`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db

logger = logging.getLogger("nexus_assistant.api.security")

router = APIRouter(prefix="/api/security", tags=["security"])

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "nexuscompose")  # défaut = docker-compose.yml NEO4J_AUTH
ENTRY_COMPONENT_ID = os.environ.get("NEO4J_ENTRY_COMPONENT_ID", "marchand")


def _check_reachability_blocking(related_node_id: str) -> Optional[bool]:
    """Synchrone/bloquant par design — appeler uniquement via
    asyncio.to_thread. Retourne None (pas False) si Neo4j est injoignable :
    None signifie ici "non déterminé", jamais confondu avec un booléen réel
    par l'appelant (voir _reachable_from_entry_for)."""
    try:
        from neo4j import GraphDatabase, RoutingControl
        from neo4j.exceptions import Neo4jError, ServiceUnavailable
    except ImportError:
        logger.warning("Le driver neo4j n'est pas installé (`pip install neo4j`) — accessibilité non calculée")
        return None

    try:
        # connection_timeout / max_transaction_retry_time réduits :
        # découvert en testant (pas supposé) que les défauts du driver
        # retentent avec un backoff exponentiel pendant ~35 s avant
        # d'abandonner quand Neo4j est injoignable — inacceptable pour un
        # endpoint HTTP synchrone appelé à chaque chargement de la vue
        # sécurité. 2 s convient largement pour un Neo4j local qui répond.
        driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD),
            connection_timeout=2.0,
            max_transaction_retry_time=2.0,
        )
        try:
            records, _, _ = driver.execute_query(
                "MATCH (start:Component {id: $start_id}), (target:Component {id: $finding_node_id}) "
                "RETURN EXISTS { (start)-[:CALLS*1..8]->(target) } AS reachable",
                start_id=ENTRY_COMPONENT_ID,
                finding_node_id=related_node_id,
                routing_=RoutingControl.READ,
                database_="neo4j",
            )
            if not records:
                # Le nœud cible n'existe pas (encore) dans le graphe Neo4j —
                # distinct d'une panne, mais tout aussi "non déterminé" pour
                # l'instant : le graphe de menaces n'a peut-être pas encore
                # été construit pour ce composant.
                logger.info("Aucun composant Neo4j trouvé pour relatedNodeId=%r", related_node_id)
                return None
            return bool(records[0]["reachable"])
        finally:
            driver.close()
    except (ServiceUnavailable, Neo4jError, OSError) as exc:
        logger.warning("Neo4j indisponible, accessibilité non calculée pour %r : %s", related_node_id, exc)
        return None


async def _reachable_from_entry_for(related_node_id: Optional[str]) -> Optional[bool]:
    if related_node_id is None:
        # Cas (a) : non applicable, la requête n'est JAMAIS lancée.
        return None
    # Cas (b)/(c) : requête tentée ; None ici veut dire "Neo4j indisponible",
    # pas "non applicable" — même valeur JSON que le cas (a), raison
    # différente, tracée dans les logs (voir _check_reachability_blocking).
    return await asyncio.to_thread(_check_reachability_blocking, related_node_id)


class IgnoreRequest(BaseModel):
    reason: str
    expiresOn: str


@router.get("/findings")
async def list_findings() -> list[dict[str, Any]]:
    findings = await asyncio.to_thread(db.list_findings)
    # Concurrent plutôt que séquentiel : même avec le timeout réduit
    # ci-dessus, attendre chaque finding l'un après l'autre ajouterait un
    # délai proportionnel au nombre de findings ayant un relatedNodeId.
    reachabilities = await asyncio.gather(
        *(_reachable_from_entry_for(f.get("relatedNodeId")) for f in findings)
    )
    return [{**f, "reachableFromEntry": r} for f, r in zip(findings, reachabilities)]


@router.post("/findings/{finding_id}/ignore")
async def ignore_finding(finding_id: str, body: IgnoreRequest) -> dict[str, str]:
    ok = await asyncio.to_thread(db.set_finding_ignored, finding_id, body.reason, body.expiresOn)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown finding {finding_id!r}")
    return {"status": "ok"}


@router.post("/findings/{finding_id}/unignore")
async def unignore_finding(finding_id: str) -> dict[str, str]:
    ok = await asyncio.to_thread(db.set_finding_ignored, finding_id, None, None)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown finding {finding_id!r}")
    return {"status": "ok"}
