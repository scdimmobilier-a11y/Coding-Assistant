"""
tests/test_api_providers.py
──────────────────────────────
Tests d'intégration pour le dashboard "Connexion API" — GET/POST/PATCH/
DELETE /api/providers, activate/deactivate, test de connexion, et
vérification que nexus_compose.llm_config.get_llm_config() lit bien le
fournisseur activé depuis la même base.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    from api import db as db_module

    db_path = tmp_path / "test_providers.sqlite3"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    # nexus_compose/llm_config.py résout le chemin de la DB via cette
    # variable d'environnement (voir module docstring) — doit pointer vers
    # la même DB isolée pour que get_llm_config() voie le fournisseur actif
    # créé par ces tests.
    monkeypatch.setenv("NEXUS_API_DB_PATH", str(db_path))
    db_module.init_db()
    return db_module


@pytest.fixture()
async def client(isolated_db):
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _valid_payload(**overrides):
    payload = {
        "provider": "openrouter",
        "label": "Mon compte OpenRouter",
        "model": "openai/gpt-oss-120b",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "api_type": "chat_completions",
        "auth_type": "bearer",
        "api_key": "sk-or-1234567890abcdef",
        "headers": {"X-Title": "Nexus Assistant"},
        "timeout_s": 30,
        "max_retries": 3,
        "http2": True,
        "compression": True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
async def test_create_list_get_provider_masks_api_key(client):
    resp = await client.post("/api/providers", json=_valid_payload())
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["provider"] == "openrouter"
    assert body["hasApiKey"] is True
    assert "sk-or-1234567890abcdef" not in json.dumps(body)  # jamais en clair
    assert body["apiKeyMasked"].endswith("cdef")
    assert body["isActive"] is False

    listing = (await client.get("/api/providers")).json()
    assert len(listing) == 1
    assert listing[0]["id"] == body["id"]

    detail = (await client.get(f"/api/providers/{body['id']}")).json()
    assert detail["label"] == "Mon compte OpenRouter"


@pytest.mark.anyio
async def test_create_rejects_invalid_fields_with_422(client):
    resp = await client.post("/api/providers", json=_valid_payload(model="bad model!"))
    assert resp.status_code == 422
    assert resp.json()["detail"]["field"] == "model"

    resp2 = await client.post("/api/providers", json=_valid_payload(endpoint="http://api.example.com/v1"))
    assert resp2.status_code == 422
    assert resp2.json()["detail"]["field"] == "endpoint"

    resp3 = await client.post("/api/providers", json=_valid_payload(headers={"Authorization": "Bearer x"}))
    assert resp3.status_code == 422
    assert resp3.json()["detail"]["field"] == "headers"


@pytest.mark.anyio
async def test_patch_updates_only_provided_fields(client):
    created = (await client.post("/api/providers", json=_valid_payload())).json()
    resp = await client.patch(f"/api/providers/{created['id']}", json={"label": "Renommé"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["label"] == "Renommé"
    assert body["model"] == created["model"]  # inchangé


@pytest.mark.anyio
async def test_delete_provider(client):
    created = (await client.post("/api/providers", json=_valid_payload())).json()
    resp = await client.delete(f"/api/providers/{created['id']}")
    assert resp.status_code == 204
    assert (await client.get(f"/api/providers/{created['id']}")).status_code == 404
    assert (await client.delete(f"/api/providers/{created['id']}")).status_code == 404


@pytest.mark.anyio
async def test_activate_is_exclusive(client):
    p1 = (await client.post("/api/providers", json=_valid_payload(label="Fournisseur 1"))).json()
    p2 = (await client.post("/api/providers", json=_valid_payload(label="Fournisseur 2"))).json()

    r1 = await client.post(f"/api/providers/{p1['id']}/activate")
    assert r1.json()["isActive"] is True

    r2 = await client.post(f"/api/providers/{p2['id']}/activate")
    assert r2.json()["isActive"] is True

    # p1 doit avoir été désactivé automatiquement
    p1_after = (await client.get(f"/api/providers/{p1['id']}")).json()
    assert p1_after["isActive"] is False


@pytest.mark.anyio
async def test_activate_unknown_id_returns_404(client):
    resp = await client.post("/api/providers/does-not-exist/activate")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_get_llm_config_reads_active_dashboard_provider(client, isolated_db):
    """Le cœur du point 1 de la demande : plus de LLM unique codé en dur —
    get_llm_config() doit refléter ce qui est installé/activé ici."""
    created = (await client.post("/api/providers", json=_valid_payload(
        model="claude-opus-4", label="Anthropic prod",
    ))).json()
    await client.post(f"/api/providers/{created['id']}/activate")

    from nexus_compose.llm_config import get_llm_config
    cfg = get_llm_config()
    assert cfg.model == "claude-opus-4"
    assert cfg.source == "dashboard"

    # Supprimé -> plus aucun fournisseur actif -> repli sur les défauts.
    await client.delete(f"/api/providers/{created['id']}")
    cfg_after = get_llm_config()
    assert cfg_after.source in ("env", "default")


@pytest.mark.anyio
async def test_connection_test_against_local_mock_server(client):
    received = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            self.rfile.read(length)
            received["auth"] = self.headers.get("Authorization")
            if self.headers.get("Authorization") != "Bearer good-key-1234567890":
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": "invalid api key"}}).encode())
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode())

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    port = srv.server_port
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        # Brouillon, bonne clé -> succès
        ok_resp = await client.post("/api/providers/test", json=_valid_payload(
            endpoint=f"http://127.0.0.1:{port}/v1/chat/completions",
            api_key="good-key-1234567890",
        ))
        assert ok_resp.status_code == 200, ok_resp.text
        assert ok_resp.json()["status"] == "success"

        # Brouillon, mauvaise clé -> erreur, sans exposer d'exception brute
        bad_resp = await client.post("/api/providers/test", json=_valid_payload(
            endpoint=f"http://127.0.0.1:{port}/v1/chat/completions",
            api_key="wrong-key-1234567890",
        ))
        assert bad_resp.status_code == 200
        assert bad_resp.json()["status"] == "error"
        assert bad_resp.json()["httpStatus"] == 401

        # Fournisseur enregistré -> test via son id
        saved = (await client.post("/api/providers", json=_valid_payload(
            endpoint=f"http://127.0.0.1:{port}/v1/chat/completions",
            api_key="good-key-1234567890",
        ))).json()
        saved_test = await client.post(f"/api/providers/{saved['id']}/test")
        assert saved_test.json()["status"] == "success"
    finally:
        srv.shutdown()
