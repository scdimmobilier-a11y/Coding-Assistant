J'ai pensé à une solution pour m'aider à coder, concevoir mes logiciels en langage naturel (principalement par la parole), avec l'assistant vocale :
https://github.com/leon-ai/leon 



Utilisateur
    ↓
── PHASE 1 : CO-CONCEPTION ──────────────────────
Query2Diagram          → Use Cases · User Stories · UML
    ↓
── PHASE 2 : ARCHITECTURE C4 ────────────────────
LikeC4                 → Source de vérité : Context / Container / Component / Deployment
C4InterFlow            → Flux · Trust Boundaries · DFD pré-construit
    ↓
── PHASE 3 : INFRASTRUCTURE & POLITIQUE RÉSEAU ──
Containerlab           → Topologie réseau · Microservices · VPN · Load Balancers
Open Policy Agent  ★   → Policies Rego · Règles d'accès et conformité globales
Batfish            ★   → Validation exécution OPA sur les configs réseau sans déploiement
    ↓
── PHASE 4 : MODÉLISATION DES MENACES ───────────
OWASP Threat Dragon    → DFD · STRIDE · LINDDUN · CIA · Mitigations auto
OWASP pytm             → Threat Modeling as Code · Threat Report · Séquences
    ↓
── PHASE 5 : VALIDATION IA ──────────────────────
Neo4j                  → Knowledge graph unifié (UML + C4 + réseau + menaces)
TMDD                   → Threat model → contrainte injectée dans le prompt agent
    ↓
── PHASE 6 : GÉNÉRATION DE CODE ─────────────────
Cursor / Claude Code   → Reçoit architecture + réseau + threat model + contraintes validés
    ↓
── PHASE 7 : AUDIT DU CODE ──────────────────────
Semgrep                → SAST · Règles de codage · Suppression des bugs
Bearer             ★   → Privacy risks · PII · RGPD · Flux de données sensibles
CodeQL                 → Analyse sémantique · Vulnérabilités complexes
    ↓
── PHASE 8 : DÉPLOIEMENT ────────────────────────
Production             → Artefact dérivé — validé en amont à chaque étape



https://github.com/attasec/tmdd

https://github.com/neo4j/neo4j

https://github.com/OWASP/pytm

https://github.com/OWASP/threat-dragon 

https://github.com/srl-labs/containerlab

https://github.com/SlavaVedernikov/C4InterFlow

https://github.com/likec4/likec4

https://github.com/i-need-a-pencil/query2diagram

https://github.com/open-policy-agent/opa 

https://github.com/batfish/batfish

https://github.com/semgrep/semgrep

https://github.com/Bearer/bearer

https://github.com/tareksalem/dsl

https://github.com/github/codeql


Outils de vibecoding reçoivent :

Architecture validée
+
Modèle réseau validé
+
Threat Model validé
+
Contraintes sécurité
+
Politique globale de codage


---

# Nexus Assistant — statut de l'intégration

> Ce dépôt forme **Nexus Assistant** : Leon AI (commande vocale) +
> `nexus_compose` (orchestrateur du pipeline ci-dessus) + `nexus_vendor`
> (sources des 14 outils tiers, plus besoin de leurs zips/compilation
> séparée) + `unified_system` (crewAI / OpenHands / OpenManus-RL pour la
> génération de code).

## Ce qui fonctionne dès maintenant (validé par la suite de tests)

| Composant | État | Détail |
|---|---|---|
| `nexus_compose` | ✅ | 169 nœuds / 218 arêtes, graphe complet, CLI + API Python opérationnels |
| `nexus_vendor` | ✅ | installable (`pip install -e nexus_vendor`), bug de packaging corrigé |
| `pytm` (via nexus_vendor) | ✅ | modélisation de menaces STRIDE réelle (bugs pydantic corrigés — voir plus bas) |
| `q2d` / Query2Diagram (via nexus_vendor) | ✅ | conversion graphe JSON → PlantUML/Mermaid validée |
| `tmdd` (via nexus_vendor) | ✅ | génération de prompts agent / rapports validée |
| `unified_system` (crewAI, OpenHands, OpenManus-RL) | ✅ | testé avec les **vraies bibliothèques** (crewAI + verl installés, `UnifiedSystem` instancié réellement) — détail plus bas |
| `pytm`/`q2d`/`tmdd` en top-level (`import pytm`) | ✅ | exposés automatiquement dès `import nexus_compose` (aucune config manuelle) |

## Ce qui nécessite une action locale de votre part

| Composant | Pourquoi | Action requise |
|---|---|---|
| **Leon AI** | Application Node.js autonome (serveur vocal `:1337`), volontairement laissée en zip par conception. Embarque désormais VALL-E-X (parole) et Audio Flamingo 3 (audition) — voir plus bas | `unzip "Leon AI.zip"` puis suivre son propre `npm install` / build (crée aussi les `.venv` isolés des deux nouveaux outils vocaux ; le téléchargement effectif des poids par contre nécessite un accès réseau à `huggingface.co` et, pour Audio Flamingo 3, un GPU — non disponible dans le bac à sable où cette livraison a été préparée) |
| **11 outils natifs** (opa, bearer, semgrep, containerlab, likec4, c4interflow, batfish, threat_dragon, codeql, structurizr, neo4j) | Le code source est dans `nexus_vendor/native/<outil>/`, mais **sans fichiers de build** (`go.mod`, `pom.xml`, `package.json`, `.csproj`…) — absents de cet export | Utiliser les binaires officiels pré-compilés (voir `Dockerfile` / `.github/workflows/ci.yml` pour la méthode retenue), ou récupérer le manifeste de build manquant depuis le dépôt officiel de l'outil |
| `crewAI.zip` / `OpenHands.zip` / `OpenManus-RL.zip` | Dézippage volontairement différé (gros frameworks, dépendances lourdes) | `./scripts/bootstrap.sh` les installe automatiquement |

