"""
api.codegen
=============

GET /api/codegen/branches, POST /api/codegen/files/{id}/accept,
POST /api/codegen/files/{id}/request-fix — Étape 1b du prompt de fusion.
Même principe de persistance que security.py — voir db.py.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException

from . import db

router = APIRouter(prefix="/api/codegen", tags=["codegen"])


@router.get("/branches")
async def list_branches() -> list[dict[str, Any]]:
    return await asyncio.to_thread(db.list_branches)


@router.post("/files/{file_id}/accept")
async def accept_file(file_id: str) -> dict[str, str]:
    ok = await asyncio.to_thread(db.set_file_status, file_id, "accepted")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown file {file_id!r}")
    return {"status": "ok"}


@router.post("/files/{file_id}/request-fix")
async def request_fix(file_id: str) -> dict[str, str]:
    ok = await asyncio.to_thread(db.set_file_status, file_id, "needs-fix")
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown file {file_id!r}")
    return {"status": "ok"}
