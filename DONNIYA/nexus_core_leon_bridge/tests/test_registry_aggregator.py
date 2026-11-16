"""
tests.test_registry_aggregator
==================================

Mission 2 (Meta Framework / Nexus Studio) — livrable D4, test requis en
§4 : « fusion correcte avec un mock HTTP pour nexus_compose, absence de
collision d'id entre les deux catalogues ».

Comme le reste de la suite du pont (cf. tests/fakes.py, docstring), le vrai
`nexus_compose` n'est jamais démarré ici — `requests.get` est mocké au
même endroit et avec le même style que `tests/test_codegen_adapter.py`
côté Nexus_Brain (`_FakeResponse` + `mock.patch("...requests.get", ...)`).

Pourquoi un échantillon d'ids "réels" plutôt qu'un import direct de
nexus_compose : ce dépôt n'a et ne doit pas avoir de dépendance Python vers
Nexus_Assistant (conteneurs séparés, cf.
Nexus_Assistant/docs/registry_schema.md §0) — `_REAL_COMPOSE_ID_SAMPLE`
ci-dessous est une copie figée d'un id réel par module de `nodes.json`
(vérifiée à la main au moment d'écrire ce test, pas inventée), pour tester
l'absence de collision contre de vraies données plutôt qu'un fixture
jouet qui pourrait cacher un problème de préfixe.

La fusion réelle bout-en-bout (169 nœuds nexus_compose + 14 nœuds Nexus
Brain = 183, 0 collision) a par ailleurs été vérifiée manuellement pendant
le développement en démarrant les deux vrais serveurs — ce fichier ne
reproduit pas ce montage à deux process (lent, non hermétique), il prouve
la même propriété par un mock HTTP, comme demandé par la mission.
"""

from __future__ import annotations

from unittest import mock

import pytest
import requests
from fastapi.testclient import TestClient

from bridge.config import BridgeConfig
from bridge.core_factory import build_nexus_core_and_runner
from bridge.registry_aggregator import (
    RegistryAggregatorError,
    aggregate_full_registry,
    fetch_compose_registry,
    filter_by_capability,
)
from bridge.server import create_app
from nexus_brain.registry import BRAIN_NODES
from tests.fakes import FakeLeonClient

# Un id réel par module de nodes.json + les 5 nœuds virtuels — copié à la
# main depuis Nexus_Assistant/nexus_compose/nodes.json, pas inventé (cf.
# docstring de module ci-dessus).
_REAL_COMPOSE_ID_SAMPLE = [
    "bearer.bearer_scan", "bf.bfq_testfilters", "c4if.executeaacstrategycommand",
    "clab.clab_generate", "codegen.unified_system", "codeql.codeql_database_create",
    "likec4.likec4_build", "neo4j.create", "opa.opa_eval", "pytm.tm_process",
    "q2d.generate", "semgrep.semgrep_scan", "struct.workspaceparser",
    "td.threatmodelcontroller_create", "tmdd.tmdd_init",
    "LEON", "CODEBASE", "CODE_GENERATED", "REPORT", "PRODUCTION",
]


def _minimal_node(node_id: str) -> dict:
    """Un dict au format NodeMeta minimal mais complet — juste assez pour
    exercer la fusion, pas un test de forme (celui-là vit dans
    test_registry_endpoint.py côté Nexus_Assistant)."""
    return {
        "id": node_id, "module": node_id.split(".")[0], "module_name": node_id,
        "function": "f()", "description": "d", "tag": "x.y", "phase": "elicit",
        "type": "generate", "io_in": "in", "io_out": "out", "ref": "r",
        "repo": "", "virtual": False, "subsection": None, "capabilities": [],
    }


