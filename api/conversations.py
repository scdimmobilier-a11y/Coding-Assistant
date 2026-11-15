"""
api.conversations
====================

POST /api/conversations, GET /api/conversations/{id} — Étape 1b du prompt
de fusion. Persistance SQLite (voir db.py) ; sqlite3 étant bloquant, chaque
appel passe par `asyncio.to_thread` plutôt qu'un appel direct dans le
handler async (même principe que le pont thread/asyncio de state.py, à
une échelle beaucoup plus modeste ici).
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import db

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


class ConversationIn(BaseModel):
    id: str
    title: str
    date: str
    transcript: list[dict[str, Any]] = []


@router.post("")
async def create_conversation(conv: ConversationIn) -> dict[str, str]:
    await asyncio.to_thread(db.insert_conversation, conv.id, conv.title, conv.date, conv.transcript)
    return {"status": "ok"}


@router.get("/{conversation_id}")
async def read_conversation(conversation_id: str) -> dict[str, Any]:
    conv = await asyncio.to_thread(db.get_conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail=f"Unknown conversation {conversation_id!r}")
    return conv
