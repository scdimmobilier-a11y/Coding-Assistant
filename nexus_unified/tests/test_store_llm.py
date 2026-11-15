"""Tests des magasins (point 7) et de la passerelle LLM / planification (points 3-5)."""
from __future__ import annotations

import os

import pytest

from nexus_unified.store import open_store, JSONLStore, SQLiteStore, StoreUnavailable
from nexus_unified.llm import LLMGateway, TaskPlan
from nexus_unified.llm.gateway import _extract_json


# ── magasins ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("factory", ["jsonl", "sqlite"])
def test_store_roundtrip(tmp_path, factory):
    if factory == "jsonl":
        st = JSONLStore(str(tmp_path / "j"))
    else:
        st = SQLiteStore(str(tmp_path / "s.db"))
    st.put("traj", "t1", {"reward": 1.0, "task": "x"})
    assert st.get("traj", "t1")["reward"] == 1.0
    st.put("traj", "t1", {"reward": 0.5, "task": "x"})       # dernière écriture gagne
    assert st.get("traj", "t1")["reward"] == 0.5
    i = st.append("traj", {"reward": 0.0, "task": "y"})
    assert st.get("traj", i)["task"] == "y"
    assert len(st.query("traj")) == 2
    assert st.query("traj", {"task": "y"})[0]["reward"] == 0.0
    st.close()


def test_store_factory_defaults_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("NEXUS_STORE_URL", raising=False)
    st = open_store(f"sqlite:///{tmp_path}/d.db")
    assert isinstance(st, SQLiteStore)
    st.put("c", "1", {"a": 1})
    assert st.get("c", "1") == {"a": 1, "id": "1"}


def test_store_jsonl_url(tmp_path):
    st = open_store(f"jsonl://{tmp_path}/jj")
    assert isinstance(st, JSONLStore)


def test_store_unknown_scheme():
    with pytest.raises(StoreUnavailable):
        open_store("mongodb://x")


def test_postgres_without_driver():
    # psycopg absent dans ce bac à sable → erreur claire, pas un magasin muet
    try:
        import psycopg  # noqa
        pytest.skip("psycopg présent")
    except Exception:
        pass
    with pytest.raises(StoreUnavailable):
        open_store("postgresql://u:p@localhost/db")


# ── planification LLM ────────────────────────────────────────────────────────
def test_extract_json_fenced():
    assert _extract_json('```json\n{"tasks":[]}\n```') == {"tasks": []}
    assert _extract_json('bla {"a":1} bla')["a"] == 1


def test_plan_parse_filters_unknown_actions():
    text = '{"tasks":[{"id":"t1","action":"oh.send_message","goal":"a"},' \
           '{"id":"t2","action":"evil.exec","goal":"b"}]}'
    plan = TaskPlan.parse(text, {"oh.send_message", "crew.kickoff"}, 12)
    assert [t.action for t in plan.tasks] == ["oh.send_message"]   # evil.exec rejeté


def test_plan_fallback_without_llm(monkeypatch):
    # pas de clé/endpoint → chat échoue → repli déterministe
    gw = LLMGateway({"api_key": "", "base_url": None, "provider": "none"})
    plan = gw.plan_tasks("lancer oh.send_message sur le dépôt",
                         available_actions=["oh.send_message", "crew.kickoff"])
    assert plan.source == "fallback"
    assert plan.tasks and plan.tasks[0].action == "oh.send_message"


def test_gateway_describe_is_external():
    gw = LLMGateway({"provider": "openai", "model": "gpt-4o-mini", "api_key": "k"})
    d = gw.describe()
    assert d["external"] is True and d["provider"] == "openai" and d["has_key"] is True
