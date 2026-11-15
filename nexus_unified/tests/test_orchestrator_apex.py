"""Tests de l'orchestrateur maître (point 5) et du cycle Apex (point 6)."""
from __future__ import annotations

import pytest

from nexus_compose.registry import build
from nexus_unified.orchestrator import MasterOrchestrator
from nexus_unified.llm import LLMGateway, TaskPlan, AgentTask
from nexus_unified.apex import (
    ApexCycle, ProtectedKernel, SharedSystemState, Observer, Learner,
    KnowledgeStatus, APEX_PHASE_IDS,
)


class _StubGateway(LLMGateway):
    """Passerelle qui renvoie un plan fixe sans appeler de LLM."""
    def __init__(self, tasks):
        super().__init__()
        self._tasks = tasks

    def plan_tasks(self, goal, *, available_actions, context=None, max_tasks=12):
        valid = [t for t in self._tasks if t["action"] in set(available_actions)]
        plan = TaskPlan(goal=goal, source="llm",
                        tasks=[AgentTask(id=t.get("id", f"t{i}"), action=t["action"],
                                         goal=t.get("goal", ""), inputs=t.get("inputs", {}))
                               for i, t in enumerate(valid)])
        return plan


@pytest.fixture(scope="module")
def packed():
    return build(("unified",))


def test_master_runs_plan(packed):
    gw = _StubGateway([
        {"action": "reward.from_tests", "inputs": {"tests_passed": 9, "tests_total": 10}},
        {"action": "eval.gate", "inputs": {"metrics": {"acc": 0.9}, "thresholds": {"acc": 0.8}}},
    ])
    mo = MasterOrchestrator(packed, gateway=gw)
    out = mo.run("améliorer le modèle")
    assert out.success
    assert [s.action for s in out.steps] == ["reward.from_tests", "eval.gate"]
    assert all(s.authorized for s in out.steps)


def test_master_blocks_risky_action(packed):
    gw = _StubGateway([{"action": "oh.sandbox_delete"}])
    mo = MasterOrchestrator(packed, gateway=gw)
    out = mo.run("nettoyer")
    assert not out.success
    assert out.steps[0].authorized is False   # refusé par défaut (GA7)


def test_master_allows_risky_with_policy(packed):
    gw = _StubGateway([{"action": "oh.sandbox_delete"}])
    mo = MasterOrchestrator(packed, gateway=gw)
    out = mo.run("nettoyer", ctx={"allow_risky": True})
    assert out.steps[0].authorized is True


def test_master_never_runs_unknown_action(packed):
    # le plan ne contient que des actions du registre (filtrées par available_actions)
    gw = _StubGateway([{"action": "evil.exec"}, {"action": "reward.from_tests",
                                                 "inputs": {"tests_passed": 1, "tests_total": 1}}])
    mo = MasterOrchestrator(packed, gateway=gw)
    out = mo.run("x")
    assert [s.action for s in out.steps] == ["reward.from_tests"]


def test_master_records_learning(packed):
    from nexus_unified.store import SQLiteStore
    st = SQLiteStore(":memory:")
    gw = _StubGateway([{"action": "reward.from_tests", "inputs": {"tests_passed": 5, "tests_total": 10}}])
    mo = MasterOrchestrator(packed, gateway=gw, learning_store=st)
    mo.run("apprendre")
    rows = st.query("orchestration")
    assert rows and rows[0]["action"] == "reward.from_tests"


# ── Apex ─────────────────────────────────────────────────────────────────────
def test_kernel_fingerprint_stable():
    k1, k2 = ProtectedKernel(), ProtectedKernel()
    assert k1.fingerprint == k2.fingerprint
    assert k1.verify(k2.fingerprint)


def test_kernel_tamper_detected():
    k = ProtectedKernel()
    fp = k.fingerprint
    tampered = ProtectedKernel(ontology=k.ontology + ("backdoor",))
    assert not tampered.verify(fp)


def test_eight_phases():
    assert len(APEX_PHASE_IDS) == 8
    assert APEX_PHASE_IDS[0] == "co_design" and APEX_PHASE_IDS[-1] == "deployment"


def test_shared_state_established_needs_second_proof():
    s = SharedSystemState()
    assert s.assert_established("x", 1, "toolA") is False        # dérivé
    assert s.get("x").status == KnowledgeStatus.DERIVED
    assert s.assert_established("x", 1, "toolA", "toolB") is True  # établi
    assert s.get("x").status == KnowledgeStatus.ESTABLISHED


def test_learner_detects_contradiction():
    s = SharedSystemState()
    s.assert_established("y", 1, "a", "b")
    lr = Learner(s)
    status = lr.integrate("y", 2, "c")   # contredit un fait établi
    assert status == KnowledgeStatus.UNRESOLVED
    assert s.contradictions()


def test_apex_cycle_blocks_on_tamper(packed):
    gw = _StubGateway([{"action": "reward.from_tests", "inputs": {"tests_passed": 1, "tests_total": 1}}])
    mo = MasterOrchestrator(packed, gateway=gw)
    cycle = ApexCycle(mo, kernel_fingerprint="mauvaise-empreinte")
    rep = cycle.run("x")
    assert rep.integrity_ok is False and not rep.actions_run


def test_apex_cycle_runs_and_integrates(packed):
    gw = _StubGateway([{"action": "reward.from_tests", "inputs": {"tests_passed": 8, "tests_total": 10}}])
    mo = MasterOrchestrator(packed, gateway=gw)
    cycle = ApexCycle(mo)
    rep = cycle.run("évaluer", conditions={"gpu_available": False})
    assert rep.integrity_ok
    assert "reward.from_tests" in rep.actions_run
