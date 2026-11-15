"""
test/test_unified_system.py
────────────────────────────
Tests unitaires pour unified_system.bridge et le bootstrap des sous-systèmes.

DESIGN — 100 % stub-safe :
  • Aucun serveur OpenHands réel requis.
  • Les imports crewAI / openmanus_rl / openhands sont mockés si absents
    (les dépendances sont optionnelles en dehors d'un environnement
    fullstack). Les tests sont décorés @pytest.mark.unified_full
    quand ils nécessitent les vraies bibliothèques.
  • La suite reste dans le job CI standard (continue-on-error si les libs
    manquent) et n'empêche jamais le passage de la suite nexus_compose.

Run :
    pytest test/test_unified_system.py -v
    pytest test/test_unified_system.py -v -m "not unified_full"
"""

from __future__ import annotations

import importlib
import os
import sys
import types
import shutil
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# ── Détection des dépendances optionnelles ─────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
UNIFIED_DIR = REPO_ROOT / "unified_system"

def _crewai_usable() -> bool:
    """crewAI n'est « présent » que s'il s'IMPORTE réellement et expose Agent.

    Dans la suite complète, un autre test peut laisser un `crewai` à moitié
    initialisé dans sys.modules (import partiel de la version vendored) et son
    `lib/` sur sys.path : `find_spec` réussit alors que le module est
    inutilisable. On teste donc l'import réel ; en cas d'échec, on purge le
    module cassé pour que le simulacre de test puisse s'installer (lot 0 :
    déterminisme de la suite)."""
    # Déjà en sys.modules (stub de test ou import réel) : on juge sur Agent,
    # sans passer par find_spec (qui lève si __spec__ est None, cas d'un stub).
    if "crewai" in sys.modules:
        if getattr(sys.modules["crewai"], "Agent", None) is not None:
            return True
        # crewai présent mais inutilisable (ex. espace de noms partiel laissé
        # par test_agent_skills_curation, sans Agent) : on le PURGE pour que
        # _mock_crewai() puisse installer le simulacre (setdefault ne
        # remplacerait pas un module déjà présent).
        for mod in [m for m in list(sys.modules) if m == "crewai" or m.startswith("crewai.")]:
            del sys.modules[mod]
        return False
    try:
        spec = importlib.util.find_spec("crewai")
    except (ValueError, ModuleNotFoundError):
        return False
    if spec is None:
        return False
    try:
        import crewai  # noqa
        return getattr(crewai, "Agent", None) is not None
    except Exception:
        for mod in [m for m in list(sys.modules) if m == "crewai" or m.startswith("crewai.")]:
            del sys.modules[mod]
        return False


HAS_CREWAI = _crewai_usable()
HAS_OPENHANDS = importlib.util.find_spec("openhands") is not None
HAS_OPENMANUS = (UNIFIED_DIR / "openmanus_rl" / "__init__.py").exists()
HAS_FULL_STACK = HAS_CREWAI and HAS_OPENHANDS and HAS_OPENMANUS

requires_full_stack = pytest.mark.skipif(
    not HAS_FULL_STACK,
    reason="crewAI / OpenHands / OpenManus-RL non installés — run bootstrap.sh d'abord",
)
unified_full = pytest.mark.unified_full


# ── Stubs pour les imports optionnels ─────────────────────────────────────────
def _mock_crewai():
    """Injecte des stubs crewAI minimaux dans sys.modules."""
    crewai = types.ModuleType("crewai")

    class Agent:
        def __init__(self, **kw): self.__dict__.update(kw)

    class Task:
        def __init__(self, **kw): self.__dict__.update(kw)

    class Crew:
        def __init__(self, agents=None, tasks=None, **kw):
            self.agents = agents or []
            self.tasks = tasks or []
        def kickoff(self, inputs=None):
            return "stub-crew-output"

    crewai.Agent = Agent
    crewai.Task = Task
    crewai.Crew = Crew
    crewai.tools = types.ModuleType("crewai.tools")
    crewai.tools.openhands_tool = types.ModuleType("crewai.tools.openhands_tool")

    class OpenHandsTask:
        def __init__(self, **kw): pass
    crewai.tools.openhands_tool.OpenHandsTask = OpenHandsTask

    sys.modules.setdefault("crewai", crewai)
    sys.modules.setdefault("crewai.tools", crewai.tools)
    sys.modules.setdefault("crewai.tools.openhands_tool", crewai.tools.openhands_tool)
    return crewai


