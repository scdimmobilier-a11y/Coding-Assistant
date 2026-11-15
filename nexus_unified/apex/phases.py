"""nexus_unified.apex.phases — les 8 phases de gouvernance Apex et le cycle.

Les 8 phases du schéma Apex (co-conception → maintenance continue) gouvernent le
pipeline existant et le laboratoire. Elles ne remplacent pas les 10 phases du
pipeline logiciel ni les 6 phases du laboratoire : elles les ENVELOPPENT. La
table `APEX_PHASES` donne l'ordre et le rôle ; `ApexCycle` exécute un tour
Observer → (threat/knowledge) → Actor → audit en s'appuyant sur le
MasterOrchestrator et l'état partagé.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .kernel import (
    Actor, KnowledgeStatus, Learner, Observer, ProtectedKernel, SharedSystemState,
)

# ── les 8 phases ─────────────────────────────────────────────────────────────
APEX_PHASES: List[Dict[str, str]] = [
    {"id": "co_design", "n": "1",
     "role": "Co-conception et définition : objectifs, frontières, contexte, "
             "entités/propriétés/ressources, relations, critères de succès mesurables."},
    {"id": "apex_architecture", "n": "2",
     "role": "Architecture Apex : noyau protégé (ontologie), connexion de "
             "consilience (protocole protégé, indépendance du modèle), rôles "
             "Observer/Learner/Actor et état partagé persistant."},
    {"id": "environment_policy", "n": "3",
     "role": "Environnement et politique : conditions internes/externes, "
             "cartographie des systèmes, modélisation des ressources, autorisation "
             "(permissions, frontières protégées, acteurs et contraintes d'action)."},
    {"id": "threat_contradiction", "n": "4",
     "role": "Menaces et contradictions : intégrité (changements non autorisés, "
             "corruption d'état), sécurité (rejeu, révocation, accès), connaissance "
             "(contradictions, lacunes, incertitude, provenance), récupération "
             "(détection d'échec, reprise sûre, rejet, quarantaine)."},
    {"id": "intelligence_validation", "n": "5",
     "role": "Intelligence et validation de connaissance : état partagé, Learner "
             "(mises à jour, révision du modèle), tests de connaissance "
             "(contradiction, propriétés cachées, transfert structurel, remplacement "
             "de modèle), validation Apex (établi/dérivé/non résolu, tests à "
             "l'aveugle, falsification)."},
    {"id": "actor_execution", "n": "6",
     "role": "Planification et exécution de l'acteur : sélection de l'acteur "
             "(modèle IA, humain, dispositif, logiciel), planification (objectifs, "
             "actions, résultats prédits, contraintes), autorisation (vérification "
             "AVANT exécution), exécution et observation des résultats réels."},
    {"id": "outcome_audit", "n": "7",
     "role": "Audit de l'intelligence et des résultats : mesure des résultats et "
             "conséquences, intégration des corrections (Learner), audit d'intégrité "
             "(protocole protégé, cohérence d'état), tests de performance (succès, "
             "fiabilité, adaptation, efficacité, effets non voulus), tests comparatifs "
             "(Apex contre témoin, indépendance du modèle)."},
    {"id": "deployment", "n": "8",
     "role": "Déploiement et maintenance continue : environnement maintenu, acteurs "
             "actifs, Observer (surveillance continue), Learner (adaptation "
             "persistante), Actor (actions correctives/proactives autorisées), "
             "validation système (résultats réels, viabilité)."},
]
APEX_PHASE_IDS = [p["id"] for p in APEX_PHASES]


@dataclass
class CycleReport:
    integrity_ok: bool
    contradictions: List[str] = field(default_factory=list)
    actions_run: List[str] = field(default_factory=list)
    actions_blocked: List[str] = field(default_factory=list)
    established: int = 0
    unresolved: int = 0
    quarantined: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"integrity_ok": self.integrity_ok, "contradictions": self.contradictions,
                "actions_run": self.actions_run, "actions_blocked": self.actions_blocked,
                "established": self.established, "unresolved": self.unresolved,
                "quarantined": self.quarantined, "notes": self.notes}


class ApexCycle:
    """Un tour de gouvernance Apex autour d'une exécution d'orchestrateur.

    `master` : un MasterOrchestrator (ou tout objet avec `.run(goal, ...)`).
    `kernel_fingerprint` : l'empreinte attendue du noyau (intégrité, phase 4/7).
    """

    def __init__(self, master: Any, *, state: Optional[SharedSystemState] = None,
                 kernel: Optional[ProtectedKernel] = None,
                 kernel_fingerprint: Optional[str] = None,
                 authorize: Optional[Callable[[str, Dict[str, Any]], bool]] = None) -> None:
        self.master = master
        self.kernel = kernel or ProtectedKernel()
        self.expected_fp = kernel_fingerprint or self.kernel.fingerprint
        self.state = state or SharedSystemState()
        self.observer = Observer(self.state)
        self.learner = Learner(self.state)
        self.actor = Actor(authorize or getattr(master, "authorizer", lambda a, c: True))

    def run(self, goal: str, *, conditions: Optional[Dict[str, Any]] = None,
            ctx: Optional[Dict[str, Any]] = None) -> CycleReport:
        report = CycleReport(integrity_ok=True)

        # Phase 4/7 — intégrité du noyau protégé AVANT toute action.
        if not self.kernel.verify(self.expected_fp):
            report.integrity_ok = False
            report.notes.append("ALERTE intégrité : l'empreinte du noyau Apex a changé — "
                                "exécution refusée (phase 4).")
            return report

        # Phase 3/5 — Observer écrit les conditions.
        if conditions:
            self.observer.observe(conditions, provenance="apex.cycle")

        # Phase 6 — l'Actor exécute via le MasterOrchestrator (autorisation incluse).
        outcome = self.master.run(goal, ctx=ctx)
        for step in outcome.steps:
            if not step.authorized:
                report.actions_blocked.append(step.action)
            elif step.success:
                report.actions_run.append(step.action)
                # Phase 7 — Learner intègre le résultat (dérivé par défaut).
                self.learner.integrate(f"result:{step.action}", _summ(step.data),
                                        provenance=f"run:{step.task_id}")
            else:
                report.actions_blocked.append(step.action)
                self.state.mark_unresolved(f"failure:{step.action}", step.error,
                                           provenance=f"run:{step.task_id}")
                report.notes.append(f"échec intégré comme non résolu : {step.action}")

        # Phase 5 — bilan de connaissance.
        report.established = len(self.state.by_status(KnowledgeStatus.ESTABLISHED))
        report.unresolved = len(self.state.by_status(KnowledgeStatus.UNRESOLVED))
        report.contradictions = [i.key for i in self.state.contradictions()]
        report.integrity_ok = self.kernel.verify(self.expected_fp)
        return report


def _summ(data: Any) -> Any:
    if isinstance(data, dict):
        return {k: v for k, v in data.items()
                if k in ("ok", "verdict", "pass", "reward", "lease_id", "conversation_id")}
    return data


def apex_phase_for(pipeline_phase: str) -> str:
    """Projette une phase laboratoire/pipeline sur sa phase Apex (gouvernance)."""
    from ..pack.catalog import PHASE_TO_APEX
    return PHASE_TO_APEX.get(pipeline_phase, "")
