"""
api.providers
================

Dashboard "Connexion API" (pop-up ouvert depuis le menu "···" du Header) —
installer, lister, mettre à jour, activer et supprimer des fournisseurs LLM.
Remplace la configuration LLM unique autrefois codée en dur / lue
uniquement depuis des variables d'environnement (voir
nexus_compose/llm_config.py::get_llm_config, qui lit maintenant en priorité
le fournisseur marqué actif ici).

Endpoints :
    GET    /api/providers            liste (clé API masquée)
    POST   /api/providers            installe un nouveau fournisseur
    GET    /api/providers/{id}       détail (clé API masquée)
    PATCH  /api/providers/{id}       met à jour (partiel)
    DELETE /api/providers/{id}       supprime
    POST   /api/providers/{id}/activate   définit ce fournisseur comme actif
    POST   /api/providers/{id}/deactivate désactive (aucun fournisseur actif
                                           -> repli sur les variables d'env)
    POST   /api/providers/{id}/test       teste la connexion d'un fournisseur enregistré
    POST   /api/providers/test            teste un brouillon avant de l'enregistrer

Toute la validation déterministe (RFC3986, longueurs, jeux de caractères,
anti-injection d'en-têtes) vit dans provider_validation.py — ce module ne
fait qu'orchestrer validation -> persistance (db.py) -> réponse. Le test de
connexion réutilise `nexus_compose.llm_http` (le MÊME client HTTP que
l'appel LLM réel), via `asyncio.to_thread` puisque httpx.Client est
synchrone/bloquant (même principe que sqlite3/neo4j ailleurs dans ce
package).

Propriété du LLM par le couple Leon/Nexus Brain (voir
nexus_compose/leon_llm_sync.py) : toute écriture qui change le fournisseur
ACTIF (activate/deactivate/delete du fournisseur actif) réapplique
immédiatement ce fournisseur à Leon (config.yml + .env), pas seulement à
q2d/crewAI/OpenHands. Avant ce module, Leon restait sur le fournisseur
patché au bootstrap du conteneur jusqu'au prochain redémarrage complet,
même après un changement fait ici — les deux moitiés du couple Leon/Nexus
Brain pouvaient silencieusement tourner sur deux fournisseurs différents.
`sync_leon_llm_config()` ne lève jamais : si Leon n'est pas déployé à côté
de ce backend, la synchronisation est un no-op signalé en log, jamais une
erreur HTTP pour l'appelant du dashboard.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import db
from .provider_validation import ValidationError, validate_provider_fields
from nexus_compose.leon_llm_sync import sync_leon_llm_config

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _http_422(exc: ValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail={"field": exc.field, "message": exc.message})


# ── schémas ──────────────────────────────────────────────────────────────────

class ProviderIn(BaseModel):
    provider: str
    label: str
    model: str
    endpoint: str
    api_type: str = "chat_completions"
    auth_type: str = "bearer"
    api_key: Optional[str] = None
    headers: dict[str, str] = Field(default_factory=dict)
    timeout_s: int = 30
    max_retries: int = 3
    http2: bool = True
    compression: bool = True


class ProviderPatch(BaseModel):
    """Tous les champs optionnels — seuls ceux fournis sont modifiés."""
    provider: Optional[str] = None
    label: Optional[str] = None
    model: Optional[str] = None
    endpoint: Optional[str] = None
    api_type: Optional[str] = None
    auth_type: Optional[str] = None
    api_key: Optional[str] = None
    headers: Optional[dict[str, str]] = None
    timeout_s: Optional[int] = None
    max_retries: Optional[int] = None
    http2: Optional[bool] = None
    compression: Optional[bool] = None


class TestResult(BaseModel):
    status: Literal["success", "error"]
    httpStatus: Optional[int] = None
    message: str
    attempts: int = 1


# ── CRUD ─────────────────────────────────────────────────────────────────────

@router.get("")
async def list_providers() -> list[dict[str, Any]]:
    return await asyncio.to_thread(db.list_providers)


@router.post("", status_code=201)
async def create_provider(body: ProviderIn) -> dict[str, Any]:
    try:
        clean = validate_provider_fields(body.model_dump(), partial=False)
    except ValidationError as exc:
        raise _http_422(exc)
    provider_id = str(uuid.uuid4())
    now = _now()
    return await asyncio.to_thread(db.insert_provider, provider_id, clean, now)


@router.get("/{provider_id}")
async def read_provider(provider_id: str) -> dict[str, Any]:
    provider = await asyncio.to_thread(db.get_provider, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider_id!r}")
    return provider


@router.patch("/{provider_id}")
async def patch_provider(provider_id: str, body: ProviderPatch) -> dict[str, Any]:
    existing = await asyncio.to_thread(db.get_provider, provider_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider_id!r}")

    raw = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    # Cohérence api_key/auth_type : si auth_type passe à "none", api_key
    # n'est plus requis même s'il n'est pas explicitement fourni dans ce
    # PATCH — et inversement, un auth_type qui reste "bearer"/"api_key"/
    # "basic" (nouveau ou déjà existant) exige une clé déjà en base ou
    # fournie dans ce PATCH.
    effective_auth_type = raw.get("auth_type", existing["authType"])
    if "api_key" not in raw and effective_auth_type != "none" and not existing["hasApiKey"]:
        raise HTTPException(
            status_code=422,
            detail={"field": "api_key", "message": "clé API requise pour ce mode d'authentification"},
        )

    try:
        clean = validate_provider_fields(raw, partial=True)
    except ValidationError as exc:
        raise _http_422(exc)

    now = _now()
    updated = await asyncio.to_thread(db.update_provider, provider_id, clean, now)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider_id!r}")
    return updated


@router.delete("/{provider_id}", status_code=204)
async def remove_provider(provider_id: str) -> None:
    existing = await asyncio.to_thread(db.get_provider, provider_id)
    was_active = bool(existing and existing.get("isActive"))
    ok = await asyncio.to_thread(db.delete_provider, provider_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider_id!r}")
    if was_active:
        # Le fournisseur ACTIF vient de disparaître -> get_llm_config()
        # retombe sur les variables d'env/défauts au prochain appel côté
        # q2d/crewAI ; Leon doit retomber sur le même repli, pas rester
        # bloqué sur un fournisseur qui n'existe plus.
        await asyncio.to_thread(sync_leon_llm_config)


@router.post("/{provider_id}/activate")
async def activate_provider(provider_id: str) -> dict[str, Any]:
    now = _now()
    updated = await asyncio.to_thread(db.set_active_provider, provider_id, now)
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider_id!r}")
    # Propriété du LLM par le couple Leon/Nexus Brain : Leon doit refléter
    # ce changement immédiatement, pas seulement au prochain redémarrage
    # du conteneur (voir nexus_compose/leon_llm_sync.py).
    await asyncio.to_thread(sync_leon_llm_config)
    return updated


@router.post("/{provider_id}/deactivate")
async def deactivate_provider(provider_id: str) -> dict[str, Any]:
    existing = await asyncio.to_thread(db.get_provider, provider_id)
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider_id!r}")
    now = _now()
    await asyncio.to_thread(db.deactivate_all_providers, now)
    await asyncio.to_thread(sync_leon_llm_config)
    return await asyncio.to_thread(db.get_provider, provider_id)  # type: ignore[return-value]


# ── test de connexion ────────────────────────────────────────────────────────

def _run_connection_test(fields: dict[str, Any]) -> TestResult:
    """Synchrone/bloquant — appeler uniquement via asyncio.to_thread.
    Réutilise nexus_compose.llm_http (même client que l'appel LLM réel du
    pipeline), avec un prompt vide, conformément à la spec ("Le test
    effectue uniquement GET /models ou POST /chat/completions avec un
    prompt vide selon le fournisseur")."""
    from nexus_compose.llm_config import LLMConfig
    from nexus_compose.llm_http import call_llm_endpoint

    cfg = LLMConfig(
        provider=fields["provider"], model=fields["model"], api_key=fields.get("api_key") or "",
        endpoint=fields["endpoint"], api_type=fields.get("api_type", "chat_completions"),
        auth_type=fields.get("auth_type", "bearer"), extra_headers=fields.get("headers") or {},
        timeout=fields.get("timeout_s", 30), max_retries=fields.get("max_retries", 3),
    )
    result = call_llm_endpoint(cfg, prompt="")
    if result.ok:
        return TestResult(status="success", httpStatus=result.status_code, message="Connexion réussie.", attempts=result.attempts)
    return TestResult(
        status="error", httpStatus=result.status_code,
        message=result.error or "Échec de la connexion.", attempts=result.attempts,
    )


@router.post("/{provider_id}/test")
async def test_saved_provider(provider_id: str) -> TestResult:
    secret = await asyncio.to_thread(db.get_provider_secret, provider_id)
    if secret is None:
        raise HTTPException(status_code=404, detail=f"Unknown provider {provider_id!r}")
    fields = {
        "provider": secret["provider"], "model": secret["model"], "api_key": secret["api_key"],
        "endpoint": secret["endpoint"], "api_type": secret["api_type"], "auth_type": secret["auth_type"],
        "headers": secret["headers"], "timeout_s": secret["timeout_s"], "max_retries": secret["max_retries"],
    }
    return await asyncio.to_thread(_run_connection_test, fields)


@router.post("/test")
async def test_draft_provider(body: ProviderIn) -> TestResult:
    """Teste un brouillon AVANT de l'installer (bouton "Tester la
    connexion" du formulaire) — ne touche jamais la base de données."""
    try:
        clean = validate_provider_fields(body.model_dump(), partial=False)
    except ValidationError as exc:
        raise _http_422(exc)
    return await asyncio.to_thread(_run_connection_test, clean)
