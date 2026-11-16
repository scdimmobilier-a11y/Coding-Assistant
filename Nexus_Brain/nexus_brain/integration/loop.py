"""
nexus_brain.integration.loop
===============================

The end-to-end integration loop (deliverable #3, prompt_nexus_brain.md):
"script/service qui fait tourner NexusFunctor.step()/on_feedback() en
continu sur un ou plusieurs objectifs actifs, avec Nexus Exec réellement
invoqué et le feedback routé vers les boucles rapide/lente."

`ObjectiveRunner` owns a set of concurrently-active objectives, each with
its **own** `NexusFunctor` instance and `ExecutionState` (per prompt:
"ExecutionState... est détenu par l'appelant, pas par le Functor — permet
plusieurs objectifs concurrents"). Every `tick_all()`:

  1. `functor.step(...)` — F0..F3 run, a `Decision` comes back.
  2. If step()'s F2 pass escalated on this tick (see `_detect_escalation`
     below), the *next* tick fetches a genuinely fresh `PlanSet` from the
     real `PlannerPort` (passing `plan_set=None` makes `step()` itself call
     `planner.generate_plans(...)` again — this is real replanning, not a
     re-ranking of stale candidates).
  3. `executor.execute_step(...)` — Nexus Exec is actually invoked (real
     `Coordinator` loop, see `adapters/exec_adapter.py`).
  4. `functor.on_feedback(...)` — routes the `FeedbackEvent` through both
     the fast loop (F2, next tick) and the slow loop (batched -> Nexus
     Harness, via `FeedbackLoopManager` inside `nexus_functor` — untouched).

Escalation detection (`_detect_escalation`): `NexusFunctor` does not
directly expose "F2 escalated this tick" on `Decision` (by design — that
detail is F2's own business). We infer it from two *public* facts already
on `ExecutionState`/`FunctorConfig`: cumulative deviation was at/above
`f2.escalate_threshold` going into the tick, and the plan was switched
during the tick (`Decision.plan_switched`). This never reads or duplicates
F2's internal logic — it is a caller-side observation of its externally
visible effect, which is exactly the kind of thing an integration loop is
allowed to look at.

D2 (`MISSION_couple_leon_nexusbrain.md`, "Delivery callback") extension:
`ObjectiveRunner` now retains the final `TickSummary` of every objective
that reaches `"complete"`, queryable via `get_completed(goal_id)` — see
that method's own docstring for why (`_active` discards an objective the
instant it completes, so nothing else in this class remembers the
result). Purely additive: no existing method's signature or return value
changed, and `_completed`'s bounded retention (`_completed_max_entries`)
is invisible to every caller that doesn't use `get_completed`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from nexus_functor.config import FunctorConfig
from nexus_functor.functor import NexusFunctor
from nexus_functor.interfaces import ExecutorPort, HarnessPort, PlannerPort, ProactivePort
from nexus_functor.types import Decision, ExecutionState, FeedbackEvent, Objective, PlanSet


@dataclass
class ActiveObjective:
    objective: Objective
    plan_set: Optional[PlanSet]
    exec_state: ExecutionState
    functor: NexusFunctor
    context: dict[str, Any]
    replan_count: int = 0
    tick_log: list[dict[str, Any]] = field(default_factory=list)
    last_event: Optional[FeedbackEvent] = None  # for escalation *prediction*, see _tick_one


@dataclass
class TickSummary:
    goal_id: str
    status: str  # "ticked" | "complete" | "no_op"
    macro_strategy: Optional[str] = None
    step_action: Optional[str] = None
    outcome: Optional[str] = None
    plan_switched: bool = False
    escalated: bool = False
    proactive_action: Optional[str] = None
    # D2 (MISSION_couple_leon_nexusbrain.md, "Delivery callback"): the last
    # FeedbackEvent's own notes, carried through so a "complete" summary
    # (which itself executes no step — see `_tick_one`) still has
    # something a delivery callback can show, e.g. a CodegenAdapter's own
    # `nexus_compose run_id=...` note. Optional and additive — every
    # existing caller of TickSummary(...) positionally or by the fields
    # already listed above is unaffected.
    notes: Optional[str] = None


class ObjectiveRunner:
    """Drives one or more concurrently-active objectives through Nexus
    Functor + the real port adapters, tick by tick."""

    def __init__(
        self,
        planner: PlannerPort,
        executor: ExecutorPort,
        harness: Optional[HarnessPort] = None,
        proactive: Optional[ProactivePort] = None,
        functor_config: Optional[FunctorConfig] = None,
    ):
        self._planner = planner
        self._executor = executor
        self._harness = harness
        self._proactive = proactive
        self._functor_config = functor_config or FunctorConfig()
        self._active: dict[str, ActiveObjective] = {}
        # D2 (MISSION_couple_leon_nexusbrain.md, "Delivery callback"):
        # `_tick_one` removes a goal_id from `_active` the instant it
        # completes (see below) — without this, the ONLY place a
        # completed objective's result ever existed was the transient
        # dict `tick_all()` returns for that one tick, gone on the next
        # call. A delivery callback (`bridge/server.py::POST
        # /objective/{goal_id}/deliver`) needs to fetch that result
        # *after* the tick that produced it, potentially several ticks
        # later. Bounded by `_completed_max_entries` so a long-running
        # process backed by many one-off objectives doesn't grow this
        # dict forever.
        self._completed: dict[str, TickSummary] = {}
        self._completed_order: list[str] = []
        self._completed_max_entries = 500

    def get_completed(self, goal_id: str) -> Optional[TickSummary]:
        """The final `TickSummary` for a completed objective, or `None` if
        `goal_id` never completed (still active, never existed, or aged
        out of the bounded retention window — see `_completed_max_entries`)."""
        return self._completed.get(goal_id)

    def _remember_completed(self, summary: TickSummary) -> None:
        if summary.goal_id in self._completed:
            self._completed_order.remove(summary.goal_id)
        self._completed[summary.goal_id] = summary
        self._completed_order.append(summary.goal_id)
        while len(self._completed_order) > self._completed_max_entries:
            oldest = self._completed_order.pop(0)
            self._completed.pop(oldest, None)

    # -- objective lifecycle ----------------------------------------------

    def add_objective(self, objective: Objective, context: dict[str, Any]) -> None:
        plan_set = self._planner.generate_plans(objective, context)
        functor = NexusFunctor(
            config=self._functor_config,
            planner=self._planner,
            harness=self._harness,
            proactive=self._proactive,
        )
        self._active[objective.goal_id] = ActiveObjective(
            objective=objective,
            plan_set=plan_set,
            exec_state=ExecutionState(objective_id=objective.goal_id),
            functor=functor,
            context=context,
        )

    def remove_objective(self, goal_id: str) -> None:
        self._active.pop(goal_id, None)

    @property
    def active_goal_ids(self) -> list[str]:
        return list(self._active.keys())

    def get(self, goal_id: str) -> Optional[ActiveObjective]:
        return self._active.get(goal_id)

    # -- ticking -------------------------------------------------------------

    def tick_all(self) -> dict[str, TickSummary]:
        return {goal_id: self._tick_one(ao) for goal_id, ao in list(self._active.items())}

    def run_forever(self, max_ticks: Optional[int] = None, sleep_s: float = 0.0) -> list[dict[str, TickSummary]]:
        history = []
        tick = 0
        while (max_ticks is None or tick < max_ticks) and self._active:
            history.append(self.tick_all())
            tick += 1
            if sleep_s:
                time.sleep(sleep_s)
        return history

    def _tick_one(self, ao: ActiveObjective) -> TickSummary:
        # Predict — BEFORE calling step() — whether F2's *next* adaptation
        # will escalate, using only public information (the same formula
        # F2 itself uses: decayed cumulative deviation + last step's
        # deviation, vs. f2.escalate_threshold). We do not decide
        # CONTINUE/PATCH/ESCALATE ourselves — F2 still does that, inside
        # step() — we only predict it so we can later *confirm* it via
        # `decision.plan_switched` and know to fetch a fresh PlanSet.
        #
        # This has to happen before step() because a successful escalation
        # that also switches plans resets `cumulative_deviation` to 0.0
        # *within that same step() call* (fresh plan, no drift yet) — by
        # the time step() returns, the "was about to escalate" evidence is
        # gone from ExecutionState itself.
        decay = self._functor_config.f2.deviation_decay
        predicted_deviation = ao.exec_state.cumulative_deviation * decay
        if ao.last_event is not None:
            predicted_deviation += ao.last_event.deviation
        escalation_imminent = predicted_deviation >= self._functor_config.f2.escalate_threshold

        decision: Decision = ao.functor.step(ao.objective, ao.plan_set, ao.exec_state, ao.context)

        escalated = escalation_imminent and decision.plan_switched
        if escalated:
            # Genuine replanning: fetch a FRESH PlanSet from the real
            # Nexus Planner (not just a re-ranking of stale candidates) —
            # applied on the *next* tick since this tick's Decision is
            # already computed against the plan_set we had.
            ao.plan_set = self._planner.generate_plans(ao.objective, ao.context)
            ao.replan_count += 1

        if decision.next_step is None:
            # Flush any buffered slow-loop feedback now — otherwise an
            # objective that completes in fewer than
            # `slow_loop_batch_size` ticks would never contribute to Nexus
            # Harness's learned prior at all (the buffer only auto-flushes
            # once it fills up).
            ao.functor.flush_learning()
            summary = TickSummary(goal_id=ao.objective.goal_id, status="complete",
                                   macro_strategy=decision.macro_strategy.name,
                                   plan_switched=decision.plan_switched, escalated=escalated,
                                   proactive_action=decision.proactive_action,
                                   notes=ao.last_event.notes if ao.last_event is not None else None)
            ao.tick_log.append(vars(summary))
            self._remember_completed(summary)
            self.remove_objective(ao.objective.goal_id)
            return summary

        event: FeedbackEvent = self._executor.execute_step(
            decision.selected_plan_id, decision.next_step.step_id, decision.next_step.params,
        )
        ao.functor.on_feedback(ao.objective, decision, ao.exec_state, event)
        ao.last_event = event

        summary = TickSummary(
            goal_id=ao.objective.goal_id, status="ticked",
            macro_strategy=decision.macro_strategy.name,
            step_action=decision.next_step.action,
            outcome=event.outcome.name,
            plan_switched=decision.plan_switched,
            escalated=escalated,
            proactive_action=decision.proactive_action,
            notes=event.notes,
        )
        ao.tick_log.append(vars(summary))
        return summary
