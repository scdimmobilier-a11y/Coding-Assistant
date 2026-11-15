"""nexus_unified.rl_trajectory — persistance open source des trajectoires RL.

Remplace la table `rl_trajectories` de la migration `enterprise/` (licence
PolyForm Free Trial, non applicable en mode open source — constat, défaut 5 et
Q7). Les trajectoires vont dans un magasin open source (point 7 : PostgreSQL,
SQLite, Neo4j, JSONL), via `nexus_unified.store`. Aucune dépendance au schéma
entreprise ni au driver SQL brut dont l'erreur était avalée par `except: pass`.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from .store import RecordStore, open_store


class TrajectoryRecorder:
    """Enregistre épisodes et pas RL. Best-effort : une écriture qui échoue est
    signalée (retour False), jamais silencieusement perdue."""

    def __init__(self, store: Optional[RecordStore] = None,
                 collection: str = "rl_trajectories") -> None:
        self.store = store or open_store()
        self.collection = collection

    def start_episode(self, conversation_id: str, task_description: str,
                      metadata: Optional[Dict[str, Any]] = None) -> bool:
        rec = {"id": conversation_id, "conversation_id": conversation_id,
               "task_description": task_description, "metadata": metadata or {},
               "steps": 0, "final_reward": None, "crew_id": (metadata or {}).get("crew_id"),
               "created_at": time.time(), "updated_at": time.time()}
        try:
            self.store.put(self.collection, conversation_id, rec)
            return True
        except Exception:  # noqa: BLE001
            return False

    def record_step(self, conversation_id: str, reward: float,
                    observation: str = "") -> bool:
        try:
            rec = self.store.get(self.collection, conversation_id) or {
                "id": conversation_id, "conversation_id": conversation_id, "steps": 0}
            rec["steps"] = int(rec.get("steps", 0)) + 1
            rec["final_reward"] = reward
            rec["last_observation"] = observation[:500]
            rec["updated_at"] = time.time()
            self.store.put(self.collection, conversation_id, rec)
            return True
        except Exception:  # noqa: BLE001
            return False

    def get(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get(self.collection, conversation_id)
