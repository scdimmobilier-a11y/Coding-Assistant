"""
nexus_brain.adapters.proactive_adapter
=========================================

`ProactivePort` adapter, fusing:
  - **Nexus Proactive — WHAT** (THUNLP ProactiveAgent): "should I propose
    anything at all, and how good is it" — Environment Gym -> Proactive
    Agent -> Reward Model.
  - **Nexus Proactive — WHEN** (Leonardo Mariga's ProactiveAgent,
    `vendor/nexus_proactive_when`, real & vendored, imported unmodified):
    "is *now* a good time" — Decision Engine + Sleep Calculator.

Per prompt_nexus_brain.md: WHAT and WHEN are two **independent** background
loops, each with its own learning signal (WHAT learns from accept/reject/
ignore; WHEN learns from engagement/timing) — "Elles ne se fusionnent **pas**
entre elles directement". The real fusion `J(a,tau) = utility(a)*
receptivity(tau) - lambda*cost(a,tau)` happens in Nexus Functor's F1, not
here. This adapter's only job is to hand F1 a `ProactiveSignal`: one
`ProactiveCandidate(action, utility, receptivity, cost, tau_offset_s)` per
WHAT-proposed action, with WHEN's receptivity/timing attached to each.

WHAT (`WhatEngine` below): the real THUNLP pipeline needs a running
ActivityWatch daemon plus a model fine-tuned specifically for that
benchmark (hosted externally, not fetchable offline). `WhatEngine`
reproduces the real *mechanism* — activity signal -> candidate proposal ->
reward-model-style score -> 3-state accept/reject/ignore feedback loop that
directly modulates future proposal frequency — via pluggable
proposer/reward callables (heuristic defaults; swap in real model calls for
a full deployment).

WHEN (`WhenEngine` below): thin wrapper around the real, vendored,
unmodified `ThresholdDecisionEngine` + `FunctionBasedSleepCalculator`.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import Any, Callable, Optional

_VENDOR_WHEN = Path(__file__).resolve().parents[2] / "vendor" / "nexus_proactive_when"
if str(_VENDOR_WHEN) not in sys.path:
    sys.path.insert(0, str(_VENDOR_WHEN))

from nexus_proactive_when.decision_engines.threshold_based import ThresholdDecisionEngine  # noqa: E402
from nexus_proactive_when.sleep_time_calculators.function_based import FunctionBasedSleepCalculator  # noqa: E402

from nexus_functor.types import ProactiveCandidate, ProactiveSignal  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# WHAT — latent-need detection + reward-model-style filtering
# ══════════════════════════════════════════════════════════════════════════

Feedback = str  # "accept" | "reject" | "ignore"

_DEFAULT_UTILITY_STEP = {"accept": +0.15, "reject": -0.30, "ignore": -0.05}


def _default_proposer(activity: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    """Heuristic stand-in for THUNLP's fine-tuned Proactive Agent: turns a
    coarse activity signal into 0-2 candidate actions. Real deployments
    swap this for an actual model call over the same `activity` shape."""
    candidates = []
    idle_s = activity.get("idle_seconds", 0)
    app = activity.get("active_window", "")
    if idle_s > 120:
        candidates.append({"action": "offer_break_summary", "base_utility": 0.4, "cost": 0.1})
    if "code" in app.lower() or "ide" in app.lower():
        candidates.append({"action": "offer_test_reminder", "base_utility": 0.55, "cost": 0.15})
    if activity.get("error_detected"):
        candidates.append({"action": "offer_error_diagnosis", "base_utility": 0.8, "cost": 0.2})
    return candidates


def _default_reward_model(candidate: dict[str, Any], activity: dict[str, Any]) -> float:
    """Heuristic stand-in for the trained Reward Model (THUNLP reports
    F1=0.918 on their benchmark) that filters candidate quality before
    presentation. Returns a [0, 1] quality score."""
    base = candidate.get("base_utility", 0.5)
    # Slightly discount candidates proposed under very sparse activity signal
    # (mirrors the real RM's role: filter out low-confidence proposals).
    confidence = 1.0 if activity else 0.6
    return max(0.0, min(1.0, base * confidence))


class WhatEngine:
    """Nexus Proactive — WHAT: environment sensing -> candidate proposal ->
    reward-model filtering -> accept/reject/ignore feedback loop that
    directly reweights future proposal frequency for that action type."""

    def __init__(
        self,
        proposer: Callable[[dict, dict], list[dict]] = _default_proposer,
        reward_model: Callable[[dict, dict], float] = _default_reward_model,
        utility_step: dict[str, float] = None,
    ):
        self._proposer = proposer
        self._reward_model = reward_model
        self._utility_step = utility_step or _DEFAULT_UTILITY_STEP
        # per-action-type running multiplier in [0.1, 1.5], updated by feedback
        self._frequency_multiplier: dict[str, float] = {}

    def propose(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        activity = context.get("activity", {})
        raw = self._proposer(activity, context)
        proposals = []
        for c in raw:
            mult = self._frequency_multiplier.get(c["action"], 1.0)
            if mult <= 0.15:
                continue  # repeatedly-rejected action type: suppressed, not proposed at all
            quality = self._reward_model(c, activity)
            proposals.append({
                "action": c["action"],
                "utility": quality * mult,
                "cost": c.get("cost", 0.1),
            })
        return proposals

    def record_feedback(self, action: str, feedback: Feedback) -> None:
        """3-state feedback (accept/reject/ignore) directly modulates the
        frequency multiplier for future proposals of this action type —
        exactly the loop described for Nexus Proactive — WHAT."""
        step = self._utility_step.get(feedback, 0.0)
        current = self._frequency_multiplier.get(action, 1.0)
        self._frequency_multiplier[action] = max(0.1, min(1.5, current + step))

    def frequency_multiplier(self, action: str) -> float:
        return self._frequency_multiplier.get(action, 1.0)


# ══════════════════════════════════════════════════════════════════════════
# WHEN — decision engine + sleep calculator (real, vendored)
# ══════════════════════════════════════════════════════════════════════════

def _default_sleep_fn(config: dict, context: dict) -> tuple[int, str]:
    """Function-based sleep calculator: shrinks the wait when engagement is
    high, stretches it when receptivity has been poor recently — a simple,
    dependency-free analogue of the AI-based calculator."""
    engagement = context.get("recent_engagement", 0.5)  # [0, 1], WHEN's own learning signal
    base = config.get("base_seconds", 60)
    factor = 1.6 - engagement  # high engagement -> shorter wait
    return max(5, int(base * factor)), f"engagement={engagement:.2f} factor={factor:.2f}"


class WhenEngine:
    """Nexus Proactive — WHEN: thin wrapper around the real, vendored
    `ThresholdDecisionEngine` + `FunctionBasedSleepCalculator`. Learns from
    engagement/timing feedback via `record_engagement`, independently of
    WHAT's accept/reject/ignore loop."""

    def __init__(
        self,
        response_thresholds: Optional[dict[str, int]] = None,
        base_sleep_seconds: int = 60,
    ):
        self._decision_engine = ThresholdDecisionEngine(response_thresholds=response_thresholds)
        self._sleep_calculator = FunctionBasedSleepCalculator(_default_sleep_fn)
        self._base_sleep_seconds = base_sleep_seconds
        self._recent_engagement = 0.5  # WHEN's own running learning signal, in [0, 1]
        self._last_event_time = time.time()

    def receptivity_and_timing(self, context: dict[str, Any]) -> tuple[float, float]:
        """Returns (receptivity in [0,1], tau_offset_s). `ThresholdDecisionEngine`
        only returns a bool + reason; we map that to a continuous receptivity
        score (0.8 if "yes, respond", 0.15 if "not yet") since F1 needs a
        continuous signal, not a hard gate — the hard gate already happened
        once, inside `should_respond`."""
        messages = context.get("messages", [])
        should, reason = asyncio.run(self._decision_engine.should_respond(
            messages=messages,
            last_user_message_time=context.get("last_user_message_time", self._last_event_time),
            context=context,
            config=context.get("when_config", {}),
            triggered_by_user_message=context.get("triggered_by_user_message", False),
        ))
        receptivity = 0.8 if should else 0.15

        sleep_s, _ = asyncio.run(self._sleep_calculator.calculate_sleep_time(
            config={"base_seconds": self._base_sleep_seconds, "max_sleep_time": 1800},
            context={**context, "recent_engagement": self._recent_engagement},
        ))
        tau_offset_s = 0.0 if should else float(sleep_s)
        return receptivity, tau_offset_s

    def record_engagement(self, engaged: bool) -> None:
        """WHEN's own learning signal (independent of WHAT's accept/reject/
        ignore): a light EMA over whether proposals-once-timed-right were
        actually engaged with."""
        alpha = 0.3
        self._recent_engagement = (1 - alpha) * self._recent_engagement + alpha * (1.0 if engaged else 0.0)
        self._last_event_time = time.time()


