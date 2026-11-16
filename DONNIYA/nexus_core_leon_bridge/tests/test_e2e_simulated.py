"""
tests.test_e2e_simulated
===========================

Deliverable #8, scenario 1: "un scénario bout-en-bout simulé (texte
transcrit fictif -> pont -> Nexus Core -> réponse -> texte à énoncer
fictif)". Uses FastAPI's TestClient to drive the bridge's real HTTP
surface exactly as leon_patch's nexus-bridge-client.ts would, with a
`FakeLeonClient` standing in for Leon's own (untouched, unmodified)
`POST /run-action` endpoint.
"""

from fastapi.testclient import TestClient

from bridge.core_factory import build_nexus_core
from bridge.server import create_app
from tests.fakes import FakeLeonClient


def _client_with_fake_leon(fake_leon: FakeLeonClient) -> TestClient:
    core = build_nexus_core(leon_client=fake_leon)
    app = create_app(core=core)
    return TestClient(app)


def test_fictive_transcribed_utterance_reaches_a_bridged_leon_skill():
    """Simulates: Micro -> Wake word -> ASR (fictively already transcribed
    to text here, exactly as it would be for the real pipeline, which this
    test does not touch) -> pont -> NexusCore.handle_turn -> TurnResult ->
    text Leon would hand to TTS."""
    fake_leon = FakeLeonClient()
    client = _client_with_fake_leon(fake_leon)

    fictive_transcribed_text = "hey leon, what time is it"
    resp = client.post(
        "/handle_turn",
        json={"user_input": fictive_transcribed_text, "context": {}, "mode": "smart", "session_id": "sess-1"},
    )

    assert resp.status_code == 200
    body = resp.json()

    # Routed through the "time" native skill (controlled mode, no ReAct
    # loop needed) -> Nexus Core called Leon's real date_time skill
    # through the bridge, exactly as the mission's point #3 asks.
    assert body["mode_used"] == "controlled"
    assert body["paused"] is False
    assert "14:32" in body["response"]  # the fictive text-to-speak
    assert fake_leon.calls == [{"skill_action": "date_time:current_time", "action_params": {}, "session_id": "sess-1"}]


def test_fictive_utterance_with_no_native_skill_match_falls_back_to_agent():
    fake_leon = FakeLeonClient()
    client = _client_with_fake_leon(fake_leon)

    resp = client.post(
        "/handle_turn",
        json={
            "user_input": "help me plan a demo for investors next week",
            "context": {},
            "mode": "smart",
            "session_id": "sess-2",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode_used"] == "agent"
    # No skill matched, so agent mode's single-step plan requires
    # human-in-the-loop approval before delegating -> PAUSED.
    assert body["paused"] is True
    assert body["goal_key"] == "help me plan a demo for investors next week"


def test_leon_memory_digest_is_loaded_as_runtime_context_before_the_turn():
    """Read side of the memory decision (docs/DECISIONS.md): whatever
    digest Leon supplies is loaded as a runtime-context file BEFORE
    Nexus Core reasons about the turn."""
    from bridge.memory_bridge import LEON_DIGEST_CONTEXT_KEY

    fake_leon = FakeLeonClient()
    core = build_nexus_core(leon_client=fake_leon)
    app = create_app(core=core)
    client = TestClient(app)

    resp = client.post(
        "/handle_turn",
        json={
            "user_input": "tell me a joke",
            "context": {"leon_memory_digest": "Owner's name is Isaac; prefers concise answers."},
            "mode": "smart",
            "session_id": "sess-3",
        },
    )
    assert resp.status_code == 200
    assert "bridge the other side" in resp.json()["response"]

    # The digest Leon supplied is now visible as a runtime context file —
    # LayeredMemory documents these as "consulted first" on any recall().
    assert (
        core.memory.runtime_context()[LEON_DIGEST_CONTEXT_KEY]
        == "Owner's name is Isaac; prefers concise answers."
    )
