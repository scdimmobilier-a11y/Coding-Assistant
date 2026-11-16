"""
nexus_brain.core.react
=========================

Nexus Core's ReAct loop (per prompt_nexus_brain.md): "planification →
exécution (résolution d'arguments, validation de schéma) → pause/reprise
human-in-the-loop sans redémarrage → recovery après échec (replanning, pas
restart) → réponse finale."

State machine
-------------
PLANNING -> EXECUTING -> {PAUSED, RECOVERING, DONE}
PAUSED   -> (resume)  -> EXECUTING | RECOVERING
RECOVERING -> (replan) -> EXECUTING | DONE (no recovery hook / gave up)

Two properties are load-bearing and directly tested:
  - **pause never restarts**: `ReactTrace.step_index` and `.steps` are
    untouched while paused; `resume()` continues from exactly where it
    left off.
  - **recovery replans, it does not restart**: on failure/rejection, only
    the *remaining* steps (from `step_index` onward) are replaced by
    whatever `recovery_fn` returns — steps already completed stay done.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, Optional


class ReactState(Enum):
    PLANNING = auto()
    EXECUTING = auto()
    PAUSED = auto()       # awaiting human-in-the-loop input; no restart on resume
    RECOVERING = auto()   # a step failed or was rejected; replanning remaining steps
    DONE = auto()


@dataclass(frozen=True)
class ReactStep:
    step_id: str
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    schema: Optional[dict[str, Any]] = None  # minimal {"required": [...]} arg-schema


@dataclass
class ReactTrace:
    goal: str
    steps: list[ReactStep]
    step_index: int = 0
    state: ReactState = ReactState.EXECUTING
    paused_reason: str = ""
    final_response: Optional[str] = None
    history: list[dict[str, Any]] = field(default_factory=list)  # for Nexus Harness's trajectory window


PlannerFn = Callable[[str, dict], list[ReactStep]]
ExecutorFn = Callable[[ReactStep, dict], dict]  # -> {"success": bool, "output": Any, ...}
ValidatorFn = Callable[[ReactStep], tuple[bool, str]]
RecoveryFn = Callable[[ReactStep, ReactTrace, dict], list[ReactStep]]  # -> replacement remaining steps


def _validate_schema(step: ReactStep) -> tuple[bool, str]:
    """Default validator: checks required args are present, per prompt's
    "résolution d'arguments, validation de schéma"."""
    if not step.schema:
        return True, ""
    missing = [k for k in step.schema.get("required", []) if k not in step.args]
    if missing:
        return False, f"missing required args: {missing}"
    return True, ""


class ReactLoop:
    def __init__(
        self,
        planner_fn: PlannerFn,
        executor_fn: ExecutorFn,
        validator_fn: ValidatorFn = _validate_schema,
        recovery_fn: Optional[RecoveryFn] = None,
    ):
        self._planner_fn = planner_fn
        self._executor_fn = executor_fn
        self._validator_fn = validator_fn
        self._recovery_fn = recovery_fn

    def start(self, goal: str, context: dict[str, Any]) -> ReactTrace:
        steps = self._planner_fn(goal, context)
        return ReactTrace(goal=goal, steps=steps, state=ReactState.EXECUTING)

    def advance(self, trace: ReactTrace, context: dict[str, Any]) -> ReactTrace:
        """Advance exactly one step. No-op if already DONE; raises if
        PAUSED (must call `resume` explicitly — advancing a paused trace
        silently would violate the "no restart" guarantee by skipping the
        approval gate)."""
        if trace.state == ReactState.DONE:
            return trace
        if trace.state == ReactState.PAUSED:
            raise RuntimeError("trace is paused — call resume(trace, human_input, context)")

        if trace.step_index >= len(trace.steps):
            trace.state = ReactState.DONE
            trace.final_response = trace.final_response or "All steps completed."
            return trace

        step = trace.steps[trace.step_index]

        ok, reason = self._validator_fn(step)
        if not ok:
            return self._recover(trace, step, context, reason=f"validation failed: {reason}")

        if step.requires_approval:
            trace.state = ReactState.PAUSED
            trace.paused_reason = f"awaiting approval for step {step.step_id} ({step.tool})"
            return trace

        return self._execute_current(trace, step, context)

    def resume(self, trace: ReactTrace, human_input: dict[str, Any], context: dict[str, Any]) -> ReactTrace:
        """Resume a PAUSED trace. `step_index`/`steps` are untouched up to
        this point — this is the "sans redémarrage" guarantee: we continue
        exactly at the paused step, we do not replan from goal/step 0."""
        if trace.state != ReactState.PAUSED:
            raise RuntimeError("resume() called on a non-paused trace")

        step = trace.steps[trace.step_index]
        if not human_input.get("approved", False):
            return self._recover(trace, step, context, reason="rejected by human-in-the-loop")

        trace.state = ReactState.EXECUTING
        return self._execute_current(trace, step, context)

    # ------------------------------------------------------------------ #

    def _execute_current(self, trace: ReactTrace, step: ReactStep, context: dict[str, Any]) -> ReactTrace:
        result = self._executor_fn(step, context)
        trace.history.append({"step_id": step.step_id, "action": step.tool, **result})

        if not result.get("success", True):
            return self._recover(trace, step, context, reason=str(result.get("error", "execution failed")))

        trace.step_index += 1
        if trace.step_index >= len(trace.steps):
            trace.state = ReactState.DONE
            trace.final_response = result.get("output", "Done.")
        else:
            trace.state = ReactState.EXECUTING
        return trace

    def _recover(self, trace: ReactTrace, failed_step: ReactStep, context: dict[str, Any], reason: str) -> ReactTrace:
        """Recovery is a REPLAN of the remaining steps, not a restart:
        everything before `step_index` (already executed) is kept as-is;
        only `trace.steps[step_index:]` is replaced."""
        trace.state = ReactState.RECOVERING
        trace.paused_reason = reason

        if self._recovery_fn is None:
            trace.state = ReactState.DONE
            trace.final_response = f"Gave up after '{failed_step.step_id}': {reason}"
            return trace

        replacement = self._recovery_fn(failed_step, trace, context)
        trace.steps = trace.steps[:trace.step_index] + replacement
        trace.state = ReactState.EXECUTING
        return trace

    def run_until_stalled(self, trace: ReactTrace, context: dict[str, Any], max_steps: int = 100) -> ReactTrace:
        """Advance repeatedly until DONE or PAUSED (or `max_steps` guard)."""
        for _ in range(max_steps):
            if trace.state in (ReactState.DONE, ReactState.PAUSED):
                break
            trace = self.advance(trace, context)
        return trace