# ══════════════════════════════════════════════════════════════════════════
# ProactivePort adapter — hands F1 the raw candidate bag; does NOT fuse
# ══════════════════════════════════════════════════════════════════════════

class NexusProactiveAdapter:
    """`ProactivePort` implementation. Runs WHAT and WHEN as two independent
    engines and packages their outputs into a `ProactiveSignal` — the real
    utility*receptivity fusion happens in Nexus Functor's F1, not here."""

    def __init__(self, what: Optional[WhatEngine] = None, when: Optional[WhenEngine] = None):
        self.what = what or WhatEngine()
        self.when = when or WhenEngine()

    def estimate(self, state_id: str, context: dict[str, Any]) -> ProactiveSignal:
        proposals = self.what.propose(context)
        receptivity, tau_offset_s = self.when.receptivity_and_timing(context)

        candidates = tuple(
            ProactiveCandidate(
                action=p["action"],
                utility=p["utility"],
                receptivity=receptivity,
                cost=p["cost"],
                tau_offset_s=tau_offset_s,
            )
            for p in proposals
        )
        return ProactiveSignal(state_id=state_id, candidates=candidates)

    # -- feedback routing, kept separate per prompt's "two independent loops" --

    def record_what_feedback(self, action: str, feedback: Feedback) -> None:
        self.what.record_feedback(action, feedback)

    def record_when_engagement(self, engaged: bool) -> None:
        self.when.record_engagement(engaged)
