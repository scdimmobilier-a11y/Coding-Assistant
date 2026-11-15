"""
tests/test_leon_llm_sync.py
──────────────────────────────
Vérifie que le fournisseur LLM ACTIF côté dashboard est bien réappliqué à
Leon (config.yml + .env) — pas seulement disponible pour q2d/crewAI via
get_llm_config(). Couvre :
  1. Le module nexus_compose.leon_llm_sync en isolation (patch de fichiers).
  2. Le branchement bout-en-bout : POST /api/providers/{id}/activate ->
     config.yml de Leon change, sans que l'appelant du dashboard n'ait à le
     savoir ni que ça puisse faire échouer la requête si Leon est absent.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from httpx import ASGITransport, AsyncClient

from nexus_compose.llm_config import LLMConfig


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture()
def fake_leon_dir(tmp_path, monkeypatch):
    """Un faux répertoire Leon minimal : config.yml avec une clé `default:`
    à la racine, comme le vrai config.sample.yml de Leon."""
    leon_dir = tmp_path / "leon"
    leon_dir.mkdir()
    (leon_dir / "config.yml").write_text(
        "core:\n  version: 1\nllm:\n  default: \"openai/gpt-4o-mini\"\n  timeout: 30\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LEON_DIR", str(leon_dir))
    return leon_dir


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    from api import db as db_module

    db_path = tmp_path / "test_providers.sqlite3"
    monkeypatch.setattr(db_module, "DB_PATH", db_path)
    monkeypatch.setenv("NEXUS_API_DB_PATH", str(db_path))
    db_module.init_db()
    return db_module


@pytest.fixture()
async def client(isolated_db, fake_leon_dir):
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


# ── module en isolation ──────────────────────────────────────────────────────

def test_sync_patches_default_model_and_writes_api_key(fake_leon_dir):
    from nexus_compose.leon_llm_sync import sync_leon_llm_config

    cfg = LLMConfig(provider="anthropic", model="claude-sonnet-4-6", api_key="sk-ant-abcdef")
    result = sync_leon_llm_config(cfg)

    assert result["synced"] is True
    assert result["qualified_model"] == "anthropic/claude-sonnet-4-6"
    assert result["env_key_written"] is True

    patched = (fake_leon_dir / "config.yml").read_text(encoding="utf-8")
    assert 'default: "anthropic/claude-sonnet-4-6"' in patched

    env_content = (fake_leon_dir / ".env").read_text(encoding="utf-8")
    assert "LEON_ANTHROPIC_API_KEY=sk-ant-abcdef" in env_content


def test_sync_is_idempotent_and_replaces_previous_key(fake_leon_dir):
    from nexus_compose.leon_llm_sync import sync_leon_llm_config

    sync_leon_llm_config(LLMConfig(provider="openai", model="gpt-4o", api_key="sk-first"))
    sync_leon_llm_config(LLMConfig(provider="openai", model="gpt-4o-mini", api_key="sk-second"))

    patched = (fake_leon_dir / "config.yml").read_text(encoding="utf-8")
    assert 'default: "openai/gpt-4o-mini"' in patched
    assert "gpt-4o\"" not in patched  # l'ancienne valeur n'a pas été laissée en doublon

    env_content = (fake_leon_dir / ".env").read_text(encoding="utf-8")
    assert env_content.count("LEON_OPENAI_API_KEY=") == 1
    assert "LEON_OPENAI_API_KEY=sk-second" in env_content


def test_sync_is_a_safe_noop_when_leon_is_not_deployed(tmp_path, monkeypatch):
    """Aucune exception : le dashboard doit rester utilisable même sans
    Leon déployé à côté (ex: Nexus_Assistant/api exécuté seul)."""
    from nexus_compose.leon_llm_sync import sync_leon_llm_config

    monkeypatch.setenv("LEON_DIR", str(tmp_path / "does-not-exist"))
    result = sync_leon_llm_config(LLMConfig(provider="openai", model="gpt-4o-mini", api_key="sk-x"))
    assert result["synced"] is False
    assert "introuvable" in result["reason"]


# ── bout-en-bout via le dashboard ────────────────────────────────────────────

def _valid_payload(**overrides):
    payload = {
        "provider": "anthropic",
        "label": "Mon compte Anthropic",
        "model": "claude-sonnet-4-6",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "api_type": "chat_completions",
        "auth_type": "api_key",
        "api_key": "sk-ant-0123456789abcdef",
        "headers": {},
        "timeout_s": 30,
        "max_retries": 3,
        "http2": True,
        "compression": True,
    }
    payload.update(overrides)
    return payload


@pytest.mark.anyio
async def test_activating_a_provider_immediately_updates_leons_config_yml(client, fake_leon_dir):
    created = (await client.post("/api/providers", json=_valid_payload())).json()

    resp = await client.post(f"/api/providers/{created['id']}/activate")
    assert resp.status_code == 200

    patched = (fake_leon_dir / "config.yml").read_text(encoding="utf-8")
    assert 'default: "anthropic/claude-sonnet-4-6"' in patched


@pytest.mark.anyio
async def test_deactivating_falls_leon_back_to_the_env_default(client, fake_leon_dir, monkeypatch):
    created = (await client.post("/api/providers", json=_valid_payload())).json()
    await client.post(f"/api/providers/{created['id']}/activate")

    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "groq")
    monkeypatch.setenv("NEXUS_LLM_MODEL", "llama-3.3-70b")

    resp = await client.post(f"/api/providers/{created['id']}/deactivate")
    assert resp.status_code == 200

    patched = (fake_leon_dir / "config.yml").read_text(encoding="utf-8")
    assert 'default: "groq/llama-3.3-70b"' in patched


@pytest.mark.anyio
async def test_deleting_the_active_provider_resyncs_leon(client, fake_leon_dir, monkeypatch):
    created = (await client.post("/api/providers", json=_valid_payload())).json()
    await client.post(f"/api/providers/{created['id']}/activate")

    monkeypatch.setenv("NEXUS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("NEXUS_LLM_MODEL", "gpt-4o-mini")

    resp = await client.delete(f"/api/providers/{created['id']}")
    assert resp.status_code == 204

    patched = (fake_leon_dir / "config.yml").read_text(encoding="utf-8")
    assert 'default: "openai/gpt-4o-mini"' in patched


@pytest.mark.anyio
async def test_activate_does_not_fail_when_leon_is_absent(isolated_db, tmp_path, monkeypatch):
    """La synchronisation Leon est un aparté, jamais une condition de succès
    de l'endpoint dashboard lui-même."""
    monkeypatch.setenv("LEON_DIR", str(tmp_path / "no-leon-here"))
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        created = (await ac.post("/api/providers", json=_valid_payload())).json()
        resp = await ac.post(f"/api/providers/{created['id']}/activate")
        assert resp.status_code == 200
        assert resp.json()["isActive"] is True