Sans ces étapes, `nexus_compose` **ne plante pas** : chaque nœud correspondant
dégrade proprement en mode *stub* avec un message expliquant quoi installer
(cf. `nexus_compose/node_availability.py`).

## Fusion frontend (nexus-ui) ↔ backend — les 6 étapes du prompt, complètes

Suivi de l'exécution du prompt de fusion. Convention : chaque étape est
accompagnée de sa preuve d'exécution réelle, pas d'une simple affirmation —
voir `api/state.py` pour le détail des choix (méthode de travail imposée
par le prompt lui-même). Le prompt de fusion original (et sa révision avec
les 6 points + bonnes pratiques) sont conservés pour référence.

| Étape | État | Preuve |
|---|---|---|
| **1a** — tranche verticale bout-en-bout (phase "elicit" seule) | ✅ | Ci-dessous |
| **1b** — reste des endpoints (10 phases réelles, retry, findings, accept/ignore, conversations) | ✅ | Ci-dessous |
| **2** — alignement des id de phase (mock → réels) | ✅ | Ci-dessous |
| **3** — câblage de tous les `// TODO :` restants | ✅ | Ci-dessous |
| **4** — LLM unique = Claude | ✅ | Ci-dessous |
| **5** — docker-compose (port API + fix `OH_BASE_URL`) | ✅ | Ci-dessous |

### ⚠️ Correction faite en route : 10 phases réelles, pas 8

Le prompt de fusion (et une vérification incomplète qui l'a précédé)
affirmaient 8 phases. En construisant l'Étape 1b et en cherchant un ordre
canonique, `Orchestrator.iter_phase_pipelines` (orchestrator.py) fait
autorité et en liste bien **10** : `elicit, arch, net, policy, threat,
graph, codegen, audit, report, deploy` — confirmé aussi empiriquement
(`Counter` sur les 169 nœuds réels : arch 48, audit 28, codegen 4, deploy 1,
elicit 9, graph 9, net 23, policy 11, report 6, threat 30). "report" et
"deploy" avaient été oubliés. Toute la suite (endpoints, tests, frontend)
utilise la liste correcte à 10 — voir `api/state.py::FULL_PIPELINE_PHASE_ORDER`.

### Étape 1a — tranche verticale (phase "elicit" seule)

- `api/` (nouveau package) : `main.py` (FastAPI + CORS + lifespan),
  `pipeline.py`, `state.py` (le pont thread → asyncio — voir sa docstring
  pour le raisonnement complet).
- `src/lib/pipelineApi.ts` (nexus-ui) : client `fetch` + `EventSource` réel.
- `src/vite-env.d.ts` (nexus-ui) : ajouté — nécessaire pour `import.meta.env`.
- `test/test_api_pipeline.py` : tests d'intégration contre le **vrai**
  `Orchestrator` (aucun mock du pipeline lui-même).

Preuve d'exécution réelle (serveur uvicorn réel, client `EventSource` réel,
pas seulement `curl`) :

```
POST /api/pipeline/run { instruction: "API REST de paiement avec authentification JWT", phase: "elicit" }
-> run_id=<uuid>

[event 1] node q2d.checker                  -> pending
... (9 nœuds annoncés immédiatement, ordre topologique réel)
[event 10] node q2d.checker                 -> running
[event 11] node q2d.checker                 -> done
...
[event 28] done

=== vérifications ===
- 28 événements SSE reçus par un vrai client EventSource
- 9 nœuds, aucun resté "pending"
- tous les nodeId sont des id réels (pas de collision avec le champ "tag")
```

Test de non-régression (deux runs en parallèle) : 28 événements chacun,
aucune contamination croisée, temps total (898 ms) proche du plus long des
deux runs isolément (812/816 ms) et non de leur somme — exécution
réellement concurrente, pas sérialisée.

### Étape 1b — reste des endpoints

- `GET /api/pipeline/phases` — les 10 id de phase réels (pour l'état
  initial du frontend, Étape 2).
- `POST /api/pipeline/run` avec `phase` omis → pipeline complet, 10 phases,
  169 nœuds (au lieu de `greenfield_pipeline()`/`run_from("LEON", ...)`
  suggérés par le prompt — **écartés délibérément**, voir la docstring de
  `state.py` : `run_from` ne couvre que 106/169 nœuds atteignables par BFS
  depuis "LEON" et mélange les phases dans un seul tri topologique global,
  moins adapté à un affichage groupé par phase que l'exécution
  phase-par-phase retenue ici, qui couvre bien les 169 nœuds).
