"""
bridge.registry_aggregator
=============================

Mission 2 (Meta Framework / Nexus Studio) — livrable D4 : « un seul
catalogue pour tout le système ». Fusionne :
  - le registre `nexus_compose` (169 nœuds, 218 arêtes), atteint en HTTP via
    `GET {NEXUS_COMPOSE_API_URL}/api/registry/nodes` (D2) — jamais en import
    Python direct, les deux services tournent dans des conteneurs séparés
    (cf. Nexus_Assistant/docs/registry_schema.md §0) ;
  - le registre statique de Nexus Brain (D3, `nexus_brain.registry`),
    importé directement puisque CE pont dépend déjà de `nexus_brain` pour
    construire son propre `NexusCore` (cf. `core_factory.py`) — l'Invariant
    « sans import croisé » de D1 concerne nexus_compose <-> Nexus_Brain,
    pas le pont, qui est justement le point de rencontre des deux.

C'est ce catalogue fusionné dont `codegen_adapter.py` (Mission 1, D3) a
besoin pour savoir que `codegen.unified_system` existe et comment
l'atteindre — cf. le document de mission, §D4.

D5 (optionnel, traité une fois D1→D4 stables) ajoute deux petits
compléments à ce module, sans nouvelle logique de fond :
  - `fetch_compose_spoken_report()` — la forme HTTP de
    `leon_spoken_report()`, déjà existant côté nexus_compose ;
  - `query_registry()` — le point d'entrée partagé entre
    `GET /registry/full` et l'outil ReAct minimal de NexusCore, qui rend
    littéralement vraie l'idée « le Brain peut interroger son propre
    système ».

Écart assumé par rapport à la lettre du document de mission : celui-ci
décrit un agrégateur qui fusionne "au démarrage du pont". Ce module fait le
choix — documenté ici, pas silencieux — de rafraîchir à chaque appel plutôt
qu'une seule fois au démarrage. Raison concrète, pas une préférence de
style : le README racine du monorepo documente un ordre de démarrage où ce
pont démarre AVANT l'API Nexus Assistant (donc avant que
`GET /api/registry/nodes` soit joignable) — une fusion figée au démarrage
manquerait alors le catalogue nexus_compose en permanence, jusqu'à un
redémarrage manuel du pont. Un GET frais à chaque appel élimine cette
course sans logique de cache/invalidation à maintenir, et reprend
exactement le pattern déjà utilisé par `codegen_adapter.deliver_software()`
pour ce même service nexus_compose (requête HTTP à chaque appel, jamais
mise en cache).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import requests

from .config import BridgeConfig, get_bridge_config

logger = logging.getLogger(__name__)


class RegistryAggregatorError(RuntimeError):
    """Levée quand les deux catalogues ne peuvent pas être fusionnés en
    sécurité — aujourd'hui, uniquement en cas de collision d'id entre
    nexus_compose et Nexus Brain. Ne devrait jamais se produire par
    construction (espaces de noms disjoints, cf.
    docs/registry_schema.md §3.2) mais vérifié activement plutôt que
    supposé : mieux vaut un 500 explicite qu'une entrée du registre
    silencieusement écrasée par l'autre."""


# ── D2, en HTTP ──────────────────────────────────────────────────────────────

def fetch_compose_registry(cfg: Optional[BridgeConfig] = None) -> dict[str, Any]:
    """
    GET {NEXUS_COMPOSE_API_URL}/api/registry/nodes (D2). Dégrade
    gracieusement — {"nodes": [], "edges": []}, jamais d'exception — si
    nexus_compose est injoignable : même posture que la gestion Neo4j-down
    de `api/security.py` côté Nexus_Assistant. Un endpoint d'introspection
    qui plante dès que l'un des deux services qu'il introspecte est encore
    en train de démarrer serait moins fiable que le système qu'il décrit.
    """
    cfg = cfg or get_bridge_config()
    url = f"{cfg.nexus_compose_api_url}/api/registry/nodes"
    try:
        resp = requests.get(url, timeout=cfg.nexus_compose_api_timeout_s)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        logger.warning("nexus_compose registry unreachable at %s: %s", url, exc)
        return {"nodes": [], "edges": []}

    return {"nodes": data.get("nodes", []), "edges": data.get("edges", [])}


