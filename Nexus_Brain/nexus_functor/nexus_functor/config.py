"""
nexus_functor.config
======================

All tunable knobs live here, in one place, instead of scattered magic
numbers through F0-F3. Every field has a comment explaining what turning
it up/down does in practice.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class F0Config:
    # How much weight F0 gives to Nexus Harness's learned prior vs. the
    # live deviation trend when picking a macro-strategy. 1.0 = trust the
    # harness completely; 0.0 = react purely to what's happening right now.
    harness_trust: float = 0.6

    # Cumulative-deviation threshold above which F0 forces RECOVER
    # regardless of what the harness prior says. Safety valve.
    recover_deviation_threshold: float = 0.75

    # Minimum number of ticks between macro-strategy changes (its own,
    # cheaper hysteresis layer; F3 adds a second, stricter one on top for
    # the full decision).
    min_dwell_ticks: int = 3


@dataclass
class F1Config:
    """
    Per-macro-strategy weight tables. Each plan gets scored as:
        score(plan) = w_reward*reward_norm + w_conf*confidence
                      + w_novelty*novelty - w_cost*cost_norm
    Weights don't need to sum to 1; only their ratios matter.
    """

    plan_weights: dict[str, dict[str, float]] = field(default_factory=lambda: {
        "EXPLOIT":  {"reward": 1.0, "confidence": 1.0, "novelty": 0.0, "cost": 0.6},
        "EXPLORE":  {"reward": 0.6, "confidence": 0.2, "novelty": 1.2, "cost": 0.3},
        "RECOVER":  {"reward": 0.3, "confidence": 1.4, "novelty": 0.0, "cost": 1.2},
        "CONSERVE": {"reward": 0.5, "confidence": 0.8, "novelty": 0.0, "cost": 1.5},
    })

    # Joint proactive score: J(a, tau) = utility * receptivity - lambda_cost * cost
    proactive_cost_lambda: float = 1.0

    # A proactive candidate is even considered only if its receptivity
    # clears this floor — below this, "the timing is just bad" and F1
    # won't propose interrupting no matter how valuable the action is.
    min_receptivity: float = 0.25


@dataclass
class F2Config:
    # Per-step deviation beyond which F2 patches the plan locally
    # (e.g. retry / substitute) instead of doing nothing.
    local_patch_threshold: float = 0.3

    # Cumulative deviation beyond which F2 stops patching locally and
    # instead escalates to F1 ("this plan is no longer working, pick again").
    escalate_threshold: float = 0.6

    # Exponential-decay factor applied to cumulative_deviation each tick,
    # so old drift doesn't haunt the run forever once things stabilize.
    deviation_decay: float = 0.9


@dataclass
class F3Config:
    """
    Anti-oscillation layer. Two independent hysteresis mechanisms: one for
    plan switches (F1's output) and one for proactive timing (also F1's
    output, the (a*, tau*) side) — this is the layer the architecture doc
    calls for specifically to counter over-anticipation / temporal
    oscillation in the fused proactive policy.
    """

    # A candidate plan must beat the currently-committed plan's score by
    # at least this margin to trigger a switch. Prevents thrashing between
    # two near-tied plans.
    plan_switch_margin: float = 0.15

    # Minimum ticks a plan must run before it's eligible to be switched
    # away from again, even if a better one appears.
    plan_min_dwell_ticks: int = 2

    # After a proactive action is taken (or explicitly deferred), how many
    # seconds before another proactive action is eligible to fire. Blocks
    # rapid back-to-back interruptions.
    proactive_cooldown_s: float = 30.0

    # Smoothing factor for the receptivity signal (exponential moving
    # average), 0 = no smoothing (raw signal), close to 1 = very smooth /
    # slow to react. Dampens noisy tau oscillation.
    receptivity_smoothing: float = 0.3


@dataclass
class FunctorConfig:
    f0: F0Config = field(default_factory=F0Config)
    f1: F1Config = field(default_factory=F1Config)
    f2: F2Config = field(default_factory=F2Config)
    f3: F3Config = field(default_factory=F3Config)
