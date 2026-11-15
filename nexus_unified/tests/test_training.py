"""Tests lot 3 : service d'entraînement, registre (promotion gardée), vLLM, pack."""
from __future__ import annotations

import pytest

from nexus_unified.training import TrainingService, ModelRegistry, VLLMManager, LocalRunner
from nexus_unified.store import SQLiteStore
from nexus_compose.registry import build


def test_training_simulated_run(tmp_path):
    st = SQLiteStore(str(tmp_path / "s.db"))
    svc = TrainingService(runner=LocalRunner(str(tmp_path / "runs")), store=st)
    job = svc.submit({"metrics": {"val_acc": 0.87}})   # run simulé (pas de commande)
    assert job.status == "running"
    done = svc.wait(job.job_id, timeout=5, interval=0.05)
    assert done.status == "finished"
    assert done.metrics["val_acc"] == 0.87


def test_training_real_command(tmp_path):
    st = SQLiteStore(str(tmp_path / "s.db"))
    svc = TrainingService(runner=LocalRunner(str(tmp_path / "runs")), store=st)
    # écrit metrics.json via une vraie commande
    job = svc.submit({"command": "echo '{\"loss\": 0.1}' > metrics.json"})
    done = svc.wait(job.job_id, timeout=10, interval=0.1)
    assert done.status == "finished"
    assert done.metrics.get("loss") == 0.1


def test_registry_promotion_requires_gate(tmp_path):
    st = SQLiteStore(str(tmp_path / "s.db"))
    reg = ModelRegistry(store=st)
    reg.register("ck1", path="/x", metrics={"acc": 0.9})
    # sans porte franchie → refus (GA5)
    r = reg.promote("ck1", gate_passed=False)
    assert not r["promoted"] and "GA5" in r["error"]
    # avec porte franchie → promu
    r2 = reg.promote("ck1", gate_passed=True, gate_report={"acc": 0.9})
    assert r2["promoted"]
    assert reg.active()["id"] == "ck1"


def test_registry_unknown_checkpoint(tmp_path):
    reg = ModelRegistry(store=SQLiteStore(str(tmp_path / "s.db")))
    r = reg.promote("ghost", gate_passed=True)
    assert not r["promoted"] and "inconnu" in r["error"]


def test_vllm_absent_binary_degrades():
    mgr = VLLMManager()
    r = mgr.serve("/models/x")
    # vllm absent dans ce bac à sable → erreur explicite, pas de faux succès
    assert r["served"] is False and "vllm" in r["error"]


def test_pack_training_flow():
    G = build(("unified",))
    # run simulé via le pack
    sub = G.node("ml.run_submit")({"metrics": {"val_acc": 0.91}})
    assert sub.success, sub.error
    jid = sub.data["job_id"]
    wait = G.node("ml.run_wait")({"job_id": jid, "timeout": 5, "interval": 0.05})
    assert wait.success and wait.data["metrics"]["val_acc"] == 0.91
    reg = G.node("ml.checkpoint_register")({"checkpoint_id": "c1", "path": "/m",
                                            "metrics": wait.data["metrics"]})
    assert reg.success
    gate = G.node("eval.gate")({"metrics": {"val_acc": 0.91}, "thresholds": {"val_acc": 0.8}})
    assert gate.success and gate.data["pass"]
    prom = G.node("ml.checkpoint_promote")({"checkpoint_id": "c1", "gate_passed": True})
    assert prom.success and prom.data["promoted"]


def test_pack_promote_refused_without_gate():
    G = build(("unified",))
    G.node("ml.checkpoint_register")({"checkpoint_id": "c2", "path": "/m"})
    prom = G.node("ml.checkpoint_promote")({"checkpoint_id": "c2", "gate_passed": False})
    assert prom.success is False   # strict: promotion refusée = échec explicite
