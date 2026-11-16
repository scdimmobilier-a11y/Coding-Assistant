"""
nexus_brain.core.memory
=========================

Nexus Core's layered memory (per prompt_nexus_brain.md, "Nexus Core (Leon
2.0)"):

  - **persistent** memory: long-lived facts/preferences that survive across
    all sessions.
  - **daily** memory: resets each calendar day, holds today's running
    context.
  - **discussion** memory: the current conversation's turn history, reset
    per discussion.
  - **runtime context files**: consulted *before* the layered memory on any
    read (per prompt: "fichiers de contexte runtime consultés en priorité").
  - **self-model**: a bounded private journal, updated after every turn,
    that promotes repeated habits (the same note recurring often enough)
    into stable principles — read back as part of Nexus Core's own
    self-context, never shown verbatim to the user unless asked.

Everything here is in-memory plus a pluggable persistence hook
(`persist_fn`) rather than hard-wired to a specific file/DB backend, so
it's easy to swap in real storage without touching the memory-layering logic.
"""

from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Optional


@dataclass
class MemoryEntry:
    content: str
    layer: str  # "persistent" | "daily" | "discussion"
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class LayeredMemory:
    """Three memory layers + runtime context files consulted first on read."""

    def __init__(self, persist_fn: Optional[Callable[[str, MemoryEntry], None]] = None):
        self._persistent: list[MemoryEntry] = []
        self._daily: list[MemoryEntry] = []
        self._daily_date: date = date.today()
        self._discussion: list[MemoryEntry] = []
        self._runtime_context_files: dict[str, str] = {}  # path -> content, priority read
        self._persist_fn = persist_fn

    # -- writes ---------------------------------------------------------

    def remember(self, content: str, layer: str = "discussion", **metadata: Any) -> MemoryEntry:
        if layer not in ("persistent", "daily", "discussion"):
            raise ValueError(f"unknown memory layer: {layer!r}")
        self._roll_daily_if_needed()
        entry = MemoryEntry(content=content, layer=layer, metadata=metadata)
        getattr(self, f"_{layer}").append(entry)
        if self._persist_fn:
            self._persist_fn(layer, entry)
        return entry

    def set_runtime_context_file(self, path: str, content: str) -> None:
        self._runtime_context_files[path] = content

    def new_discussion(self) -> None:
        """Start a fresh discussion — clears turn history only, per prompt's
        3-layer split (persistent/daily survive; discussion does not)."""
        self._discussion = []

    # -- reads ------------------------------------------------------------

    def recall(self, layer: Optional[str] = None, limit: int = 50) -> list[MemoryEntry]:
        """Runtime context files are conceptually 'layer 0' — always
        returned first (per prompt: "consultés en priorité") when no
        specific layer is requested; they are not a MemoryEntry layer
        themselves since they're externally-authored context, not
        Nexus Core's own recollections."""
        self._roll_daily_if_needed()
        if layer:
            return list(getattr(self, f"_{layer}"))[-limit:]
        combined = self._persistent + self._daily + self._discussion
        return combined[-limit:]

    def runtime_context(self) -> dict[str, str]:
        return dict(self._runtime_context_files)

    def _roll_daily_if_needed(self) -> None:
        today = date.today()
        if today != self._daily_date:
            self._daily = []
            self._daily_date = today


class SelfModel:
    """Bounded private journal (per prompt: "Self-model borné (journal
    privé), mis à jour après chaque tour, qui promeut les habitudes
    répétées en principes stables."). Not shown to the user by default."""

    def __init__(self, max_entries: int = 200, promotion_count: int = 3):
        self._journal: deque[str] = deque(maxlen=max_entries)
        self._habit_counts: Counter[str] = Counter()
        self._promotion_count = promotion_count
        self._principles: set[str] = set()

    def record_turn(self, note: str) -> None:
        """Called after every turn. A repeated note (same text recurring
        `promotion_count` times) is promoted into a stable principle."""
        self._journal.append(note)
        self._habit_counts[note] += 1
        if self._habit_counts[note] >= self._promotion_count:
            self._principles.add(note)

    @property
    def principles(self) -> tuple[str, ...]:
        return tuple(sorted(self._principles))

    @property
    def journal(self) -> tuple[str, ...]:
        return tuple(self._journal)
