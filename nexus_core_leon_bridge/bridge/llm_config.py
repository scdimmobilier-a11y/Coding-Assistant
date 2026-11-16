"""
bridge.llm_config
====================

Deliverable #7 ("Configuration LLM"): the mission asks to reuse, AS-IS, the
single LLM config already standardized for the rest of Nexus Assistant
(`NEXUS_LLM_PROVIDER` / `NEXUS_LLM_MODEL` / `NEXUS_LLM_API_KEY` /
`NEXUS_LLM_BASE_URL`, resolved by `nexus_compose.llm_config.get_llm_config()`)
— including for any LLM call Leon used to make on its own. This module does
NOT reimplement that resolution logic a second time (that would immediately
create the same "N components, N configs" drift the mission is fixing).

Two deployment shapes are supported, per the "Nexus Core must stay usable
independently of Leon's Node.js runtime" constraint:

  1. This bridge lives inside/next to the Nexus Assistant repo (its
     intended home) -> `nexus_compose` is importable -> we call the real
     `get_llm_config()` directly. This is the only code path used in
     production; the fallback below exists solely so this package's own
     tests don't require the whole Nexus Assistant tree to be present.
  2. Nexus Core / this bridge is exercised standalone (e.g. this package's
     own test suite, or a future non-Leon integration) -> `nexus_compose`
     is not on the path -> `_FallbackLLMConfig` reads the *exact same* env
     vars with the *exact same* priority order, so behaviour is identical
     wherever `nexus_compose` happens to be absent. It is intentionally a
     read-only mirror, not a second source of truth: if `nexus_compose`'s
     resolution logic ever changes, only case 2 (tests-without-the-repo)
     would need to catch up, never case 1 (real deployments).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None

    @property
    def qualified_model(self) -> str:
        return f"{self.provider}/{self.model}"


def _fallback_get_llm_config(overrides: Optional[dict] = None) -> LLMConfig:
    """Mirrors nexus_compose.llm_config.get_llm_config() exactly (same env
    vars, same priority order, same defaults) for use when nexus_compose
    is not importable. See module docstring, case 2."""
    overrides = overrides or {}
    provider = overrides.get("provider") or os.environ.get("NEXUS_LLM_PROVIDER") or "openai"
    model = (
        overrides.get("model")
        or os.environ.get("NEXUS_LLM_MODEL")
        or os.environ.get("CREWAI_LLM_MODEL")
        or "gpt-4o-mini"
    )
    api_key = (
        overrides.get("api_key")
        or os.environ.get("NEXUS_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or ""
    )
    base_url = overrides.get("base_url") or os.environ.get("NEXUS_LLM_BASE_URL") or None
    return LLMConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)


def get_llm_config(overrides: Optional[dict] = None) -> LLMConfig:
    """Single entry point the bridge (and anything it wires into NexusCore
    — planner/executor callables that need an LLM) should call. Never call
    os.environ[...] for LLM settings anywhere else in this package."""
    try:
        from nexus_compose.llm_config import get_llm_config as _real_get_llm_config

        real = _real_get_llm_config(overrides)
        return LLMConfig(
            provider=real.provider, model=real.model, api_key=real.api_key, base_url=real.base_url
        )
    except ImportError:
        return _fallback_get_llm_config(overrides)
