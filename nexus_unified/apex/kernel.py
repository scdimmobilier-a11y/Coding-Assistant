"""nexus_unified.apex.kernel — noyau Apex protégé, état partagé, Observer/Learner/Actor.

Point 6 — architecture Apex en surcouche de gouvernance du pipeline. Trois
pièces :

- **Apex Kernel** : une ontologie fondatrice PROTÉGÉE (champ → chaos →
  distinction → information organisée → structure → résonance → traduction →
  relations). Protégée = figée par empreinte : toute modification non autorisée
  est détectée (modèle d'intégrité, phase 4). Le noyau est indépendant du
  modèle (aucun LLM, aucune donnée de fournisseur).
- **Shared Persistent System State** : l'état partagé que l'Observer écrit, que
  le Learner révise et sur lequel l'Actor agit ; historisé, avec provenance.
- **Observer / Learner / Actor** : les trois rôles qui tournent en continu.
  L'Observer mesure les conditions ; le Learner met à jour les connaissances
  (établi / dérivé / non résolu) ; l'Actor planifie et exécute sous
  autorisation.

Le noyau ne remplace pas l'orchestrateur : il le gouverne. Un cycle Apex
enveloppe une exécution (MasterOrchestrator) et pose dessus les garde-fous
d'intégrité, de connaissance et de récupération.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple


# ── ontologie fondatrice, protégée ──────────────────────────────────────────
APEX_ONTOLOGY: Tuple[str, ...] = (
    "field",                 # champ
    "chaos",                 # chaos
    "distinction",           # distinction (entités, propriétés, ressources)
    "organized_information", # information organisée
    "structure",             # structure
    "resonance",             # résonance
    "translation",           # traduction
    "relationships",         # relations (interactions, dépendances)
)


class KnowledgeStatus(str, Enum):
    ESTABLISHED = "established"   # établi (validé, preuve indépendante)
    DERIVED = "derived"          # dérivé (conclusion d'un autre fait établi)
    UNRESOLVED = "unresolved"    # non résolu (contradiction / incertitude)


@dataclass(frozen=True)
class ProtectedKernel:
    """Noyau fondateur figé par empreinte. Toute dérive est détectable."""
    ontology: Tuple[str, ...] = APEX_ONTOLOGY
    version: str = "apex-1"

    @property
    def fingerprint(self) -> str:
        payload = json.dumps({"ontology": list(self.ontology), "version": self.version},
                             sort_keys=True).encode()
        return hashlib.sha256(payload).hexdigest()

    def verify(self, expected_fingerprint: str) -> bool:
        return self.fingerprint == expected_fingerprint


@dataclass
class KnowledgeItem:
    key: str
    value: Any
    status: KnowledgeStatus
    provenance: str                 # run_id, nœud, source
    updated_at: float = field(default_factory=time.time)
    history: List[Tuple[float, Any, str]] = field(default_factory=list)


class SharedSystemState:
    """État partagé persistant : l'Observer écrit, le Learner révise, l'Actor lit.

    Chaque écriture est historisée avec provenance (phase 4 : provenance ;
    phase 5 : révision de modèle). Un `store` RecordStore optionnel persiste.
    """

    def __init__(self, store: Optional[Any] = None, collection: str = "apex_state") -> None:
        self._items: Dict[str, KnowledgeItem] = {}
        self._store = store
        self._collection = collection

    def observe(self, key: str, value: Any, provenance: str) -> None:
        """Écriture d'une condition observée (mesure brute, statut dérivé)."""
        self._write(key, value, KnowledgeStatus.DERIVED, provenance)

    def assert_established(self, key: str, value: Any, provenance: str,
                           second_proof: Optional[str] = None) -> bool:
        """Promotion en 'établi' : exige une seconde preuve indépendante (G4).
        Sans seconde preuve, reste 'dérivé'."""
        if not second_proof:
            self._write(key, value, KnowledgeStatus.DERIVED, provenance)
            return False
        self._write(key, value, KnowledgeStatus.ESTABLISHED, f"{provenance}+{second_proof}")
        return True

    def mark_unresolved(self, key: str, value: Any, provenance: str) -> None:
        self._write(key, value, KnowledgeStatus.UNRESOLVED, provenance)

    def _write(self, key: str, value: Any, status: KnowledgeStatus, provenance: str) -> None:
        prev = self._items.get(key)
        hist = prev.history if prev else []
        hist = hist + [(time.time(), prev.value if prev else None, provenance)]
        item = KnowledgeItem(key, value, status, provenance, time.time(), hist[-50:])
        self._items[key] = item
        if self._store is not None:
            try:
                self._store.put(self._collection, key,
                                {"key": key, "value": value, "status": status.value,
                                 "provenance": provenance, "updated_at": item.updated_at})
            except Exception:  # noqa: BLE001
                pass

    def get(self, key: str) -> Optional[KnowledgeItem]:
        return self._items.get(key)

    def by_status(self, status: KnowledgeStatus) -> List[KnowledgeItem]:
        return [i for i in self._items.values() if i.status == status]

    def contradictions(self) -> List[KnowledgeItem]:
        return self.by_status(KnowledgeStatus.UNRESOLVED)

    def snapshot(self) -> Dict[str, Any]:
        return {k: {"value": i.value, "status": i.status.value, "provenance": i.provenance}
                for k, i in self._items.items()}


# ── rôles ────────────────────────────────────────────────────────────────────
@dataclass
class Observer:
    """Mesure les conditions internes/externes et les écrit dans l'état partagé."""
    state: SharedSystemState

    def observe(self, conditions: Dict[str, Any], provenance: str = "observer") -> None:
        for k, v in conditions.items():
            self.state.observe(k, v, provenance)


@dataclass
class Learner:
    """Met à jour les connaissances : intègre les résultats, détecte les
    contradictions, révise le modèle (établi/dérivé/non résolu)."""
    state: SharedSystemState

    def integrate(self, key: str, value: Any, provenance: str,
                  second_proof: Optional[str] = None) -> KnowledgeStatus:
        prev = self.state.get(key)
        if prev is not None and prev.status == KnowledgeStatus.ESTABLISHED and prev.value != value:
            # contradiction avec un fait établi → non résolu, pas d'écrasement silencieux
            self.state.mark_unresolved(key, {"old": prev.value, "new": value}, provenance)
            return KnowledgeStatus.UNRESOLVED
        self.state.assert_established(key, value, provenance, second_proof)
        return self.state.get(key).status

    def resolve(self, key: str, value: Any, provenance: str, second_proof: str) -> bool:
        return self.state.assert_established(key, value, provenance, second_proof)


@dataclass
class Actor:
    """Planifie et exécute des actions autorisées, observe les résultats réels.

    Délègue l'exécution au MasterOrchestrator ; l'autorisation est vérifiée
    AVANT exécution (permission check before execution, phase 6)."""
    authorize: Callable[[str, Dict[str, Any]], bool]

    def may_act(self, action: str, ctx: Dict[str, Any]) -> bool:
        return self.authorize(action, ctx)
