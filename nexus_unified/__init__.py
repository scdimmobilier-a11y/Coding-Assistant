"""nexus_unified — laboratoire GPU/RL et gouvernance Apex par-dessus nexus_compose.

Ce paquet rassemble tout ce que l'intégration ajoute au-dessus du pipeline de
base `nexus_compose`, selon le cahier des charges :

- `security`      : inspection obligatoire des artefacts + sandbox durci (point 9) ;
- `accelerators`  : découverte multi-constructeur, CDI compris (point 1) + baux
                    bornés par les ressources (point 2) ;
- `llm`           : passerelle LLM unique, tout fournisseur, externe (points 3, 4) ;
- `store`         : magasins open source enfichables (point 7) ;
- `openhands_client` : client API OpenHands V1 (lot 0, point 6) ;
- `pack`          : ~227 nœuds ajoutés au graphe de composabilité (lot 2) ;
- `orchestrator`  : orchestrateur maître piloté par requête LLM (point 5) ;
- `apex`          : gouvernance Apex en 8 phases, Observer/Learner/Actor (point 6) ;
- `training`      : entraînement/évaluation/service de modèles (lot 3) ;
- `learning`      : apprentissage par succès et échecs des agents (point 8, lot 4) ;
- `rl_trajectory` : persistance open source des trajectoires RL.

Le point d'entrée du graphe composé : `nexus_compose.build(("unified",))`.
"""
from __future__ import annotations

__version__ = "0.1.0"

__all__ = [
    "security", "accelerators", "llm", "store", "openhands_client",
    "orchestrator", "apex", "training", "learning", "pack", "rl_trajectory",
    "conformity_report",
]


def conformity_report() -> dict:
    """Vérifie la conformité du système aux 9 points + pipeline 8 phases.

    Retourne un dict {exigence: {ok, detail}} calculé en interrogeant
    réellement le graphe et les modules (pas une simple déclaration).
    """
    from .conformity import check_conformity
    return check_conformity()
