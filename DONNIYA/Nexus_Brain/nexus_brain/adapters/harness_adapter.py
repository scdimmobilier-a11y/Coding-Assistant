"""
nexus_brain.adapters.harness_adapter
=======================================

Nexus Harness has **two distinct roles** (per prompt_nexus_brain.md — "ne
pas confondre") implemented by the same module but kept as separate data
flows:

  (a) **`HarnessPort`** — talks to Nexus Functor's F0: `get_policy_prior`
      hands F0 a learned prior over `MacroStrategy` names; `record_outcome`
      is the slow-loop update, fed by Functor's batched feedback. This
      specific prior-learning mechanism is a Nexus Brain architectural
      extension (F0 blending a learned prior with live drift signals) —
      it does not exist as such in the Continual Harness paper/repo, which
      the prompt itself frames as new integration glue, not something to
      import.

  (b) **`evolve_harness`** — the actual tool exposed to Nexus Core, a
      generic re-implementation of the REAL 4-pass CRUD mechanism in
      `vendor/nexus_harness/agents/utils/harness_evolver.py`
      (`HarnessEvolver.evolve`): every `optimization_window_length` steps,
      read the recent trajectory window and run 4 independently-wrapped
      passes (prompt rewrite, subagent CRUD, skill CRUD, memory CRUD) live,
      in-episode, no reset. The real `HarnessEvolver` is tightly coupled to
      a specific game harness (VLM calls, Pokemon-specific stores) and
      can't be imported as a library; `HarnessEvolver` below reproduces its
      *shape* (windowed trajectory -> reasoner -> structured
      create/update/retire directives -> apply -> per-pass error isolation)
      generically, over Nexus Core's own prompt/subagents/skills/memory,
      via a pluggable `reasoner` callable (heuristic default; swap in a
      real LLM call using the same JSON-directive protocol the source
      project uses for a full deployment).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from nexus_functor.types import Decision, FeedbackEvent, MacroStrategy, Objective

logger = logging.getLogger(__name__)

_STRATEGY_NAMES = [s.name for s in MacroStrategy]


# ══════════════════════════════════════════════════════════════════════════
# (b) Generic harness stores + evolver — the evolve_harness mechanism
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class HarnessStores:
    """Generic, in-memory CRUD stores for Nexus Core's own harness. Deliberately
    generic (unlike the real HarnessEvolver's Pokemon-specific stores) since
    here they hold Nexus Core's system prompt / subagents / skills / memory,
    not a game-playing agent's."""

    system_prompt: str = "You are Nexus Core, a helpful assistant."
    subagents: dict[str, dict[str, Any]] = field(default_factory=dict)
    skills: dict[str, dict[str, Any]] = field(default_factory=dict)
    memory_notes: list[str] = field(default_factory=list)

    def subagents_overview(self) -> str:
        if not self.subagents:
            return "(none)"
        return "\n".join(f"- {sid}: {s.get('description', '')}" for sid, s in self.subagents.items())

    def skills_overview(self) -> str:
        if not self.skills:
            return "(none)"
        return "\n".join(f"- {sid}: {s.get('description', '')}" for sid, s in self.skills.items())


ReasonerFn = Callable[[str, list[dict[str, Any]]], dict[str, Any]]


def _default_reasoner(task: str, trajectory_window: list[dict[str, Any]]) -> dict[str, Any]:
    """Heuristic stand-in for the real HarnessEvolver's LLM call. Looks at
    simple failure/success counts in the trajectory window and emits the
    same *shape* of structured directive the real project's LLM prompt asks
    for (create/update/retire, or a rewritten prompt fragment) — swap this
    callable for a real LLM call (same JSON-directive contract) in a full
    deployment."""
    failures = [t for t in trajectory_window if t.get("outcome") == "FAILURE"]
    successes = [t for t in trajectory_window if t.get("outcome") == "SUCCESS"]
    failure_rate = len(failures) / max(1, len(trajectory_window))

    if task == "prompt":
        if failure_rate > 0.4:
            return {"append": (
                " Recent steps show a high failure rate — double-check "
                "preconditions before acting and prefer smaller, verifiable steps."
            )}
        return {"append": ""}

    if task == "subagents":
        create = []
        repeated_action, count = _most_common_action(successes)
        if repeated_action and count >= 3:
            create.append({
                "id": f"sa_{repeated_action}",
                "description": f"Specialist for repeated action '{repeated_action}'",
            })
        return {"create": create, "update": [], "retire": []}

    if task == "skills":
        codify = []
        repeated_action, count = _most_common_action(successes)
        if repeated_action and count >= 3:
            codify.append({"id": f"skill_{repeated_action}", "description": f"Codified sequence: {repeated_action}"})
        repair = [f["step_id"] for f in failures if f.get("step_id")]
        return {"codify": codify, "repair": repair}

    if task == "memory":
        notes = []
        if failure_rate > 0.5:
            notes.append(f"Elevated failure rate ({failure_rate:.0%}) observed in recent window.")
        return {"add_notes": notes, "prune": []}

    return {}


def _most_common_action(events: list[dict[str, Any]]) -> tuple[Optional[str], int]:
    counts: dict[str, int] = {}
    for e in events:
        a = e.get("action")
        if a:
            counts[a] = counts.get(a, 0) + 1
    if not counts:
        return None, 0
    best = max(counts, key=counts.get)
    return best, counts[best]


class HarnessEvolver:
    """Generic re-implementation of `HarnessEvolver.evolve`'s 4-pass CRUD
    shape (see module docstring). Each pass is wrapped independently so one
    failing pass never blocks the others — faithful to the real mechanism."""

    def __init__(
        self,
        stores: Optional[HarnessStores] = None,
        reasoner: ReasonerFn = _default_reasoner,
        optimization_window_length: int = 50,
    ):
        self.stores = stores or HarnessStores()
        self._reasoner = reasoner
        self.optimization_window_length = optimization_window_length
        self.generation = 0

    def maybe_evolve(self, current_step: int, trajectory_window: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
        """Only evolves every `optimization_window_length` steps — a
        background process, not a per-tick meta-policy (per prompt)."""
        if current_step == 0 or current_step % self.optimization_window_length != 0:
            return None
        return self.evolve(trajectory_window, current_step)

    def evolve(self, trajectory_window: list[dict[str, Any]], current_step: int) -> dict[str, Any]:
        if not trajectory_window:
            return {"skipped": True, "reason": "no_trajectories"}

        results: dict[str, Any] = {}
        for name, fn in [
            ("prompt", lambda: self._evolve_prompt(trajectory_window)),
            ("subagents", lambda: self._evolve_subagents(trajectory_window)),
            ("skills", lambda: self._evolve_skills(trajectory_window)),
            ("memory", lambda: self._evolve_memory(trajectory_window)),
        ]:
            try:
                results[name] = fn()
            except Exception as e:  # pragma: no cover - defensive, mirrors source's per-pass isolation
                logger.error("Evolution pass %r failed: %s", name, e)
                results[name] = {"error": str(e)}

        self.generation += 1
        results["generation"] = self.generation
        results["step"] = current_step
        return results

    def _evolve_prompt(self, window: list[dict[str, Any]]) -> dict[str, Any]:
        directive = self._reasoner("prompt", window)
        addition = directive.get("append", "")
        if addition and addition not in self.stores.system_prompt:
            self.stores.system_prompt += addition
            return {"rewritten": True, "length": len(self.stores.system_prompt)}
        return {"rewritten": False}

    def _evolve_subagents(self, window: list[dict[str, Any]]) -> dict[str, Any]:
        directive = self._reasoner("subagents", window)
        created = []
        for spec in directive.get("create", []):
            sid = spec["id"]
            if sid not in self.stores.subagents:
                self.stores.subagents[sid] = spec
                created.append(sid)
        for sid in directive.get("retire", []):
            self.stores.subagents.pop(sid, None)
        return {"created": created, "retired": directive.get("retire", [])}

    def _evolve_skills(self, window: list[dict[str, Any]]) -> dict[str, Any]:
        directive = self._reasoner("skills", window)
        codified = []
        for spec in directive.get("codify", []):
            sid = spec["id"]
            if sid not in self.stores.skills:
                self.stores.skills[sid] = spec
                codified.append(sid)
        return {"codified": codified, "repaired": directive.get("repair", [])}

    def _evolve_memory(self, window: list[dict[str, Any]]) -> dict[str, Any]:
        directive = self._reasoner("memory", window)
        added = directive.get("add_notes", [])
        self.stores.memory_notes.extend(added)
        for note in directive.get("prune", []):
            if note in self.stores.memory_notes:
                self.stores.memory_notes.remove(note)
        return {"added": len(added), "pruned": len(directive.get("prune", []))}


# ══════════════════════════════════════════════════════════════════════════
# (a) HarnessPort — F0 prior + slow-loop outcome recording
# ══════════════════════════════════════════════════════════════════════════

class NexusHarnessAdapter:
    """`HarnessPort` implementation, plus the `evolve_harness` tool exposed
    separately to Nexus Core (see module docstring — two distinct data
    flows sharing one module)."""

    def __init__(self, harness_trust: float = 0.6, evolver: Optional[HarnessEvolver] = None):
        self.harness_trust = harness_trust
        self.evolver = evolver or HarnessEvolver()
        # per-objective outcome tallies feeding the learned prior
        self._tallies: dict[str, dict[str, float]] = {}

    # -- HarnessPort protocol -------------------------------------------------

    def get_policy_prior(self, objective: Objective, context: dict[str, Any]) -> dict[str, float]:
        tallies = self._tallies.get(objective.goal_id)
        if not tallies:
            # No history yet: uniform prior (F0 will rely on live drift signals).
            return {name: 1.0 / len(_STRATEGY_NAMES) for name in _STRATEGY_NAMES}
        total = sum(tallies.values()) or 1.0
        return {name: tallies.get(name, 0.0) / total for name in _STRATEGY_NAMES}

    def record_outcome(self, objective: Objective, decision: Decision, feedback: FeedbackEvent) -> None:
        tallies = self._tallies.setdefault(objective.goal_id, {name: 0.0 for name in _STRATEGY_NAMES})
        # Reward the macro-strategy that was active when a good outcome landed;
        # this is the slow-loop update the prompt describes ("reçoit en retour
        # les résultats agrégés de la boucle lente").
        weight = {"SUCCESS": 1.0, "PARTIAL": 0.3, "FAILURE": -0.5}.get(feedback.outcome.name, 0.0)
        tallies[decision.macro_strategy.name] = max(0.0, tallies[decision.macro_strategy.name] + weight)

    # -- evolve_harness tool, exposed to Nexus Core --------------------------

    def evolve_harness(self, current_step: int, trajectory_window: list[dict[str, Any]]) -> dict[str, Any]:
        """The tool Nexus Core calls (per prompt: "Exposé comme outil
        evolve_harness, appelable par Nexus Core")."""
        return self.evolver.maybe_evolve(current_step, trajectory_window) or {
            "skipped": True, "reason": "not_at_window_boundary",
        }
