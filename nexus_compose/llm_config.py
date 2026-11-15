"""nexus_compose.llm_config — point de configuration LLM UNIQUE du système.

Avant ce module, chaque étage du pipeline choisissait son propre modèle par
défaut, indépendamment des autres :

    - q2d (co-conception, phase 1)   → "gpt-4o"       codé en dur
    - crewAI (codegen, phase 6)      → "gpt-4o-mini"   via CREWAI_LLM_MODEL
    - OpenHands (sandbox d'exécution) → défaut interne OpenHands (ni l'un ni
                                         l'autre — docker-compose.yml ne lui
                                         passait même pas de nom de modèle)
    - Leon AI (voix)                  → totalement non configuré

Résultat : sur un seul run du pipeline, jusqu'à 3-4 modèles différents (ou
non définis) pouvaient être sollicités sans que l'utilisateur ne l'ait
demandé. Ce module fournit UN SEUL jeu de variables d'environnement lu par
tous les composants Python (q2d, UnifiedSystem/crewAI) ; docker-compose.yml
propage les mêmes valeurs à OpenHands (LLM_MODEL/LLM_API_KEY/LLM_BASE_URL)
et à Leon (LEON_<PROVIDER>_API_KEY + génération de config.yml).

── Dashboard d'installation (nouveau point de configuration principal) ──────

Historiquement, ce module ne lisait QUE des variables d'environnement — un
seul jeu de valeurs, codé en dur au démarrage du process, qu'un utilisateur
ne peut ni consulter ni changer ni supprimer sans redémarrer le backend.
Ce n'est plus le cas : `api/providers.py` expose un dashboard CRUD
(installer / mettre à jour / supprimer / activer un fournisseur LLM),
persisté dans la table SQLite `llm_providers` (voir `api/db.py`). Le
fournisseur marqué `is_active = 1` dans cette table est maintenant la
SOURCE PRINCIPALE de configuration, lue par `_read_active_provider_row()`
ci-dessous.

Ce module ne peut PAS importer le package `api` (mauvais sens de
dépendance : `api/state.py` importe déjà `nexus_compose`, donc l'inverse
créerait un import circulaire — et `nexus_compose` doit rester utilisable
seul, en CLI ou dans les tests, sans FastAPI installé). `_read_active_provider_row()`
fait donc une lecture SQLite directe, en miroir du schéma de
`api/db.py::llm_providers` et de la même résolution de chemin
(`NEXUS_API_DB_PATH`) — lecture seule, jamais une deuxième source de
vérité : si le schéma de `api/db.py` change, seule cette fonction doit
suivre (même principe déjà appliqué par
`nexus_core_leon_bridge/bridge/llm_config.py` pour son propre repli).

Variables d'environnement canoniques (repli si AUCUN fournisseur n'est
installé depuis le dashboard) :
    NEXUS_LLM_PROVIDER   ex: "openai", "anthropic", "openrouter", "groq"…
                          (défaut : "openai")
    NEXUS_LLM_MODEL       ex: "gpt-4o-mini"   (défaut : "gpt-4o-mini")
    NEXUS_LLM_API_KEY     clé API du fournisseur ci-dessus
    NEXUS_LLM_BASE_URL    optionnel — endpoint compatible OpenAI (proxy,
                          modèle auto-hébergé, LiteLLM, etc.)

Compatibilité ascendante : si NEXUS_LLM_* est absent, on retombe sur les
anciennes variables (CREWAI_LLM_MODEL, OPENAI_API_KEY) pour ne pas casser
les déploiements existants.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LLMConfig:
    provider: str
    model: str
    api_key: str
    base_url: Optional[str] = None

    # ── Champs enrichis, renseignés quand la config vient d'un fournisseur
    # installé depuis le dashboard (voir api/providers.py). Restent à leurs
    # valeurs par défaut sur le chemin de repli purement env-var, pour ne
    # rien changer au comportement historique de ce module dans ce cas.
    endpoint: Optional[str] = None
    api_type: str = "chat_completions"
    auth_type: str = "bearer"
    extra_headers: dict[str, str] = field(default_factory=dict)
    timeout: int = 30
    max_retries: int = 3

    # "dashboard" | "env" | "default" — traçabilité uniquement (logs/debug),
    # jamais utilisé pour une décision de routage.
    source: str = "default"

    @property
    def qualified_model(self) -> str:
        """Format 'provider/model', tel qu'attendu par Leon AI (llm.default)."""
        return f"{self.provider}/{self.model}"


_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_PROVIDER = "openai"

# Suffixes de chemin connus à retirer d'un endpoint complet
# (ex: "https://api.example.com/v1/chat/completions") pour obtenir une
# "base_url" façon SDK OpenAI (ex: "https://api.example.com/v1"),
# consommée par le code existant qui appelle encore `openai.OpenAI(base_url=...)`
# (voir nexus_compose/drivers.py::_q2d_llm, chemin de repli). N'affecte QUE
# ce champ dérivé — `endpoint` conserve toujours l'URL complète telle
# qu'installée, pour l'appel HTTP direct (voir nexus_compose/llm_http.py).
_KNOWN_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/completions",
    "/responses",
    "/embeddings",
)


