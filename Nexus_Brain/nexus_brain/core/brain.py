"""
nexus_brain.core.brain
=========================

`NexusCore` — Nexus Core's brain (per prompt_nexus_brain.md, "Nexus Core
(Leon 2.0)"): routing across 3 modes, the ReAct loop, layered memory +
self-model, and the pulse manager. Nexus Core **poses objectives** consumed
by Nexus Functor and stays outside Functor's tight plan/exec loop — it
dispatches an `Objective`, later sees the outcome as an ordinary tool result
inside its own ReAct trace, and manages its own memory/pulse independently
(per prompt: "Nexus Core reste en dehors de cette boucle serrée").

Routing modes
-------------
  - **controlled**: deterministic native skills only — a direct lookup,
    no ReAct loop, no LLM reasoning. Fastest, most predictable path.
  - **agent**: full ReAct loop (plan -> execute -> pause/resume -> recover
    -> final response), used for anything a native skill can't handle
    directly, including delegating to Nexus Functor for objectives that
    need the plan/exec/proactive/harness machinery.
  - **smart**: automatic — tries `controlled` first (native skill lookup);
    falls back to `agent` if no native skill matches.

Native skill/tool stack (per prompt): "Empilement natif Skills -> Actions ->
Tools -> Functions (-> Binaries)" — `NexusCore` only models the top of that
stack explicitly (named Skills mapping to callables); each callable is free
to internally call Actions/Tools/Functions/Binaries however it likes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from nexus_functor.types import Objective

from .memory import LayeredMemory, SelfModel
from .pulse import Matter, PulseManager
from .react import ReactLoop, ReactState, ReactStep, ReactTrace

Mode = str  # "smart" | "controlled" | "agent"
Skill = Callable[[dict[str, Any]], Any]


@dataclass
class TurnResult:
    response: Any
    mode_used: str
    trace: Optional[ReactTrace] = None
    paused: bool = False


class NexusCore:
    def __init__(
        self,
        skills: Optional[dict[str, Skill]] = None,
        react_loop: Optional[ReactLoop] = None,
        memory: Optional[LayeredMemory] = None,
        self_model: Optional[SelfModel] = None,
        pulse: Optional[PulseManager] = None,
        evolve_harness_tool: Optional[Callable[[int, list[dict]], dict]] = None,
        post_objective: Optional[Callable[[Objective, dict], Any]] = None,
        diagnostics_report_fn: Optional[Callable[[], Optional[str]]] = None,
    ):
        self.skills: dict[str, Skill] = skills or {}
        self._react_loop = react_loop
        self.memory = memory or LayeredMemory()
        self.self_model = self_model or SelfModel()
        self.pulse = pulse
        self._evolve_harness_tool = evolve_harness_tool
        self._post_objective = post_objective
        # D5.2 (Mission 2, Meta Framework/Nexus Studio) — opt-in hook: when
        # a caller's context asks for it, append a spoken diagnostic phrase
        # (NodeAvailabilityChecker.leon_spoken_report(), unchanged, reached
        # through this injected callable — never a direct nexus_compose
        # import, same boundary as `evolve_harness_tool` above) to the end
        # of that turn's response. See `_maybe_append_diagnostics_report`.
        self._diagnostics_report_fn = diagnostics_report_fn

        self._active_traces: dict[str, ReactTrace] = {}  # goal_id -> paused/in-flight trace
        self._turn_count = 0

    # -- mode routing ------------------------------------------------------

    def handle_turn(self, user_input: str, context: dict[str, Any], mode: Mode = "smart") -> TurnResult:
        self.memory.remember(f"user: {user_input}", layer="discussion")
        context = {**context, "memory": self.memory, "self_model": self.self_model}

        if mode == "controlled":
            result = self._handle_controlled(user_input, context)
        elif mode == "agent":
            result = self._handle_agent(user_input, context)
        else:  # "smart": try controlled first, fall back to agent
            skill_name = self._match_native_skill(user_input)
            result = self._handle_controlled(user_input, context) if skill_name else self._handle_agent(user_input, context)

        result = self._maybe_append_diagnostics_report(result, context)

        self.memory.remember(f"nexus_core: {result.response}", layer="discussion")
        self._record_self_model(result)
        self._maybe_evolve_harness(result)
        self._turn_count += 1
        return result

    def _match_native_skill(self, user_input: str) -> Optional[str]:
        for name in self.skills:
            if name.lower() in user_input.lower():
                return name
        return None

    def _handle_controlled(self, user_input: str, context: dict[str, Any]) -> TurnResult:
        skill_name = self._match_native_skill(user_input)
        if skill_name is None:
            return TurnResult(response="No matching native skill.", mode_used="controlled")
        output = self.skills[skill_name](context)
        return TurnResult(response=output, mode_used="controlled")

    def _handle_agent(self, user_input: str, context: dict[str, Any]) -> TurnResult:
        if self._react_loop is None:
            return TurnResult(response="Agent mode unavailable (no ReactLoop configured).", mode_used="agent")
        trace = self._react_loop.start(user_input, context)
        trace = self._react_loop.run_until_stalled(trace, context)
        if trace.state == ReactState.PAUSED:
            self._active_traces[user_input] = trace
            return TurnResult(response=trace.paused_reason, mode_used="agent", trace=trace, paused=True)
        return TurnResult(response=trace.final_response, mode_used="agent", trace=trace)

    def resume_paused(self, goal_key: str, human_input: dict[str, Any], context: dict[str, Any]) -> TurnResult:
        """Resume a previously-paused ReAct trace WITHOUT restarting (see
        `nexus_brain.core.react` for the guarantee this relies on)."""
        trace = self._active_traces.get(goal_key)
        if trace is None or self._react_loop is None:
            return TurnResult(response="Nothing to resume.", mode_used="agent")
        trace = self._react_loop.resume(trace, human_input, context)
        trace = self._react_loop.run_until_stalled(trace, context)
        if trace.state == ReactState.PAUSED:
            self._active_traces[goal_key] = trace
            result = TurnResult(response=trace.paused_reason, mode_used="agent", trace=trace, paused=True)
        else:
            self._active_traces.pop(goal_key, None)
            result = TurnResult(response=trace.final_response, mode_used="agent", trace=trace)

        # Resuming completes a turn just as much as handle_turn() does —
        # same post-turn bookkeeping (self-model, evolve_harness, tick count,
        # and — D5.2 — the same opt-in diagnostics phrase).
        result = self._maybe_append_diagnostics_report(result, context)
        self._record_self_model(result)
        self._maybe_evolve_harness(result)
        self._turn_count += 1
        return result

    # -- Nexus Functor integration point ------------------------------------

    def pose_objective(self, description: str, context: dict[str, Any], **constraints: Any) -> Any:
        """Nexus Core's side of the "objectif" arrow in the architecture
        diagram: builds an `Objective` and hands it to whatever consumes it
        (typically an integration-loop `ObjectiveRunner` driving
        `NexusFunctor`). Nexus Core does not itself loop on Functor's
        tick/feedback cycle — it fires the objective and moves on; the
        *result*, whenever it lands, comes back as an ordinary tool output
        inside a future ReAct step (kept decoupled, per prompt: "Nexus Core
        reste en dehors de cette boucle serrée")."""
        objective = Objective(
            goal_id=f"goal-{abs(hash(description)) % 10_000_000}",
            description=description,
            constraints=constraints,
        )
        if self._post_objective is None:
            return {"posted": False, "reason": "no post_objective sink configured", "objective": objective}
        return self._post_objective(objective, context)

    # -- pulse ---------------------------------------------------------------

    def pulse_tick(self, now: Optional[float] = None) -> Optional[str]:
        """Drive the pulse manager one tick (per prompt: "exécute au plus un
        [matter] par tick"). Returns a human-readable summary, or None."""
        if self.pulse is None:
            return None
        result = self.pulse.tick(now=now)
        if result is None:
            return None
        self.memory.remember(f"pulse: {result.matter.description} -> {result.result}", layer="daily")
        return f"{result.matter.description}: {result.result}"

    def reject_last_matter(self, matter: Matter) -> None:
        if self.pulse is not None:
            self.pulse.record_outcome(matter, accepted=False)

    # -- internals -------------------------------------------------------

    def _record_self_model(self, result: TurnResult) -> None:
        note = f"mode={result.mode_used} paused={result.paused}"
        self.self_model.record_turn(note)

    def _maybe_append_diagnostics_report(self, result: TurnResult, context: dict[str, Any]) -> TurnResult:
        """D5.2 (Mission 2, Meta Framework/Nexus Studio) — opt-in only:
        fires when the caller's context asks for it
        (`context["diagnostics_report"]` truthy — same opt-in convention as
        `context["deliver_software"]` / `context["query_registry"]`
        elsewhere in this codebase), never on an ordinary turn. A
        diagnostic phrase appended to every reply would be noise, not the
        "petit gain" the mission describes.

        NexusCore never talks to nexus_compose directly — only through
        `self._diagnostics_report_fn`, wired in
        bridge/core_factory.py to `registry_aggregator.fetch_compose_spoken_report`
        (itself an HTTP call, since nexus_compose runs in a separate
        container). Same boundary `evolve_harness_tool` already uses:
        Nexus Core reasons, the bridge supplies the outside world."""
        if not context.get("diagnostics_report") or self._diagnostics_report_fn is None:
            return result
        report = self._diagnostics_report_fn()
        if not report:
            return result
        if isinstance(result.response, str):
            result.response = f"{result.response} {report}"
        return result

    def _maybe_evolve_harness(self, result: TurnResult) -> Optional[dict]:
        if self._evolve_harness_tool is None or result.trace is None:
            return None
        return self._evolve_harness_tool(self._turn_count, result.trace.history)
