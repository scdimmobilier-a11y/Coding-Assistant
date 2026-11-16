"""
tests.test_core
==================

Smoke tests for Nexus Core: 3 routing modes, layered memory, self-model
principle promotion, pulse manager wiring, ReAct pause/resume without
restart, and the `evolve_harness` tool hookup.
"""

import _pathfix  # noqa: F401
import unittest

from nexus_brain.core.brain import NexusCore
from nexus_brain.core.memory import LayeredMemory, SelfModel
from nexus_brain.core.pulse import Matter, PulseManager
from nexus_brain.core.react import ReactLoop, ReactState, ReactStep
from nexus_brain.adapters.harness_adapter import NexusHarnessAdapter


class TestModeRouting(unittest.TestCase):

    def test_smart_mode_prefers_native_skill_when_available(self):
        core = NexusCore(skills={"weather": lambda ctx: "sunny"})
        result = core.handle_turn("what's the weather like", {}, mode="smart")
        self.assertEqual(result.mode_used, "controlled")
        self.assertEqual(result.response, "sunny")

    def test_smart_mode_falls_back_to_agent_without_native_skill(self):
        loop = ReactLoop(
            planner_fn=lambda goal, ctx: [ReactStep("s1", "search", {"q": goal})],
            executor_fn=lambda step, ctx: {"success": True, "output": "found it"},
        )
        core = NexusCore(skills={"weather": lambda ctx: "sunny"}, react_loop=loop)
        result = core.handle_turn("book me a flight to Lyon", {}, mode="smart")
        self.assertEqual(result.mode_used, "agent")
        self.assertEqual(result.response, "found it")

    def test_controlled_mode_never_falls_back_to_agent(self):
        loop = ReactLoop(
            planner_fn=lambda goal, ctx: [ReactStep("s1", "x", {})],
            executor_fn=lambda step, ctx: {"success": True, "output": "should not run"},
        )
        core = NexusCore(skills={"weather": lambda ctx: "sunny"}, react_loop=loop)
        result = core.handle_turn("book me a flight to Lyon", {}, mode="controlled")
        self.assertEqual(result.mode_used, "controlled")
        self.assertEqual(result.response, "No matching native skill.")


class TestReactPauseResumeAtCoreLevel(unittest.TestCase):

    def test_pause_then_resume_without_restart(self):
        executed = []

        def planner(goal, ctx):
            return [
                ReactStep("s1", "draft", {}),
                ReactStep("s2", "send", {}, requires_approval=True),
            ]

        def executor(step, ctx):
            executed.append(step.step_id)
            return {"success": True, "output": f"{step.tool} done"}

        core = NexusCore(react_loop=ReactLoop(planner, executor))
        r1 = core.handle_turn("send the report", {}, mode="agent")
        self.assertTrue(r1.paused)
        self.assertEqual(executed, ["s1"])  # s2 not executed yet — paused before it

        r2 = core.resume_paused("send the report", {"approved": True}, {})
        self.assertFalse(r2.paused)
        self.assertEqual(executed, ["s1", "s2"])  # resumed, did NOT re-run s1


class TestMemoryAndSelfModel(unittest.TestCase):

    def test_layers_are_independent_and_discussion_resets(self):
        mem = LayeredMemory()
        mem.remember("fact", layer="persistent")
        mem.remember("today", layer="daily")
        mem.remember("turn", layer="discussion")
        mem.new_discussion()
        self.assertEqual(mem.recall(layer="discussion"), [])
        self.assertEqual(len(mem.recall(layer="persistent")), 1)
        self.assertEqual(len(mem.recall(layer="daily")), 1)

    def test_repeated_habit_promoted_to_principle(self):
        sm = SelfModel(promotion_count=3)
        for _ in range(2):
            sm.record_turn("always double-check before deleting")
        self.assertEqual(sm.principles, ())
        sm.record_turn("always double-check before deleting")
        self.assertIn("always double-check before deleting", sm.principles)


