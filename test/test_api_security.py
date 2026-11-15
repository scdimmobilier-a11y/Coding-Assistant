"""
tests/test_api_security.py
─────────────────────────────
Tests d'intégration pour GET /api/security/findings,
POST /api/security/findings/{id}/ignore, .../unignore — Étape 1b.

Vérifie les TROIS cas de reachableFromEntry (voir security.py) :
  a) sans relatedNodeId -> null, requête jamais lancée
  b) relatedNodeId + Neo4j répond -> booléen réel (nécessite un vrai
     Neo4j — voir test_reachability_when_neo4j_is_up, skip sinon)
  c) relatedNodeId + Neo4j down -> null (cas par défaut dans ce sandbox,
     Neo4j n'y tourne pas)

Base SQLite isolée par test (fixture `tmp_path`) pour ne pas dépendre de
l'ordre d'exécution ni laisser de résidus entre tests.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """Redirige api.db.DB_PATH vers un fichier temporaire, pour que chaque
    test parte d'un état propre plutôt que de partager le fichier
    nexus_api.sqlite3 utilisé par ailleurs (README, autres modules de
    test). monkeypatch direct de l'attribut plutôt qu'une variable d'env +
    reload : `_connect()` relit `DB_PATH` à chaque appel (résolution de
    nom de module au moment de l'appel, pas figée à l'import), donc patcher
    l'attribut suffit et prend effet immédiatement, sans jonglage d'import."""
    from api import db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_security.sqlite3")
    return db_module


@pytest.fixture()
async def client(isolated_db):
    from api.main import app

    seed_findings = [
        {"id": "f1", "tool": "CodeQL", "severity": "warning", "title": "t1", "detail": "d1",
         "relatedNodeId": "payment-service"},
        {"id": "f2", "tool": "Semgrep", "severity": "info", "title": "t2", "detail": "d2",
         "relatedNodeId": None},
    ]
    isolated_db.init_db()
    isolated_db.seed_if_empty(seed_findings, [])

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_finding_without_related_node_id_is_null_without_attempting_a_query(client: AsyncClient):
    resp = await client.get("/api/security/findings")
    assert resp.status_code == 200
    findings = {f["id"]: f for f in resp.json()}
    assert findings["f2"]["relatedNodeId"] is None
    assert findings["f2"]["reachableFromEntry"] is None


@pytest.mark.anyio
async def test_finding_with_related_node_id_is_null_when_neo4j_is_down(client: AsyncClient):
    """Ce sandbox ne fait pas tourner Neo4j — reachableFromEntry doit être
    null (cas c), sans lever d'exception ni faire échouer la requête HTTP
    dans son ensemble."""
    resp = await client.get("/api/security/findings")
    assert resp.status_code == 200
    findings = {f["id"]: f for f in resp.json()}
    assert findings["f1"]["relatedNodeId"] == "payment-service"
    assert findings["f1"]["reachableFromEntry"] is None


@pytest.mark.anyio
async def test_ignore_then_unignore_round_trips(client: AsyncClient):
    resp = await client.post(
        "/api/security/findings/f1/ignore", json={"reason": "faux positif", "expiresOn": "2026-12-31"}
    )
    assert resp.status_code == 200

    findings = {f["id"]: f for f in (await client.get("/api/security/findings")).json()}
    assert findings["f1"]["ignored"] == {"reason": "faux positif", "expiresOn": "2026-12-31"}

    resp = await client.post("/api/security/findings/f1/unignore")
    assert resp.status_code == 200
    findings = {f["id"]: f for f in (await client.get("/api/security/findings")).json()}
    assert "ignored" not in findings["f1"] or findings["f1"]["ignored"] is None


@pytest.mark.anyio
async def test_ignore_unknown_finding_returns_404(client: AsyncClient):
    resp = await client.post(
        "/api/security/findings/does-not-exist/ignore", json={"reason": "x", "expiresOn": "2026-01-01"}
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_unignore_unknown_finding_returns_404(client: AsyncClient):
    resp = await client.post("/api/security/findings/does-not-exist/unignore")
    assert resp.status_code == 404
