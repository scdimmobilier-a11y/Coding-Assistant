# Unified Agent System

Trois dépôts fusionnés en une pile cohérente :

| Couche | Dépôt | Rôle |
|--------|-------|------|
| Entraînement RL | `OpenManus-RL/` | Boucle de rollout, algorithme GiGPO, environnements vectorisés |
| Orchestration | `crewAI/` | Crews d'agents, flows, outils MCP |
| Exécution | `OpenHands/` | Sandbox Docker isolé, API REST de conversation |

---

## Démarrage rapide

```python
from unified_system.bridge import UnifiedSystem

system = UnifiedSystem.from_env()
print(system.health_check())
result = system.run_task("Écrire un serveur HTTP minimal en Python")
print(result)
```

Variables d'environnement :

```bash
OH_BASE_URL=http://localhost:3000   # serveur OpenHands
OH_TOKEN=                           # bearer token (vide si auth désactivée)

# LLM — partagé avec q2d/nexus_compose (nexus_compose/llm_config.py) : le
# fournisseur ACTIF du dashboard (voir api/providers.py) prime sur tout
# ce qui suit ; NEXUS_LLM_* est la source de repli principale, lue avant
# les variables CREWAI_LLM_MODEL/OPENAI_API_KEY historiques ci-dessous.
NEXUS_LLM_PROVIDER=openai
NEXUS_LLM_MODEL=gpt-4o-mini
NEXUS_LLM_API_KEY=sk-...

# Repli rétro-compatible, seulement lu si les variables NEXUS_LLM_* ci-dessus
# sont absentes :
OPENAI_API_KEY=sk-...
CREWAI_LLM_MODEL=gpt-4o-mini

# Agent Skills (D5, voir MISSION_couple_leon_nexusbrain.md) — dossier
# Nexus-owned de skills curées pour l'agent "Software Engineer" (5 skills :
# test-driven-development, code-review-and-quality, ci-cd-and-automation,
# security-and-hardening, debugging-and-error-recovery). Ne pointe PAS vers
# le paquet vendored agent-skills-main de crewAI (chemin instable d'une
# version à l'autre) — voir nexus_compose/agent_skills/.
NEXUS_AGENT_SKILLS_DIR=./nexus_compose/agent_skills
```

---

## Fichiers modifiés et nouveaux

### OpenManus-RL — `OpenManus-RL/`
| Fichier | Statut | Contenu |
|---------|--------|---------|
| `openmanus_rl/engines/openai.py` | ★ modifié | Ajout `CrewAIEngine` — wraps un Crew crewAI comme politique RL |
| `openmanus_rl/environments/env_manager.py` | ★ modifié | Ajout `OpenHandsEnvironmentManager` + patch `make_envs` |
| `openmanus_rl/multi_turn_rollout/tool_integration.py` | ★ modifié | Ajout `SSRFSafeToolRegistry` |

### crewAI — `crewAI/`
| Fichier | Statut | Contenu |
|---------|--------|---------|
| `lib/crewai/src/crewai/tools/openhands_tool.py` | ✦ nouveau | `OpenHandsTask` — BaseTool qui délègue au sandbox OpenHands |
| `lib/crewai-tools/src/crewai_tools/security/safe_requests.py` | branche SSRF | `SSRFProtectedAdapter`, `create_safe_session` |
| `lib/crewai-tools/src/crewai_tools/security/safe_path.py` | branche SSRF | Validation de chemins et URLs |

### OpenHands — `OpenHands/`
| Fichier | Statut | Contenu |
|---------|--------|---------|
| `openhands/app_server/app.py` | ★ modifié | Import + enregistrement de `rl_agent_router` |
| `openhands/app_server/rl_agent_router.py` | ✦ nouveau | Endpoints `/api/rl/*` pour OpenManus-RL |
| `enterprise/migrations/versions/118_create_rl_trajectories_table.py` | ✦ nouveau | Table `rl_trajectories` (Alembic) |

### Racine
| Fichier | Statut | Contenu |
|---------|--------|---------|
| `bridge.py` | ✦ nouveau | `UnifiedSystem` — assemble les trois couches |

---

## Architecture des flux

```
OpenManus-RL (training)
    │  trajectoires + récompenses
    ▼
crewAI (orchestration)          ← CrewAIEngine wraps le crew comme politique
    │  actions → sandbox
    ▼
OpenHands (exécution)           ← OpenHandsTask délègue les tâches au sandbox
    │  observations + reward
    └──────────────────────────► OpenManus-RL (boucle RL)
```

---

## Endpoints RL ajoutés à OpenHands

```
POST   /api/rl/conversations                   # reset() — crée un épisode
POST   /api/rl/conversations/{id}/step         # step()  — exécute une action
GET    /api/rl/conversations/{id}/status       # poll du statut
```

---

## Installation

```bash
# 1. OpenManus-RL
cd OpenManus-RL && pip install -e ".[train]"

# 2. crewAI
cd ../crewAI && pip install -e "lib/crewai" -e "lib/crewai-tools"

# 3. OpenHands
cd ../OpenHands && pip install -e ".[server]"
alembic -c enterprise/alembic.ini upgrade head   # applique la migration 118

# 4. Pont unifié
cd .. && pip install -e .
```

---

## Agent Skills (D5, `MISSION_couple_leon_nexusbrain.md`)

`bridge.py::UnifiedSystem._default_crew_factory` charge des [Agent
Skills](https://docs.crewai.com) via `crewai.skills.discover_skills()` et
les passe à l'agent "Software Engineer" (`Agent(skills=...)`). Le dossier
chargé (`NEXUS_AGENT_SKILLS_DIR`, défaut `./nexus_compose/agent_skills`)
est une copie curée et Nexus-owned de 5 skills du paquet vendored
`crewAI/.../crewai/skills/agent-skills-main/` — pas ce paquet vendored
directement, dont le chemin n'est pas garanti stable d'une mise à jour
crewAI à l'autre :

- `test-driven-development`
- `code-review-and-quality`
- `ci-cd-and-automation`
- `security-and-hardening`
- `debugging-and-error-recovery`

Dégrade proprement (agent sans skills, pas d'exception) si crewAI n'est
pas installé, si le dossier est absent, ou si le chargement échoue — voir
`_discover_agent_skills()`'s own docstring dans `bridge.py`.
