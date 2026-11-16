"""
tests.test_post_objective_wiring
====================================

§7 (`MISSION_couple_leon_nexusbrain.md`) required test: "un objectif posé
via `NexusCore.pose_objective()` atteint bien un `ObjectiveRunner` réel
(planner/executor/harness réels ou fakes), et le retour est non-bloquant."

Also covers, since they're all part of the same D1/D2/D3/D6 wiring and
share the same fixtures:
  - D2's delivery endpoints (`/objective/{goal_id}/status`,
    `/objective/{goal_id}/deliver`).
  - D3's opt-in `deliver_software` routing, end-to-end from
    `pose_objective` through to a (fake, no real network)
    `CodegenAdapter`.
  - D6's `evolve_harness_tool` wiring.

Real `NexusPlannerAdapter`/`NexusHarnessAdapter` are used throughout (fast,
no subprocess call unless a `planning_problem` is supplied, no network) —
only `CodegenAdapter` is faked, since its whole job is an HTTP call to a
`nexus_compose` process this test suite never starts (matches
`FakeLeonClient`'s own reasoning in `tests/fakes.py`).
"""

from __future__ import annotations

import re
from unittest import mock

from fastapi.testclient import TestClient

from bridge.core_factory import build_nexus_core_and_runner
from bridge.server import create_app
from nexus_brain.adapters.codegen_adapter import CodegenAdapter
from nexus_brain.adapters.exec_adapter import NexusExecAdapter
from nexus_brain.adapters.harness_adapter import NexusHarnessAdapter
from tests.fakes import FakeLeonClient


def _fake_codegen(run_id: str = "run-777"):
    fake = mock.create_autospec(CodegenAdapter, instance=True)
    fake.deliver_software.return_value = {"run_id": run_id}
    return fake


def _build(codegen=None, harness=None):
    codegen = codegen or _fake_codegen()
    executor = NexusExecAdapter(codegen_adapter=codegen)
    harness = harness or NexusHarnessAdapter()
    core, runner = build_nexus_core_and_runner(
        leon_client=FakeLeonClient(), executor=executor, harness=harness
    )
    return core, runner, codegen, harness


# ── pose_objective reaches a real runner, non-blocking ───────────────────────

def test_pose_objective_reaches_a_real_objective_runner():
    core, runner, _codegen, _harness = _build()

    result = core.pose_objective("ship the feature", {})

    assert result["posted"] is True
    goal_id = result["goal_id"]
    active = runner.get(goal_id)
    assert active is not None
    assert active.objective.description == "ship the feature"


def test_pose_objective_returns_immediately_without_ticking(monkeypatch):
    """Invariant #2: NexusCore must never loop on functor.step() itself —
    add_objective() only plans, it must not have executed anything yet."""
    core, runner, _codegen, _harness = _build()

    result = core.pose_objective("ship the feature", {})

    active = runner.get(result["goal_id"])
    assert active.tick_log == []  # nothing ticked — planning only, fire-and-forget


def test_explicit_post_objective_none_override_still_works():
    """build_nexus_core(post_objective=None) must still reproduce the
    pre-D1 behaviour on purpose — see core_factory.py's _UNSET sentinel."""
    from bridge.core_factory import build_nexus_core

    core = build_nexus_core(leon_client=FakeLeonClient(), post_objective=None)
    result = core.pose_objective("ship the feature", {})
    assert result["posted"] is False


# ── D3: opt-in deliver_software routing ──────────────────────────────────────

def test_deliver_software_opt_in_calls_codegen_adapter_on_tick():
    codegen = _fake_codegen(run_id="run-42")
    core, runner, codegen, _harness = _build(codegen=codegen)

    result = core.pose_objective("Livrer le module de facturation", {"deliver_software": True})
    codegen.deliver_software.assert_not_called()  # not yet — only on tick

    runner.run_forever(max_ticks=5)

    codegen.deliver_software.assert_called_once()
    called_instruction = codegen.deliver_software.call_args.args[0]
    assert called_instruction == "Livrer le module de facturation"
    assert runner.get_completed(result["goal_id"]) is not None


def test_deliver_software_opt_in_with_explicit_instruction_string():
    codegen = _fake_codegen()
    core, runner, codegen, _harness = _build(codegen=codegen)

    core.pose_objective(
        "aide-moi avec la facturation",
        {"deliver_software": "Générer le module de facturation avec tests"},
    )
    runner.tick_all()

    codegen.deliver_software.assert_called_once()
    assert codegen.deliver_software.call_args.args[0] == "Générer le module de facturation avec tests"


