"""
bridge.leon_client
====================

Thin client for the Leon -> bridge -> Leon round trip described in the
mission's point #3 ("pont bidirectionnel"): a NexusCore native `Skill`
needs to actually run one of Leon's existing skill actions (native voice
skills, unchanged) rather than reimplementing it in Python. Leon already
exposes exactly the HTTP surface needed for this —
`POST /api/{version}/run-action` (see `server/src/core/http-server/api/
run-action/post.ts`, untouched by this integration) — so this client calls
that endpoint rather than reaching into Leon's skill runtime directly.

This is the (a) option from the mission's skill-mapping point: "un `Skill`
natif de `NexusCore.skills` qui rappelle Leon via un second appel HTTP pour
exécuter l'action réelle". See bridge/skills.py for the 2-3 skills wired up
this way.
"""

from __future__ import annotations

from typing import Any, Optional

import requests

from .config import BridgeConfig, get_bridge_config, leon_run_action_url


class LeonActionError(RuntimeError):
    pass


class LeonClient:
    def __init__(self, cfg: Optional[BridgeConfig] = None):
        self._cfg = cfg or get_bridge_config()

    def run_action(
        self, skill_action: str, action_params: Optional[dict[str, Any]] = None, session_id: Optional[str] = None
    ) -> dict[str, Any]:
        """Calls Leon's POST /run-action with `skill_action` formatted as
        "skill_name:action_name" (Leon's own required format — see
        run-action/post.ts's `actionName.split(':')`). Raises
        `LeonActionError` on any transport/HTTP failure so callers (the
        Skill callables in skills.py) can decide how to surface that to
        NexusCore's TurnResult rather than silently returning nothing."""
        url = leon_run_action_url(self._cfg)
        body = {
            "skill_action": skill_action,
            # Leon's endpoint requires a truthy action_params even for
            # actions that take no parameters (see run-action/post.ts:
            # `if (!actionName || !actionParams)`) — {} is truthy in JS.
            "action_params": action_params or {},
        }
        if session_id:
            body["session_id"] = session_id

        try:
            resp = requests.post(url, json=body, timeout=self._cfg.leon_request_timeout_s)
        except requests.RequestException as e:
            raise LeonActionError(f"could not reach Leon at {url}: {e}") from e

        try:
            payload = resp.json()
        except ValueError as e:
            raise LeonActionError(f"Leon returned a non-JSON response ({resp.status_code}): {e}") from e

        if not payload.get("success", False):
            raise LeonActionError(
                f"Leon rejected run-action for {skill_action!r}: "
                f"{payload.get('code')} — {payload.get('message')}"
            )
        return payload
