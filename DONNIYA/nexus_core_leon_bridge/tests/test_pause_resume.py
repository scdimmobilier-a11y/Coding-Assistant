"""
tests.test_pause_resume
==========================

Deliverable #8, scenario 2: "un scénario de pause/reprise déclenché par le
pont." Also exercises deliverable #4's core claim: Nexus Core's PAUSED
state maps to a Leon-side confirmation, and the human's answer (captured
by Leon's *existing*, unmodified voice pipeline — simulated here as plain
text, since ASR itself is explicitly out of scope) is what unblocks
`resume_paused`, without restarting the whole turn from scratch.
"""

from fastapi.testclient import TestClient

from bridge.core_factory import build_nexus_core
from bridge.server import create_app
from tests.fakes import FakeLeonClient


def _new_client():
    fake_leon = FakeLeonClient()
    core = build_nexus_core(leon_client=fake_leon)
    app = create_app(core=core)
    return TestClient(app), fake_leon, core


def test_paused_turn_can_be_resumed_via_session_id_without_the_caller_tracking_goal_key():
    client, fake_leon, core = _new_client()

    # 1) fictive transcribed utterance that doesn't match a native skill
    #    -> agent mode -> single ReAct step requires approval -> PAUSED.
    first = client.post(
        "/handle_turn",
        json={
            "user_input": "reorganize my calendar for the CyclOne investor week",
            "context": {},
            "mode": "smart",
            "session_id": "sess-pause-1",
        },
    ).json()

    assert first["paused"] is True
    assert first["mode_used"] == "agent"
    # This is exactly the text Leon should speak/display as the
    # confirmation prompt ("veux-tu que je continue ?" in the mission's
    # own wording) — it comes straight from ReactLoop's PAUSED response.
    assert isinstance(first["response"], str) and len(first["response"]) > 0

    # 2) Leon's OWN unmodified voice pipeline (ASR) captures the human's
    #    spoken reply. leon_patch's nexus-bridge-client.ts sees this
    #    session is "awaiting resume" and calls /resume_paused instead of
    #    a fresh /handle_turn — it only needs session_id, never the
    #    original goal string (the bridge tracked that server-side).
    second = client.post(
        "/resume_paused",
        json={
            "session_id": "sess-pause-1",
            "approved": True,
            "human_input": {},
            "context": {},
        },
    ).json()

    assert second["paused"] is False
    assert "Delegated to Nexus Functor" in second["response"] or "I can't delegate" in second["response"]

    # 3) Session is no longer tracked as paused -> a THIRD call to
    #    /resume_paused for the same session correctly 404s instead of
    #    silently reusing a stale goal_key.
    third = client.post("/resume_paused", json={"session_id": "sess-pause-1", "approved": True})
    assert third.status_code == 404


def test_rejecting_the_pause_does_not_crash_and_still_clears_session_state():
    client, fake_leon, core = _new_client()

    client.post(
        "/handle_turn",
        json={"user_input": "book a flight to nowhere", "context": {}, "mode": "agent", "session_id": "sess-pause-2"},
    )

    resumed = client.post(
        "/resume_paused",
        json={"session_id": "sess-pause-2", "approved": False, "human_input": {"reason": "changed my mind"}},
    )
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False

    # Session cleared either way — approve or reject, no leftover state.
    again = client.post("/resume_paused", json={"session_id": "sess-pause-2", "approved": True})
    assert again.status_code == 404


def test_resume_without_a_prior_paused_turn_returns_404_not_a_500():
    client, fake_leon, core = _new_client()
    resp = client.post("/resume_paused", json={"session_id": "never-started", "approved": True})
    assert resp.status_code == 404