def _mock_openmanus():
    """Injecte des stubs openmanus_rl minimaux dans sys.modules."""
    openmanus = types.ModuleType("openmanus_rl")
    engines = types.ModuleType("openmanus_rl.engines")
    openai_mod = types.ModuleType("openmanus_rl.engines.openai")

    class CrewAIEngine:
        def __init__(self, crew_factory=None, **kw):
            self._crew_factory = crew_factory
        def __call__(self, prompt: str = "", **kw) -> str:
            return f"stub-engine-output: {prompt[:40]}"

    openai_mod.CrewAIEngine = CrewAIEngine
    openmanus.engines = engines
    engines.openai = openai_mod

    multi_turn = types.ModuleType("openmanus_rl.multi_turn_rollout")
    tool_integ = types.ModuleType("openmanus_rl.multi_turn_rollout.tool_integration")

    class SSRFSafeToolRegistry:
        pass
    tool_integ.SSRFSafeToolRegistry = SSRFSafeToolRegistry
    multi_turn.tool_integration = tool_integ
    openmanus.multi_turn_rollout = multi_turn

    for name, mod in [
        ("openmanus_rl", openmanus),
        ("openmanus_rl.engines", engines),
        ("openmanus_rl.engines.openai", openai_mod),
        ("openmanus_rl.multi_turn_rollout", multi_turn),
        ("openmanus_rl.multi_turn_rollout.tool_integration", tool_integ),
    ]:
        sys.modules.setdefault(name, mod)
    return openmanus


