"""
nexus_compose.llm_http
=========================

Client HTTP natif et déterministe pour parler à N'IMPORTE QUEL fournisseur
ou serveur LLM compatible HTTP (cloud ou auto-hébergé), à partir d'un objet
`LLMConfig` déjà résolu (voir llm_config.py). Ce module est le point
d'arrivée de l'architecture décrite dans la spec du pop-up "Connexion API" :

    Interface graphique
            │
            ▼
    Validation syntaxique / RFC (api/provider_validation.py)
            │
            ▼
    Construction d'un objet HTTP interne (LLMConfig)
            │
            ▼
    Client HTTP natif (CE MODULE — httpx, jamais subprocess/shell/curl)
            │
            ▼
    Serveur LLM

Utilisé par DEUX appelants :
  - nexus_compose/drivers.py::_q2d_llm — l'appel LLM réel du pipeline.
  - api/providers.py — le bouton "Tester la connexion" du dashboard
    (via asyncio.to_thread, ce module étant synchrone/bloquant comme le
    reste des appels réseau de nexus_compose).

Aucun texte utilisateur n'est jamais concaténé dans une commande shell ;
aucun `exec()`/`system()`/`subprocess` n'est utilisé ici — uniquement un
client HTTP (`httpx`), conformément à la politique de sécurité de la spec
d'origine.
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from .llm_config import LLMConfig

# Erreurs considérées transitoires -> éligibles à une nouvelle tentative
# (max_retries). Les erreurs 4xx (auth, requête invalide) ne sont JAMAIS
# retentées : une nouvelle tentative identique échouerait de la même façon.
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


@dataclass
class LLMCallResult:
    ok: bool
    status_code: Optional[int]
    text: Optional[str] = None
    error: Optional[str] = None
    raw: Optional[dict[str, Any]] = None
    attempts: int = 1


def build_auth_headers(auth_type: str, api_key: Optional[str]) -> dict[str, str]:
    """Construit l'en-tête d'authentification à partir du TYPE choisi par
    l'utilisateur (Bearer / API Key / Basic / Aucun) — jamais depuis une
    syntaxe libre saisie par l'utilisateur (voir spec : "Le logiciel
    construit automatiquement Authorization: Bearer ... sans que
    l'utilisateur puisse modifier la syntaxe")."""
    auth_type = (auth_type or "none").lower()
    if auth_type == "none" or not api_key:
        return {}
    if auth_type == "bearer":
        return {"Authorization": f"Bearer {api_key}"}
    if auth_type == "api_key":
        # Convention la plus répandue chez les fournisseurs qui utilisent une
        # clé plutôt qu'un bearer token (ex: Anthropic "x-api-key").
        return {"x-api-key": api_key}
    if auth_type == "basic":
        token = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("ascii")
        return {"Authorization": f"Basic {token}"}
    return {}


def build_request(api_type: str, model: str, *, prompt: str = "", messages: Optional[list[dict]] = None) -> tuple[str, dict[str, Any]]:
    """Retourne (méthode HTTP, corps JSON) pour le type d'API choisi. Le
    corps suit le schéma "Chat Completions" compatible OpenAI pour les
    types les plus courants (ce que la majorité des fournisseurs listés —
    OpenAI, OpenRouter, Groq, Mistral, NVIDIA, Ollama, LM Studio, vLLM —
    exposent nativement). Les fournisseurs à schéma propriétaire (ex:
    Anthropic Messages API) peuvent être ciblés en choisissant "Custom"
    comme type d'API et en renseignant les en-têtes nécessaires."""
    api_type = (api_type or "chat_completions").lower()
    body_messages = messages if messages is not None else [{"role": "user", "content": prompt}]

    if api_type == "chat_completions":
        return "POST", {"model": model, "messages": body_messages, "max_tokens": 1 if not prompt and messages is None else 256}
    if api_type == "responses":
        return "POST", {"model": model, "input": prompt}
    if api_type == "embeddings":
        return "POST", {"model": model, "input": prompt}
    if api_type == "images":
        return "POST", {"model": model, "prompt": prompt, "n": 1}
    # "audio" et "custom" : pas de schéma générique fiable (l'audio attend
    # généralement un upload multipart) -> simple vérification de
    # joignabilité par GET plutôt qu'un corps potentiellement invalide.
    return "GET", {}