class _FakeResponse:
    """Même pattern que Nexus_Brain/tests/test_codegen_adapter.py."""

    def __init__(self, status_code: int = 200, json_body=None):
        self.status_code = status_code
        self._json_body = json_body if json_body is not None else {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._json_body


def _fake_get_returning(nodes: list, edges: list | None = None):
    def fake_get(url, timeout=None):
        return _FakeResponse(200, {"nodes": nodes, "edges": edges or []})
    return fake_get


# ── fetch_compose_registry ────────────────────────────────────────────────────

def test_fetch_compose_registry_calls_the_documented_endpoint():
    captured = {}

    def fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return _FakeResponse(200, {"nodes": [_minimal_node("q2d.generate")], "edges": []})

    cfg = BridgeConfig(nexus_compose_api_url="http://nexus-compose.test", nexus_compose_api_timeout_s=3.0)
    with mock.patch("bridge.registry_aggregator.requests.get", fake_get):
        result = fetch_compose_registry(cfg)

    assert captured["url"] == "http://nexus-compose.test/api/registry/nodes"
    assert captured["timeout"] == 3.0
    assert result["nodes"][0]["id"] == "q2d.generate"


def test_fetch_compose_registry_degrades_gracefully_when_unreachable():
    def fake_get(url, timeout=None):
        raise requests.ConnectionError("connection refused")

    with mock.patch("bridge.registry_aggregator.requests.get", fake_get):
        result = fetch_compose_registry(BridgeConfig())

    assert result == {"nodes": [], "edges": []}


def test_fetch_compose_registry_degrades_gracefully_on_http_error_status():
    with mock.patch(
        "bridge.registry_aggregator.requests.get",
        lambda url, timeout=None: _FakeResponse(500, {}),
    ):
        result = fetch_compose_registry(BridgeConfig())

    assert result == {"nodes": [], "edges": []}


# ── aggregate_full_registry ───────────────────────────────────────────────────

def test_aggregate_merges_compose_and_all_brain_nodes():
    compose_nodes = [_minimal_node("q2d.generate"), _minimal_node("LEON")]
    with mock.patch("bridge.registry_aggregator.requests.get", _fake_get_returning(compose_nodes)):
        result = aggregate_full_registry(BridgeConfig())

    assert len(result["nodes"]) == len(compose_nodes) + len(BRAIN_NODES)
    ids = {n["id"] for n in result["nodes"]}
    assert "q2d.generate" in ids
    assert "LEON" in ids
    assert "core.brain" in ids  # un nœud Nexus Brain (D3) est bien présent
    assert "adapters.codegen_adapter" in ids


def test_aggregate_no_collision_against_real_compose_id_sample():
    """Le test demandé par la mission §4 : fusion correcte + absence de
    collision — vérifié contre un échantillon d'ids RÉELS de
    nexus_compose (cf. _REAL_COMPOSE_ID_SAMPLE), pas un fixture jouet."""
    compose_nodes = [_minimal_node(node_id) for node_id in _REAL_COMPOSE_ID_SAMPLE]
    with mock.patch("bridge.registry_aggregator.requests.get", _fake_get_returning(compose_nodes)):
        result = aggregate_full_registry(BridgeConfig())  # ne doit PAS lever

    all_ids = [n["id"] for n in result["nodes"]]
    assert len(all_ids) == len(_REAL_COMPOSE_ID_SAMPLE) + len(BRAIN_NODES)
    assert len(all_ids) == len(set(all_ids))  # aucune collision


def test_aggregate_raises_registry_aggregator_error_on_synthetic_id_collision():
    """La garde anti-collision se déclenche vraiment — testé avec un id
    volontairement dupliqué (core.brain existe côté Nexus Brain), pas
    seulement l'absence de collision sur des données propres ci-dessus."""
    compose_nodes = [_minimal_node("q2d.generate"), _minimal_node("core.brain")]
    with mock.patch("bridge.registry_aggregator.requests.get", _fake_get_returning(compose_nodes)):
        with pytest.raises(RegistryAggregatorError, match="core.brain"):
            aggregate_full_registry(BridgeConfig())


def test_aggregate_edges_come_only_from_compose_not_from_brain():
    compose_nodes = [_minimal_node("q2d.generate"), _minimal_node("LEON")]
    compose_edges = [{"source": "LEON", "target": "q2d.generate", "label": "l", "type": "data_flow"}]
    with mock.patch(
        "bridge.registry_aggregator.requests.get",
        _fake_get_returning(compose_nodes, compose_edges),
    ):
        result = aggregate_full_registry(BridgeConfig())

    assert result["edges"] == compose_edges


def test_aggregate_degrades_to_brain_only_when_compose_unreachable():
    with mock.patch(
        "bridge.registry_aggregator.requests.get",
        lambda url, timeout=None: (_ for _ in ()).throw(requests.ConnectionError("down")),
    ):
        result = aggregate_full_registry(BridgeConfig())

    assert len(result["nodes"]) == len(BRAIN_NODES)
    assert result["edges"] == []


# ── filter_by_capability ──────────────────────────────────────────────────────

def test_filter_by_capability_keeps_only_matching_nodes_and_their_edges():
    registry = {
        "nodes": [
            {**_minimal_node("a"), "capabilities": ["codage"]},
            {**_minimal_node("b"), "capabilities": []},
            {**_minimal_node("c"), "capabilities": ["codage"]},
        ],
        "edges": [
            {"source": "a", "target": "b", "label": "l", "type": "data_flow"},  # b filtré -> arête tombe
            {"source": "a", "target": "c", "label": "l", "type": "data_flow"},  # a et c gardés -> arête garde
        ],
    }
    result = filter_by_capability(registry, "codage")

    assert {n["id"] for n in result["nodes"]} == {"a", "c"}
    assert result["edges"] == [{"source": "a", "target": "c", "label": "l", "type": "data_flow"}]


def test_filter_by_capability_on_real_brain_registry_returns_codegen_adapter_only():
    with mock.patch("bridge.registry_aggregator.requests.get", _fake_get_returning([])):
        full = aggregate_full_registry(BridgeConfig())
    filtered = filter_by_capability(full, "codage")

    assert [n["id"] for n in filtered["nodes"]] == ["adapters.codegen_adapter"]


# ── endpoints HTTP : /registry/nodes, /registry/full ──────────────────────────

@pytest.fixture()
def client():
    core, runner = build_nexus_core_and_runner(leon_client=FakeLeonClient())
    app = create_app(core=core, runner=runner)
    return TestClient(app)


def test_registry_nodes_endpoint_returns_the_brain_registry(client: TestClient):
    resp = client.get("/registry/nodes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == len(BRAIN_NODES)
    assert data["edges"] == []


def test_registry_full_endpoint_degrades_when_compose_unreachable(client: TestClient):
    with mock.patch(
        "bridge.registry_aggregator.requests.get",
        lambda url, timeout=None: (_ for _ in ()).throw(requests.ConnectionError("down")),
    ):
        resp = client.get("/registry/full")

    assert resp.status_code == 200
    assert len(resp.json()["nodes"]) == len(BRAIN_NODES)


def test_registry_full_endpoint_merges_when_compose_reachable(client: TestClient):
    compose_nodes = [_minimal_node("q2d.generate")]
    with mock.patch("bridge.registry_aggregator.requests.get", _fake_get_returning(compose_nodes)):
        resp = client.get("/registry/full")

    assert resp.status_code == 200
    ids = {n["id"] for n in resp.json()["nodes"]}
    assert "q2d.generate" in ids
    assert "core.brain" in ids


def test_registry_full_endpoint_capability_query_param(client: TestClient):
    with mock.patch("bridge.registry_aggregator.requests.get", _fake_get_returning([])):
        resp = client.get("/registry/full", params={"capability": "codage"})

    assert resp.status_code == 200
    assert [n["id"] for n in resp.json()["nodes"]] == ["adapters.codegen_adapter"]


def test_registry_full_endpoint_returns_500_with_readable_detail_on_collision(client: TestClient):
    compose_nodes = [_minimal_node("core.memory")]  # collide avec un vrai id Nexus Brain
    with mock.patch("bridge.registry_aggregator.requests.get", _fake_get_returning(compose_nodes)):
        resp = client.get("/registry/full")

    assert resp.status_code == 500
    assert "core.memory" in resp.json()["detail"]
