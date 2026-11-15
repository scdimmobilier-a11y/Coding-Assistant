# Registry schema — le contrat partagé nexus_compose ↔ Nexus Brain

> Mission 2 (Meta Framework / Nexus Studio), livrable D1. Ce document est le
> **seul** endroit de référence pour la forme JSON du registre de nœuds.
> `nexus_compose` (ce dépôt) et `Nexus_Brain` (dépôt séparé, autre conteneur)
> respectent tous les deux ce contrat, mais **sans import Python croisé** —
> chacun le réimplémente dans son propre langage/schéma. Si ce document et le
> code divergent un jour, c'est le code de `nexus_compose/graph.py::NodeMeta`
> qui fait foi pour la structure, et une PR doit mettre à jour ce fichier dans
> le même commit.

## 0. Pourquoi ce document existe

Trois systèmes distincts produisent ou consomment ce JSON, dans trois dépôts
qui ne s'importent jamais les uns les autres (ils tournent dans des
conteneurs séparés — cf. `MISSION_couple_leon_nexusbrain.md` §4/D3) :

| Dépôt                   | Rôle                                                              | Endpoint(s)                              |
|--------------------------|--------------------------------------------------------------------|-------------------------------------------|
| `Nexus_Assistant`        | Source de vérité du graphe pipeline (164 nœuds réels + 5 virtuels) | `GET /api/registry/nodes`, `GET /api/registry/diagnostics` |
| `Nexus_Brain`             | Registre statique de ses propres composants cognitifs (Niveau 1)  | *(pas de serveur HTTP propre — cf. §4)*   |
| `nexus_core_leon_bridge`  | Réexpose le registre Brain + agrège les deux catalogues            | `GET /registry/nodes`, `GET /registry/full` |

Sans ce document, chaque dépôt finirait par inventer sa propre variante du
schéma (un champ renommé, un type légèrement différent) et l'agrégateur (D4)
casserait silencieusement. Ce fichier fixe la forme une bonne fois.

## 1. `NodeMeta` — un nœud du registre

Définition canonique : `nexus_compose/graph.py::NodeMeta` (dataclass Python,
zéro dépendance externe). Tout producteur de registre (nexus_compose,
Nexus_Brain) doit émettre un objet JSON avec exactement ces clés :

| Champ          | Type JSON          | Obligatoire | Description                                                                 |
|-----------------|---------------------|:-----------:|-------------------------------------------------------------------------------|
| `id`            | string              | oui         | Identifiant unique **global** du nœud (cf. §3, namespacing).                 |
| `module`        | string              | oui         | Code court du module/composant (ex. `"q2d"`, `"core"`, `"adapters"`).        |
| `module_name`   | string              | oui         | Nom humain du module (ex. `"Query2Diagram"`, `"Nexus Core"`).                |
| `function`      | string              | oui         | Fonction/méthode/classe concrète exposée (ex. `"generate()"`).               |
| `description`   | string              | oui         | Une phrase : ce que fait le nœud.                                            |
| `tag`           | string              | oui         | `"{phase}.{type}"` — voir §2 pour le vocabulaire de `phase`/`type`.          |
| `phase`         | string              | oui         | Étape du pipeline (`elicit`, `arch`, `net`, `policy`, `threat`, `graph`, `codegen`, `audit`, `report`, `deploy`) **ou** `"brain"` pour les composants Niveau 1 de Nexus Brain, qui sont hors pipeline (cf. §4). |
| `type`          | string              | oui         | Nature de l'opération (`generate`, `transform`, `validate`, `query`, `bridge`, `store`, `analyze`, `simulate`, `export`, `model`, `elicit`, …). Vocabulaire ouvert, mais réutiliser l'existant avant d'en inventer un nouveau. |
| `io_in`         | string              | oui         | Entrée(s), en langage naturel concis.                                        |
| `io_out`        | string              | oui         | Sortie(s), en langage naturel concis.                                        |
| `ref`           | string              | oui         | Chemin de fichier ou point d'entrée du code source réel.                     |
| `repo`          | string              | non (`""`)  | Dépôt/monorepo où vit le code du nœud. **Ne pas inventer** un dépôt externe si le composant est natif à ce monorepo — voir §3.2. |
| `virtual`       | bool                | non (`false`) | `true` pour les nœuds symboliques (`LEON`, `PRODUCTION`, …) qui n'exécutent rien. |
| `subsection`    | string ou `null`    | non (`null`)  | Sous-partie facultative d'un module.                                        |
| `capabilities`  | array de string     | non (`[]`)  | Voir §2.3 — filtre transversal, pas une taxonomie stricte.                   |

