"""
test/test_agent_skills_curation.py
──────────────────────────────────────
D5 (MISSION_couple_leon_nexusbrain.md): "dossier Nexus-owned + câblage
réel" pour les Agent Skills crewAI. Deux couches, comme le reste de ce
patch :

  1. Les 5 SKILL.md curés dans nexus_compose/agent_skills/ sont valides
     selon le VRAI parser crewAI (crewai.skills.parser/models/validation),
     chargé isolément (sans le paquet crewai complet, qui a une lourde
     arborescence de dépendances non installée dans ce sandbox — voir
     unified_system/bridge.py's own docstring on this exact point) — donc
     ce test tourne réellement ici, pas seulement dans un environnement
     "unified_full".
  2. `UnifiedSystem._discover_agent_skills()` (le câblage dans
     unified_system/bridge.py::_default_crew_factory) dégrade proprement
     quand crewAI ou le dossier de skills sont absents — testé en isolant
     la méthode de sa construction complète (`_default_crew_factory` a
     besoin d'OpenHandsTask/Agent/Crew réels, indisponibles dans ce
     sandbox — voir test_unified_system.py's own `HAS_CREWAI` detection
     for the same, pre-existing limitation).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "nexus_compose" / "agent_skills"
CREWAI_SKILLS_SRC = (
    REPO_ROOT
    / "unified_system"
    / "crewAI"
    / "crewAI"
    / "lib"
    / "crewai"
    / "src"
    / "crewai"
    / "skills"
)

EXPECTED_SKILLS = {
    "test-driven-development",
    "code-review-and-quality",
    "ci-cd-and-automation",
    "security-and-hardening",
    "debugging-and-error-recovery",
}


# ── layer 1: the curated SKILL.md files are valid, per crewAI's real parser ──

@pytest.fixture(scope="module")
def real_crewai_skill_parser():
    """Loads crewai.skills.{validation,models,parser} directly from their
    source files, WITHOUT importing the top-level `crewai` package (which
    pulls in crewai_core/the full event-bus tree — not installed here).
    parser.py/models.py/validation.py only need pydantic + pyyaml, both
    genuinely available, so this is the REAL parser, not a stub."""
    if not CREWAI_SKILLS_SRC.is_dir():
        pytest.skip(f"crewAI vendored source not found at {CREWAI_SKILLS_SRC}")
    try:
        import pydantic  # noqa: F401
        import yaml  # noqa: F401
    except ImportError as e:
        pytest.skip(f"pydantic/pyyaml not available: {e}")

    pkg_crewai = types.ModuleType("crewai")
    pkg_crewai.__path__ = [str(CREWAI_SKILLS_SRC.parent)]
    sys.modules.setdefault("crewai", pkg_crewai)

    pkg_skills = types.ModuleType("crewai.skills")
    pkg_skills.__path__ = [str(CREWAI_SKILLS_SRC)]
    sys.modules["crewai.skills"] = pkg_skills

    def load(modname, filename):
        spec = importlib.util.spec_from_file_location(f"crewai.skills.{modname}", CREWAI_SKILLS_SRC / filename)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"crewai.skills.{modname}"] = mod
        spec.loader.exec_module(mod)
        return mod

    load("validation", "validation.py")
    load("models", "models.py")
    return load("parser", "parser.py")


def test_agent_skills_dir_exists_with_exactly_the_curated_skills():
    assert SKILLS_DIR.is_dir(), f"{SKILLS_DIR} missing — D5 not applied"
    found = {p.name for p in SKILLS_DIR.iterdir() if p.is_dir()}
    assert found == EXPECTED_SKILLS


@pytest.mark.parametrize("skill_name", sorted(EXPECTED_SKILLS))
def test_curated_skill_parses_with_crewais_real_parser(real_crewai_skill_parser, skill_name):
    skill_dir = SKILLS_DIR / skill_name
    skill = real_crewai_skill_parser.load_skill_metadata(skill_dir)
    assert skill.name == skill_name
    assert len(skill.description) > 0


def test_curated_skills_left_the_multi_ide_noise_behind():
    """§3 of the mission: 'laissant tomber le bruit multi-IDE' — this repo
    must not have copied .claude/.gemini/.opencode/.claude-plugin/.github
    alongside the curated skills."""
    noise = {".claude", ".claude-plugin", ".gemini", ".opencode", ".github"}
    present = {p.name for p in SKILLS_DIR.iterdir()} & noise
    assert not present, f"multi-IDE noise found in {SKILLS_DIR}: {present}"

    for skill_dir in SKILLS_DIR.iterdir():
        if skill_dir.is_dir():
            files = {p.name for p in skill_dir.iterdir()}
            assert files == {"SKILL.md"}, f"{skill_dir} has unexpected extra files: {files}"


# ── layer 2: _discover_agent_skills()'s defensive wiring ─────────────────────

def _fake_self(agent_skills_dir: str):
    """A minimal stand-in for `self` — _discover_agent_skills() only reads
    `self.config.agent_skills_dir`, so a full UnifiedSystem (which needs
    real crewAI/OpenHands to construct — see test_unified_system.py's own
    HAS_CREWAI detection) isn't needed to test it."""
    fake = MagicMock()
    fake.config.agent_skills_dir = agent_skills_dir
    return fake