class TestPulseIntegration(unittest.TestCase):

    def test_pulse_tick_runs_at_most_one_matter_and_updates_memory(self):
        calls = []
        pulse = PulseManager(
            lambda: [Matter("m1", "summarize the day", lambda: calls.append(1) or "ok")],
            tick_interval_s=0,
        )
        core = NexusCore(pulse=pulse)
        core.pulse_tick()
        self.assertEqual(len(calls), 1)
        daily = core.memory.recall(layer="daily")
        self.assertEqual(len(daily), 1)
        self.assertIn("summarize the day", daily[0].content)

    def test_rejected_matter_never_recurs(self):
        pulse = PulseManager(
            lambda: [Matter("m1", "nag about X", lambda: "done")],
            tick_interval_s=0,
        )
        core = NexusCore(pulse=pulse)
        core.pulse_tick()  # executes m1 once
        # simulate the user rejecting it after the fact
        core.reject_last_matter(Matter("m1", "nag about X", lambda: None))
        core.pulse_tick()
        core.pulse_tick()
        self.assertIn("nag about X", pulse.rejected_keys)


class TestEvolveHarnessWiring(unittest.TestCase):

    def test_evolve_harness_invoked_after_agent_turns(self):
        harness = NexusHarnessAdapter()
        harness.evolver.optimization_window_length = 1

        def planner(goal, ctx):
            return [ReactStep("s1", "run_tests", {})]

        def executor(step, ctx):
            return {"success": True, "output": "ok"}

        core = NexusCore(react_loop=ReactLoop(planner, executor), evolve_harness_tool=harness.evolve_harness)
        core.handle_turn("run the tests", {}, mode="agent")  # turn_count 0 -> deliberately skipped (see evolve_harness)
        self.assertEqual(harness.evolver.generation, 0)
        core.handle_turn("run the tests again", {}, mode="agent")  # turn_count 1 -> window boundary
        self.assertEqual(harness.evolver.generation, 1)


class TestDiagnosticsReportWiring(unittest.TestCase):
    """D5.2 (Mission 2, Meta Framework/Nexus Studio) — leon_spoken_report()
    branché en phrase de fin de tour optionnelle, opt-in via
    context["diagnostics_report"]."""

    def test_not_appended_when_not_requested(self):
        calls = []
        core = NexusCore(
            skills={"ping": lambda ctx: "pong"},
            diagnostics_report_fn=lambda: calls.append(1) or "3 tools available.",
        )
        result = core.handle_turn("ping", {}, mode="controlled")  # pas de diagnostics_report dans le context
        self.assertEqual(result.response, "pong")
        self.assertEqual(calls, [])  # le hook n'est même pas appelé

    def test_appended_when_requested_and_configured(self):
        core = NexusCore(
            skills={"ping": lambda ctx: "pong"},
            diagnostics_report_fn=lambda: "3 tools available.",
        )
        result = core.handle_turn("ping", {"diagnostics_report": True}, mode="controlled")
        self.assertEqual(result.response, "pong 3 tools available.")

    def test_not_appended_when_report_fn_returns_none(self):
        """nexus_compose injoignable (cf. fetch_compose_spoken_report côté
        pont) -> None -> pas de suffixe, pas de crash."""
        core = NexusCore(
            skills={"ping": lambda ctx: "pong"},
            diagnostics_report_fn=lambda: None,
        )
        result = core.handle_turn("ping", {"diagnostics_report": True}, mode="controlled")
        self.assertEqual(result.response, "pong")

    def test_noop_when_requested_but_no_fn_configured(self):
        core = NexusCore(skills={"ping": lambda ctx: "pong"})  # diagnostics_report_fn=None (défaut)
        result = core.handle_turn("ping", {"diagnostics_report": True}, mode="controlled")
        self.assertEqual(result.response, "pong")

    def test_also_appended_on_resume_paused(self):
        def planner(goal, ctx):
            return [ReactStep("s1", "send", {}, requires_approval=True)]

        def executor(step, ctx):
            return {"success": True, "output": "sent"}

        core = NexusCore(
            react_loop=ReactLoop(planner, executor),
            diagnostics_report_fn=lambda: "3 tools available.",
        )
        core.handle_turn("send the report", {}, mode="agent")  # paused before s1
        result = core.resume_paused("send the report", {"approved": True}, {"diagnostics_report": True})
        self.assertEqual(result.response, "sent 3 tools available.")


if __name__ == "__main__":
    unittest.main()