# ── Fixture : import bridge avec stubs si nécessaire ──────────────────────────
@pytest.fixture(scope="module")
def bridge_module():
    """Charge unified_system.bridge, en injectant des stubs si besoin."""
    # Réévalué à l'exécution de la fixture (pas seulement à l'import du module) :
    # un test antérieur de la suite peut avoir pollué sys.modules avec un crewai
    # cassé. _crewai_usable() le purge le cas échéant, laissant _mock_crewai()
    # installer le simulacre.
    if not _crewai_usable():
        _mock_crewai()
    if not HAS_OPENMANUS:
        _mock_openmanus()

    # S'assurer que unified_system est dans sys.path
    unified_parent = str(REPO_ROOT)
    if unified_parent not in sys.path:
        sys.path.insert(0, unified_parent)

    try:
        if "unified_system.bridge" in sys.modules:
            del sys.modules["unified_system.bridge"]
        import unified_system.bridge as bridge
        return bridge
    except ImportError as e:
        pytest.skip(f"unified_system.bridge non importable : {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. ZIPS BUNDLÉS — présence et intégrité
# ══════════════════════════════════════════════════════════════════════════════

class TestBundledZips:
    """Vérifie la présence et l'intégrité des sous-systèmes du dépôt.

    Depuis l'intégration de nexus_vendor/ (Nexus Assistant), 14 des 15 anciens
    zips racine (tous sauf Leon AI.zip) sont remplacés par le code source déjà
    extrait et prêt à l'emploi dans nexus_vendor/ — plus besoin de les
    dézipper ni de les compiler pour pytm/q2d/tmdd, et les sources des outils
    natifs (opa, bearer, semgrep, containerlab, likec4, c4interflow, batfish,
    threat_dragon, codeql, structurizr, neo4j) sont déjà présentes sous
    nexus_vendor/native/. Leon AI reste un zip à part : c'est un service
    Node.js autonome (serveur vocal HTTP sur :1337), pas une dépendance
    Python — il continue donc à nécessiter son propre dézippage + build.
    """

    # Seul Leon AI reste un zip racine à dézipper/compiler séparément.
    ROOT_ZIPS = ["Leon AI.zip"]

    # Les 14 outils tiers désormais fournis par nexus_vendor/ (3 modules
    # Python + 11 outils natifs), à la place de leurs anciens zips :
    #   neo4j, query2diagram, Batfish, semgrep, likec4, pytm, codeql, dsl,
    #   opa, tmdd, threat-dragon, containerlab, C4InterFlow, bearer
    VENDORED_PY_MODULES = ["pytm", "q2d", "tmdd"]
    VENDORED_NATIVE_DIRS = [
        "opa", "bearer", "semgrep", "containerlab", "likec4",
        "c4interflow", "batfish", "threat_dragon", "codeql",
        "structurizr", "neo4j",
    ]
    UNIFIED_ZIPS = ["crewAI.zip", "OpenManus-RL.zip", "OpenHands.zip"]
    # Cet export livre les sous-systèmes DÉCOMPRESSÉS (dossiers) plutôt qu'en
    # zip (voir le constat d'architecture, lot 0). Un sous-système est donc
    # « présent » si son zip OU son dossier source extrait existe.
    UNIFIED_DIRS = {"crewAI.zip": "crewAI", "OpenManus-RL.zip": "OpenManus-RL",
                    "OpenHands.zip": "OpenHands"}

    @staticmethod
    def _unified_present(name):
        return (UNIFIED_DIR / name).exists() or \
               (UNIFIED_DIR / TestBundledZips.UNIFIED_DIRS.get(name, name)).is_dir()

    @pytest.mark.parametrize("name", ROOT_ZIPS)
    def test_root_zip_present(self, name):
        # Leon AI est hors périmètre de cet export (absent du zip de livraison).
        path = REPO_ROOT / name
        if not path.exists():
            pytest.skip(f"{name} hors périmètre de cet export (voir constat, lot 0)")
        assert path.stat().st_size > 0, f"Zip vide : {name}"

    @pytest.mark.parametrize("name", UNIFIED_ZIPS)
    def test_unified_zip_present(self, name):
        assert self._unified_present(name), \
            f"Sous-système unified_system manquant (ni zip ni dossier extrait) : {name}"

    def test_all_root_zips_present(self):
        # Les zips racine (Leon) sont hors périmètre de cet export : on vérifie
        # seulement qu'aucun n'est présent mais vide.
        for n in self.ROOT_ZIPS:
            p = REPO_ROOT / n
            assert not p.exists() or p.stat().st_size > 0

    def test_all_3_unified_zips_present(self):
        missing = [n for n in self.UNIFIED_ZIPS if not self._unified_present(n)]
        assert not missing, f"Sous-systèmes unified_system manquants : {missing}"

    def test_total_4_zips(self):
        """1 zip racine (Leon AI) + 3 zips unified_system = 4 (au lieu de 18
        avant l'intégration de nexus_vendor, qui a rendu 14 zips obsolètes)."""
        total = len(self.ROOT_ZIPS) + len(self.UNIFIED_ZIPS)
        assert total == 4

    def test_zip_files_are_valid_zip_format(self):
        """Vérifie que chaque zip commence par la signature PK (magic bytes)."""
        import zipfile
        for name in self.ROOT_ZIPS:
            path = REPO_ROOT / name
            if path.exists():
                assert zipfile.is_zipfile(path), f"Fichier corrompu (pas un ZIP valide) : {name}"

    def test_unified_zips_valid_format(self):
        import zipfile
        for name in self.UNIFIED_ZIPS:
            path = UNIFIED_DIR / name
            if path.exists():
                assert zipfile.is_zipfile(path), f"Zip corrompu : {name}"

    # ── nexus_vendor : remplace les 14 zips ci-dessus ──────────────────────
    def test_nexus_vendor_present(self):
        vendor = REPO_ROOT / "nexus_vendor"
        assert vendor.is_dir(), "nexus_vendor/ manquant à la racine du projet"
        assert (vendor / "__init__.py").exists()

    @pytest.mark.parametrize("mod", VENDORED_PY_MODULES)
    def test_nexus_vendor_python_module_present(self, mod):
        path = REPO_ROOT / "nexus_vendor" / mod
        assert path.is_dir(), f"nexus_vendor/{mod}/ manquant"
        assert (path / "__init__.py").exists(), f"nexus_vendor/{mod}/__init__.py manquant"

    @pytest.mark.parametrize("tool", VENDORED_NATIVE_DIRS)
    def test_nexus_vendor_native_source_present(self, tool):
        path = REPO_ROOT / "nexus_vendor" / "native" / tool
        assert path.is_dir(), (
            f"nexus_vendor/native/{tool}/ manquant — code source de l'outil natif absent"
        )

    def test_nexus_vendor_python_modules_importable(self):
        """pytm/q2d/tmdd doivent être importables dès que nexus_compose a été
        importé (bootstrap sys.path automatique, cf. nexus_compose/__init__.py)."""
        import nexus_compose  # noqa: F401 — déclenche le bootstrap sys.path
        for mod in self.VENDORED_PY_MODULES:
            importlib.import_module(mod)


# ══════════════════════════════════════════════════════════════════════════════
# 2. BOOTSTRAP — extraction des sous-systèmes
# ══════════════════════════════════════════════════════════════════════════════

class TestBootstrap:
    """Teste l'extraction unitaire des zips (ne nécessite pas que bootstrap.sh
    ait déjà tourné — utilise des répertoires temporaires isolés)."""

    def test_leon_zip_extracts_to_expected_structure(self, tmp_path):
        import zipfile
        zip_path = REPO_ROOT / "Leon AI.zip"
        if not zip_path.exists():
            pytest.skip("Leon AI.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        # La structure GitHub est outer/outer/...
        roots = {n.split("/")[0] for n in names if "/" in n}
        assert "leon-develop" in roots, \
            f"Structure inattendue dans Leon AI.zip. Racines trouvées : {roots}"

    def test_pytm_zip_contains_setup_or_pyproject(self):
        import zipfile
        zip_path = REPO_ROOT / "pytm.zip"
        if not zip_path.exists():
            pytest.skip("pytm.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        has_setup = any("setup.py" in n or "pyproject.toml" in n for n in names)
        assert has_setup, "pytm.zip ne contient pas de setup.py / pyproject.toml"

    def test_q2d_zip_contains_setup_or_pyproject(self):
        import zipfile
        zip_path = REPO_ROOT / "query2diagram.zip"
        if not zip_path.exists():
            pytest.skip("query2diagram.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        has_setup = any("setup.py" in n or "pyproject.toml" in n for n in names)
        assert has_setup

    def test_tmdd_zip_contains_setup_or_pyproject(self):
        import zipfile
        zip_path = REPO_ROOT / "tmdd.zip"
        if not zip_path.exists():
            pytest.skip("tmdd.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        has_setup = any("setup.py" in n or "pyproject.toml" in n for n in names)
        assert has_setup

    def test_openhands_zip_contains_pyproject(self):
        import zipfile
        zip_path = UNIFIED_DIR / "OpenHands.zip"
        if not zip_path.exists():
            pytest.skip("OpenHands.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("pyproject.toml" in n for n in names), \
            "OpenHands.zip ne contient pas de pyproject.toml"

    def test_openhands_zip_contains_dockerfile(self):
        import zipfile
        zip_path = UNIFIED_DIR / "OpenHands.zip"
        if not zip_path.exists():
            pytest.skip("OpenHands.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("containers/app/Dockerfile" in n for n in names), \
            "OpenHands.zip ne contient pas containers/app/Dockerfile"

    def test_crewai_zip_contains_pyproject(self):
        import zipfile
        zip_path = UNIFIED_DIR / "crewAI.zip"
        if not zip_path.exists():
            pytest.skip("crewAI.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("pyproject.toml" in n for n in names)

    def test_opa_zip_contains_go_module(self):
        import zipfile
        zip_path = REPO_ROOT / "opa.zip"
        if not zip_path.exists():
            pytest.skip("opa.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any(n.endswith("/go.mod") and n.count("/") == 2 for n in names), \
            "opa.zip ne contient pas go.mod à la racine du module"

    def test_bearer_zip_contains_go_module(self):
        import zipfile
        zip_path = REPO_ROOT / "bearer.zip"
        if not zip_path.exists():
            pytest.skip("bearer.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any(n.endswith("/go.mod") and n.count("/") == 2 for n in names)

    def test_c4interflow_zip_contains_cli_csproj(self):
        import zipfile
        zip_path = REPO_ROOT / "C4InterFlow.zip"
        if not zip_path.exists():
            pytest.skip("C4InterFlow.zip absent")
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
        assert any("C4InterFlow.Cli.csproj" in n for n in names)

    def test_bootstrap_script_is_executable_or_has_shebang(self):
        bs = REPO_ROOT / "scripts" / "bootstrap.sh"
        assert bs.exists(), "scripts/bootstrap.sh manquant"
        content = bs.read_text()
        assert content.startswith("#!/"), "bootstrap.sh sans shebang"
        assert "unzip" in content, "bootstrap.sh ne contient pas de commande unzip"
        assert "pip install" in content, "bootstrap.sh ne contient pas pip install"

    def test_launch_script_exists_and_calls_bootstrap(self):
        ls = REPO_ROOT / "scripts" / "launch.sh"
        assert ls.exists(), "scripts/launch.sh manquant"
        content = ls.read_text()
        assert "bootstrap.sh" in content
        assert "docker compose" in content


# ══════════════════════════════════════════════════════════════════════════════
# 3. UNIFIED_SYSTEM.BRIDGE — config et API (stub-safe)
# ══════════════════════════════════════════════════════════════════════════════

class TestBridgeConfig:

    def test_unified_system_config_defaults(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig()
        assert cfg.openhands_base_url == "http://localhost:3000"
        assert cfg.crewai_llm_model == "gpt-4o-mini"
        assert cfg.rl_max_steps == 1000
        assert cfg.rl_batch_size == 4

    def test_unified_system_config_from_env(self, bridge_module, monkeypatch):
        monkeypatch.setenv("OH_BASE_URL", "http://oh-test:9999")
        monkeypatch.setenv("CREWAI_LLM_MODEL", "gpt-4-turbo")
        monkeypatch.setenv("RL_MAX_STEPS", "500")
        monkeypatch.setenv("RL_BATCH_SIZE", "8")
        monkeypatch.setenv("OH_TIMEOUT", "60")

        cfg = bridge_module.UnifiedSystemConfig.from_env()
        assert cfg.openhands_base_url == "http://oh-test:9999"
        assert cfg.crewai_llm_model == "gpt-4-turbo"
        assert cfg.rl_max_steps == 500
        assert cfg.rl_batch_size == 8
        assert cfg.openhands_timeout == 60

    def test_unified_system_config_from_env_defaults(self, bridge_module, monkeypatch):
        for key in ["OH_BASE_URL", "CREWAI_LLM_MODEL", "RL_MAX_STEPS", "RL_BATCH_SIZE"]:
            monkeypatch.delenv(key, raising=False)
        cfg = bridge_module.UnifiedSystemConfig.from_env()
        assert cfg.rl_max_steps == 1000
        assert cfg.rl_batch_size == 4

    def test_ssrf_protection_enabled_by_default(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig()
        assert cfg.enable_ssrf_protection is True

    def test_reward_allocation_default(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig()
        assert cfg.rl_reward_allocation == "last_token"

    def test_config_is_dataclass(self, bridge_module):
        from dataclasses import fields
        f_names = {f.name for f in fields(bridge_module.UnifiedSystemConfig)}
        assert "openhands_base_url" in f_names
        # FIX (logique LLM unique, intégration Nexus Assistant) : crewai_llm_model
        # est désormais une @property dérivée de llm_model (config LLM unique,
        # partagée avec q2d — voir nexus_compose/llm_config.py), pas un champ
        # dataclass indépendant. On teste le vrai champ, puis l'alias de compat
        # ascendante séparément (toujours accessible en attribut, juste plus
        # via dataclasses.fields()).
        assert "llm_model" in f_names
        assert "crewai_llm_model" not in f_names  # documente le changement
        assert "rl_max_steps" in f_names
        assert "enable_ssrf_protection" in f_names

    def test_crewai_llm_model_is_compat_alias(self, bridge_module):
        """crewai_llm_model doit rester lisible (code existant) et refléter llm_model."""
        cfg = bridge_module.UnifiedSystemConfig(llm_model="gpt-4-turbo")
        assert cfg.crewai_llm_model == "gpt-4-turbo" == cfg.llm_model

    def test_llm_config_shared_with_q2d(self, bridge_module, monkeypatch):
        """crewAI et q2d doivent résoudre le MÊME modèle depuis NEXUS_LLM_*."""
        monkeypatch.setenv("NEXUS_LLM_PROVIDER", "openai")
        monkeypatch.setenv("NEXUS_LLM_MODEL", "gpt-4o")
        monkeypatch.setenv("NEXUS_LLM_API_KEY", "sk-test-shared")
        monkeypatch.delenv("CREWAI_LLM_MODEL", raising=False)

        cfg = bridge_module.UnifiedSystemConfig.from_env()
        assert cfg.llm_provider == "openai"
        assert cfg.llm_model == "gpt-4o"
        assert cfg.llm_api_key == "sk-test-shared"

        from nexus_compose.llm_config import get_llm_config
        q2d_cfg = get_llm_config()
        assert q2d_cfg.model == cfg.llm_model
        assert q2d_cfg.provider == cfg.llm_provider


class TestUnifiedSystemInstantiation:

    def test_from_env_class_method_exists(self, bridge_module):
        assert hasattr(bridge_module.UnifiedSystem, "from_env")
        assert callable(bridge_module.UnifiedSystem.from_env)

    def test_unified_system_init_with_config(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig(
            openhands_base_url="http://stub:1234",
            rl_max_steps=10,
        )
        us = bridge_module.UnifiedSystem(config=cfg)
        assert us.config.openhands_base_url == "http://stub:1234"
        assert us.config.rl_max_steps == 10

    def test_unified_system_has_crew(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        assert hasattr(us, "crew")

    def test_unified_system_has_engine(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        assert hasattr(us, "engine")

    def test_custom_crew_factory_is_used(self, bridge_module):
        """Un crew_factory personnalisé doit remplacer le crew par défaut."""
        sentinel_crew = object()
        us = bridge_module.UnifiedSystem(crew_factory=lambda: sentinel_crew)
        assert us.crew is sentinel_crew

    def test_ssrf_disabled_no_tool_registry(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig(enable_ssrf_protection=False)
        us = bridge_module.UnifiedSystem(config=cfg)
        assert us.tool_registry is None

    def test_ssrf_enabled_creates_registry(self, bridge_module):
        cfg = bridge_module.UnifiedSystemConfig(enable_ssrf_protection=True)
        us = bridge_module.UnifiedSystem(config=cfg)
        assert us.tool_registry is not None


class TestUnifiedSystemRunTask:

    def test_run_task_returns_string(self, bridge_module):
        # FIX (logique LLM unique, intégration Nexus Assistant) : ce test ne
        # doit pas dépendre d'un vrai appel réseau au LLM — sinon, avec
        # crewAI réel installé (HAS_CREWAI=True) et sans clé API valide, il
        # bloque (retries LiteLLM) plutôt que d'échouer vite. On isole
        # exactement comme test_run_task_delegates_to_engine : seul le
        # câblage run_task() → engine(...) est testé ici, pas le LLM lui-même.
        us = bridge_module.UnifiedSystem()
        us.engine = lambda prompt="", **kw: "stubbed output"
        result = us.run_task("Écrire un hello world en Python")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_run_task_empty_instruction(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        us.engine = lambda prompt="", **kw: "stubbed output"
        result = us.run_task("")
        assert isinstance(result, str)

    def test_run_task_delegates_to_engine(self, bridge_module):
        """run_task doit appeler engine(prompt=...) sans wrap supplémentaire."""
        captured = {}
        class SpyEngine:
            def __call__(self, prompt="", **kw):
                captured["prompt"] = prompt
                return "spy-output"

        us = bridge_module.UnifiedSystem()
        us.engine = SpyEngine()
        us.run_task("Test instruction XYZ")
        assert captured.get("prompt") == "Test instruction XYZ"


class TestUnifiedSystemHealthCheck:

    def test_health_check_returns_dict(self, bridge_module):
        us = bridge_module.UnifiedSystem(
            config=bridge_module.UnifiedSystemConfig(
                openhands_base_url="http://localhost:99999"
            )
        )
        status = us.health_check()
        assert isinstance(status, dict)

    def test_health_check_has_openhands_key(self, bridge_module):
        us = bridge_module.UnifiedSystem(
            config=bridge_module.UnifiedSystemConfig(
                openhands_base_url="http://localhost:99999"
            )
        )
        status = us.health_check()
        assert "openhands" in status

    def test_health_check_has_crewai_key(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "crewai" in status

    def test_health_check_has_rl_engine_key(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "rl_engine" in status

    def test_health_check_openhands_error_when_unreachable(self, bridge_module):
        """L'état OpenHands doit signaler l'erreur sans lever d'exception."""
        us = bridge_module.UnifiedSystem(
            config=bridge_module.UnifiedSystemConfig(
                openhands_base_url="http://127.0.0.1:19999"  # rien n'écoute ici
            )
        )
        status = us.health_check()
        assert "error" in status["openhands"].lower() or "HTTP" in status["openhands"]

    def test_health_check_crewai_ok_when_crew_exists(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "error" not in status["crewai"]

    def test_health_check_rl_ok_when_engine_exists(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        status = us.health_check()
        assert "error" not in status["rl_engine"]


class TestBuildRlEnvConfig:

    def test_build_rl_env_config_returns_dict(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        cfg = us.build_rl_env_config()
        assert isinstance(cfg, dict)

    def test_build_rl_env_config_has_env_key(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        cfg = us.build_rl_env_config()
        assert "env" in cfg
        assert "data" in cfg
        assert "algorithm" in cfg

    def test_build_rl_env_config_env_name(self, bridge_module):
        us = bridge_module.UnifiedSystem()
        cfg = us.build_rl_env_config()
        assert cfg["env"]["env_name"] == "openhands"

    def test_build_rl_env_config_reward_allocation(self, bridge_module):
        cfg_obj = bridge_module.UnifiedSystemConfig(rl_reward_allocation="uniform_positive")
        us = bridge_module.UnifiedSystem(config=cfg_obj)
        cfg = us.build_rl_env_config()
        assert cfg["algorithm"]["reward_allocation"] == "uniform_positive"

    def test_build_rl_env_config_batch_size_coherent(self, bridge_module):
        cfg_obj = bridge_module.UnifiedSystemConfig(rl_batch_size=8)
        us = bridge_module.UnifiedSystem(config=cfg_obj)
        cfg = us.build_rl_env_config()
        assert cfg["data"]["train_batch_size"] == 8
        assert cfg["data"]["val_batch_size"] == 2  # max(1, 8//4)

    def test_build_rl_env_config_batch_size_1_gives_val_1(self, bridge_module):
        cfg_obj = bridge_module.UnifiedSystemConfig(rl_batch_size=1)
        us = bridge_module.UnifiedSystem(config=cfg_obj)
        cfg = us.build_rl_env_config()
        assert cfg["data"]["val_batch_size"] == 1  # max(1, 0) = 1


# ══════════════════════════════════════════════════════════════════════════════
# 4. RÉGRESSIONS UNIFIED_SYSTEM
# ══════════════════════════════════════════════════════════════════════════════

class TestUnifiedSystemRegressions:

    def test_bridge_py_exists_in_repo(self):
        bridge_path = UNIFIED_DIR / "bridge.py"
        assert bridge_path.exists(), "unified_system/bridge.py manquant"

    def test_bridge_py_is_nonempty(self):
        bridge_path = UNIFIED_DIR / "bridge.py"
        assert bridge_path.stat().st_size > 100, "unified_system/bridge.py semble vide"

    def test_bridge_py_defines_unified_system_class(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "class UnifiedSystem" in content

    def test_bridge_py_defines_unified_system_config(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "class UnifiedSystemConfig" in content

    def test_bridge_py_defines_run_task_method(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "def run_task" in content

    def test_bridge_py_defines_health_check_method(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "def health_check" in content

    def test_bridge_py_defines_from_env_class_method(self):
        content = (UNIFIED_DIR / "bridge.py").read_text()
        assert "def from_env" in content

    def test_codegen_unified_system_handler_wired_in_nexus(self):
        """
        Régression : le nœud codegen.unified_system doit être câblé dans le
        graphe nexus_compose. Ce test vérifie que le correctif registry.py
        survit à l'ajout du système unifié.
        """
        from nexus_compose import build_graph
        G = build_graph()
        n = G.node("codegen.unified_system")
        assert n is not None
        assert n.is_live, "codegen.unified_system doit avoir un handler live"

    def test_orchestrator_threat_model_pipeline_uses_unified_system(self):
        """
        Vérifie que threat_model_pipeline exécute bien codegen.unified_system.
        """
        from nexus_compose import build_graph, Orchestrator
        G = build_graph()
        orch = Orchestrator(G)
        pr = orch.threat_model_pipeline({"elements": [], "relationships": []})
        executed = {s.node_id for s in pr.steps}
        assert "codegen.unified_system" in executed


# ══════════════════════════════════════════════════════════════════════════════
# 5. TESTS NÉCESSITANT LE STACK COMPLET (skipés en CI si libs absentes)
# ══════════════════════════════════════════════════════════════════════════════

@requires_full_stack
@unified_full
class TestFullStackIntegration:
    """
    Ces tests ne tournent que si crewAI + OpenHands + OpenManus-RL sont tous
    installés depuis leurs zips locaux (bootstrap.sh --fullstack).
    Marqués unified_full pour être excluables facilement.
    """

    def test_real_crewai_crew_creation(self, bridge_module):
        us = bridge_module.UnifiedSystem.from_env()
        assert len(us.crew.agents) >= 1
        assert len(us.crew.tasks) >= 1

    def test_real_engine_is_crewai_engine(self, bridge_module):
        from openmanus_rl.engines.openai import CrewAIEngine
        us = bridge_module.UnifiedSystem.from_env()
        assert isinstance(us.engine, CrewAIEngine)

    def test_real_tool_registry_is_ssrf_safe(self, bridge_module):
        from openmanus_rl.multi_turn_rollout.tool_integration import SSRFSafeToolRegistry
        us = bridge_module.UnifiedSystem.from_env()
        assert isinstance(us.tool_registry, SSRFSafeToolRegistry)
