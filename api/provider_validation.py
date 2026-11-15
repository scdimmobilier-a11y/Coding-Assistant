"""
api.provider_validation
==========================

Validation déterministe des champs du dashboard "Connexion API" (installer
/ mettre à jour un fournisseur LLM) — implémente les règles de la spec
fournie pour le pop-up : chaque champ a un type, un domaine de valeurs
autorisées et une règle de validation indépendante des autres. Rien ici
n'interprète un texte utilisateur comme une commande ; ce module ne fait
que valider et normaliser des valeurs atomiques avant construction de
l'objet `LLMConfig`/de la ligne SQLite — jamais de `exec`/`subprocess`.

Toutes les fonctions lèvent `ValidationError(field, message)` en cas de
valeur invalide ; `api/providers.py` les convertit en HTTP 422 avec le
détail du champ fautif.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any, Optional
from urllib.parse import urlparse

# ── domaines de valeurs ──────────────────────────────────────────────────────

PROVIDER_CHOICES = {
    "custom", "openai", "anthropic", "openrouter", "google_gemini", "nvidia",
    "groq", "mistral", "ollama", "lm_studio", "vllm", "other",
}
API_TYPE_CHOICES = {"chat_completions", "responses", "embeddings", "images", "audio", "custom"}
AUTH_TYPE_CHOICES = {"bearer", "api_key", "basic", "none"}

_MODEL_RE = re.compile(r"^[A-Za-z0-9._/:-]{1,128}$")
_API_KEY_RE = re.compile(r"^[A-Za-z0-9._~-]{16,512}$")
_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_PROVIDER_SLUG_RE = re.compile(r"^[a-z0-9_-]{1,32}$")

_FORBIDDEN_SCHEMES = {"file", "ftp", "ssh"}
_LOCAL_HOSTS = {"localhost", "0.0.0.0"}

_MAX_ENDPOINT_LENGTH = 2048
_MAX_LABEL_LENGTH = 80


class ValidationError(ValueError):
    def __init__(self, field: str, message: str):
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


# ── champs individuels ───────────────────────────────────────────────────────

def validate_provider(provider: str) -> str:
    slug = (provider or "").strip().lower().replace(" ", "_")
    if not _PROVIDER_SLUG_RE.fullmatch(slug):
        raise ValidationError("provider", "identifiant de fournisseur invalide (a-z 0-9 _ -, 1 à 32 caractères)")
    return slug


def validate_label(label: str) -> str:
    label = (label or "").strip()
    if not label:
        raise ValidationError("label", "nom requis")
    if len(label) > _MAX_LABEL_LENGTH:
        raise ValidationError("label", f"{_MAX_LABEL_LENGTH} caractères maximum")
    if any(ord(c) < 0x20 for c in label):
        raise ValidationError("label", "aucun caractère de contrôle autorisé")
    return label


def validate_model(model: str) -> str:
    if not model or not _MODEL_RE.fullmatch(model):
        raise ValidationError("model", "1 à 128 caractères parmi A-Z a-z 0-9 . _ - / :")
    return model


def _is_local_or_private_host(host: str) -> bool:
    host = host.lower()
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        return True
    if host == "127.0.0.1" or host.startswith("127."):
        return True
    try:
        ip = ipaddress.ip_address(host)
        return ip.is_private or ip.is_loopback or ip.is_link_local
    except ValueError:
        return False


def validate_endpoint(endpoint: str, *, allow_local: bool = True) -> str:
    """HTTPS obligatoire, URI RFC3986 valide, longueur < 2048, aucun
    espace/retour-ligne/caractère de contrôle. `file://`, `ftp://`,
    `ssh://` sont TOUJOURS interdits. `http://` est interdit sauf vers un
    hôte local/privé (127.0.0.1, ::1, 192.168.x.x, 10.x.x.x, localhost…) —
    exception nécessaire pour les serveurs auto-hébergés du catalogue
    (Ollama, LM Studio, vLLM tournent typiquement sans TLS en local) ;
    voir la note de sécurité dans provider_catalog. Cette exception peut
    être désactivée (`allow_local=False`) par une politique plus stricte."""
    if not endpoint:
        raise ValidationError("endpoint", "URL requise")
    if len(endpoint) >= _MAX_ENDPOINT_LENGTH:
        raise ValidationError("endpoint", f"{_MAX_ENDPOINT_LENGTH} caractères maximum")
    if any(c.isspace() for c in endpoint) or any(ord(c) < 0x20 for c in endpoint):
        raise ValidationError("endpoint", "aucun espace ni caractère de contrôle autorisé")

    parsed = urlparse(endpoint)
    if not parsed.scheme or not parsed.netloc or not parsed.hostname:
        raise ValidationError("endpoint", "URL invalide (RFC 3986) — schéma et hôte requis")

    scheme = parsed.scheme.lower()
    if scheme in _FORBIDDEN_SCHEMES:
        raise ValidationError("endpoint", f"schéma « {scheme}:// » interdit")
    if scheme == "https":
        return endpoint
    if scheme == "http":
        if allow_local and _is_local_or_private_host(parsed.hostname):
            return endpoint
        raise ValidationError("endpoint", "HTTPS obligatoire (http:// réservé à un hôte local/privé auto-hébergé)")
    raise ValidationError("endpoint", "seuls les schémas https:// (ou http:// en local) sont autorisés")


def validate_api_key(api_key: Optional[str], *, required: bool) -> Optional[str]:
    if not api_key:
        if required:
            raise ValidationError("api_key", "clé API requise pour ce mode d'authentification")
        return None
    if any(c.isspace() for c in api_key) or any(ord(c) < 0x20 for c in api_key):
        raise ValidationError("api_key", "aucun espace ni caractère de contrôle autorisé")
    if not _API_KEY_RE.fullmatch(api_key):
        raise ValidationError("api_key", "16 à 512 caractères parmi A-Z a-z 0-9 - _ . ~")
    return api_key


def validate_api_type(api_type: str) -> str:
    api_type = (api_type or "chat_completions").lower()
    if api_type not in API_TYPE_CHOICES:
        raise ValidationError("api_type", f"doit être l'un de : {', '.join(sorted(API_TYPE_CHOICES))}")
    return api_type


def validate_auth_type(auth_type: str) -> str:
    auth_type = (auth_type or "bearer").lower()
    if auth_type not in AUTH_TYPE_CHOICES:
        raise ValidationError("auth_type", f"doit être l'un de : {', '.join(sorted(AUTH_TYPE_CHOICES))}")
    return auth_type


def validate_headers(headers: Optional[dict[str, str]]) -> dict[str, str]:
    """Empêche l'injection d'en-têtes : noms restreints à
    `^[A-Za-z0-9-]{1,64}$`, valeurs en ASCII imprimable uniquement, aucun
    CR/LF/NULL. `Authorization` est explicitement rejeté ici — construit
    séparément par build_auth_headers() à partir de auth_type/api_key,
    jamais depuis une valeur libre (voir spec : "sans que l'utilisateur
    puisse modifier la syntaxe")."""
    clean: dict[str, str] = {}
    for name, value in (headers or {}).items():
        if not _HEADER_NAME_RE.fullmatch(name or ""):
            raise ValidationError("headers", f"nom d'en-tête invalide : {name!r}")
        if name.lower() == "authorization":
            raise ValidationError("headers", "l'en-tête Authorization est géré automatiquement (voir Authentification), il ne peut pas être défini manuellement")
        value = value or ""
        if any(ch in value for ch in ("\r", "\n", "\x00")):
            raise ValidationError("headers", f"valeur d'en-tête invalide pour {name!r} (retour ligne ou NULL interdit)")
        if not all(0x20 <= ord(ch) <= 0x7E for ch in value):
            raise ValidationError("headers", f"valeur d'en-tête non-ASCII imprimable pour {name!r}")
        clean[name] = value
    return clean


def validate_timeout(timeout_s: int) -> int:
    if not isinstance(timeout_s, int) or isinstance(timeout_s, bool) or not (1 <= timeout_s <= 300):
        raise ValidationError("timeout_s", "entier entre 1 et 300 secondes")
    return timeout_s


def validate_max_retries(max_retries: int) -> int:
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or not (0 <= max_retries <= 10):
        raise ValidationError("max_retries", "entier entre 0 et 10")
    return max_retries


# ── validation complète d'un enregistrement ─────────────────────────────────

def validate_provider_fields(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    """Valide un enregistrement complet (POST) ou partiel (PATCH — seules
    les clés présentes dans `data` sont validées/retournées). L'auth_type
    final (nouveau si fourni, existant sinon pour un PATCH) détermine si
    `api_key` est obligatoire ; pour un PATCH, cette cohérence-là reste à la
    charge de l'appelant (api/providers.py connaît l'auth_type existant).
    """
    out: dict[str, Any] = {}

    def _has(key: str) -> bool:
        return (not partial) or (key in data)

    if _has("provider"):
        out["provider"] = validate_provider(data.get("provider", ""))
    if _has("label"):
        out["label"] = validate_label(data.get("label", ""))
    if _has("model"):
        out["model"] = validate_model(data.get("model", ""))
    if _has("api_type"):
        out["api_type"] = validate_api_type(data.get("api_type", "chat_completions"))
    if _has("auth_type"):
        out["auth_type"] = validate_auth_type(data.get("auth_type", "bearer"))

    auth_type_for_key_check = out.get("auth_type", data.get("auth_type", "bearer"))
    if _has("api_key") or (not partial):
        out["api_key"] = validate_api_key(
            data.get("api_key"), required=(auth_type_for_key_check != "none"),
        )

    if _has("endpoint"):
        out["endpoint"] = validate_endpoint(data.get("endpoint", ""))
    if _has("headers"):
        out["headers"] = validate_headers(data.get("headers"))
    if _has("timeout_s"):
        out["timeout_s"] = validate_timeout(data.get("timeout_s", 30))
    if _has("max_retries"):
        out["max_retries"] = validate_max_retries(data.get("max_retries", 3))
    if _has("http2"):
        out["http2"] = bool(data.get("http2", True))
    if _has("compression"):
        out["compression"] = bool(data.get("compression", True))

    return out
