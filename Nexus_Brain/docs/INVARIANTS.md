# Nexus Brain — invariants architecturaux

Ce document liste les invariants que l'implémentation de Nexus Brain
préserve, et **comment** chacun est concrètement assuré dans le code (pas
seulement affirmé). Voir aussi `README.md` pour la vue d'ensemble et le
détail module par module.

## 1. Nexus Planner / Proactive / Exec / Harness ne s'appellent jamais entre eux

Aucun des cinq modules `vendor/nexus_planner`, `vendor/nexus_exec`,
`vendor/nexus_harness`, `vendor/nexus_proactive_what`,
`vendor/nexus_proactive_when` n'importe un autre de ces modules. Chacun ne
communique qu'à travers :

- son adaptateur dans `nexus_brain/adapters/` (qui implémente exactement
  un des 4 `Protocol` de `nexus_functor/interfaces.py` : `PlannerPort`,
  `ExecutorPort`, `HarnessPort`, `ProactivePort`) ;
- **Nexus Functor comme hub explicite** — `nexus_functor.functor.NexusFunctor`,
  fourni tel quel, non modifié. C'est lui qui appelle les 4 ports depuis
  `step()`/`on_feedback()` ; aucun adaptateur n'appelle un autre adaptateur.

Vérifiable directement : `grep -rl "^from nexus_\(planner\|exec\|harness\|proactive" vendor/*/`
ne doit renvoyer que des imports internes à chaque module (jamais un module
vendor important un autre module vendor).

## 2. Nexus Core reste hors de la boucle serrée plan/exécution

`NexusCore` (`nexus_brain/core/brain.py`) ne détient ni `NexusFunctor`, ni
`ExecutionState`, ni aucun des 4 ports. Son unique point de contact est
`pose_objective()`, qui construit un `Objective` et le remet à un callback
`post_objective` fourni par l'appelant (typiquement un
`ObjectiveRunner.add_objective`) — puis **rend la main immédiatement**.
Nexus Core ne boucle jamais sur `functor.step()`/`on_feedback()` lui-même ;
le résultat, quand il arrive, redevient un simple résultat d'outil dans un
futur tour ReAct. Sa mémoire (`LayeredMemory`), son self-model
(`SelfModel`) et son pulse (`PulseManager`) tournent entièrement
indépendamment de tout tick de Functor.

## 3. Isolation de licence — PDDLStream (et pyperplan) restent hors-process

`nexus_brain/adapters/planner_adapter.py` n'importe **jamais**
`nexus_planner` (le seul import est `subprocess`). Le seul fichier autorisé
à importer du code GPLv3 (PDDLStream lui-même, et pyperplan comme moteur de
repli réel — également GPLv3) est `vendor/nexus_planner/nexus_brain_bridge.py`,
invoqué exclusivement via `subprocess.run([sys.executable, bridge_path, ...])`.

Conséquence testable : `grep -rn "import nexus_planner" nexus_brain/` ne doit
renvoyer aucun résultat. C'est vérifié par construction (voir le docstring
de `nexus_brain_bridge.py` pour le détail des 3 paliers de secours :
PDDLStream réel → pyperplan réel → repli sans PDDL).

## 4. Nexus Proactive : WHAT et WHEN restent indépendants jusqu'au `ProactiveSignal`

`nexus_brain/adapters/proactive_adapter.py` contient deux classes,
`WhatEngine` et `WhenEngine`, qui ne se référencent jamais l'une l'autre.
Chacune a sa propre boucle d'apprentissage :

- `WhatEngine.record_feedback(action, "accept"|"reject"|"ignore")` module
  un multiplicateur de fréquence **par type d'action**, indépendant de tout
  signal WHEN.
- `WhenEngine.record_engagement(engaged: bool)` met à jour une moyenne
  mobile d'engagement, indépendante de tout signal WHAT.

`NexusProactiveAdapter.estimate()` les interroge toutes les deux et
retourne un `ProactiveSignal` **sans repondérer, filtrer, ni combiner** —
chaque `ProactiveCandidate` porte `utility` (de WHAT) et `receptivity` (de
WHEN) côte à côte, non fusionnés. La fusion réelle
`J(a,τ) = utility·receptivity − λ·cost` n'existe qu'à un seul endroit :
`nexus_functor/f1_plan_selector.py::score_proactive` — non modifié, fourni
tel quel. Testé explicitement par
`tests/test_proactive_gating_scenario.py`.

## 5. Le mécanisme anti-oscillation de F3 n'est jamais contourné hors `force_release()` légitime

`nexus_brain/adapters/*` n'appellent jamais `force_release()` : ce sont
uniquement `nexus_functor.functor.NexusFunctor.step()` (non modifié) qui
l'invoque, et seulement quand `F2LocalAdapter.adapt()` retourne
`AdaptationAction.ESCALATE`. `nexus_brain/integration/loop.py` ne fait que
**détecter après coup** qu'une escalade a eu lieu (en comparant la dérive
cumulée prédite au seuil `f2.escalate_threshold`, puis en confirmant via
`decision.plan_switched`) pour décider de rappeler le vrai planificateur —
il ne décide jamais lui-même de lever l'hystérésis. Testé explicitement par
`tests/test_escalation_scenario.py`.

## 6. Nexus Exec : routage séquentiel par rôle, jamais fan-out/fan-in

`nexus_brain/adapters/exec_adapter.py` délègue entièrement la boucle
multi-tours au vrai `nexus_exec.mini.Coordinator` (vendored, non modifié) :
un seul worker + un seul rôle par tour, terminaison sur `ACCEPT` du
Verifier / `max_turns` / override `<suggested_role>` du Thinker.
`HeuristicExecRouter` (le seul ajout de Nexus Brain ici) ne fait que
*choisir un rôle par tour* — il ne parallélise, n'agrège, ni n'appelle
plusieurs workers à la fois. Testé par
`tests/test_adapters.py::TestExecutorPortAdapter`.

## 7. `ExecutionState` est détenu par l'appelant, jamais par le Functor

`nexus_functor.NexusFunctor` ne stocke aucun état inter-tick propre à un
objectif (confirmé par son propre `README.md` et son code : `step()` ne
fait que lire/écrire l'`ExecutionState` qu'on lui passe). Dans Nexus Brain,
c'est `nexus_brain/integration/loop.py::ActiveObjective` qui possède
`exec_state`, un par objectif actif, permettant `ObjectiveRunner` de faire
tourner plusieurs objectifs concurrents, chacun avec son propre
`NexusFunctor` + `ExecutionState`. Testé par
`tests/test_integration_loop.py::test_multiple_concurrent_objectives_have_independent_state`.

## 8. Nexus Harness : deux flux de données séparés, un seul module

`nexus_brain/adapters/harness_adapter.py::NexusHarnessAdapter` expose :
- `get_policy_prior` / `record_outcome` (implémente `HarnessPort`, parlé
  uniquement par Nexus Functor F0/boucle lente) ;
- `evolve_harness` (outil appelé directement par Nexus Core, jamais par
  Nexus Functor).

Ces deux flux partagent la même instance (`self._tallies` pour le prior,
`self.evolver` pour le CRUD) mais n'interagissent pas entre eux : recorder
un outcome ne déclenche jamais une évolution du harness, et `evolve_harness`
ne modifie jamais le prior F0.
