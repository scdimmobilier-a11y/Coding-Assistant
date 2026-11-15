"""unified_system.bridge — Unified System orchestration entry point.

This module wires the three layers together:

    OpenManus-RL (training)
        ↕  trajectoires + récompenses
    crewAI        (orchestration)
        ↕  actions exécutées dans sandbox
    OpenHands     (exécution)

Quick-start
-----------
::

    from unified_system.bridge import UnifiedSystem

    system = UnifiedSystem.from_env()          # reads env vars
    system.train(n_steps=500)                  # RL training loop
    result = system.run_task("Write a merge-sort in Python")   # inference

Environment variables
---------------------
OH_BASE_URL             URL of the running OpenHands server  (default: http://localhost:3000)
OH_TOKEN                Bearer token for OpenHands           (default: "")
NEXUS_LLM_PROVIDER      LLM provider, shared with q2d/nexus_compose (default: openai)
NEXUS_LLM_MODEL         LLM model, shared with q2d/nexus_compose    (default: gpt-4o-mini)
NEXUS_LLM_API_KEY       API key, shared with q2d/nexus_compose
NEXUS_LLM_BASE_URL      Optional self-hosted provider base URL
CREWAI_LLM_MODEL        Back-compat fallback for NEXUS_LLM_MODEL, only read if it's unset
OPENAI_API_KEY          Back-compat fallback for NEXUS_LLM_API_KEY, only read if it's unset
NEXUS_AGENT_SKILLS_DIR  Directory of Nexus-owned Agent Skills (D5, see
                        `Nexus_Assistant/nexus_compose/agent_skills/`)  (default: ./nexus_compose/agent_skills)
RL_MAX_STEPS            Max RL training steps                (default: 1000)
RL_BATCH_SIZE           Parallel sandboxes per RL step        (default: 4)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# ── crewAI imports (optionnel — absent dans l'image Docker nexus_compose) ─────
# crewAI est installé via son zip local dans bootstrap.sh (dev local).
# Dans l'image Docker, le conteneur nexus_compose n'a pas crewAI installé :
# le Unified System tourne via bridge.py + API HTTP OpenHands (service séparé).
# Chaque symbole crewAI est importé INDÉPENDAMMENT : un symbole optionnel
# absent (ex. `LLM` ou `skills` dans un simulacre de test, ou une version de
# crewAI qui a bougé une classe) ne doit pas annuler les symboles de base ni
# empêcher la construction du crew (défaut identifié au constat, lot 0 : un
# seul `from crewai import Agent, Crew, LLM, Task` faisait planter tout le
# Unified System dès que `LLM` manquait, mettant OpenHandsTask à None).
def _try_import(module: str, name: str):
    try:
        import importlib
        return getattr(importlib.import_module(module), name)
    except Exception:
        return None

Agent = _try_import("crewai", "Agent")
Crew = _try_import("crewai", "Crew")
Task = _try_import("crewai", "Task")
LLM = _try_import("crewai", "LLM")
OpenHandsTask = _try_import("crewai.tools.openhands_tool", "OpenHandsTask")
_CREWAI_AVAILABLE = all(x is not None for x in (Agent, Crew, Task, OpenHandsTask))

# Les Agent Skills (D5) sont une dépendance SÉPARÉE et optionnelle : leur
# absence ne doit PAS annuler OpenHandsTask ni empêcher la construction du
# crew (sinon un simulacre de crewAI sans `crewai.skills`, comme en test,
# fait planter tout le Unified System — défaut identifié au constat, lot 0).
try:
    from crewai.skills import discover_skills
except ImportError:
    discover_skills = None  # type: ignore

# ── OpenManus-RL imports (optionnel — namespace package via .pth) ─────────────
try:
    from openmanus_rl.engines.openai import CrewAIEngine
    from openmanus_rl.multi_turn_rollout.tool_integration import SSRFSafeToolRegistry
    _OPENMANUS_AVAILABLE = True
except ImportError:
    CrewAIEngine = SSRFSafeToolRegistry = None  # type: ignore
    _OPENMANUS_AVAILABLE = False


# ── Configuration ─────────────────────────────────────────────────────────────

@dataclass
class UnifiedSystemConfig:
    """All runtime parameters for the unified stack."""

    # OpenHands
    openhands_base_url: str = "http://localhost:3000"
    openhands_token: str = ""
    openhands_timeout: int = 120

    # LLM — FIX (logique LLM unique, intégration Nexus Assistant) : avant ce
    # correctif, ce champ (crewai_llm_model) était le SEUL point de config
    # LLM du Unified System, complètement déconnecté du modèle utilisé par
    # q2d en phase 1 (voir nexus_compose/llm_config.py) et d'OpenHands (qui
    # ne recevait même pas de nom de modèle dans docker-compose.yml — il
    # tournait sur SON PROPRE défaut interne). Les 4 champs ci-dessous sont
    # désormais lus depuis les MÊMES variables NEXUS_LLM_* que q2d.
    # `crewai_llm_model` est conservé (dérivé de llm_model) pour compat
    # ascendante avec le code existant qui le lit directement.
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: Optional[str] = None
    crewai_verbose: bool = False

    # OpenManus-RL
    rl_max_steps: int = 1000
    rl_batch_size: int = 4
    rl_reward_allocation: str = "last_token"  # "last_token" | "uniform_positive" | "discounted"

    # Tool security
    enable_ssrf_protection: bool = True

    # Agent Skills (D5, MISSION_couple_leon_nexusbrain.md) — Nexus-owned
    # curated skills, NOT the vendored agent-skills-main pack directly (see
    # Nexus_Assistant/nexus_compose/agent_skills/ and _default_crew_factory
    # below for why: crewAI upgrades can move/rename its vendored copy,
    # this path can't).
    agent_skills_dir: str = "./nexus_compose/agent_skills"

    @property
    def crewai_llm_model(self) -> str:
        """Alias de compat ascendante — code existant qui lisait ce nom."""
        return self.llm_model

    @classmethod
    def from_env(cls) -> "UnifiedSystemConfig":
        """Build config from environment variables.

        Lit NEXUS_LLM_* en priorité (point de configuration unique partagé
        avec q2d) ; retombe sur CREWAI_LLM_MODEL / OPENAI_API_KEY (anciennes
        variables) si NEXUS_LLM_* est absent, pour ne pas casser les
        déploiements existants.
        """
        return cls(
            openhands_base_url=os.getenv("OH_BASE_URL", "http://localhost:3000"),
            openhands_token=os.getenv("OH_TOKEN", ""),
            openhands_timeout=int(os.getenv("OH_TIMEOUT", "120")),
            llm_provider=os.getenv("NEXUS_LLM_PROVIDER", "openai"),
            llm_model=(
                os.getenv("NEXUS_LLM_MODEL")
                or os.getenv("CREWAI_LLM_MODEL")  # compat ascendante
                or "gpt-4o-mini"
            ),
            llm_api_key=(
                os.getenv("NEXUS_LLM_API_KEY")
                or os.getenv("OPENAI_API_KEY")  # compat ascendante
                or ""
            ),
            llm_base_url=os.getenv("NEXUS_LLM_BASE_URL") or None,
            rl_max_steps=int(os.getenv("RL_MAX_STEPS", "1000")),
            rl_batch_size=int(os.getenv("RL_BATCH_SIZE", "4")),
            agent_skills_dir=os.getenv("NEXUS_AGENT_SKILLS_DIR", "./nexus_compose/agent_skills"),
        )


# ── Core unified system ───────────────────────────────────────────────────────

class UnifiedSystem:
    """Entry point that assembles and exposes the three-layer agent stack.

    Layers
    ------
    1. **Tool registry** (OpenManus-RL + crewAI security)
       :class:`SSRFSafeToolRegistry` loads RL tools while routing every HTTP
       request through the crewAI SSRF-protected adapter.

    2. **crewAI Crew** (orchestration)
       A single-agent crew whose sole tool is :class:`OpenHandsTask`.  The
       crew translates high-level instructions into OpenHands API calls.

    3. **OpenManus-RL engine** (training)
       :class:`CrewAIEngine` wraps the crew so OpenManus-RL can treat it as an
       LLM policy and collect RL trajectories against an OpenHands environment.

    Args:
        config: :class:`UnifiedSystemConfig` with all runtime parameters.
        crew_factory: Optional custom factory returning a crewAI :class:`Crew`.
            When omitted, the default software-developer crew is used.
    """

    def __init__(
        self,
        config: Optional[UnifiedSystemConfig] = None,
        crew_factory: Optional[Callable[[], Crew]] = None,
    ) -> None:
        self.config = config or UnifiedSystemConfig()

        # ── Layer 1: SSRF-safe tool registry ──────────────────────────────
        self.tool_registry = SSRFSafeToolRegistry() if self.config.enable_ssrf_protection else None

        # ── Layer 2: crewAI crew ───────────────────────────────────────────
        self._crew_factory = crew_factory or self._default_crew_factory
        self.crew = self._crew_factory()

        # ── Layer 3: OpenManus-RL engine ───────────────────────────────────
        self.engine = CrewAIEngine(crew_factory=self._crew_factory)

    # ── Public API ─────────────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "UnifiedSystem":
        """Create a UnifiedSystem using environment variable configuration."""
        return cls(config=UnifiedSystemConfig.from_env())

    def run_task(self, instruction: str) -> str:
        """Run a single task through the full crewAI → OpenHands stack.

        This is the **inference** path: no RL training is involved.

        Args:
            instruction: Natural-language task description.

        Returns:
            The final output from the OpenHands sandbox agent.
        """
        return self.engine(prompt=instruction)

    def build_rl_env_config(self) -> dict:
        """Return an omegaconf-compatible dict for OpenManus-RL's env config.

        Inject into your training config with::

            from omegaconf import OmegaConf
            cfg = OmegaConf.create(system.build_rl_env_config())

        Returns:
            dict with ``env.*`` keys expected by :class:`OpenHandsEnvironmentManager`.
        """
        return {
            "env": {
                "env_name": "openhands",
                "openhands_base_url": self.config.openhands_base_url,
                "openhands_token": self.config.openhands_token,
                "openhands_timeout": self.config.openhands_timeout,
                "rollout": {"n": 1},
                "history_length": 0,
                "seed": 42,
            },
            "data": {
                "train_batch_size": self.config.rl_batch_size,
                "val_batch_size": max(1, self.config.rl_batch_size // 4),
            },
            "algorithm": {
                "reward_allocation": self.config.rl_reward_allocation,
            },
        }

    def health_check(self) -> dict:
        """Ping each layer and return a status report.

        Returns:
            dict with ``openhands``, ``crewai``, and ``rl_engine`` keys.
        """
        import requests

        status: dict[str, Any] = {}

        # OpenHands
        try:
            r = requests.get(
                f"{self.config.openhands_base_url}/health",
                timeout=5,
                headers={"Authorization": f"Bearer {self.config.openhands_token}"}
                if self.config.openhands_token else {},
            )
            status["openhands"] = "ok" if r.ok else f"HTTP {r.status_code}"
        except Exception as exc:
            status["openhands"] = f"error: {exc}"

        # crewAI — just verify the crew object exists
        try:
            status["crewai"] = f"ok — {len(self.crew.agents)} agent(s)"
        except Exception as exc:
            status["crewai"] = f"error: {exc}"

        # LLM actif — visibilité directe sur la config unifiée (voir
        # nexus_compose/llm_config.py pour le même point de configuration
        # côté q2d)
        status["llm"] = (
            f"{self.config.llm_provider}/{self.config.llm_model}"
            + (" (clé API absente)" if not self.config.llm_api_key else "")
        )

        # OpenManus-RL engine
        try:
            _ = self.engine  # non-None check
            status["rl_engine"] = "ok — CrewAIEngine ready"
        except Exception as exc:
            status["rl_engine"] = f"error: {exc}"

        return status

    # ── Default crewAI crew ────────────────────────────────────────────────

    def _default_crew_factory(self) -> Crew:
        """Build the default software-developer crew.

        The crew has one agent (a software engineer) whose single tool is
        :class:`OpenHandsTask`.  To customise the crew, pass your own
        ``crew_factory`` to :class:`UnifiedSystem.__init__`.
        """
        oh_tool = OpenHandsTask(
            openhands_base_url=self.config.openhands_base_url,
            openhands_token=self.config.openhands_token,
            timeout=self.config.openhands_timeout,
        )

        # FIX (logique LLM unique, intégration Nexus Assistant) : on
        # construisait auparavant l'Agent avec `llm=self.config.crewai_llm_model`
        # (une simple chaîne) — crewAI/LiteLLM résolvait alors la clé API tout
        # seul depuis OPENAI_API_KEY, sans passer par la config unifiée (donc
        # sans jamais utiliser NEXUS_LLM_API_KEY ni NEXUS_LLM_BASE_URL, par ex.
        # pour un provider auto-hébergé).
        #
        # On construit un objet crewai.LLM explicite avec le même
        # provider/modèle/clé/URL que q2d SEULEMENT si une clé a été résolue.
        # Passer `api_key=None` explicitement au constructeur LLM bloque le
        # repli natif de LiteLLM vers os.environ["OPENAI_API_KEY"] au moment
        # de l'appel (contrairement à une simple chaîne de modèle) — donc sans
        # clé connue, on repasse à l'ancien comportement (chaîne nue) pour ne
        # pas régresser sur les déploiements qui comptent sur ce repli natif.
        if self.config.llm_api_key or self.config.llm_base_url:
            llm = LLM(
                model=self.config.llm_model,
                api_key=self.config.llm_api_key or None,
                base_url=self.config.llm_base_url,
                provider=self.config.llm_provider,
            )
        else:
            llm = self.config.llm_model

        engineer = Agent(
            role="Software Engineer",
            goal=(
                "Implement software tasks precisely and efficiently "
                "using the OpenHands sandbox."
            ),
            backstory=(
                "You are an expert software engineer trained via reinforcement "
                "learning on thousands of real coding tasks.  You always produce "
                "clean, tested, documented code."
            ),
            tools=[oh_tool],
            skills=self._discover_agent_skills(),
            llm=llm,
            verbose=self.config.crewai_verbose,
        )

        task = Task(
            description="Complete the following software task: {observation}",
            expected_output=(
                "A concise description of what was implemented, plus the "
                "sandbox output confirming success."
            ),
            agent=engineer,
        )

        return Crew(
            agents=[engineer],
            tasks=[task],
            verbose=self.config.crewai_verbose,
        )

    def _discover_agent_skills(self) -> Optional[list]:
        """D5 (`MISSION_couple_leon_nexusbrain.md`): load the curated,
        Nexus-owned Agent Skills (`config.agent_skills_dir`, default
        `Nexus_Assistant/nexus_compose/agent_skills/`) via crewAI's own
        `discover_skills()` — no reimplementation of skill discovery/
        parsing, this is the exact same function `Agent(skills=...)`
        expects.

        Deliberately does NOT point at `agent-skills-main`'s vendored copy
        directly (`unified_system/crewAI/.../crewai/skills/agent-skills-main/`):
        that path lives inside crewAI's own vendored source tree and can
        move or disappear across crewAI upgrades — `nexus_compose/agent_skills/`
        is a small, curated, Nexus-owned copy of the 5 skills actually
        relevant to this single automated "Software Engineer" agent
        (see that directory for the full list and provenance notes in
        each `SKILL.md`).

        Returns `None` (not `[]`) on any failure — same as `Agent(skills=None)`,
        crewAI's own "no skills" default — so a missing/misconfigured
        skills directory degrades this agent back to its pre-D5 behaviour
        instead of raising out of `_default_crew_factory`. `discover_skills`
        itself already returns `[]` (not an error) for an empty directory;
        this only additionally guards against the directory being entirely
        absent or `discover_skills` not being importable at all (same
        defensive shape as `_CREWAI_AVAILABLE` above)."""
        if discover_skills is None:
            logger.warning(
                "crewai.skills.discover_skills is not importable — "
                "agent running without Agent Skills (D5)."
            )
            return None

        skills_dir = Path(self.config.agent_skills_dir)
        if not skills_dir.is_dir():
            logger.warning(
                "NEXUS_AGENT_SKILLS_DIR=%s is not a directory — agent "
                "running without Agent Skills (D5). Expected e.g. "
                "Nexus_Assistant/nexus_compose/agent_skills/.",
                skills_dir,
            )
            return None

        try:
            discovered = discover_skills(skills_dir)
        except Exception:
            logger.exception(
                "discover_skills(%s) failed — agent running without Agent "
                "Skills (D5) rather than failing crew construction.",
                skills_dir,
            )
            return None

        return discovered or None
