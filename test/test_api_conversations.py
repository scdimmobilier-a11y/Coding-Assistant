"""
tests/test_api_conversations.py
───────────────────────────────────
Tests d'intégration pour POST /api/conversations,
GET /api/conversations/{id} — Étape 1b.
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
    from api import db as db_module

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_conversations.sqlite3")
    db_module.init_db()
    return db_module


@pytest.fixture()
async def client(isolated_db):
    from api.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_create_then_read_round_trips_transcript(client: AsyncClient):
    payload = {
        "id": "c-test", "title": "Test conv", "date": "Aujourd'hui",
        "transcript": [{"role": "user", "text": "salut"}, {"role": "system", "text": "bonjour"}],
    }
    resp = await client.post("/api/conversations", json=payload)
    assert resp.status_code == 200

    resp = await client.get("/api/conversations/c-test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Test conv"
    assert body["transcript"] == payload["transcript"]


@pytest.mark.anyio
async def test_read_unknown_conversation_returns_404(client: AsyncClient):
    resp = await client.get("/api/conversations/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_creating_the_same_id_twice_updates_rather_than_duplicates(client: AsyncClient):
    await client.post("/api/conversations", json={"id": "c1", "title": "v1", "date": "d1", "transcript": []})
    await client.post(
        "/api/conversations", json={"id": "c1", "title": "v2", "date": "d2", "transcript": [{"role": "user", "text": "x"}]}
    )
    resp = await client.get("/api/conversations/c1")
    body = resp.json()
    assert body["title"] == "v2"
    assert body["transcript"] == [{"role": "user", "text": "x"}]
