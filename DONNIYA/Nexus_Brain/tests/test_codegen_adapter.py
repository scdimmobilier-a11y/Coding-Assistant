"""
tests.test_codegen_adapter
=============================

D3 (`MISSION_couple_leon_nexusbrain.md`), §7 test requirement:
"un objectif taggé deliver_software déclenche un appel HTTP mocké vers
/api/pipeline/run (pas de dépendance à un vrai nexus_compose en cours
d'exécution)".

Two layers, matching how the adapter is actually used:
  1. `CodegenAdapter` in isolation — HTTP contract only (mocked
     `requests.post`, no real `nexus_compose` process).
  2. `NexusExecAdapter.execute_step` — proves a *registered*
     `deliver_software` step routes to `CodegenAdapter` instead of the
     normal `Coordinator` role-routing loop, and that unregistered steps
     are completely unaffected (Invariant #6 still holds for them).
"""

import _pathfix  # noqa: F401
import unittest
from unittest import mock

from nexus_functor.types import FeedbackEvent, Outcome

from nexus_brain.adapters.codegen_adapter import (
    CodegenAdapter,
    CodegenAdapterConfig,
    CodegenAdapterError,
)
from nexus_brain.adapters.exec_adapter import NexusExecAdapter


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text or (str(json_body) if json_body is not None else "")

    def json(self):
        if self._json_body is None:
            raise ValueError("no JSON body")
        return self._json_body


class TestCodegenAdapterHttpContract(unittest.TestCase):
    def _cfg(self) -> CodegenAdapterConfig:
        return CodegenAdapterConfig(base_url="http://nexus-compose.test", request_timeout_s=5.0)

    def test_deliver_software_posts_to_the_real_pipeline_endpoint(self):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return _FakeResponse(200, {"run_id": "run-123", "phases": ["p0"]})

        with mock.patch("nexus_brain.adapters.codegen_adapter.requests.post", fake_post):
            result = CodegenAdapter(self._cfg()).deliver_software(
                "Générer un rapport de sécurité", goal_id="goal-42"
            )

        self.assertEqual(captured["url"], "http://nexus-compose.test/api/pipeline/run")
        self.assertEqual(captured["timeout"], 5.0)
        self.assertEqual(captured["json"]["instruction"], "[objective:goal-42] Générer un rapport de sécurité")
        self.assertEqual(result, {"run_id": "run-123", "phases": ["p0"]})

    def test_deliver_software_without_goal_id_sends_instruction_untagged(self):
        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["json"] = json
            return _FakeResponse(200, {"run_id": "run-1"})

        with mock.patch("nexus_brain.adapters.codegen_adapter.requests.post", fake_post):
            CodegenAdapter(self._cfg()).deliver_software("Analyser le dépôt")

        self.assertEqual(captured["json"]["instruction"], "Analyser le dépôt")

    def test_raises_codegen_adapter_error_on_http_error_status(self):
        with mock.patch(
            "nexus_brain.adapters.codegen_adapter.requests.post",
            lambda *a, **k: _FakeResponse(422, text="instruction must not be empty"),
        ):
            with self.assertRaisesRegex(CodegenAdapterError, "422"):
                CodegenAdapter(self._cfg()).deliver_software("")

    def test_raises_codegen_adapter_error_when_api_unreachable(self):
        import requests

        def fake_post(*a, **k):
            raise requests.ConnectionError("connection refused")

        with mock.patch("nexus_brain.adapters.codegen_adapter.requests.post", fake_post):
            with self.assertRaisesRegex(CodegenAdapterError, "could not reach"):
                CodegenAdapter(self._cfg()).deliver_software("Générer un rapport")


class TestExecAdapterDeliverSoftwareRouting(unittest.TestCase):
    """Proves the wiring D3 asks for: a plan step tagged (via prior
    registration — see exec_adapter.py's module docstring for why) as
    `deliver_software` goes to CodegenAdapter, not Coordinator."""

    def test_registered_step_calls_codegen_adapter_not_the_coordinator(self):
        fake_codegen = mock.create_autospec(CodegenAdapter, instance=True)
        fake_codegen.deliver_software.return_value = {"run_id": "run-777"}

        adapter = NexusExecAdapter(codegen_adapter=fake_codegen)
        adapter.register_deliver_software_step("step-1", "Livrer le module de facturation", goal_id="goal-1")

        event = adapter.execute_step("plan-1", "step-1", {})

        fake_codegen.deliver_software.assert_called_once_with(
            "Livrer le module de facturation", goal_id="goal-1"
        )
        self.assertIsInstance(event, FeedbackEvent)
        self.assertEqual(event.outcome, Outcome.SUCCESS)
        self.assertIn("run-777", event.notes)

    def test_registered_step_failure_is_reported_as_feedback_failure_not_raised(self):
        fake_codegen = mock.create_autospec(CodegenAdapter, instance=True)
        fake_codegen.deliver_software.side_effect = CodegenAdapterError("pipeline unreachable")

        adapter = NexusExecAdapter(codegen_adapter=fake_codegen)
        adapter.register_deliver_software_step("step-1", "Livrer le module de facturation")

        event = adapter.execute_step("plan-1", "step-1", {})

        self.assertEqual(event.outcome, Outcome.FAILURE)
        self.assertIn("pipeline unreachable", event.notes)

    def test_registration_is_consumed_once_then_falls_back_to_normal_routing(self):
        """A step_id is only ever a deliver_software step once — re-using
        the same step_id (shouldn't normally happen, plan steps are
        unique, but must not silently misroute forever) goes back to the
        real Coordinator loop."""
        fake_codegen = mock.create_autospec(CodegenAdapter, instance=True)
        fake_codegen.deliver_software.return_value = {"run_id": "run-1"}

        adapter = NexusExecAdapter(codegen_adapter=fake_codegen)
        adapter.register_deliver_software_step("step-1", "Livrer X")
        adapter.execute_step("plan-1", "step-1", {})

        second = adapter.execute_step("plan-1", "step-1", {})
        fake_codegen.deliver_software.assert_called_once()  # not called again
        self.assertIn(second.outcome, (Outcome.SUCCESS, Outcome.PARTIAL, Outcome.FAILURE))

    def test_unregistered_steps_are_completely_unaffected(self):
        """No registration ever happened -> ordinary Coordinator routing,
        byte-for-byte the pre-D3 behaviour (regression guard)."""
        fake_codegen = mock.create_autospec(CodegenAdapter, instance=True)
        adapter = NexusExecAdapter(codegen_adapter=fake_codegen)

        event = adapter.execute_step("plan-1", "step-1", {"action": "demo"})

        fake_codegen.deliver_software.assert_not_called()
        self.assertIsInstance(event, FeedbackEvent)


if __name__ == "__main__":
    unittest.main()
