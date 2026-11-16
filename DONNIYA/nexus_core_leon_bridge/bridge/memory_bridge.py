"""
bridge.memory_bridge
=======================

Implements deliverable #5 ("Mémoire") per the explicit decision written up
in docs/DECISIONS.md — read that file for the *why*; this module is only
the *how*. Short version: Leon's own `memory-manager` (SQL + qmd retrieval,
already real and already durable) stays the single source of truth for
durable, cross-session facts. `LayeredMemory` is NOT a second copy of it —
it is Nexus Core's own in-process reasoning bookkeeping (self-model notes,
turn history), scoped so nothing it writes could ever diverge from what
Leon's memory-manager holds, because it never writes the same facts.

Two small pieces:

  1. `bridge_persist_fn` — the `persist_fn` hook handed to `LayeredMemory`.
     It writes `persistent`/`daily` entries (Nexus Core's own bookkeeping)
     to a local JSONL file so the bridge's own state survives a process
     restart. `discussion`-layer entries are deliberately NOT persisted
     here — they are the current turn's ReAct scratchpad, cleared every
     new discussion by `LayeredMemory.new_discussion()`, and persisting
     them would be persisting a duplicate of what Leon's own
     conversation-history / memory-manager already durably stores.
  2. `apply_leon_context_digest` — reads whatever short memory digest Leon
     included in the request body (`context["leon_memory_digest"]`, built
     from Leon's own memory-manager/persona context assembly — the bridge
     does not recompute it) and loads it as a runtime context file, which
     `LayeredMemory.recall()` documents as "consulted first" on any read.
     This is the read side; `bridge_persist_fn` is the write side. Exactly
     one write path (this file, for bookkeeping only) and one read path
     (Leon hands over the digest every turn) — no independent Python-side
     store of durable facts, so nothing can drift silently.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from nexus_brain.core.memory import LayeredMemory, MemoryEntry

_LOCK = threading.Lock()

DEFAULT_STORE_PATH = Path(
    os.environ.get("NEXUS_BRIDGE_MEMORY_STORE", "./nexus_core_bookkeeping.jsonl")
)

LEON_DIGEST_CONTEXT_KEY = "leon:memory-manager-digest"


def bridge_persist_fn(layer: str, entry: MemoryEntry, store_path: Path = DEFAULT_STORE_PATH) -> None:
    """LayeredMemory's persist_fn hook. Only persistent/daily are written
    to disk — see module docstring for why discussion is excluded."""
    if layer not in ("persistent", "daily"):
        return
    record = {
        "layer": layer,
        "content": entry.content,
        "created_at": entry.created_at,
        "metadata": entry.metadata,
    }
    with _LOCK:
        store_path.parent.mkdir(parents=True, exist_ok=True)
        with store_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_bookkeeping_into(memory: LayeredMemory, store_path: Path = DEFAULT_STORE_PATH) -> int:
    """Replay the bridge's own bookkeeping file back into a fresh
    LayeredMemory on startup (process-restart durability for Nexus Core's
    OWN notes only — never Leon's facts, which Leon keeps itself). Returns
    the number of entries replayed."""
    if not store_path.exists():
        return 0
    count = 0
    with store_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            memory.remember(record["content"], layer=record["layer"], **record.get("metadata", {}))
            count += 1
    return count


def apply_leon_context_digest(memory: LayeredMemory, context: dict[str, Any]) -> None:
    """Read side of the memory decision: load whatever digest Leon supplied
    for this turn as a runtime context file (consulted first on recall()).
    A missing/empty digest is not an error — Leon may not have anything
    relevant for this turn, or may not have wired this field yet."""
    digest = context.get("leon_memory_digest")
    if digest:
        memory.set_runtime_context_file(LEON_DIGEST_CONTEXT_KEY, str(digest))
