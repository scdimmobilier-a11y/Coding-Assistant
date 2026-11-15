# nexus_unified — laboratoire GPU/RL et gouvernance Apex

Ce paquet est l'implémentation des lots 0 à 4 et des 9 exigences du cahier des
charges, par-dessus le pipeline de base `nexus_compose` (169 nœuds, 10 phases).
Il n'altère pas le graphe de base : il s'ajoute en **pack** chargé à part.

Point d'entrée : `nexus_compose.build(("unified",))` — 169 nœuds de base
+ 227 nœuds du pack, reliés par des arêtes typées.

## Correspondance exigences → modules

| # | Exigence | Module |
|---|---|---|
| 1 | GPU tout constructeur (NVIDIA/AMD/Intel/NPU/CDI, puces personnalisées) | `accelerators/discovery.py` |
| 2 | Baux illimités, bornés par les ressources | `accelerators/lease.py` |
| 3 | LLM global, tout fournisseur | `llm/gateway.py` (+ `nexus_compose/llm_config.py`) |
| 4 | Modèle externe à la pipeline | `llm/gateway.py` (endpoint + clé, jamais embarqué) |
| 5 | Orchestrateur maître piloté par requête LLM | `orchestrator.py` |
| 6 | OpenHands fourni dans le système (API V1) | `openhands_client.py` (+ `unified_system/OpenHands`) |
| 7 | Magasins open source (PostgreSQL/SQL/Neo4j/autres) | `store/backends.py` |
| 8 | Apprentissage par succès ET échecs | `learning/loop.py` |
| 9 | Sandbox obligatoire sécurisé + inspection des artefacts | `security/` |

## Phases Apex (gouvernance, point 6)

`apex/` fournit les 8 phases (co-conception → maintenance), le noyau protégé
(ontologie figée par empreinte), l'état partagé persistant et les rôles
Observer / Learner / Actor. `ApexCycle` enveloppe une exécution de
l'orchestrateur et pose les garde-fous d'intégrité, de connaissance et de
récupération.

## Lots

- **Lot 0** — socle réparé : client OpenHands V1 (`openhands_client.py`),
  correctifs du pont (`unified_system/bridge.py`), du routeur RL
  (`rl_agent_router.py`, 5 défauts + auth + magasin open source), de
  l'environnement RL (`env_manager.py`, routes V1 + ancrage par tâche), de
  l'outil crewAI (`openhands_tool.py`, V1) ; échec explicite + contexte
  cloisonné + `run_loop` borné dans le moteur (`nexus_compose`).
- **Lot 1** — exécution et GPU : phase `exec`, découverte multi-constructeur,
  baux, correctif GPU + durcissement du sandbox OpenHands
  (`docker_sandbox_service.py`, `SANDBOX_GPU_ENABLED` / `SANDBOX_HARDENING`).
- **Lot 2** — pack de 227 nœuds (`pack/`) avec capacités, phase Apex,
  ressources ; arêtes typées `execute`/`reward`/`update`/`lease`.
- **Lot 3** — entraînement/évaluation/service (`training/`) : `TrainingService`,
  `ModelRegistry` (promotion gardée, GA5), `VLLMManager`.
- **Lot 4** — apprentissage (`learning/`) : trajectoires succès/échec séparées,
  banque de compétences, distillation ; persistance RL open source
  (`rl_trajectory.py`).

## Garde-fous (sans humain dans la boucle)

La politique OPA (`opa.opa_eval`) tient le rôle de l'approbation. Les actions
irréversibles (`oh.sandbox_delete`, `oh.mcp_create_*`, promotion de poids…)
sont refusées par défaut par l'orchestrateur (GA7). Tout artefact téléchargé
(modèle, données) passe par `ArtifactGate` (quarantaine → inspection → admission)
avant d'être exposé au code de l'agent (point 9).

## Tests

```bash
pip install -e . && pip install pytest pytest-timeout fastapi httpx pyyaml
python -m pytest test/ nexus_unified/tests/ -q      # 413 passed, 0 failed
python -c "from nexus_unified.conformity import check_conformity, format_report; \
           print(format_report(check_conformity()))"   # 21/21 conformes
```

## Dépendances optionnelles (dégradation propre)

Sans crewAI / verl / serveur OpenHands / GPU / ClamAV / YARA, chaque nœud
concerné renvoie une erreur explicite décrivant ce qui manque — jamais un faux
succès. Les magasins PostgreSQL et Neo4j exigent leur pilote (`psycopg`,
`neo4j`) ; SQLite et JSONL fonctionnent partout.
