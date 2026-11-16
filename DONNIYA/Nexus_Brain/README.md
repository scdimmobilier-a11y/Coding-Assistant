# Nexus Brain

Un système **unifié** (pas une pipeline séquentielle) de planification et
d'exécution adaptative : six modules — cinq inspirés de projets open-source,
un ( **Nexus Functor** ) fourni tel quel — qui lisent/écrivent un état
partagé et communiquent via des ports typés (`typing.Protocol`), avec
**Nexus Functor comme hub explicite** de la boucle plan/exécution/proactif.

```
Nexus Core (Leon) ──── objectif ────► Nexus Functor ◄──── PlannerPort ──── Nexus Planner
                                          │  ▲
                                  ExecutorPort │ ProactivePort
                                          ▼  │
                                     Nexus Exec        Nexus Proactive (WHAT + WHEN)
                                          │
                                   FeedbackEvent
                                     ┌────┴────┐
                              boucle rapide   boucle lente
                                 (F2)      (Nexus Harness, HarnessPort)
```

Voir `docs/INVARIANTS.md` pour la liste précise des invariants architecturaux
et comment chacun est concrètement assuré (pas seulement affirmé) dans le
code.

## Nomenclature des modules

| Nom Nexus | Inspiré de / fourni par | Où dans ce dépôt |
|---|---|---|
| **Nexus Core** | Leon 2.0 | `nexus_brain/core/` (implémentation neuve, fidèle au comportement décrit) |
| **Nexus Harness** | Continual Harness | `vendor/nexus_harness/` (source réelle) + `nexus_brain/adapters/harness_adapter.py` |
| **Nexus Planner** | PDDLStream-diverse | `vendor/nexus_planner/` (source réelle, GPLv3, hors-process) + `nexus_brain/adapters/planner_adapter.py` |
| **Nexus Proactive — WHAT** | ProactiveAgent (THUNLP) | `vendor/nexus_proactive_what/` (source réelle) + `nexus_brain/adapters/proactive_adapter.py::WhatEngine` |
| **Nexus Proactive — WHEN** | ProactiveAgent (Leonardo Mariga) | `vendor/nexus_proactive_when/` (source réelle, corrigée — voir plus bas) + `nexus_brain/adapters/proactive_adapter.py::WhenEngine` |
| **Nexus Exec** | OpenFugu / Fugu | `vendor/nexus_exec/` (source réelle) + `nexus_brain/adapters/exec_adapter.py` |
| **Nexus Functor** | Fourni tel quel | `nexus_functor/` — **non modifié**, 21 tests d'origine toujours verts |

## Installation

```bash
# 1. nexus_functor (fourni, dépendance) — pas publié sur PyPI
pip install -e ./nexus_functor

# 2. nexus_brain (ce dépôt) — le bootstrap dans nexus_brain/__init__.py
#    ajoute automatiquement nexus_functor/ et vendor/nexus_exec,
#    vendor/nexus_proactive_when à sys.path dès `import nexus_brain`
pip install -e .

# 3. Backend réel de Nexus Planner (GPLv3, hors-process — voir plus bas)
pip install pyperplan   # ou : pip install -e ".[planner-real]"

# 4. (optionnel) Router neuronal réel de Nexus Exec
pip install -e ".[exec-real]"   # torch + transformers ; sinon HeuristicExecRouter (sans dépendance)
```

## Démarrage rapide

```python
from nexus_functor.types import Objective
from nexus_brain.adapters.planner_adapter import NexusPlannerAdapter
from nexus_brain.adapters.exec_adapter import NexusExecAdapter
from nexus_brain.adapters.harness_adapter import NexusHarnessAdapter
from nexus_brain.adapters.proactive_adapter import NexusProactiveAdapter
from nexus_brain.integration.loop import ObjectiveRunner

runner = ObjectiveRunner(
    planner=NexusPlannerAdapter(),
    executor=NexusExecAdapter(),
    harness=NexusHarnessAdapter(),
    proactive=NexusProactiveAdapter(),
)

objective = Objective(goal_id="demo", description="Ship the feature")
context = {"planning_problem": {
    "init": ["at_start"], "goal": ["task_done"],
    "actions": [
        {"name": "gather_requirements", "precond": ["at_start"], "add": ["requirements_ready"], "del": [], "cost": 1, "expected_reward": 0.3},
        {"name": "write_code", "precond": ["requirements_ready"], "add": ["code_written"], "del": [], "cost": 2, "expected_reward": 0.4},
        {"name": "run_tests", "precond": ["code_written"], "add": ["task_done"], "del": [], "cost": 1, "expected_reward": 0.3},
    ],
}}
runner.add_objective(objective, context)
runner.run_forever(max_ticks=10)
```

Et côté Nexus Core (mode conversationnel, découplé de la boucle serrée) :

```python
from nexus_brain.core.brain import NexusCore
from nexus_brain.core.react import ReactLoop, ReactStep

def planner(goal, ctx): return [ReactStep("s1", "search", {"q": goal})]
def executor(step, ctx): return {"success": True, "output": f"handled {step.args['q']}"}

core = NexusCore(react_loop=ReactLoop(planner, executor))
result = core.handle_turn("find me a good restaurant nearby", {}, mode="smart")
print(result.response)
```