def _first_not_none(*values: Any) -> Any:
    """Comme un enchaînement de `or`, mais correct pour des valeurs
    numériques où 0 est une valeur explicite légitime (ex: max_retries=0,
    "aucune tentative") — un `or` traiterait 0 comme absent et sauterait à
    la valeur suivante, ce qui serait un bug silencieux."""
    for v in values:
        if v is not None:
            return v
    return None


def _derive_base_url(endpoint: Optional[str]) -> Optional[str]:
    if not endpoint:
        return None
    stripped = endpoint.rstrip("/")
    for suffix in _KNOWN_ENDPOINT_SUFFIXES:
        if stripped.lower().endswith(suffix):
            return stripped[: -len(suffix)] or stripped
    return endpoint


def _read_active_provider_row() -> Optional[dict[str, Any]]:
    """Lecture seule du fournisseur actif installé depuis le dashboard
    (table `llm_providers`, voir api/db.py). Retourne None — jamais
    d'exception propagée — dans tous les cas où le dashboard n'a encore
    rien installé : fichier DB absent, table absente (API jamais démarrée),
    ou aucune ligne `is_active = 1`. L'appelant (get_llm_config) retombe
    alors sur les variables d'environnement, exactement comme avant
    l'introduction du dashboard.
    """
    db_path = os.environ.get("NEXUS_API_DB_PATH", "./nexus_api.sqlite3")
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM llm_providers WHERE is_active = 1 LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        # Table pas encore créée (le process api n'a jamais appelé
        # db.init_db()) — pas une erreur, juste "pas de dashboard actif".
        return None
    if row is None:
        return None
    data = dict(row)
    try:
        data["headers"] = json.loads(data.get("headers") or "{}")
    except (TypeError, ValueError):
        data["headers"] = {}
    return data


def get_llm_config(overrides: Optional[dict] = None) -> LLMConfig:
    """Résout la configuration LLM unique du système.

    Ordre de priorité :
      1. `overrides` explicite (ex: ctx["model"] passé à un nœud du graphe)
         — un choix ponctuel et volontaire reste toujours prioritaire.
      2. Fournisseur actif installé depuis le dashboard (table SQLite
         `llm_providers`, is_active = 1) — LE nouveau point de
         configuration principal du système, que l'utilisateur installe,
         met à jour ou supprime depuis l'UI (pop-up "Connexion API").
      3. Variables NEXUS_LLM_* — repli si aucun fournisseur n'est installé.
      4. Anciennes variables (CREWAI_LLM_MODEL, OPENAI_API_KEY) — compat.
      5. Défauts codés en dur (gpt-4o-mini / openai) — dernier recours,
         jamais le seul chemin possible désormais.
    """
    overrides = overrides or {}
    active = _read_active_provider_row()

    provider = (
        overrides.get("provider")
        or (active["provider"] if active else None)
        or os.environ.get("NEXUS_LLM_PROVIDER")
        or _DEFAULT_PROVIDER
    )
    model = (
        overrides.get("model")
        or (active["model"] if active else None)
        or os.environ.get("NEXUS_LLM_MODEL")
        or os.environ.get("CREWAI_LLM_MODEL")  # compat ascendante
        or _DEFAULT_MODEL
    )
    api_key = (
        overrides.get("api_key")
        or (active["api_key"] if active else None)
        or os.environ.get("NEXUS_LLM_API_KEY")
        or os.environ.get("OPENAI_API_KEY")  # compat ascendante
        or ""
    )
    endpoint = (
        overrides.get("endpoint")
        or (active["endpoint"] if active else None)
        or os.environ.get("NEXUS_LLM_ENDPOINT")
        or None
    )
    base_url = (
        overrides.get("base_url")
        or (_derive_base_url(active["endpoint"]) if active else None)
        or os.environ.get("NEXUS_LLM_BASE_URL")
        or None
    )

    if active:
        source = "dashboard"
    elif os.environ.get("NEXUS_LLM_PROVIDER") or os.environ.get("NEXUS_LLM_MODEL") or os.environ.get("NEXUS_LLM_API_KEY"):
        source = "env"
    else:
        source = "default"

    timeout = _first_not_none(overrides.get("timeout"), active["timeout_s"] if active else None, 30)
    max_retries = _first_not_none(overrides.get("max_retries"), active["max_retries"] if active else None, 3)

    return LLMConfig(
        provider=provider,
        model=model,
        api_key=api_key,
        base_url=base_url,
        endpoint=endpoint,
        api_type=overrides.get("api_type") or (active["api_type"] if active else None) or "chat_completions",
        auth_type=overrides.get("auth_type") or (active["auth_type"] if active else None) or "bearer",
        extra_headers=overrides.get("extra_headers") or (active["headers"] if active else None) or {},
        timeout=timeout,
        max_retries=max_retries,
        source=source,
    )