def test_without_deliver_software_key_goes_through_normal_generic_routing():
    codegen = _fake_codegen()
    core, runner, codegen, _harness = _build(codegen=codegen)

    core.pose_objective("book a flight to nowhere", {})
    runner.run_forever(max_ticks=5)

    codegen.deliver_software.assert_not_called()  # ordinary Coordinator path, unaffected


# ── D6: evolve_harness_tool wiring ───────────────────────────────────────────

def test_evolve_harness_tool_is_wired_to_the_same_harness_instance():
    harness = NexusHarnessAdapter()
    core, _runner, _codegen, harness = _build(harness=harness)

    assert core._evolve_harness_tool is not None
    assert core._evolve_harness_tool.__self__ is harness


# ── D2: delivery endpoints, end-to-end from HTTP ─────────────────────────────

def _extract_goal_id(response_text: str) -> str:
    match = re.search(r"'goal_id': '(goal-\d+)'", response_text)
    assert match, f"no goal_id found in {response_text!r}"
    return match.group(1)


def test_objective_status_and_deliver_endpoints_end_to_end():
    codegen = _fake_codegen(run_id="run-999")
    core, runner, codegen, _harness = _build(codegen=codegen)
    app = create_app(core=core, runner=runner)
    client = TestClient(app)

    paused = client.post(
        "/handle_turn",
        json={
            "user_input": "livre-moi le module de facturation avec un rapport de sécurité",
            "context": {"deliver_software": True},
            "mode": "smart",
            "session_id": "sess-deliver-1",
        },
    ).json()
    assert paused["paused"] is True

    resumed = client.post(
        "/resume_paused",
        json={
            "session_id": "sess-deliver-1",
            "approved": True,
            "human_input": {},
            # resume_paused() takes a FRESH context, not inherited from the
            # paused /handle_turn call (see nexus_brain/core/brain.py) — so
            # whoever wants deliver_software routing (here: Leon, via
            # nexus-bridge-client.ts) resends it at resume time too.
            "context": {"deliver_software": True},
        },
    ).json()
    goal_id = _extract_goal_id(resumed["response"])

    # Not ticked yet (background loop isn't running under a bare TestClient
    # without a `with` block — see server.py's lifespan docstring) -> active.
    status_before = client.get(f"/objective/{goal_id}/status").json()
    assert status_before["status"] == "active"

    deliver_before = client.post(f"/objective/{goal_id}/deliver")
    assert deliver_before.status_code == 404

    runner.run_forever(max_ticks=5)  # deterministic, same as background ticks would do

    status_after = client.get(f"/objective/{goal_id}/status").json()
    assert status_after["status"] == "complete"

    delivered = client.post(f"/objective/{goal_id}/deliver").json()
    assert delivered["status"] == "complete"
    assert "run-999" in delivered["report"]


def test_objective_status_unknown_goal_id():
    core, runner, _codegen, _harness = _build()
    client = TestClient(create_app(core=core, runner=runner))

    resp = client.get("/objective/no-such-goal/status").json()
    assert resp["status"] == "unknown"


def test_objective_endpoints_501_without_a_configured_runner():
    """Every pre-D1 test in this package builds `create_app(core=core)`
    with no runner — must degrade cleanly, not crash."""
    core, _runner, _codegen, _harness = _build()
    client = TestClient(create_app(core=core))  # no runner passed

    assert client.get("/objective/whatever/status").status_code == 501
    assert client.post("/objective/whatever/deliver").status_code == 501


def test_background_tick_loop_actually_progresses_an_objective():
    """Lightweight smoke test of the lifespan wiring itself (not just the
    manual runner.tick_all() calls used elsewhere in this file) — a fast
    tick_interval_s means the objective should complete on its own within
    a short, bounded wait, with nobody calling tick_all() by hand."""
    import time

    codegen = _fake_codegen()
    core, runner, codegen, _harness = _build(codegen=codegen)
    app = create_app(core=core, runner=runner, tick_interval_s=0.02)

    with TestClient(app) as client:
        result = core.pose_objective("Livrer un rapport", {"deliver_software": True})
        goal_id = result["goal_id"]

        deadline = time.time() + 2.0
        status = "active"
        while time.time() < deadline:
            status = client.get(f"/objective/{goal_id}/status").json()["status"]
            if status == "complete":
                break
            time.sleep(0.05)

        assert status == "complete"
        codegen.deliver_software.assert_called_once()
