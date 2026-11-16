"""
nexus_brain.registry
──────────────────────
Mission 2 (Meta Framework / Nexus Studio) — livrable D3.

Avant cette mission, aucune entrée de registre ne décrivait Nexus Brain :
zéro visibilité pour le Brain sur lui-même (cf. le document de mission,
§1). Ce module comble ce trou avec une liste STATIQUE de dicts au format
`NodeMeta` — le même contrat JSON que `nexus_compose.graph.NodeMeta`,
documenté dans `Nexus_Assistant/docs/registry_schema.md` (D1) — décrivant
les composants Niveau 1 (cognitif) déjà audités en Mission 1.

Volontairement **pas** un import de `nexus_compose.graph.NodeMeta` : les
deux dépôts tournent dans des conteneurs séparés (cf. Mission 1 §4/D3,
Mission 2 §D1 — "sans import croisé"), donc ce fichier respecte juste la
même FORME en pur dict, sans lien Python entre les deux paquets. Pas de
`ComposabilityGraph` non plus ici — Niveau 1 reste du raisonnement, pas un
graphe de composition logicielle (cf. mission §3, "pas de fusion Niveau 1 /
Niveau 3").

Chaque `description`/`io_in`/`io_out` ci-dessous est tiré directement des
docstrings et signatures réelles du code (`nexus_brain/core/*.py`,
`nexus_brain/adapters/*_adapter.py`, `nexus_functor/nexus_functor/f*.py`,
`functor.py`) — ce travail de description était déjà fait dans le code, il
s'agit de le refléter, pas de l'inventer (cf. mission §1).

Portée volontairement un peu plus large que la liste littérale du document
source (qui citait `nexus_functor.f0/f1/f2/f3`, les 4 adapters historiques
et les 4 modules `core.*`, soit 12 entrées) : deux entrées ont été ajoutées
pour rester honnête vis-à-vis du code réel plutôt que de suivre l'énumération
à la lettre :
  - `nexus_functor.functor` (le hub `NexusFunctor.step()` qui orchestre
    F0→F1→F2→F3) — c'est le point d'entrée public réel de nexus_functor,
    omis par le raccourci "f0/f1/f2/f3" du document source.
  - `adapters.codegen_adapter` — c'est le livrable D3 de la Mission 1, déjà
    présent dans le code et explicitement rediscuté par le D4 de CETTE
    mission ("c'est cet annuaire fusionné dont codegen_adapter.py a besoin
    pour savoir que codegen.unified_system existe") ; l'omettre du registre
    Brain aurait laissé un trou pile là où D4 en a le plus besoin.
"""
from __future__ import annotations

from typing import Any, Optional

# ── Le registre ──────────────────────────────────────────────────────────────
# Un tuple de dicts (immuable au niveau module) plutôt qu'une liste : ces
# entrées sont des faits sur le code, pas un état qui se modifie à
# l'exécution. `list_nodes()` en renvoie une copie défensive (cf. plus bas).
#
# Phase commune "brain" (au lieu d'une des 9 phases du pipeline
# nexus_compose) : ces composants ne sont pas des étapes d'un pipeline
# logiciel, ils tournent en continu — cf. docs/registry_schema.md §2.2.