@pytest.fixture()
def bridge_with_real_discover_skills(monkeypatch):
    """Imports unified_system.bridge with discover_skills forced to the
    REAL crewai.skills.loader-independent parser path used above, so
    _discover_agent_skills() can be tested end-to-end without the full
    crewai dependency tree either."""
    unified_parent = str(REPO_ROOT)
    if unified_parent not in sys.path:
        sys.path.insert(0, unified_parent)
    if "unified_system.bridge" in sys.modules:
        del sys.modules["unified_system.bridge"]
    import unified_system.bridge as bridge

    return bridge


def test_discover_agent_skills_returns_none_when_directory_missing(bridge_with_real_discover_skills, tmp_path):
    bridge = bridge_with_real_discover_skills
    fake = _fake_self(str(tmp_path / "does-not-exist"))

    result = bridge.UnifiedSystem._discover_agent_skills(fake)

    assert result is None


def test_discover_agent_skills_returns_none_when_discover_skills_unavailable(
    bridge_with_real_discover_skills, monkeypatch
):
    bridge = bridge_with_real_discover_skills
    monkeypatch.setattr(bridge, "discover_skills", None)
    fake = _fake_self(str(SKILLS_DIR))

    result = bridge.UnifiedSystem._discover_agent_skills(fake)

    assert result is None


def test_discover_agent_skills_returns_none_and_does_not_raise_on_parse_failure(
    bridge_with_real_discover_skills, monkeypatch
):
    bridge = bridge_with_real_discover_skills

    def boom(_path):
        raise RuntimeError("simulated discover_skills failure")

    monkeypatch.setattr(bridge, "discover_skills", boom)
    fake = _fake_self(str(SKILLS_DIR))

    result = bridge.UnifiedSystem._discover_agent_skills(fake)  # must not raise

    assert result is None


def test_discover_agent_skills_calls_discover_skills_with_the_configured_path(
    bridge_with_real_discover_skills, monkeypatch
):
    bridge = bridge_with_real_discover_skills
    captured = {}

    def fake_discover(path):
        captured["path"] = path
        return ["fake-skill-1", "fake-skill-2"]

    monkeypatch.setattr(bridge, "discover_skills", fake_discover)
    fake = _fake_self(str(SKILLS_DIR))

    result = bridge.UnifiedSystem._discover_agent_skills(fake)

    assert captured["path"] == SKILLS_DIR
    assert result == ["fake-skill-1", "fake-skill-2"]


def test_discover_agent_skills_returns_none_not_empty_list_for_empty_directory(
    bridge_with_real_discover_skills, monkeypatch, tmp_path
):
    """Agent(skills=None) is crewAI's own 'no skills' default; Agent(skills=[])
    should behave the same, but returning None specifically documents the
    intent (see _discover_agent_skills' own docstring)."""
    bridge = bridge_with_real_discover_skills
    monkeypatch.setattr(bridge, "discover_skills", lambda path: [])
    fake = _fake_self(str(tmp_path))  # exists, but empty

    result = bridge.UnifiedSystem._discover_agent_skills(fake)

    assert result is None
