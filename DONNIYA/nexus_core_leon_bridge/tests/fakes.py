"""
tests.fakes
=============

A fake `LeonClient` so the bridge's own tests never need a real Leon
Node.js server running — they test the bridge's logic (routing, pause/
resume, skill dispatch), not Leon's `run-action` endpoint itself (which is
untouched Leon code, out of scope for this delivery to re-test).
"""

from __future__ import annotations

from typing import Any, Optional

from bridge.leon_client import LeonActionError


class FakeLeonClient:
    """Records every call and returns a scripted response per
    `skill_action`, mirroring the real shape of Leon's
    POST /api/{version}/run-action success payload (see
    server/src/core/http-server/api/run-action/post.ts)."""

    def __init__(self, scripted_speeches: Optional[dict[str, list[str]]] = None):
        self.calls: list[dict[str, Any]] = []
        self._scripted_speeches = scripted_speeches or {
            "date_time:current_time": ["It's 14:32."],
            "joke:run": ["Why did the AI cross the road? To bridge the other side."],
            "introduction:introduce_leon": ["I'm Leon, now running on Nexus Core."],
        }
        self.fail_on: set[str] = set()

    def run_action(
        self, skill_action: str, action_params: Optional[dict[str, Any]] = None, session_id: Optional[str] = None
    ) -> dict[str, Any]:
        self.calls.append(
            {"skill_action": skill_action, "action_params": action_params or {}, "session_id": session_id}
        )
        if skill_action in self.fail_on:
            raise LeonActionError(f"scripted failure for {skill_action}")

        speeches = self._scripted_speeches.get(skill_action, [])
        return {
            "success": True,
            "status": 200,
            "code": "action_executed",
            "message": "Skill action executed successfully.",
            "result": {"speeches": speeches, "lastOutputFromSkill": {"answer": {}, "core": None}},
        }
