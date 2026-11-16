"""
nexus_functor.feedback
========================

The architecture doc describes a double feedback loop: a *fast* loop
(Nexus Exec's per-step results feeding straight back into local
adaptation) and a *slow* loop (aggregated outcomes feeding Nexus Harness's
learned policy prior). This module is the thin coordinator that fans one
FeedbackEvent out to both destinations, so `functor.py` doesn't have to
know the distinction — it just calls `on_feedback(...)` once per event.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .interfaces import HarnessPort
from .types import Decision, ExecutionState, FeedbackEvent, Objective


@dataclass
class FeedbackLoopManager:
    harness: Optional[HarnessPort] = None
    _slow_loop_buffer: list[tuple[Objective, Decision, FeedbackEvent]] = field(default_factory=list)
    slow_loop_batch_size: int = 5

    def fast_loop(self, execution_state: ExecutionState, event: FeedbackEvent) -> None:
        """Immediate: append to history so F2 sees it on the very next tick."""
        execution_state.last_step_result = event
        execution_state.history.append(event)

    def slow_loop(self, objective: Objective, decision: Decision, event: FeedbackEvent) -> None:
        """
        Buffered: don't hammer Nexus Harness with a policy update on every
        single step. Batch, then flush. Real deployments will likely want
        this on a timer too, not just a count — left as a straightforward
        extension point.
        """
        if self.harness is None:
            return
        self._slow_loop_buffer.append((objective, decision, event))
        if len(self._slow_loop_buffer) >= self.slow_loop_batch_size:
            self.flush_slow_loop()

    def flush_slow_loop(self) -> None:
        if self.harness is None:
            self._slow_loop_buffer.clear()
            return
        for objective, decision, event in self._slow_loop_buffer:
            self.harness.record_outcome(objective, decision, event)
        self._slow_loop_buffer.clear()

    def on_feedback(
        self,
        objective: Objective,
        decision: Decision,
        execution_state: ExecutionState,
        event: FeedbackEvent,
    ) -> None:
        self.fast_loop(execution_state, event)
        self.slow_loop(objective, decision, event)
