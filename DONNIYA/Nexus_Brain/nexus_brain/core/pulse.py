"""
nexus_brain.core.pulse
=========================

Nexus Core's pulse manager (per prompt_nexus_brain.md, "Nexus Core (Leon
2.0)"): "Pulse manager périodique : génère des 'matters' autonomes, exécute
au plus un par tick, supprime les propositions répétées après refus."

A *matter* is an autonomously-generated candidate action (e.g. "you have 3
unread notes from yesterday, want a summary?"). Every `tick()`:

  1. if the configured interval has elapsed, ask the pluggable `generator`
     for fresh matters (skipping any whose dedup key was previously
     rejected);
  2. execute **at most one** pending matter (FIFO), returning it plus its
     result — never more than one per tick, regardless of how many are
     queued;
  3. the caller (Nexus Core) later reports whether the matter was accepted
     or rejected via `record_outcome`; a rejected matter's dedup key is
     remembered forever so the same proposal is never surfaced again.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class Matter:
    """One autonomously-generated candidate action."""

    matter_id: str
    description: str
    action: Callable[[], Any]
    priority: float = 0.5
    dedup_key: str = ""  # defaults to description if not set

    def key(self) -> str:
        return self.dedup_key or self.description


@dataclass
class MatterResult:
    matter: Matter
    result: Any
    executed_at: float = field(default_factory=time.time)


class PulseManager:
    def __init__(
        self,
        generator: Callable[[], list[Matter]],
        tick_interval_s: float = 60.0,
    ):
        self._generator = generator
        self._tick_interval_s = tick_interval_s
        self._rejected_keys: set[str] = set()
        self._pending: list[Matter] = []
        self._last_generation_time: float = 0.0

    def tick(self, now: Optional[float] = None) -> Optional[MatterResult]:
        """Generate fresh matters if due, then execute at most one pending
        matter. Returns None if nothing was executed this tick."""
        now = now if now is not None else time.time()

        if now - self._last_generation_time >= self._tick_interval_s:
            self._last_generation_time = now
            for m in self._generator():
                if m.key() in self._rejected_keys:
                    continue  # permanently dropped after a prior refusal
                if any(p.key() == m.key() for p in self._pending):
                    continue  # already queued, avoid duplicate proposals
                self._pending.append(m)

        if not self._pending:
            return None

        matter = self._pending.pop(0)
        result = matter.action()
        return MatterResult(matter=matter, result=result, executed_at=now)

    def record_outcome(self, matter: Matter, accepted: bool) -> None:
        """Reject -> permanently dedup this matter's key so it is never
        proposed again (per prompt: "supprime les propositions répétées
        après refus"), AND purge any already-queued matter sharing that key
        (it may have been re-generated and queued before this rejection was
        recorded — a stale copy sitting in `_pending` must not survive).
        Accept -> no special bookkeeping needed here; Nexus Core's own
        memory/self-model records the interaction."""
        if not accepted:
            self._rejected_keys.add(matter.key())
            self._pending = [p for p in self._pending if p.key() != matter.key()]

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def rejected_keys(self) -> frozenset[str]:
        return frozenset(self._rejected_keys)