def parse_response_text(api_type: str, data: Any) -> Optional[str]:
    """Extraction best-effort du texte de réponse, schéma OpenAI-compatible
    pour les types les plus courants. Retourne None si la forme de la
    réponse n'est pas reconnue plutôt que de lever — un appelant qui a
    juste besoin de savoir "la requête a-t-elle abouti" (test de connexion)
    n'a pas besoin que ceci réussisse."""
    if not isinstance(data, dict):
        return None
    try:
        api_type = (api_type or "chat_completions").lower()
        if api_type == "chat_completions":
            return data["choices"][0]["message"]["content"]
        if api_type == "responses":
            if "output_text" in data:
                return data["output_text"]
            return str(data.get("output") or data)
        if api_type == "embeddings":
            return None  # pas de texte à extraire, ok=True suffit
    except (KeyError, IndexError, TypeError):
        return None
    return None


def call_llm_endpoint(cfg: LLMConfig, *, messages: Optional[list[dict]] = None, prompt: str = "") -> LLMCallResult:
    """Appel réel, synchrone/bloquant (à appeler depuis un thread dédié,
    jamais depuis une boucle asyncio — même contrainte que sqlite3/neo4j
    ailleurs dans ce projet). Retente jusqu'à `cfg.max_retries` fois sur les
    erreurs réseau/serveur transitoires ; jamais sur une erreur 4xx (auth ou
    requête invalide), qui ne peut pas être corrigée par une répétition à
    l'identique."""
    if not cfg.endpoint:
        return LLMCallResult(ok=False, status_code=None, error="Aucun endpoint configuré (aucun fournisseur actif installé, et NEXUS_LLM_BASE_URL absent).")

    method, body = build_request(cfg.api_type, cfg.model, prompt=prompt, messages=messages)
    headers = {"Content-Type": "application/json", **build_auth_headers(cfg.auth_type, cfg.api_key), **(cfg.extra_headers or {})}

    attempts = 0
    last_error: Optional[str] = None
    last_status: Optional[int] = None
    max_attempts = max(1, (cfg.max_retries or 0) + 1)

    with httpx.Client(timeout=cfg.timeout or 30, http2=False) as client:
        while attempts < max_attempts:
            attempts += 1
            try:
                if method == "GET":
                    resp = client.get(cfg.endpoint, headers=headers)
                else:
                    resp = client.post(cfg.endpoint, headers=headers, json=body)
            except httpx.TimeoutException:
                last_error = f"Délai dépassé ({cfg.timeout}s)"
                last_status = None
            except httpx.TransportError as exc:
                last_error = f"Erreur réseau : {exc}"
                last_status = None
            else:
                last_status = resp.status_code
                if 200 <= resp.status_code < 300:
                    try:
                        data = resp.json()
                    except ValueError:
                        data = None
                    return LLMCallResult(
                        ok=True, status_code=resp.status_code,
                        text=parse_response_text(cfg.api_type, data) if data is not None else resp.text,
                        raw=data if isinstance(data, dict) else None, attempts=attempts,
                    )
                # Erreur HTTP : ne retenter QUE si transitoire.
                last_error = _short_error_message(resp)
                if resp.status_code not in _RETRYABLE_STATUS:
                    return LLMCallResult(ok=False, status_code=resp.status_code, error=last_error, attempts=attempts)

            if attempts < max_attempts:
                time.sleep(min(2 ** (attempts - 1) * 0.5, 4.0))  # backoff léger, plafonné

    return LLMCallResult(ok=False, status_code=last_status, error=last_error or "Échec inconnu", attempts=attempts)


def _short_error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            msg = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else data.get("error") or data.get("message")
            if msg:
                return f"HTTP {resp.status_code} — {str(msg)[:200]}"
    except ValueError:
        pass
    return f"HTTP {resp.status_code} — {resp.text[:200]}"
