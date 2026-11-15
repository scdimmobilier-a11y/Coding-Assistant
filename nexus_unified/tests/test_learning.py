"""Tests lot 4 : apprentissage par succès/échecs, banque de compétences, distillation."""
from __future__ import annotations

import pytest

from nexus_compose.registry import build
from nexus_unified.orchestrator import MasterOrchestrator
from nexus_unified.llm import LLMGateway, TaskPlan, AgentTask
from nexus_unified.learning import LearningLoop, SkillBank
from nexus_unified.store import SQLiteStore


class _StubGateway(LLMGateway):
    def __init__(self, tasks):
        super().__init__()
        self._tasks = tasks

    def plan_tasks(self, goal, *, available_actions, context=None, max_tasks=12):
        valid = [t for t in self._tasks if t["action"] in set(available_actions)]
        self.last_context = context   # pour vérifier l'injection de compétences
        return TaskPlan(goal=goal, source="llm",
                        tasks=[AgentTask(id=f"t{i}", action=t["action"], goal="",
                                         inputs=t.get("inputs", {}))
                               for i, t in enumerate(valid)])

    def chat(self, messages, **kw):
        from nexus_unified.llm import ChatResult
        return ChatResult(ok=False, error="pas de LLM en test")  # force le repli


@pytest.fixture(scope="module")
def packed():
    return build(("unified",))


def test_skillbank_roundtrip(tmp_path):
    bank = SkillBank(SQLiteStore(str(tmp_path / "s.db")))
    bank.add_general("toujours vérifier les préconditions")
    bank.add_task_specific("training", "figer le dataset avant d'entraîner")
    bank.add_mistake("training", "lancer sans bail GPU")
    ctx = bank.as_context("training")
    assert "préconditions" in ctx and "dataset" in ctx and "bail GPU" in ctx


def test_learning_stores_success_and_failure(packed, tmp_path):
    st = SQLiteStore(str(tmp_path / "s.db"))
    gw = _StubGateway([{"action": "reward.from_tests", "inputs": {"tests_passed": 10, "tests_total": 10}}])
    mo = MasterOrchestrator(packed, gateway=gw)
    loop = LearningLoop(mo, store=st, gateway=gw)
    traj = loop.run_episode("améliorer le code", category="coding")
    assert traj.outcome == "success"
    assert st.count("traj_success", {"category": "coding"}) == 1


def test_learning_failure_triggers_distillation(packed, tmp_path):
    st = SQLiteStore(str(tmp_path / "s.db"))
    # eval.gate sans métriques → échec explicite → trajectoire d'échec
    gw = _StubGateway([{"action": "eval.gate", "inputs": {"metrics": {}, "thresholds": {}}}])
    mo = MasterOrchestrator(packed, gateway=gw)
    loop = LearningLoop(mo, store=st, gateway=gw, fail_threshold=0.5, min_episodes=2)
    for _ in range(3):
        traj = loop.run_episode("entraîner le modèle", category="training")
        assert traj.outcome == "failure"
    # distillation déclenchée → une erreur courante apprise (repli déterministe)
    mistakes = st.query("skills_mistakes", {"category": "training"})
    assert mistakes, "la distillation aurait dû produire une erreur courante"


def test_learning_injects_skills_into_next_request(packed, tmp_path):
    st = SQLiteStore(str(tmp_path / "s.db"))
    gw = _StubGateway([{"action": "reward.from_tests", "inputs": {"tests_passed": 1, "tests_total": 1}}])
    mo = MasterOrchestrator(packed, gateway=gw)
    loop = LearningLoop(mo, store=st, gateway=gw)
    loop.bank.add_task_specific("coding", "écrire les tests d'abord")
    loop.run_episode("coder une fonction", category="coding")
    # la compétence apprise a été injectée dans le contexte de la requête LLM
    assert gw.last_context and "tests d'abord" in gw.last_context


def test_learning_stats(packed, tmp_path):
    st = SQLiteStore(str(tmp_path / "s.db"))
    gw = _StubGateway([{"action": "reward.from_tests", "inputs": {"tests_passed": 1, "tests_total": 1}}])
    mo = MasterOrchestrator(packed, gateway=gw)
    loop = LearningLoop(mo, store=st, gateway=gw)
    loop.run_episode("coder", category="coding")
    s = loop.stats("coding")
    assert s["success"] == 1 and s["success_rate"] == 1.0