BRAIN_NODES: tuple[dict[str, Any], ...] = (
    # ── Niveau 1 — cœur cognitif : core.* ────────────────────────────────
    {
        "id": "core.brain",
        "module": "core",
        "module_name": "Nexus Core — Brain",
        "function": "NexusCore.handle_turn()",
        "description": (
            "Point d'entrée unique du raisonnement : route chaque tour "
            "entre les 3 modes (controlled/agent/smart), gère la pause/"
            "reprise humaine (resume_paused) et le pilotage d'objectifs "
            "long-cours (pose_objective, pulse_tick)."
        ),
        "tag": "brain.route",
        "phase": "brain",
        "type": "route",
        "io_in": "user_input (str) + context (dict) + mode ('controlled'|'agent'|'smart')",
        "io_out": "TurnResult (response, mode_used, trace, paused, …)",
        "ref": "nexus_brain/core/brain.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("dialogue", "planification"),
    },
    {
        "id": "core.memory",
        "module": "core",
        "module_name": "Nexus Core — Memory",
        "function": "LayeredMemory.remember() / .recall() + SelfModel.record_turn()",
        "description": (
            "Mémoire en couches (persistent/daily/discussion) et modèle de "
            "soi (principes, journal) consultés par NexusCore à chaque tour."
        ),
        "tag": "brain.store",
        "phase": "brain",
        "type": "store",
        "io_in": "content (str) + layer ('persistent'|'daily'|'discussion') + metadata",
        "io_out": "MemoryEntry / list[MemoryEntry] (recall) ; tuple[str,...] (principles/journal)",
        "ref": "nexus_brain/core/memory.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("memoire",),
    },
    {
        "id": "core.react",
        "module": "core",
        "module_name": "Nexus Core — ReAct Loop",
        "function": "ReactLoop.start() / .advance() / .run_until_stalled()",
        "description": (
            "Boucle ReAct (Reason+Act) : Plan → Act → Observe, avec reprise "
            "possible après intervention humaine (resume), jusqu'à "
            "stabilisation ou blocage (ReactState)."
        ),
        "tag": "brain.loop",
        "phase": "brain",
        "type": "loop",
        "io_in": "goal (str) + context (dict), puis ReactTrace en cours pour advance()/resume()",
        "io_out": "ReactTrace (steps, ReactState, réponse finale)",
        "ref": "nexus_brain/core/react.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("planification", "execution"),
    },
    {
        "id": "core.pulse",
        "module": "core",
        "module_name": "Nexus Core — Pulse",
        "function": "PulseManager.tick()",
        "description": (
            "Générateur proactif périodique : propose des Matter au rythme "
            "du contexte à chaque tick, avec suivi des refus persistants "
            "(rejected_keys) pour ne pas re-proposer ce qui a déjà été rejeté."
        ),
        "tag": "brain.schedule",
        "phase": "brain",
        "type": "schedule",
        "io_in": "now (float, optionnel) + Matter générés par les sources enregistrées",
        "io_out": "MatterResult | None par tick",
        "ref": "nexus_brain/core/pulse.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("proactivite",),
    },
    # ── Niveau 1 — nexus_functor (F0→F3 + hub) ───────────────────────────
    {
        "id": "nexus_functor.functor",
        "module": "nexus_functor",
        "module_name": "Nexus Functor — Hub",
        "function": "NexusFunctor.step()",
        "description": (
            "Point d'entrée public du functor : une passe step() orchestre "
            "F0→F1→F2→F3 (tire un PlanSet si besoin via le planner port, "
            "réagit au feedback du tick précédent, sélectionne et stabilise "
            "la décision) et retourne une Decision unique."
        ),
        "tag": "brain.orchestrate",
        "phase": "brain",
        "type": "orchestrate",
        "io_in": "Objective + PlanSet optionnel (généré via planner port sinon) + ExecutionState + context",
        "io_out": "Decision (plan_id stabilisé, next_step, signal proactif stabilisé)",
        "ref": "nexus_functor/nexus_functor/functor.py",
        "repo": "Nexus_Brain/nexus_functor",
        "virtual": False,
        "subsection": None,
        "capabilities": ("planification", "execution"),
    },
    {
        "id": "nexus_functor.f0",
        "module": "nexus_functor",
        "module_name": "Nexus Functor — F0 Macro-Strategy",
        "function": "F0MacroStrategySelector.select()",
        "description": (
            "Choisit (ou conserve) la macro-stratégie du tick — EXPLOIT/"
            "EXPLORE/RECOVER/CONSERVE — avec hystérésis : dwell-time minimal "
            "avant tout changement, et valve de sécurité qui bascule en "
            "RECOVER dès que la déviation cumulée dépasse le seuil critique."
        ),
        "tag": "brain.select",
        "phase": "brain",
        "type": "select",
        "io_in": "harness_prior (dict[str, float]) + execution_state (ExecutionState)",
        "io_out": "MacroStrategy retenue pour ce tick",
        "ref": "nexus_functor/nexus_functor/f0_macro_strategy.py",
        "repo": "Nexus_Brain/nexus_functor",
        "virtual": False,
        "subsection": None,
        "capabilities": ("planification",),
    },
    {
        "id": "nexus_functor.f1",
        "module": "nexus_functor",
        "module_name": "Nexus Functor — F1 Plan Selector",
        "function": "F1PlanSelector.score_plans() / .best_plan() / .score_proactive()",
        "description": (
            "Classe les plans candidats du PlanSet et note le signal "
            "proactif en fonction de la macro-stratégie choisie par F0."
        ),
        "tag": "brain.score",
        "phase": "brain",
        "type": "score",
        "io_in": "PlanSet + MacroStrategy (F0) + ProactiveSignal optionnel",
        "io_out": "list[PlanScore] classé + ProactiveChoice noté",
        "ref": "nexus_functor/nexus_functor/f1_plan_selector.py",
        "repo": "Nexus_Brain/nexus_functor",
        "virtual": False,
        "subsection": None,
        "capabilities": ("planification",),
    },
    {
        "id": "nexus_functor.f2",
        "module": "nexus_functor",
        "module_name": "Nexus Functor — F2 Local Adapter",
        "function": "F2LocalAdapter.adapt()",
        "description": (
            "Réagit au feedback du pas précédent : décroît la déviation "
            "cumulée existante, y ajoute la déviation du dernier pas, puis "
            "décide CONTINUE, PATCH ou ESCALATE selon le total obtenu."
        ),
        "tag": "brain.adapt",
        "phase": "brain",
        "type": "adapt",
        "io_in": "Plan en cours + ExecutionState + dernier FeedbackEvent (optionnel)",
        "io_out": "AdaptationResult (action CONTINUE/PATCH/ESCALATE, next_step, déviation mise à jour)",
        "ref": "nexus_functor/nexus_functor/f2_local_adapter.py",
        "repo": "Nexus_Brain/nexus_functor",
        "virtual": False,
        "subsection": None,
        "capabilities": ("execution",),
    },
    {
        "id": "nexus_functor.f3",
        "module": "nexus_functor",
        "module_name": "Nexus Functor — F3 Stabilizer",
        "function": "F3Stabilizer.stabilize_plan() / .stabilize_proactive()",
        "description": (
            "Dernier verrou avant de figer le tick : stabilise le plan "
            "classé par F1 et le signal proactif avec anti-flapping, pour "
            "éviter de changer de décision à chaque tick sur des scores "
            "quasi-identiques."
        ),
        "tag": "brain.stabilize",
        "phase": "brain",
        "type": "stabilize",
        "io_in": "list[PlanScore] classé (F1) + ProactiveChoice noté (F1)",
        "io_out": "(plan_id stabilisé, changed: bool) + ProactiveChoice stabilisé",
        "ref": "nexus_functor/nexus_functor/f3_stabilizer.py",
        "repo": "Nexus_Brain/nexus_functor",
        "virtual": False,
        "subsection": None,
        "capabilities": ("planification", "execution"),
    },
    # ── Niveau 1 — adapters (implémentent les ports Nexus Functor) ───────
    {
        "id": "adapters.planner_adapter",
        "module": "adapters",
        "module_name": "Nexus Brain Adapters — Planner",
        "function": "NexusPlannerAdapter.generate_plans()",
        "description": (
            "Implémente PlannerPort : génère un PlanSet diversifié via un "
            "vrai solveur STRIPS (pyperplan) quand disponible, avec repli "
            "heuristique sinon (cf. adapter.last_backend == 'pyperplan' | "
            "'fallback')."
        ),
        "tag": "brain.bridge",
        "phase": "brain",
        "type": "bridge",
        "io_in": "Objective + context (context['planning_problem'] = problème STRIPS optionnel)",
        "io_out": "PlanSet (plans candidats diversifiés)",
        "ref": "nexus_brain/adapters/planner_adapter.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("planification",),
    },
    {
        "id": "adapters.exec_adapter",
        "module": "adapters",
        "module_name": "Nexus Brain Adapters — Executor",
        "function": "NexusExecAdapter.execute_step()",
        "description": (
            "Implémente ExecutorPort : exécute un pas de plan et retourne "
            "un FeedbackEvent, via un routeur réel (Coordinator/nexus_exec, "
            "cf. using_real_router) ou un HeuristicExecRouter de repli."
        ),
        "tag": "brain.bridge",
        "phase": "brain",
        "type": "bridge",
        "io_in": "plan_id (str) + step_id (str) + params (dict)",
        "io_out": "FeedbackEvent (outcome, deviation, notes)",
        "ref": "nexus_brain/adapters/exec_adapter.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("execution",),
    },
    {
        "id": "adapters.harness_adapter",
        "module": "adapters",
        "module_name": "Nexus Brain Adapters — Harness",
        "function": "NexusHarnessAdapter.get_policy_prior() / .evolve_harness()",
        "description": (
            "Implémente HarnessPort : fournit un a priori de politique par "
            "objectif (get_policy_prior) et fait évoluer le harness "
            "(sous-agents/compétences, HarnessEvolver) selon la trajectoire "
            "récente d'exécution."
        ),
        "tag": "brain.bridge",
        "phase": "brain",
        "type": "bridge",
        "io_in": "Objective + context (get_policy_prior) ; trajectory_window + current_step (evolve_harness)",
        "io_out": "dict[str, float] (a priori de politique) ; directives d'évolution du harness",
        "ref": "nexus_brain/adapters/harness_adapter.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("diagnostic", "planification"),
    },
    {
        "id": "adapters.proactive_adapter",
        "module": "adapters",
        "module_name": "Nexus Brain Adapters — Proactive",
        "function": "NexusProactiveAdapter.estimate()",
        "description": (
            "Implémente ProactivePort : combine WhatEngine (quoi proposer, "
            "avec fréquence adaptative au feedback) et WhenEngine "
            "(réceptivité/timing) en un ProactiveSignal unique."
        ),
        "tag": "brain.bridge",
        "phase": "brain",
        "type": "bridge",
        "io_in": "state_id (str) + context (dict)",
        "io_out": "ProactiveSignal (candidats notés : utilité + réceptivité/timing)",
        "ref": "nexus_brain/adapters/proactive_adapter.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("proactivite",),
    },
    {
        "id": "adapters.codegen_adapter",
        "module": "adapters",
        "module_name": "Nexus Brain Adapters — Codegen",
        "function": "CodegenAdapter.deliver_software()",
        "description": (
            "Mission 1, livrable D3 — pont HTTP vers nexus_compose : "
            "délègue la génération de code réelle à codegen.unified_system "
            "via POST {NEXUS_COMPOSE_API_URL}/api/pipeline/run. C'est ce "
            "nœud dont l'agrégateur (Mission 2, D4) confirme l'existence "
            "et l'accessibilité de sa cible."
        ),
        "tag": "brain.bridge",
        "phase": "brain",
        "type": "bridge",
        "io_in": "instruction (str) + goal_id (optionnel)",
        "io_out": "JSON HTTP (run_id, status, phases…) renvoyé par nexus_compose",
        "ref": "nexus_brain/adapters/codegen_adapter.py",
        "repo": "Nexus_Brain/nexus_brain",
        "virtual": False,
        "subsection": None,
        "capabilities": ("codage",),
    },
)


# ── Accès ────────────────────────────────────────────────────────────────────

def list_nodes() -> list[dict[str, Any]]:
    """Copie défensive de BRAIN_NODES — un appelant qui mute le résultat ne
    doit jamais affecter le registre lui-même (même esprit que
    `ComposabilityGraph.list_nodes()` de nexus_compose, qui renvoie aussi
    une liste neuve à chaque appel plutôt qu'une référence interne)."""
    return [dict(node) for node in BRAIN_NODES]


def get_node(node_id: str) -> Optional[dict[str, Any]]:
    """Retrouve une entrée par id, ou None si absente — utilisé par
    test_brain_registry.py et par l'agrégateur du pont (D4) pour détecter
    une éventuelle collision d'id avec le catalogue nexus_compose."""
    for node in BRAIN_NODES:
        if node["id"] == node_id:
            return dict(node)
    return None
