"""
nexus_brain.adapters.codegen_adapter
=======================================

D3 (`MISSION_couple_leon_nexusbrain.md`): the adapter that lets Nexus Exec
actually reach the real deliverable-producing system — `nexus_compose`'s
pipeline in `Nexus_Assistant/api` (the 10-phase/169-node graph:
co-design -> ... -> crewAI/OpenHands codegen -> ... -> deployment) — for
plan steps whose action is `"deliver_software"`.

Before this adapter existed, M3 (`MISSION_couple_leon_nexusbrain.md`,
verified by grep: zero mention of `nexus_compose`/`crewai`/`openhands`/
`openmanus` anywhere under `Nexus_Brain/`) meant Nexus Functor had no way
to reach the pipeline no matter what a plan said — the only door into it
was `POST /api/pipeline/run`, called directly by `nexus-ui`.

**Deliberately does not import `nexus_compose` or `unified_system` in
Python.** The `nexus_compose` container is not guaranteed to have crewAI
installed (see `unified_system/bridge.py`'s own docstring on this exact
point), and Invariant #1 (`docs/INVARIANTS.md`) is that Nexus Brain's five
modules — and, by the same logic, anything Nexus Brain talks to outside
itself — communicate through an explicit seam, never an in-process import
that silently couples two independently-deployed codebases. So this
module talks to `nexus_compose` the same way `nexus_core_leon_bridge`
already talks to Leon (`bridge/leon_client.py`): a local HTTP call, a
dedicated exception type, a configurable timeout — nothing shared at
import time.

`nexus_compose` remains the single source of truth for the 10-phase
pipeline (`nexus_compose/drivers.py::_codegen_unified` and friends,
unmodified) — this adapter is a caller of `POST /api/pipeline/run`
(`Nexus_Assistant/api/pipeline.py`, already existing, unmodified), never a
second implementation of what that endpoint does.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional

import requests

# Default matches the root README's own documented dev invocation
# (`uvicorn api.main:app --reload --port 8000`, run from `Nexus_Assistant/`).
_DEFAULT_NEXUS_COMPOSE_API_URL = "http://127.0.0.1:8000"


class CodegenAdapterError(RuntimeError):
    """Raised on any transport/HTTP failure talking to `nexus_compose`'s
    pipeline API — never swallowed silently, so `NexusExecAdapter` can
    turn it into an honest `FeedbackEvent(outcome=Outcome.FAILURE, ...)`
    rather than pretending a pipeline run started."""


@dataclass(frozen=True)
class CodegenAdapterConfig:
    base_url: str = os.environ.get("NEXUS_COMPOSE_API_URL", _DEFAULT_NEXUS_COMPOSE_API_URL)
    request_timeout_s: float = float(os.environ.get("NEXUS_COMPOSE_API_TIMEOUT_S", "10.0"))


class CodegenAdapter:
    """The tool `NexusExecAdapter` invokes for `deliver_software` plan
    steps (see `exec_adapter.py::NexusExecAdapter.register_deliver_software_step`
    and its `execute_step` override)."""

    def __init__(self, cfg: Optional[CodegenAdapterConfig] = None):
        self._cfg = cfg or CodegenAdapterConfig()

    def deliver_software(self, instruction: str, *, goal_id: Optional[str] = None) -> dict[str, Any]:
        """Calls Nexus Assistant's `POST /api/pipeline/run` — the exact
        same endpoint `nexus-ui`'s own "Run" button calls — so a run
        triggered from a Leon conversation, via Nexus Functor, shows up
        identically in the pipeline dashboard (same run_id, same SSE
        stream, same node graph, same dashboard-registered LLM — see
        `nexus_compose/llm_config.py` — as any other run).

        `goal_id`, when given, is folded into the tracked instruction so
        the eventual report can be traced back to the objective that
        requested it, without requiring a schema change on
        `Nexus_Assistant/api/pipeline.py`'s side (its `RunRequest` only
        has `instruction`/`phase` — see D3's own scope note on this).

        Raises `CodegenAdapterError` on any transport/HTTP failure.
        """
        url = f"{self._cfg.base_url}/api/pipeline/run"
        tagged_instruction = instruction if not goal_id else f"[objective:{goal_id}] {instruction}"

        try:
            resp = requests.post(
                url, json={"instruction": tagged_instruction}, timeout=self._cfg.request_timeout_s
            )
        except requests.RequestException as e:
            raise CodegenAdapterError(f"could not reach Nexus Assistant's pipeline API at {url}: {e}") from e

        if resp.status_code >= 400:
            raise CodegenAdapterError(
                f"pipeline API rejected the run (HTTP {resp.status_code}): {resp.text[:200]}"
            )

        try:
            return resp.json()
        except ValueError as e:
            raise CodegenAdapterError(
                f"pipeline API returned a non-JSON response ({resp.status_code}): {e}"
            ) from e