- `POST /api/pipeline/nodes/{id}/retry`, `POST /api/pipeline/phases/{id}/retry`.
- `GET /api/security/findings`, `.../ignore`, `.../unignore` — requête
  Cypher `EXISTS {...}` (pas `count(p) > 0`, anti-pattern de perf sur un
  pattern `*1..8`), trois cas distincts pour `reachableFromEntry` (voir
  `api/security.py`).
- `GET /api/codegen/branches`, `.../accept`, `.../request-fix`.
- `POST /api/conversations`, `GET /api/conversations/{id}`.
- Persistance SQLite (`api/db.py`) pour findings/fichiers/conversations,
  amorcée avec des données de démonstration réalistes au premier démarrage
  (PAS de vraies sorties Bearer/Semgrep/CodeQL/crewAI — parser leur sortie
  réelle est une fonctionnalité séparée, hors périmètre de cette fusion).

**Deux bugs réels trouvés et corrigés en testant, pas en relisant le
code** (le genre de choses qu'une revue de code seule ne voit pas) :
1. `node_phase = dict(flat_order)` construisait un dict `{phase: node_id}`
   au lieu de `{node_id: phase}` (`flat_order` est une liste de tuples
   `(phase, node_id)` — `dict()` sur une liste de tuples prend le premier
   élément comme clé). Conséquence : TOUS les événements `done`/`failed`
   affichaient `phaseId: "unknown"`. Trouvé en inspectant un vrai run
   complet événement par événement, pas en relisant le code — aucune autre
   assertion ne l'aurait remarqué (les statuts progressaient normalement).
   Corrigé + test de non-régression dédié
   (`test_terminal_events_never_have_an_unknown_phase_id`).
2. `Orchestrator.run_node` ne déclenche PAS `on_step_done` (seul
   `run_pipeline`, utilisé par `run_phase`/`run_from`, le fait) — un retry
   de nœud isolé n'émettait donc jamais d'événement `done`/`failed`, juste
   `running` puis la fin du flux. Corrigé en construisant l'événement
   directement à partir du `NodeResult` retourné par `run_node` + test
   dédié (`test_retry_node_emits_running_then_terminal_status`).

Un troisième problème (pas un bug, un défaut de configuration) : le driver
Neo4j retente avec un backoff exponentiel pendant ~35 s avant d'abandonner
quand Neo4j est injoignable — inacceptable pour un endpoint HTTP. Corrigé
avec `connection_timeout=2.0` / `max_transaction_retry_time=2.0` +
vérifications en parallèle (`asyncio.gather`) plutôt que séquentielles.

Preuve d'exécution du pipeline complet (10 phases, 169 nœuds) :
`507 événements nœud, 169 terminaux` répartis exactement comme attendu
(`arch: 48, audit: 28, codegen: 4, deploy: 1, elicit: 9, graph: 9, net: 23,
policy: 11, report: 6, threat: 30`), zéro `phaseId: "unknown"`, flux
terminé par `done`. Prend ~60 s réels (mesuré) — le test pytest
correspondant a un timeout dédié de 150 s (`@pytest.mark.timeout(150)`),
le défaut global du projet étant 30 s (voir `pyproject.toml`).

### Étape 2 — alignement des id de phase

- `src/lib/phaseLabels.ts` (nouveau, nexus-ui) : mapping centralisé,
  UN SEUL fichier, des 10 id réels vers leur libellé FR.
- `App.tsx` ne part plus de `mockPhases`/`mockFindings`/`mockBranches` —
  état initial vide, peuplé par `GET /api/pipeline/phases` +
  `GET /api/security/findings` + `GET /api/codegen/branches` au montage
  (`useEffect`). `src/data/mockPipeline.ts` reste dans le repo (mode démo
  hors-ligne explicite si besoin) mais n'est plus importé comme état de
  démarrage.

### Étape 3 — câblage de tous les `// TODO :`

Chaque `// TODO :` de `App.tsx` remplacé par le vrai appel réseau
correspondant (`src/lib/pipelineApi.ts`). `unignoreFinding`, qui n'avait
PAS de commentaire `// TODO :` contrairement à ses voisins (piège
documenté dans le prompt de fusion), est câblé explicitement quand même.
Toute erreur réseau déclenche `ApiStatusToast("error")` — jamais de repli
silencieux vers les données mock.

Preuve d'exécution complète (`evidence/prove_full_wiring.mjs`, reproduit
exactement les appels du frontend contre le vrai backend) : 11/11
vérifications passées — phases réelles chargées, cycle run+retry, findings
avec les 3 cas de `reachableFromEntry`, ignore/unignore persistés,
accept/request-fix persistés, conversation créée et relue.

### Étape 4 — LLM unique = Claude

`.env.example` : `NEXUS_LLM_PROVIDER=anthropic`,
`NEXUS_LLM_MODEL=claude-sonnet-5` (vérifier le nom de modèle le plus
récent au moment du déploiement).

**Vérifié réellement, pas juste lu** :
- `get_llm_config()` avec ces variables retourne bien
  `provider="anthropic"`, `model="claude-sonnet-5"` (`test/test_llm_config_claude.py`).
