"""nexus_unified.pack.edges — arêtes typées du pack unified.

Le laboratoire se branche sur le pipeline de base en trois points (constat
« graphe cible ») : `codegen` lui délègue l'exécution, `graph` reçoit ses
connaissances, `audit` nourrit sa récompense. Les arêtes internes relient les
nœuds d'infrastructure et de RL.

Chaque arête est (source, cible, libellé, EdgeType). Les EdgeType EXECUTE,
REWARD, UPDATE, LEASE sont ajoutés dans nexus_compose.graph.
"""
from __future__ import annotations

from typing import List, Tuple

from nexus_compose.graph import EdgeType as E

PACK_EDGES: List[Tuple[str, str, str, "E"]] = [
    # ── branchement sur le pipeline de base ───────────────────────────────────
    ("codegen.unified_system", "oh.send_message", "délègue l'exécution au sandbox", E.EXECUTE),
    ("tmdd.generate_agent_prompt", "oh.send_message", "contraintes → agent (chemin direct)", E.INJECT),
    ("oh.send_message", "CODE_GENERATED", "code produit par le sandbox", E.DATA_FLOW),
    ("oh.git_diff", "CODE_GENERATED", "diff produit", E.DATA_FLOW),
    ("semgrep.semgrep_scan", "reward.from_audit", "constats SAST → pénalité", E.REWARD),
    ("bearer.bearer_scan", "reward.from_audit", "constats privacy → pénalité", E.REWARD),
    ("codeql.codeql_database_analyze", "reward.from_audit", "constats sémantiques → pénalité", E.REWARD),
    ("crew.memory_remember", "neo4j.create", "connaissances → graphe", E.STORE),
    ("ml.dataset_snapshot", "neo4j.create", "fiche dataset → graphe", E.STORE),

    # ── GPU / baux ────────────────────────────────────────────────────────────
    ("gpu.discover", "gpu.lease", "flotte découverte", E.DATA_FLOW),
    ("gpu.lease", "oh.sandbox_start", "périphérique exposé au sandbox", E.LEASE),
    ("gpu.lease", "ml.run_submit", "bail pour l'entraînement", E.LEASE),
    ("gpu.lease", "vllm.serve", "bail pour le service", E.LEASE),
    ("ml.run_submit", "gpu.release", "bail rendu en fin de run", E.LEASE),
    ("vllm.stop", "gpu.release", "VRAM libérée", E.LEASE),
    ("budget.guard", "ml.run_submit", "autorise si budget restant", E.VALIDATE),
    ("budget.guard", "oh.send_message", "autorise si budget restant", E.VALIDATE),

    # ── recherche / conception ────────────────────────────────────────────────
    ("oh.git_suggested_tasks", "crew.kickoff", "tâches candidates", E.DATA_FLOW),
    ("crew.kickoff", "oh.send_message", "action déléguée au sandbox", E.EXECUTE),
    ("crew.kickoff_for_each", "oh.send_message", "fan-out d'actions", E.EXECUTE),
    ("crewtools.arxiv_paper", "crew.memory_remember", "sources → mémoire", E.STORE),
    ("crewtools.pdf_search", "ml.dataset_snapshot", "documents → dataset", E.DATA_FLOW),
    ("ml.artifact_inspect", "ml.dataset_snapshot", "artefact admis", E.VALIDATE),

    # ── entraînement / évaluation ─────────────────────────────────────────────
    ("ml.dataset_snapshot", "ml.run_submit", "données figées", E.DATA_FLOW),
    ("ml.run_submit", "ml.run_wait", "job lancé", E.DATA_FLOW),
    ("ml.run_wait", "ml.metrics_read", "run terminé", E.DATA_FLOW),
    ("ml.metrics_read", "eval.gate", "métriques → porte", E.VALIDATE),
    ("eval.gate", "ml.checkpoint_promote", "promotion si seuils atteints", E.UPDATE),
    ("ml.run_wait", "ml.checkpoint_register", "checkpoint enregistré", E.STORE),
    ("ml.checkpoint_promote", "vllm.swap", "modèle promu servi", E.UPDATE),
    ("ml.checkpoint_promote", "oh.switch_profile", "cerveau bascule sur le modèle promu", E.UPDATE),

    # ── apprentissage RL (boucle) ─────────────────────────────────────────────
    ("oh.git_suggested_tasks", "omrl.make_envs", "tâches → environnements", E.DATA_FLOW),
    ("omrl.make_envs", "omrl.rollout_vanilla", "environnements prêts", E.DATA_FLOW),
    ("omrl.rollout_vanilla", "omrl.env_openhands", "politique agit dans le sandbox", E.EXECUTE),
    ("omrl.env_openhands", "oh.rl_step", "pas RL dans OpenHands", E.EXECUTE),
    ("oh.rl_step", "reward.from_tests", "observation → tests", E.REWARD),
    ("oh.rl_step", "reward.from_audit", "observation → audit", E.REWARD),
    ("reward.from_tests", "omrl.gigpo_step_group", "récompense → crédit par étape", E.REWARD),
    ("reward.from_audit", "omrl.gigpo_step_group", "pénalité → crédit par étape", E.REWARD),
    ("omrl.gigpo_step_group", "omrl.ppo_train", "avantages → mise à jour", E.UPDATE),
    ("omrl.ppo_train", "ml.checkpoint_register", "nouveaux poids", E.STORE),
    ("ml.checkpoint_register", "eval.gate", "checkpoint → évaluation", E.VALIDATE),
    ("vllm.swap", "omrl.rollout_vanilla", "nouvelle politique servie (boucle)", E.UPDATE),

    # ── diagnostic / reprise ──────────────────────────────────────────────────
    ("oh.events_search", "omrl.agent_debugger_detect", "trajectoire → détection d'erreur", E.ANALYZE),
    ("omrl.agent_debugger_detect", "crew.kickoff", "remède borné", E.INJECT),
    ("eval.gate", "REPORT", "verdict de promotion", E.REPORT),
    ("gpu.discover", "REPORT", "inventaire des accélérateurs", E.REPORT),
]
