"""
bridge.config
===============

All the bridge's own configuration in one place, entirely env-driven so it
fits into the existing Nexus Assistant `.env` (deliverable #7 — one LLM
config for the whole system, Leon included; see docs/DECISIONS.md for how
this module treats that requirement).

Nothing here is Leon-specific state (session/pause tracking lives in
`server.py`) — this module only answers "where is Leon, and what does the
bridge listen on".
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeConfig:
    # -- where Leon's own HTTP server is reachable (unchanged Leon server,
    # not something this project introduces) --
    leon_base_url: str = os.environ.get("LEON_BASE_URL", "http://localhost:5366")
    leon_api_version: str = os.environ.get("LEON_API_VERSION", "v1")
    leon_request_timeout_s: float = float(os.environ.get("LEON_REQUEST_TIMEOUT_S", "8.0"))

    # -- where THIS bridge listens (consumed from Leon's Node.js runtime via
    # fetch/axios, per the mission's point #1) --
    bridge_host: str = os.environ.get("NEXUS_BRIDGE_HOST", "127.0.0.1")
    bridge_port: int = int(os.environ.get("NEXUS_BRIDGE_PORT", "8420"))

    # -- default NexusCore routing mode when Leon doesn't send one
    # explicitly (Leon always will in practice — see leon_patch — but the
    # bridge must not crash if called directly, e.g. from curl/tests) --
    default_mode: str = os.environ.get("NEXUS_BRIDGE_DEFAULT_MODE", "smart")

    # -- how often the background ObjectiveRunner tick loop runs (D1,
    # MISSION_couple_leon_nexusbrain.md) — see server.py's lifespan --
    objective_tick_interval_s: float = float(os.environ.get("NEXUS_BRIDGE_TICK_INTERVAL_S", "2.0"))

    # -- where nexus_compose's own HTTP API is reachable (Mission 2 —
    # Meta Framework / Nexus Studio, D4). Same env var names as
    # `nexus_brain.adapters.codegen_adapter.CodegenAdapterConfig`
    # deliberately — one env var configures "where is nexus_compose" for
    # both the codegen bridge (Mission 1, D3) and the registry aggregator
    # (Mission 2, D4), no need to set it twice. See
    # bridge/registry_aggregator.py. --
    nexus_compose_api_url: str = os.environ.get("NEXUS_COMPOSE_API_URL", "http://127.0.0.1:8000")
    nexus_compose_api_timeout_s: float = float(os.environ.get("NEXUS_COMPOSE_API_TIMEOUT_S", "10.0"))


def get_bridge_config() -> BridgeConfig:
    return BridgeConfig()


def leon_run_action_url(cfg: BridgeConfig) -> str:
    return f"{cfg.leon_base_url}/api/{cfg.leon_api_version}/run-action"
