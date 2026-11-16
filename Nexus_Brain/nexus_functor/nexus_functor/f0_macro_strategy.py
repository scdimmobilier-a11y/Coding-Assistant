"""
nexus_functor.f0_macro_strategy
=================================

F0 — the top level of the hierarchy. Decides *which broad regime* the run
is currently in (EXPLOIT / EXPLORE / RECOVER / CONSERVE). Everything below
(F1's scoring weights) is conditioned on F0's choice.

F0 blends two signals:
  1. Nexus Harness's learned prior over strategies for this kind of
     objective (the "slow loop" — what has worked before).
  2. The live deviation trend from ExecutionState (the "fast loop" — what
     is happening right now, this run).

A hard safety valve overrides both: if cumulative deviation blows past
`recover_deviation_threshold`, F0 forces RECOVER no matter what.
"""

from __future__ import annotations

from .config import F0Config
from .types import ExecutionState, MacroStrategy


class F0MacroStrategySelector:
    def __init__(self, config: F0Config) -> None:
        self._config = config
        self._current: MacroStrategy = MacroStrategy.EXPLOIT
        self._ticks_in_current: int = 0

    @property
    def current(self) -> MacroStrategy:
        return self._current

    def select(
        self,
        harness_prior: dict[str, float],
        execution_state: ExecutionState,
    ) -> MacroStrategy:
        """Pick (or stick with) a macro-strategy for this tick."""
        self._ticks_in_current += 1

        # Hard safety valve: bypasses hysteresis entirely, deviation this
        # bad is never "wait and see".
        if execution_state.cumulative_deviation >= self._config.recover_deviation_threshold:
            return self._commit(MacroStrategy.RECOVER)

        # Below the minimum dwell time, don't even evaluate a change —
        # cheap first line of defense against flapping (F3 adds a second,
        # stricter check on the final decision).
        if self._ticks_in_current < self._config.min_dwell_ticks:
            return self._current

        candidate = self._blend(harness_prior, execution_state)
        return self._commit(candidate)

    def _blend(
        self,
        harness_prior: dict[str, float],
        execution_state: ExecutionState,
    ) -> MacroStrategy:
        trust = self._config.harness_trust
        live_bias = self._live_strategy_bias(execution_state)

        scores: dict[MacroStrategy, float] = {}
        for strategy in MacroStrategy:
            prior_score = harness_prior.get(strategy.name, 0.0)
            live_score = live_bias.get(strategy, 0.0)
            scores[strategy] = trust * prior_score + (1.0 - trust) * live_score

        return max(scores, key=scores.get)

    @staticmethod
    def _live_strategy_bias(execution_state: ExecutionState) -> dict[MacroStrategy, float]:
        """
        Turn the raw deviation trend into a rough preference over
        strategies, independent of any learned prior. This is deliberately
        simple (linear thresholds) — it's a fast, cheap fallback signal,
        not meant to be the sophisticated part of the system.
        """
        dev = execution_state.cumulative_deviation
        if dev < 0.15:
            return {MacroStrategy.EXPLOIT: 1.0, MacroStrategy.EXPLORE: 0.6,
                     MacroStrategy.RECOVER: 0.0, MacroStrategy.CONSERVE: 0.2}
        if dev < 0.4:
            return {MacroStrategy.EXPLOIT: 0.6, MacroStrategy.EXPLORE: 0.3,
                     MacroStrategy.RECOVER: 0.4, MacroStrategy.CONSERVE: 0.3}
        return {MacroStrategy.EXPLOIT: 0.1, MacroStrategy.EXPLORE: 0.0,
                MacroStrategy.RECOVER: 1.0, MacroStrategy.CONSERVE: 0.5}

    def _commit(self, strategy: MacroStrategy) -> MacroStrategy:
        if strategy != self._current:
            self._current = strategy
            self._ticks_in_current = 0
        return self._current
