"""Tests du pack unified : chargement, non-régression du graphe de base, handlers, GPU."""
from __future__ import annotations

import pytest

from nexus_compose.registry import build
from nexus_compose.graph import EdgeType


@pytest.fixture(scope="module")
def base():
    return build()


@pytest.fixture(scope="module")
def packed():
    return build(("unified",))


def test_base_graph_unchanged(base):
    # Le pack ne doit JAMAIS modifier les comptes du graphe de base.
    assert base.node_count == 169
    assert base.edge_count == 218


def test_pack_adds_nodes_and_edges(packed, base):
    assert packed.node_count > base.node_count
    assert packed.node_count - base.node_count >= 220
    assert packed.edge_count > base.edge_count


def test_pack_node_has_capabilities_and_apex(packed):
    n = packed.node("gpu.lease")
    assert n.meta.capabilities  # non vide
    assert n.meta.apex_phase    # phase Apex renseignée
    assert n.meta.resources.get("gpu") == 1


def test_new_edge_types_present(packed):
    types = {e.type for e in packed.edges()}
    assert EdgeType.EXECUTE in types
    assert EdgeType.REWARD in types
    assert EdgeType.LEASE in types
    assert EdgeType.UPDATE in types


def test_branch_points_wired(packed):
    # codegen délègue à l'exécution ; audit nourrit la récompense
    succ = {e.target for e in packed.successors("codegen.unified_system")}
    assert "oh.send_message" in succ
    pred = {e.source for e in packed.predecessors("reward.from_audit")}
    assert {"semgrep.semgrep_scan", "bearer.bearer_scan"} <= pred


def test_strict_error_makes_failure(packed):
    # un handler qui renvoie {"error":...} = échec explicite (pas un faux succès)
    r = packed.node("oh.health")({})
    assert r.success is False
    r2 = packed.node("eval.gate")({"metrics": {}, "thresholds": {}})
    assert r2.success is False


def test_eval_gate_pass_and_fail(packed):
    ok = packed.node("eval.gate")({"metrics": {"acc": 0.9}, "thresholds": {"acc": 0.8}})
    assert ok.success and ok.data["pass"] is True
    ko = packed.node("eval.gate")({"metrics": {"acc": 0.5}, "thresholds": {"acc": 0.8}})
    assert ko.success is False  # strict: pass=False → error


def test_reward_from_tests(packed):
    r = packed.node("reward.from_tests")({"tests_passed": 8, "tests_total": 10})
    assert r.success and abs(r.data["reward"] - 0.8) < 1e-9


def test_reward_from_audit(packed):
    r = packed.node("reward.from_audit")({"audit_findings": [
        {"severity": "ERROR"}, {"severity": "WARNING"}]})
    assert r.success and r.data["reward"] < 0


def test_gpu_lease_release_cycle(packed):
    # Avec une flotte injectée via le gestionnaire du contexte
    from nexus_unified.pack.drivers import PackContext
    from nexus_unified.accelerators import AcceleratorLeaseManager, Accelerator
    PackContext.get()._lease = AcceleratorLeaseManager(
        [Accelerator("nvidia", 0, "A100", "GPU-x", 80000, "gpu")], default_ttl=100)
    r = packed.node("gpu.lease")({"holder": "t", "gpu_count": 1})
    assert r.success and r.data["lease_id"]
    lid = r.data["lease_id"]
    rel = packed.node("gpu.release")({"lease_id": lid})
    assert rel.success and rel.data["released"]
    PackContext.get()._lease = None  # reset


def test_run_loop_over_pack(packed):
    from nexus_compose.orchestrator import Orchestrator, LoopBudget
    orch = Orchestrator(packed)
    lr = orch.run_loop(["reward.from_tests"], max_iterations=2,
                       ctx={"tests_passed": 5, "tests_total": 10})
    assert len(lr.iterations) == 2
