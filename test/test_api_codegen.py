"""
tests/test_api_codegen.py
────────────────────────────
Tests d'intégration pour GET /api/codegen/branches,
POST /api/codegen/files/{id}/accept, .../request-fix — Étape 1b.
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

    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test_codegen.sqlite3")
    return db_module


@pytest.fixture()
async def client(isolated_db):
    from api.main import app

    seed_branches = [
        {
            "id": "b1", "label": "API", "agent": "crewAI", "status": "done",
            "files": [
                {"id": "f_a", "path": "a.py", "summary": "s", "linesAdded": 1, "linesRemoved": 0,
                 "status": "pending"},
                {"id": "f_b", "path": "b.py", "summary": "s", "linesAdded": 1, "linesRemoved": 0,
                 "status": "pending"},
            ],
        },
    ]
    isolated_db.init_db()
    isolated_db.seed_if_empty([], seed_branches)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_list_branches_reconstructs_nested_shape(client: AsyncClient):
    resp = await client.get("/api/codegen/branches")
    assert resp.status_code == 200
    branches = resp.json()
    assert len(branches) == 1
    assert branches[0]["id"] == "b1"
    assert len(branches[0]["files"]) == 2


@pytest.mark.anyio
async def test_accept_file_persists(client: AsyncClient):
    resp = await client.post("/api/codegen/files/f_a/accept")
    assert resp.status_code == 200
    branches = (await client.get("/api/codegen/branches")).json()
    files_by_id = {f["id"]: f for f in branches[0]["files"]}
    assert files_by_id["f_a"]["status"] == "accepted"
    assert files_by_id["f_b"]["status"] == "pending"  # inchangé


@pytest.mark.anyio
async def test_request_fix_persists(client: AsyncClient):
    resp = await client.post("/api/codegen/files/f_b/request-fix")
    assert resp.status_code == 200
    branches = (await client.get("/api/codegen/branches")).json()
    files_by_id = {f["id"]: f for f in branches[0]["files"]}
    assert files_by_id["f_b"]["status"] == "needs-fix"


@pytest.mark.anyio
async def test_accept_unknown_file_returns_404(client: AsyncClient):
    resp = await client.post("/api/codegen/files/does-not-exist/accept")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_request_fix_unknown_file_returns_404(client: AsyncClient):
    resp = await client.post("/api/codegen/files/does-not-exist/request-fix")
    assert resp.status_code == 404