## Structure du dépôt

```
nexus_functor/           fourni, non modifié (21 tests stdlib)
vendor/                  code source réel des 5 projets inspirants
  nexus_exec/              OpenFugu/Fugu — Coordinator (routage multi-tours par rôle)
  nexus_planner/           PDDLStream-diverse (GPLv3) + nexus_brain_bridge.py (pont hors-process)
  nexus_harness/           Continual Harness — HarnessEvolver (référence du mécanisme CRUD)
  nexus_proactive_what/    ProactiveAgent THUNLP — Environment Gym / Reward Model (référence)
  nexus_proactive_when/    ProactiveAgent Leonardo Mariga — Decision Engine / Sleep Calculator (corrigé, voir plus bas)
nexus_brain/
  adapters/                les 4 adaptateurs de port (PlannerPort, ExecutorPort, HarnessPort, ProactivePort)
  core/                    Nexus Core : memory.py, pulse.py, react.py, brain.py
  integration/             loop.py — ObjectiveRunner (boucle bout-en-bout)
tests/                    28 tests : 4×adaptateurs, scénarios requis, Nexus Core, boucle d'intégration
docs/
  INVARIANTS.md            invariants architecturaux, vérifiables
```

## Bugs de vendoring trouvés et corrigés

En intégrant ces 6 modules (comme pour le projet-frère Nexus Assistant),
plusieurs bugs réels ont été trouvés en testant, pas supposés :

1. **`vendor/nexus_proactive_when`** : un remplacement automatique
   "ProactiveAgent" → "Nexus Proactive" avait corrompu `agent.py` et
   `__init__.py` — `class Nexus Proactive:` (espace invalide en Python,
   **erreur de syntaxe**, package totalement inutilisable). Corrigé en
   `NexusProactiveWhen` partout (code *et* documentation).
2. **`nexus_brain/adapters/harness_adapter.py`** (trouvé en testant) :
   `successes.count(repeated_action)` comparait une chaîne à une liste de
   dictionnaires — toujours `0`, la création de sous-agents/compétences ne
   se déclenchait jamais. Corrigé.
3. **`nexus_brain/integration/loop.py`** (trouvé en testant le scénario
   d'escalade) : la détection d'escalade vérifiait `cumulative_deviation`
   *après* l'appel à `step()`, alors que F3 la remet à zéro dans ce même
   appel en cas de switch — la condition n'était donc jamais vraie.
   Corrigé pour *prédire* l'escalade avant `step()` à partir du dernier
   `FeedbackEvent` connu, puis la confirmer via `decision.plan_switched`.
4. **`nexus_brain/integration/loop.py`** (trouvé en testant l'apprentissage) :
   un objectif qui se termine en moins de `slow_loop_batch_size` (5) ticks
   ne poussait jamais son feedback vers Nexus Harness (le lot ne se
   remplissait jamais). Corrigé : `flush_learning()` appelé à la complétion
   de chaque objectif.

## Limites connues, documentées honnêtement

- **Nexus Planner** : le vrai `diverse_from_task` (PDDLStream) a besoin
  d'un Fast Downward compilé (traducteur + binaire C++), non fourni et non
  compilable hors-ligne. `nexus_brain_bridge.py` bascule alors sur
  **pyperplan** (solveur STRIPS réel, aussi GPLv3, isolé au même endroit) —
  testé et fonctionnel (`tests/test_adapters.py`).
- **Nexus Exec** : le vrai `ExecRouter` neuronal a besoin de `torch` +
  `transformers` + un checkpoint entraîné (tête linéaire sur Qwen3-0.6B),
  non fourni. `HeuristicExecRouter` (sans dépendance) préserve exactement
  la même boucle de contrôle (`Coordinator`, réel, non modifié) — seul le
  choix du rôle par tour diffère.
- **Nexus Proactive — WHAT** : le vrai pipeline THUNLP a besoin d'un démon
  ActivityWatch et d'un modèle fine-tuné hébergé en externe.
  `WhatEngine` reproduit le mécanisme (capteur → proposition → scoring →
  boucle accept/reject/ignore) avec des callables interchangeables.
- **Nexus Harness** : le vrai `HarnessEvolver` est couplé à un jeu
  (Pokémon, VLM). La logique CRUD à 4 passes est réimplémentée
  génériquement pour le harness de Nexus Core lui-même.

## Tests

```bash
cd nexus_functor && python3 -m unittest discover -s tests -q   # 21 tests, non modifié
cd ../tests && python3 -m unittest discover -s . -p "test_*.py" -q   # 28 tests
```

Scénarios explicitement requis, tous deux verts :
- `test_escalation_scenario.py` — escalade F2→F3 (`force_release`) déclenchant un **vrai** second appel à `PlannerPort.generate_plans`.
- `test_proactive_gating_scenario.py` — WHAT propose (`utility > 0`), WHEN répond "trop tôt" (réceptivité `0.15 < min_receptivity=0.25`), F1 bloque (`decision.proactive_action is None`) ; cas de contrôle prouvant que le blocage est bien dû à la réceptivité.