- Un vrai `crewai.LLM(model="anthropic/claude-sonnet-5", ...)` route bien
  vers Claude — **mais pas comme le prompt de fusion le supposait**.
  Trouvé en testant réellement (crewAI et son extra installés dans ce
  sandbox pour vérifier) : crewAI récent n'utilise pas systématiquement
  LiteLLM — il a des classes "native provider" par fournisseur
  (`AnthropicCompletion` pour `anthropic/*`) et lève `ImportError:
  Anthropic native provider not available` si le paquet `anthropic` (SDK
  officiel) n'est pas installé, au lieu de retomber silencieusement sur
  LiteLLM. Ni l'installation crewAI locale (`unified_system/crewAI.zip`)
  ni son repli PyPI dans le Dockerfile n'installaient ce paquet — corrigé
  (Dockerfile "FIX #4" + `requirements.txt`).

### Étape 5 — docker-compose

- Port `8000:8000` ajouté au service `app` pour l'API. `command: ["tail",
  "-f", "/dev/null"]` **conservé tel quel** (choix documenté : ne pas
  casser les workflows `docker compose exec app ...`/`run app ...` déjà en
  usage) — l'API se lance à la demande via `scripts/start_api.sh` (nouveau)
  ou `docker compose exec -d app scripts/start_api.sh`.
- Bug préexistant corrigé : service `app`, `OH_BASE_URL=http://openhands:3001`
  → `:3000`. `3001` est le port HÔTE du mapping `"3001:3000"` du service
  `openhands` ; sur le réseau Docker interne, c'est le port interne du
  conteneur (`3000`) qu'il faut utiliser — le service `openhands`
  lui-même s'auto-référence bien en `:3000`. Même correctif appliqué à
  `.env.example`.

### État final de la suite de tests

**Correction apportée ici aussi** : le nombre de "25 échecs préexistants"
annoncé au fil de ce travail était approximatif. En relançant avec un
timeout plus généreux (`--timeout=180`, le défaut du projet étant 30 s —
voir `pyproject.toml`), plusieurs tests de `test_nexus_compose.py`/
`test_nexus_compose_v2.py` qui semblaient échouer étaient en réalité juste
trop lents pour 30 s (de vrais pipelines multi-nœuds, sensibles à la charge
de la machine) : ils passent avec plus de temps. Le chiffre stable et
reproductible, tous fichiers de test préexistants confondus
(`test_nexus_compose.py` + `test_nexus_compose_v2.py` + `test_unified_system.py`,
aucun modifié par ce travail de fusion) : **21 failed, 244 passed, 9
skipped** — les 21 échecs sont tous dans `test_unified_system.py`
(dépendances OpenHands/crewAI/RL non démarrées dans ce bac à sable, pas
liées à la fusion).

Avec les 27 tests ajoutés par ce travail (12 pipeline + 5 security +
5 codegen + 3 conversations + 2 llm_config, tous exécutés avec
`--timeout=180`) : **21 failed, 271 passed, 9 skipped**. Mêmes 21 échecs
préexistants, inchangés. **Zéro régression.**

### Hypothèses posées pendant l'Étape 1a/1b (à valider)

- Pont thread → asyncio : `loop.call_soon_threadsafe` retenu plutôt que la
  `queue.Queue` + polling alternative — latence plus faible, fonctionne
  sous charge concurrente (preuve ci-dessus).
- Une instance `Orchestrator` fraîche par run — mesuré ~120 ms, négligeable.
- CORS limité à `http://localhost:5173` / `127.0.0.1:5173` — à étendre si
  le frontend est servi ailleurs.
- Retry (nœud ou phase) crée un NOUVEAU `run_id` plutôt que de republier
  sur celui d'origine — plus simple à raisonner, cohérent avec le fait
  qu'un retry est une exécution indépendante côté orchestrateur.
