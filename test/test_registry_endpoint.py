"""
tests/test_registry_endpoint.py
────────────────────────────────
Mission 2 (Meta Framework / Nexus Studio) — livrable D2, test requis en §4 :
« GET /api/registry/nodes renvoie les 164+5 nœuds avec tous les champs
NodeMeta ».

Le principe de D2 est : « aucune nouvelle logique de fond, ce livrable est
de la sérialisation d'un objet qui existe déjà ». Ces tests vérifient donc
moins « est-ce que le HTTP répond quelque chose de plausible » que « est-ce
que le HTTP répond EXACTEMENT ce que `nexus_compose.registry.build()`
produit directement » — pour prouver qu'on sérialise, qu'on n'a pas
réinventé une seconde source de vérité qui pourrait diverger.
"""

from __future__ import annotations

import dataclasses
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from httpx import ASGITransport, AsyncClient

from nexus_compose import build_graph
from nexus_compose.graph import NodeMeta


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Même fixture que test_api_security.py — ces endpoints ne touchent
    pas la base findings/branches, mais le lifespan de l'app l'initialise
    quand même à l'entrée du client ; isoler évite d'écrire dans le
    nexus_api.sqlite3 partagé comme effet de bord."""
    from api import db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_registry.sqlite3")
    return db_module


@pytest.fixture()
async def client(isolated_db):
    from api.main import app

    isolated_db.init_db()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── GET /api/registry/nodes ──────────────────────────────────────────────────

@pytest.mark.anyio
async def test_nodes_endpoint_returns_all_164_plus_5_virtual_nodes(client: AsyncClient):
    resp = await client.get("/api/registry/nodes")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["nodes"]) == 169  # 164 nodes.json + 5 VIRTUAL_DEFS


@pytest.mark.anyio
async def test_nodes_endpoint_serialises_every_nodemeta_field(client: AsyncClient):
    """« tous les champs NodeMeta » — vérifié contre les champs réels de la
    dataclass plutôt qu'une liste recopiée à la main, pour que ce test
    reste vrai si NodeMeta gagne un champ demain."""
    expected_fields = {f.name for f in dataclasses.fields(NodeMeta)}

    resp = await client.get("/api/registry/nodes")
    data = resp.json()

    assert len(data["nodes"]) > 0
    for node in data["nodes"]:
        assert set(node.keys()) == expected_fields


@pytest.mark.anyio
async def test_nodes_endpoint_matches_direct_graph_construction_exactly(client: AsyncClient):
    """Preuve de non-réinvention : les 169 ids renvoyés par HTTP sont
    exactement ceux que produit build_graph() en direct, sans écart."""
    direct_graph = build_graph()
    expected_ids = {node.meta.id for node in direct_graph.nodes()}

    resp = await client.get("/api/registry/nodes")
    data = resp.json()
    actual_ids = {node["id"] for node in data["nodes"]}

    assert actual_ids == expected_ids


@pytest.mark.anyio
async def test_nodes_endpoint_returns_all_218_typed_edges(client: AsyncClient):
    direct_graph = build_graph()
    expected_edge_count = sum(1 for _ in direct_graph.edges())

    resp = await client.get("/api/registry/nodes")
    data = resp.json()

    assert len(data["edges"]) == expected_edge_count == 218
    valid_edge_types = {
        "data_flow", "transform", "validate", "query", "inject",
        "store", "indirect", "report", "simulate", "analyze",
    }
    for edge in data["edges"]:
        assert {"source", "target", "label", "type"} <= set(edge.keys())
        assert edge["type"] in valid_edge_types


@pytest.mark.anyio
async def test_nodes_endpoint_exposes_new_capabilities_field_defaulting_empty(client: AsyncClient):
    """D1 : capabilities est un champ optionnel — les 169 nœuds existants
    ne le renseignent pas encore (cf. docs/registry_schema.md), il doit
    donc apparaître comme une liste vide plutôt que d'être absent."""
    resp = await client.get("/api/registry/nodes")
    data = resp.json()

    assert all("capabilities" in node for node in data["nodes"])
    assert all(node["capabilities"] == [] for node in data["nodes"])


@pytest.mark.anyio
async def test_nodes_endpoint_known_node_has_expected_content(client: AsyncClient):
    """Un nœud connu et stable (le pont opaque vers UnifiedSystem, cf.
    Mission 2 §1) a bien le contenu attendu, pas juste la bonne forme."""
    resp = await client.get("/api/registry/nodes")
    data = resp.json()
    by_id = {node["id"]: node for node in data["nodes"]}

    assert "codegen.unified_system" in by_id
    node = by_id["codegen.unified_system"]
    assert node["phase"] == "codegen"
    assert node["type"] == "bridge"
    assert node["virtual"] is False


# ── GET /api/registry/diagnostics ────────────────────────────────────────────

@pytest.mark.anyio
async def test_diagnostics_endpoint_returns_the_six_report_categories(client: AsyncClient):
    resp = await client.get("/api/registry/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {
        "available", "unavailable", "external", "frontend", "saas", "manual",
    }
    for statuses in data.values():
        assert isinstance(statuses, list)


@pytest.mark.anyio
async def test_diagnostics_endpoint_tool_status_has_expected_shape(client: AsyncClient):
    resp = await client.get("/api/registry/diagnostics")
    data = resp.json()

    all_statuses = [s for statuses in data.values() for s in statuses]
    assert len(all_statuses) > 0
    expected_fields = {
        "name", "available", "version", "path", "reason",
        "install", "category", "node_ids",
    }
    for status in all_statuses:
        assert set(status.keys()) == expected_fields


@pytest.mark.anyio
async def test_diagnostics_endpoint_matches_direct_checker_call(client: AsyncClient):
    """Preuve de non-réinvention, même principe que pour /nodes : le set de
    noms d'outils « available » via HTTP == celui obtenu en appelant
    NodeAvailabilityChecker().full_report() directement dans ce process."""
    from nexus_compose import NodeAvailabilityChecker

    direct_report = NodeAvailabilityChecker().full_report()
    expected_available = {status.name for status in direct_report["available"]}

    resp = await client.get("/api/registry/diagnostics")
    data = resp.json()
    actual_available = {status["name"] for status in data["available"]}

    assert actual_available == expected_available


# ── GET /api/registry/diagnostics/spoken (D5.2) ──────────────────────────────

@pytest.mark.anyio
async def test_diagnostics_spoken_endpoint_returns_a_summary_sentence(client: AsyncClient):
    resp = await client.get("/api/registry/diagnostics/spoken")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"summary"}
    assert isinstance(data["summary"], str)
    assert data["summary"].endswith(".")


@pytest.mark.anyio
async def test_diagnostics_spoken_endpoint_matches_direct_leon_spoken_report_call(client: AsyncClient):
    """Même principe de preuve que les tests /nodes et /diagnostics
    ci-dessus : ce endpoint ne fait QUE réexposer leon_spoken_report(),
    déjà existant — pas une variante recalculée séparément."""
    from nexus_compose import NodeAvailabilityChecker

    expected = NodeAvailabilityChecker().leon_spoken_report()

    resp = await client.get("/api/registry/diagnostics/spoken")
    assert resp.json()["summary"] == expected