Note d'implémentation : côté Python, `capabilities` est un `tuple[str, ...]`
(immuable — c'est un tag de filtrage, pas une structure qu'on modifie nœud
par nœud à l'exécution) ; il se sérialise en tableau JSON standard.

## 2. Vocabulaire des champs à valeurs contrôlées

### 2.1 `EdgeType` (arêtes, pas nœuds — mais fait partie du même contrat)

Définition canonique : `nexus_compose/graph.py::EdgeType`. Une arête est
`{"source": <id>, "target": <id>, "label": <string>, "type": <EdgeType>}`.

| Valeur         | Sens                                              |
|-----------------|----------------------------------------------------|
| `data_flow`     | Flux de données principal du pipeline              |
| `transform`     | Conversion de format                               |
| `validate`      | Vérification / assertion                           |
| `query`         | Lecture / interrogation                            |
| `inject`        | Injection de contrainte dans un agent/LLM           |
| `store`         | Persistance vers un graphe / une base               |
| `indirect`      | Pont médié par un humain                            |
| `report`        | Sortie vers un artefact de rapport                  |
| `simulate`      | Étape de simulation réseau                          |
| `analyze`       | Analyse sémantique profonde                         |

### 2.2 `phase` / `type` / `tag`

`tag` est toujours la concaténation `"{phase}.{type}"` (ex. `"elicit.generate"`,
`"codegen.bridge"`). Les 9 phases du pipeline nexus_compose (`elicit` → `deploy`,
`deploy` n'existe aujourd'hui que sur le nœud virtuel `PRODUCTION`) restent
inchangées par cette mission. **`"brain"` est la seule phase ajoutée** par
D3, réservée aux composants Niveau 1 de Nexus Brain (Functor, Planner,
Executor, Memory, ReAct, Proactive) : ils ne sont pas des étapes d'un
pipeline logiciel, ils tournent en continu, donc les faire rentrer de force
dans une des 9 phases existantes serait trompeur.

### 2.3 `capabilities` — vocabulaire proposé (non figé)

Objectif (cf. document source, §1) : répondre à des questions du type
« quels nœuds font de la planification ? » via
`GET /registry/full?capability=planification`, sans construire un second
objet graphe parallèle — une capacité est juste une étiquette de plus sur
`NodeMeta`, filtrée côté agrégateur (D4).

Vocabulaire de départ (français, pour rester cohérent avec l'exemple du
document source « Vision, Audio, Codage, Planification… ») :

`vision · audio · codage · planification · execution · memoire · securite ·
architecture · reseau · proactivite · diagnostic · dialogue`

Ce n'est **pas** une enum stricte côté code (`capabilities` reste
`tuple[str, ...]` libre) — c'est une convention de nommage documentée ici
pour que les futurs producteurs de nœuds (nexus_compose comme Nexus Brain)
utilisent les mêmes mots plutôt que des synonymes qui casseraient le filtre.

**Statut actuel du champ `capabilities`** (honnête, pas déduit après coup) :
- Les 169 nœuds `nexus_compose` (164 `nodes.json` + 5 virtuels) ont tous
  `capabilities: []` à ce stade. Les catégoriser correctement demanderait
  d'auditer un par un 164 outils tiers réels — un travail légitime mais
  distinct de cette mission, qu'on ne fait pas ici pour ne pas inventer des
  étiquettes non vérifiées. C'est un candidat naturel pour une mission de
  suivi.
- Les nœuds `Nexus_Brain` ajoutés en D3 renseignent `capabilities`, à titre
  d'exemple fonctionnel concret du filtre (cf. `nexus_brain/registry.py`).