def fetch_compose_spoken_report(cfg: Optional[BridgeConfig] = None) -> Optional[str]:
    """
    D5.2 (Mission 2) — la forme HTTP-atteignable du
    `NodeAvailabilityChecker.leon_spoken_report()` déjà existant côté
    nexus_compose (`GET {NEXUS_COMPOSE_API_URL}/api/registry/diagnostics/spoken`).
    Retourne None — jamais d'exception — si nexus_compose est injoignable,
    même posture fail-soft que `fetch_compose_registry()` ci-dessus : une
    phrase de diagnostic manquante ne doit jamais faire échouer un tour par
    ailleurs normal. C'est cette fonction qu'on injecte dans NexusCore
    comme `diagnostics_report_fn` (cf. core_factory.py et
    nexus_brain.core.brain.NexusCore._maybe_append_diagnostics_report).
    """
    cfg = cfg or get_bridge_config()
    url = f"{cfg.nexus_compose_api_url}/api/registry/diagnostics/spoken"
    try:
        resp = requests.get(url, timeout=cfg.nexus_compose_api_timeout_s)
        resp.raise_for_status()
        return resp.json().get("summary")
    except requests.RequestException as exc:
        logger.warning("nexus_compose spoken diagnostics unreachable at %s: %s", url, exc)
        return None


# ── D3 + D2 → D4 ─────────────────────────────────────────────────────────────

def aggregate_full_registry(cfg: Optional[BridgeConfig] = None) -> dict[str, Any]:
    """Le catalogue unique — cf. module docstring pour le choix "par appel"
    plutôt que "au démarrage". Lève RegistryAggregatorError en cas de
    collision d'id plutôt que d'écraser silencieusement une entrée."""
    # Import différé (pas en tête de module) : évite un import circulaire
    # si `nexus_brain` venait un jour à dépendre de ce paquet pour autre
    # chose, et rend explicite, au point d'appel, que c'est la SEULE
    # dépendance Python croisée que D4 introduit (cf. docstring ci-dessus).
    from nexus_brain import registry as brain_registry

    compose = fetch_compose_registry(cfg)
    brain_nodes = brain_registry.list_nodes()

    compose_ids = {node["id"] for node in compose["nodes"]}
    brain_ids = {node["id"] for node in brain_nodes}
    collisions = compose_ids & brain_ids
    if collisions:
        raise RegistryAggregatorError(
            "Id collision between the nexus_compose and Nexus Brain "
            f"registries: {sorted(collisions)!r} — fix the offending id(s) "
            "before merging (see docs/registry_schema.md §3.2)."
        )

    return {
        "nodes": compose["nodes"] + brain_nodes,
        "edges": list(compose["edges"]),  # Nexus Brain n'a pas d'arêtes propres (D3)
    }


def filter_by_capability(full_registry: dict[str, Any], capability: str) -> dict[str, Any]:
    """
    D1 : « une capacité devient un simple filtre sur le registre de
    nœuds » — GET /registry/full?capability=codage. Les arêtes sont
    restreintes à celles dont LES DEUX extrémités survivent au filtre, pour
    que la réponse ne référence jamais un id de nœud absent de `nodes`.
    """
    kept_nodes = [
        node for node in full_registry["nodes"]
        if capability in (node.get("capabilities") or [])
    ]
    kept_ids = {node["id"] for node in kept_nodes}
    kept_edges = [
        edge for edge in full_registry["edges"]
        if edge["source"] in kept_ids and edge["target"] in kept_ids
    ]
    return {"nodes": kept_nodes, "edges": kept_edges}


def query_registry(capability: Optional[str] = None, cfg: Optional[BridgeConfig] = None) -> dict[str, Any]:
    """
    D5.3 (Mission 2) — le point d'entrée unique derrière DEUX chemins
    d'accès au même résultat :
      - `GET /registry/full[?capability=]` (bridge/server.py, D4/D5) ;
      - l'outil ReAct minimal `query_registry` de NexusCore
        (bridge/core_factory.py::_execute_query_registry_step), « le Brain
        peut interroger son propre système » au sens littéral du document
        de mission.

    Le second chemin appelle CETTE fonction Python directement plutôt que
    de boucler en HTTP sur `GET /registry/full` — les deux tournent déjà
    dans le même process (celui du pont) : un aller-retour réseau vers
    soi-même n'apporterait rien de plus qu'un appel de fonction, pour un
    coût et une source d'échec en plus. Si `query_registry` devait un jour
    tourner depuis un AUTRE process que le pont, un vrai appel HTTP
    deviendrait nécessaire — mais ce serait alors un changement d'un
    endroit unique (ce module reste le seul point de vérité).
    """
    full = aggregate_full_registry(cfg)
    if capability is not None:
        full = filter_by_capability(full, capability)
    return full