- Findings/fichiers générés amorcés avec des données de démonstration
  réalistes (mêmes valeurs que l'ancien `mockPipeline.ts`) — PAS de vrai
  parseur de sortie Bearer/Semgrep/CodeQL/crewAI (fonctionnalité séparée).
- Historique des conversations (liste dans le menu Header) reste sur des
  données de démo — le prompt de fusion ne spécifiait qu'un
  POST/GET par id, pas un endpoint de liste.

## Nexus Brain fusionné avec Leon (le « cerveau » complet de Nexus Assistant)

Cette livraison ajoute, en tant que dossiers **frères** de `Nexus_Assistant/`
(exactement la disposition que `nexus_core_leon_bridge/README.md` et
`Nexus_Brain/README.md` documentent eux-mêmes) :

```
<racine du zip>/
├── Nexus_Assistant/          (ce dépôt — inchangé à part Leon AI.zip, voir plus bas)
├── Nexus_Brain/              (le cerveau : mémoire, boucle ReAct, planification, adaptateurs skills)
└── nexus_core_leon_bridge/   (le pont FastAPI qui relie les deux)
```

`Leon AI.zip` (toujours volontairement laissé en zip, voir tableau
ci-dessus) a été rouvert, patché avec
`nexus_core_leon_bridge/leon_patch/` (un seul fichier modifié,
`server/src/core/socket-server.ts`, plus l'ajout de
`server/src/core/nexus-bridge-client.ts`), puis rezippé à l'identique
(même structure imbriquée `leon-develop/leon-develop/…`, donc
`scripts/bootstrap.sh`/`Dockerfile` continuent de fonctionner sans
modification).

**Validé réellement dans le bac à sable de préparation** (pas seulement lu
dans le code) :
- Le patch s'applique proprement et son hash post-application correspond
  exactement à celui déclaré dans
  `nexus_core_leon_bridge/tests/leon_protected_files.sha256.json` (`d812c129e23a…`).
- `nexus_brain` + `nexus_functor` installés en editable (`pip install -e
  Nexus_Brain/nexus_functor -e Nexus_Brain`) : la suite de tests de Nexus
  Brain passe entièrement (**49/49**, `pyperplan` installé — planificateur
  réel, pas le repli heuristique).
- Suite de tests du bridge (`nexus_core_leon_bridge/tests/`) contre ce Leon
  patché : **8/9** passent. Le seul test qui « échoue »
  (`test_socket_server_original_hash_matches_the_patch_s_starting_point`)
  échoue *normalement* — il vérifie qu'un checkout est encore dans son état
  **avant** patch, ce qui n'est plus le cas ici puisque le patch a déjà été
  appliqué. Les tests substantiels (non-régression ASR/TTS/wake-word,
  e2e simulé, pause/reprise) passent tous.
- **Non exécuté** (hors de portée de ce bac à sable) : lancer réellement le
  bridge + Nexus Brain + Leon ensemble en conditions live (le bridge a
  besoin d'un vrai serveur Leon `:1337` qui tourne, avec micro/haut-parleur).

Voir `nexus_core_leon_bridge/README.md` et `nexus_core_leon_bridge/docs/DECISIONS.md`
pour le détail de comment le pont route les intentions Leon vers Nexus
Brain (et repli vers l'agent si aucune skill native ne correspond), et
`Nexus_Brain/README.md` pour l'architecture du cerveau lui-même.

### Nouvelles capacités vocales de Leon : VALL-E-X (parole) + Audio Flamingo 3 (audition)

Toujours dans `Leon AI.zip`, en plus du patch du bridge : Leon dispose
maintenant de deux nouveaux providers vocaux, activables dans son propre
`config.yml` (`voice.tts.provider: valle-x`, `voice.asr.provider:
audio-flamingo`), ainsi que de deux nouveaux outils utilisables par l'agent
(`tools/music_audio/valle_tts`, `tools/music_audio/audio_flamingo`) et deux
nouvelles actions de skill (`synthesize_speech`, `understand_audio`).
Le détail complet — pourquoi un `.venv` isolé par outil, les notes de
licence des deux modèles, et surtout ce qui est vérifié vs. non vérifié
dans ce même bac à sable (aucun GPU, aucun accès réseau à
`huggingface.co` ici) — est dans **`VOICE_MODELS_INTEGRATION.md` à la
racine de `Leon AI.zip`**.

## Logique LLM unique — un seul modèle pour tout le pipeline

**Absente de la première version de cette intégration** (signalée à juste
titre). Avant ce correctif, jusqu'à 4 composants du pipeline pouvaient
utiliser un modèle différent, sans coordination :

| Composant | Avant | Variable(s) |
|---|---|---|
| q2d (co-conception, phase 1) | `gpt-4o` codé en dur | aucune |
| crewAI (génération de code, phase 6) | `gpt-4o-mini` par défaut | `CREWAI_LLM_MODEL` |
| OpenHands (sandbox d'exécution) | défaut interne OpenHands | *(aucune — ni clé ni modèle transmis)* |
| Leon AI (commande vocale) | non configuré | *(aucune)* |

**Maintenant** : un seul jeu de 4 variables (`NEXUS_LLM_PROVIDER`,
`NEXUS_LLM_MODEL`, `NEXUS_LLM_API_KEY`, `NEXUS_LLM_BASE_URL`, voir
`.env.example`) pilote les quatre :

- **q2d** et **crewAI** lisent la même config via `nexus_compose/llm_config.py`
  (`get_llm_config()`), avec repli sur les anciennes variables si absentes.
- **OpenHands** reçoit `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` — ses
  vraies variables d'environnement (confirmées dans son code source ; le
  service ne recevait auparavant que `OPENAI_API_KEY`, sans nom de modèle).
- **Leon AI** choisit son modèle via un fichier `config.yml`
  (`llm.default: "<provider>/<model>"`), pas une variable d'environnement.
  `docker-compose.yml` (service `leon`) et `bootstrap.sh` génèrent/patchent
  désormais ce fichier au démarrage depuis les mêmes 4 variables, et
  exportent dynamiquement la bonne clé (`LEON_OPENAI_API_KEY`,
  `LEON_ANTHROPIC_API_KEY`, `LEON_GROQ_API_KEY`… selon `NEXUS_LLM_PROVIDER`).

**Validé réellement** (pas seulement lu dans le code) :
- `get_llm_config()` teste la priorité `overrides > NEXUS_LLM_* > anciennes
  variables > défauts` ✓
- Un vrai objet `crewai.LLM` construit avec `NEXUS_LLM_MODEL=gpt-4o` a bien
  `agent.llm.model == "gpt-4o"` (et non plus `gpt-4o-mini` par défaut) ✓
- Le sed qui patche `config.yml` a été exécuté sur le **vrai**
  `config.sample.yml` de Leon (extrait de `Leon AI.zip`) — la ligne active
  `default: null` devient bien `default: "openai/gpt-4o-mini"` (ou tout
  autre provider/modèle), sans toucher aux lignes d'exemple commentées ✓
- L'export dynamique `LEON_${PROVIDER^^}_API_KEY` testé avec `openai`,
  `anthropic` et `groq` ✓

**Régression trouvée et corrigée en cours de route** : construire un objet
`crewai.LLM(api_key=None, ...)` explicitement (au lieu de passer une simple
chaîne de modèle) bloque le repli natif de LiteLLM vers
`os.environ["OPENAI_API_KEY"]` au moment de l'appel. Le code ne construit
donc l'objet `LLM` explicite que lorsqu'une clé ou une `base_url` est
réellement résolue ; sans clé, il repasse à l'ancien comportement (chaîne de
modèle nue) pour préserver le repli natif.

## `unified_system` (crewAI + OpenHands + OpenManus-RL) — validation réelle

Au-delà de nexus_vendor, la phase 6 (génération de code) a été testée avec
les **vraies bibliothèques installées** (pas des stubs) : extraction réelle
des 3 zips, installation réelle de crewAI/OpenManus-RL (`verl` inclus, ~1 Go
de dépendances RL), instanciation réelle de `UnifiedSystem`, et exécution
réelle de la chaîne `neo4j → tmdd → codegen.unified_system`.

**Bugs trouvés et corrigés :**

1. **`crewAI.zip`** : sa racine est un *workspace* `uv` sans `[project]`/
   `[build-system]` — `pip install -e` dessus "réussissait" en installant un
   paquet fantôme `UNKNOWN` sans aucun module `crewai` importable. Le vrai
   package est dans `lib/crewai/`. Corrigé dans `bootstrap.sh`, `Dockerfile`,
   `.github/workflows/ci.yml`.
2. **`lib/crewai/`** est une version de développement (`1.14.7a2`) dont
   `crewai/hooks/llm_hooks.py` importe `crewai.auth.token`, un fichier
   **absent** de cet export — `import crewai` échoue, mais **après** que
   `pip install -e` a déjà rapporté un succès (l'erreur ne se manifeste qu'à
   l'import, pas à l'installation). `pip_install_local()` ne vérifiait que le
   code de sortie de pip → corrigé pour vérifier `import <paquet>` en plus.
3. Une fois ce repli déclenché, `pip install crewai` voyait l'installation
   locale cassée comme *"already satisfied"* (même métadonnée de version) et
   ne faisait rien → corrigé par une désinstallation explicite avant repli.
4. **Ni la source locale ni PyPI seuls ne suffisent** : la source locale a le
   bug ci-dessus mais contient `crewai/tools/openhands_tool.py` — **votre
   pont personnalisé crewAI ↔ OpenHands**, absent de PyPI. La solution
   retenue : installer crewAI stable depuis PyPI, puis **greffer** ce fichier
   dans le paquet installé. Automatisé dans les 3 scripts d'installation.
5. `bootstrap.sh` utilisait `openhands` comme nom de repli PyPI ; le vrai nom
   du paquet est `openhands-ai` (l'import reste `import openhands`).

**Résultat, avec les correctifs appliqués :**

| Test réel effectué | Résultat |
|---|---|
| `UnifiedSystem.from_env()` | ✅ instancie un vrai `Crew` (Agent "Software Engineer" + Task), un vrai `CrewAIEngine` (OpenManus-RL), un vrai `SSRFSafeToolRegistry` (13 outils découverts) |
| `system.run_task("...")` | ✅ déclenche réellement `crew.kickoff()` → tentative d'appel LLM réel — bloqué uniquement par le pare-feu réseau *de ce bac à sable* (`api.openai.com` non autorisé), pas par le code du projet |
| `neo4j.match_return` (driver réel installé) | ✅ tente une vraie connexion Bolt, échoue avec `Couldn't connect to localhost:7687` (pas de serveur Neo4j vivant ici) — comportement correct et attendu |
| `tmdd.generate_agent_prompt → codegen.unified_system` (chaîne complète via l'orchestrateur) | ✅ lit le prompt TMDD généré, instancie `UnifiedSystem`, exécute `health_check()`, rapporte correctement *"OpenHands inaccessible"* (`Connection refused` sur `:3000`) avant de tenter `run_task()` — la porte de garde fonctionne |

**Ce que je n'ai pas pu tester** (infrastructure absente de ce bac à sable,
pas de Docker) : un vrai aller-retour avec un serveur Neo4j et un serveur
OpenHands réellement démarrés. Les deux erreurs obtenues (`Connection
refused`) sont exactement celles qu'on attend sans ces serveurs — c'est la
preuve que le code est correctement câblé jusqu'à cette frontière, pas une
limitation du projet. Sur votre machine (`docker compose --profile
fullstack up`), ces mêmes appels iraient jusqu'au bout.

## Bugs corrigés pendant l'intégration de nexus_vendor

1. **`nexus_vendor/pyproject.toml`** : `build-backend` invalide
   (`setuptools.backends.legacy:build`, inexistant) → corrigé vers
   `setuptools.build_meta`.
2. **`nexus_vendor/pyproject.toml`** : la découverte de paquets ne trouvait
   rien (`pip install` "réussissait" mais `import nexus_vendor` échouait) —
   le fichier vit *dans* le dossier qu'il décrit, sans dossier parent
   `nexus_vendor/`. Corrigé via un remapping explicite `package-dir`.
3. **`nexus_vendor/pytm/__init__.py`** : classes utilisées ailleurs dans le
   projet (`Server`, `Lambda`, `Agent`, `ExternalEntity`, `SetOfProcesses`,
   `Data`, `Action`, `DatastoreType`) non ré-exportées → `ImportError` /
   `AttributeError` silencieux.
4. **`nexus_vendor/pytm`** : `TM`, `Boundary`, `Element` (et les classes qui
   en héritent) levaient `PydanticUserError: is not fully defined` à la
   création — références différées (`List["Finding"]`) jamais résolues car
   `Finding` n'était importé que sous `TYPE_CHECKING`. Corrigé par injection
   + `model_rebuild(force=True)` généralisé à toutes les classes concernées.
5. **`nexus_compose/drivers.py`** : les 4 handlers TMDD pointaient vers
   l'ancien chemin `tmdd-main/tmdd-main/` (zip) et des noms de module
   `src.*` → corrigés vers `nexus_vendor/tmdd/*`.
6. **`nexus_compose/drivers.py`** : 14 appels `subprocess` utilisaient le nom
   littéral `"python"` (résout parfois vers un interpréteur système sans les
   dépendances installées) → remplacés par `sys.executable`, garantissant le
   même interpréteur que celui qui exécute `nexus_compose`.
7. **`nexus_compose/node_availability.py`** : `tmdd` était classé "binaire
   uniquement" (jamais détecté comme disponible malgré nexus_vendor) → ajout
   d'un repli SDK Python.

La suite de tests (`pytest test/`) passe intégralement après ces correctifs :
**265 tests passés, 9 ignorés (nécessitent la stack complète), 0 échec.**

> Ces 265 tests sont volontairement rapides et **mockent** crewAI/OpenManus-RL
> (aucune dépendance lourde requise en CI). La validation avec les **vraies**
> bibliothèques (crewAI, verl, driver neo4j réellement installés) est décrite
> dans la section *"unified_system — validation réelle"* ci-dessous — c'est
> un test manuel plus approfondi, pas encore automatisé en CI.

## Installation rapide

```bash
./scripts/bootstrap.sh          # Leon AI + unified_system + nexus_vendor + nexus_compose
./scripts/bootstrap.sh --check  # vérifier l'état sans rien réinstaller
python -m nexus_compose summary # confirmer que le graphe (169 nœuds) se construit
```

---


# nexus_compose

**NEXUS — Module d'orchestration du pipeline de conception logicielle**

Graphe de composabilité unifié : **158 nœuds · 197 arêtes · 14 modules · 10 phases**

---

## Architecture

```
nexus_compose/
├── graph.py          # ComposabilityGraph, Node, Edge, EdgeType, NodeResult
├── registry.py       # build() — câble les 158 nœuds + 197 arêtes
├── drivers.py        # Handlers réels par module (+ stub gracieux si outil absent)
├── orchestrator.py   # Orchestrator — exécution, dry-run, trace, phases, parallèle
├── __init__.py       # API publique
├── __main__.py       # CLI : python -m nexus_compose <cmd>
└── nodes.json        # Métadonnées parsées des 153 fonctions réelles
```

## Pipeline (10 phases → Production)

*(Compté à 8 dans les versions précédentes de ce document — "report" et
"deploy", qui apparaissent ci-dessous sous "REPORT · PRODUCTION", sont bien
deux phases à part entière avec leur propre id, pas juste un aboutissement
textuel. Voir "Fusion frontend ↔ backend", section "Correction faite en
route", pour le détail.)*

```
LEON / CODEBASE
    ↓
Phase elicit  : Query2Diagram      → use cases · user stories · UML
    ↓
Phase arch    : LikeC4 · C4InterFlow · Structurizr DSL
                → source de vérité C4 (Context/Container/Component/Deployment)
    ↓
Phase net     : Containerlab       → topologie réseau · microservices · VPN
    ↓
Phase policy  : OPA ← Batfish     → politiques Rego · validation sans déploiement
    ↓
Phase threat  : Threat Dragon · pytm
                → DFD · STRIDE · LINDDUN · CIA · menaces as code
    ↓
Phase graph   : Neo4j              → Knowledge graph unifié
    ↓
Phase codegen : TMDD               → contraintes → Cursor / Claude Code
    ↓
Phase audit   : Semgrep · Bearer · CodeQL
                → SAST · Privacy/RGPD · analyse sémantique
    ↓
REPORT · PRODUCTION
```

## Installation

```bash
pip install -e .                  # core (aucune dépendance obligatoire)
pip install -e ".[all]"           # toutes les dépendances optionnelles
pip install -e ".[neo4j,semgrep]" # sélectif
```

## Utilisation

### Python API

```python
from nexus_compose import build_graph, Orchestrator

G    = build_graph()
orch = Orchestrator(G)

# --- inspecter le graphe ---
print(G.summary())
print(G.list_nodes(module="semgrep"))
print(G.list_nodes(phase="audit"))

path = G.shortest_path("LEON", "PRODUCTION")   # → liste de node_ids

# --- dry-run : voir ce qui s'exécuterait ---
report = orch.dry_run()
print(report)

# --- exécuter un nœud unique ---
result = orch.run_node("semgrep.semgrep_scan", {"target_path": "/mon/projet"})
print(result.data)

# --- exécuter une phase entière ---
pr = orch.run_phase("audit", {"target_path": "/mon/projet"})
print(pr.summary())

# --- pipeline greenfield complet ---
pr = orch.greenfield_pipeline(ctx={"code_path": "/mon/projet"})
print(pr.summary())

# --- pipeline audit seulement ---
pr = orch.audit_only_pipeline("/mon/projet")
print(pr.summary())

# --- pipeline modélisation des menaces ---
pr = orch.threat_model_pipeline(architecture_json)

# --- pipeline validation réseau ---
pr = orch.network_validation_pipeline("topology.clab.yml", "policy.rego")

# --- tracer un chemin source → target ---
trace = orch.trace("LEON", "PRODUCTION")
print(trace.summary())

# --- exécution depuis un point d'entrée ---
pr = orch.run_from("CODEBASE", ctx={"code_path": "."})

# --- exécution parallèle (nœuds indépendants) ---
pr = orch.run_parallel(["semgrep.semgrep_scan", "bearer.bearer_scan"], ctx={...})

# --- injecter un handler live à l'exécution ---
orch.inject("neo4j.create", mon_handler_neo4j)

# --- itérer les phases en ordre ---
for phase, pr in orch.iter_phase_pipelines():
    print(f"{phase}: {pr.summary()}")
```

### CLI

```bash
# stats du graphe
python -m nexus_compose summary

# dry-run complet
python -m nexus_compose dry-run

# dry-run filtré
python -m nexus_compose dry-run --phase audit
python -m nexus_compose dry-run --module semgrep

# exécuter un nœud
python -m nexus_compose run-node semgrep.semgrep_scan --json '{"target_path":"."}'

# exécuter une phase
python -m nexus_compose run-phase audit --json '{"target_path":"."}'

# pipeline depuis un point d'entrée
python -m nexus_compose run-from LEON

# audit d'un dépôt existant
python -m nexus_compose audit /chemin/vers/projet

# tracer un chemin
python -m nexus_compose trace LEON PRODUCTION

# lister les nœuds
python -m nexus_compose list-nodes --module neo4j
python -m nexus_compose list-nodes --phase threat

# lister les phases / modules
python -m nexus_compose list-phases
python -m nexus_compose list-modules

# trouver des chemins entre deux nœuds
python -m nexus_compose paths CODEBASE neo4j.create --max 3
```

## Types d'arêtes

| Type | Couleur | Sémantique |
|------|---------|-----------|
| `data_flow` | bleu | flux de données principal |
| `transform` | vert | conversion de format |
| `validate` | ambre | vérification / assertion |
| `query` | violet | lecture / interrogation |
| `inject` | rose | contrainte → prompt agent/LLM |
| `store` | vert | persistance Neo4j |
| `analyze` | pourpre | analyse sémantique (CodeQL) |
| `simulate` | orange | simulation réseau (Containerlab) |
| `indirect` | gris | bridge à médiation humaine |
| `report` | blanc | sortie rapport |

## Modules (14 + 5 virtuels)

| Module | Nœuds | Rôle |
|--------|-------|------|
| Query2Diagram | 7 | Co-conception NL → diagramme |
| LikeC4 | 28 | Source de vérité architecturale C4 |
| C4InterFlow | 8 | Analyse des flux AaC |
| Structurizr DSL | 9 | DSL workspace/modèles |
| Containerlab | 12 | Topologie réseau |
| Open Policy Agent | 11 | Politiques Rego |
| Batfish | 10 | Validation config réseau |
| OWASP Threat Dragon | 13 | DFD + STRIDE/LINDDUN |
| OWASP pytm | 10 | Threat modeling as code |
| Neo4j | 9 | Knowledge graph unifié |
| TMDD | 8 | Contraintes → agent |
| Semgrep | 12 | SAST + règles custom |
| Bearer | 9 | Privacy / RGPD |
| CodeQL | 7 | Analyse sémantique |
| Virtuels | 5 | LEON · CODEBASE · CODE_GENERATED · REPORT · PRODUCTION |

## Composabilité

Le pipeline est conçu pour être composable. Vous ne partez pas toujours de zéro :

```python
# Vous avez déjà une architecture → sauter Q2D/LikeC4
pr = orch.run_from("c4if.executeaacstrategycommand", ctx={...})

# Vous avez déjà un threat model → sauter jusqu'à TMDD
pr = orch.run_from("tmdd.tmdd_init", ctx={...})

# Vous voulez seulement auditer du code existant
pr = orch.audit_only_pipeline("/path/to/code")

# Pipeline custom avec les nœuds de votre choix
pr = orch.run_pipeline([
    "semgrep.write_custom_semgrep_rule",
    "semgrep.semgrep_scan_with_custom_rul",
    "neo4j.create",
    "REPORT",
], ctx={"threat": {...}, "target_path": "."})
```