## 3. Identifiants — namespacing entre les deux catalogues

### 3.1 Convention

`id = "{module}.{nom_court}"`, module court en minuscules, sans espace.
Exemples déjà en usage :
- `nexus_compose` : `"q2d.generate"`, `"codegen.unified_system"`, `"LEON"` (virtuel, pas de point — les 5 nœuds virtuels dérogent volontairement à la convention `module.nom` car ils ne représentent pas une fonction de module).
- `Nexus_Brain` (D3) : `"core.brain"`, `"core.memory"`, `"nexus_functor.f0"`, `"adapters.planner_adapter"`, …

### 3.2 Pas de collision, par construction — pas par vérification a posteriori

Les préfixes de module utilisés côté `nexus_compose`
(`q2d, bf, c4if, clab, opa, td, tmdd, neo4j, pytm, bearer, codeql, semgrep,
struct, likec4, codegen`) et côté `Nexus_Brain`
(`core, adapters, nexus_functor`) ne se recoupent pas aujourd'hui. L'agrégateur
(D4, `bridge/registry_aggregator.py`) vérifie quand même activement l'absence
de collision d'`id` à chaque fusion (et lève une erreur explicite sinon,
plutôt que d'écraser silencieusement une entrée) — cf. section suivante.

### 3.3 `repo` : ne pas inventer un dépôt externe

Convention observée dans `nodes.json` (ex. nœud `codegen.unified_system` →
`repo: "KELEBA-LAM/Vocale-vibecoding-"`) : `repo` pointe vers le dépôt où vit
**le code du nœud lui-même**, pas vers chaque bibliothèque qu'il enveloppe
éventuellement en interne. Pour les nœuds `Nexus_Brain` (D3), le code est
natif à ce monorepo (pas un fork d'un projet externe) : `repo` vaut donc
`"Nexus_Brain/nexus_brain"` ou `"Nexus_Brain/nexus_functor"` selon le
sous-paquet — jamais un nom d'organisation GitHub inventé.

## 4. Qui expose quoi, concrètement

```
GET /api/registry/nodes            (Nexus_Assistant, D2)
  → { "nodes": [...169 NodeMeta nexus_compose...],
      "edges": [...218 Edge...] }

GET /api/registry/diagnostics      (Nexus_Assistant, D2)
  → { "available": [...], "unavailable": [...], "external": [...],
      "frontend": [...], "saas": [...], "manual": [...] }
  (reexpose NodeAvailabilityChecker.full_report(), un ToolStatus par outil)

GET /registry/nodes                (bridge, D3 — PAS sur Nexus_Brain lui-même :
                                     Nexus Core reste hors de la boucle serrée,
                                     cf. Nexus_Brain/docs/INVARIANTS.md #2)
  → { "nodes": [...14 NodeMeta Nexus Brain...], "edges": [] }
  (Nexus Brain n'a pas d'arêtes internes modélisées ici — Niveau 1 reste du
  raisonnement, pas un graphe de composition, cf. mission §3)

GET /registry/full[?capability=X]  (bridge, D4)
  → { "nodes": [...169 + 14 = 183 NodeMeta fusionnés...],
      "edges": [...218 + 0 = 218 Edge...] }
  (fusion de /api/registry/nodes de nexus_compose, appelé en HTTP — jamais
  en import Python direct — et du registre statique Nexus_Brain ci-dessus ;
  filtre optionnel ?capability= appliqué après fusion)
```

`edges` est toujours un tableau, même vide, dans les trois formes — pour que
l'agrégateur D4 puisse toujours faire `compose["edges"] + brain["edges"]`
sans cas particulier.

## 5. Ce que ce contrat ne couvre pas

- Le raisonnement du Niveau 1 (Functor/Planner/Executor/Memory/ReAct/Proactive)
  reste interne à `Nexus_Brain` ; ce schéma décrit *que ces composants
  existent et ce qu'ils prennent en entrée/sortie*, jamais *comment ils
  décident*.
- L'outillage Niveau 2 (explorateur, diagrammes, refactoring — futur
  "Nexus Studio") consomme ce contrat en lecture seule ; il ne l'étend pas.
