"""
api.main
==========

Point d'entrée FastAPI. Lancer avec :
    uvicorn api.main:app --reload --port 8000
(depuis Nexus_Assistant/, avec nexus_compose, nexus_vendor et
requirements.txt installés — voir README.md, section "Fusion frontend ↔
backend").
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .codegen import router as codegen_router
from .conversations import router as conversations_router
from .pipeline import router as pipeline_router
from .providers import router as providers_router
from .registry import router as registry_router
from .security import router as security_router

# Données de démonstration réalistes pour amorcer les tables `findings`/
# `files` au premier démarrage — PAS de vraies sorties Bearer/Semgrep/
# CodeQL/crewAI (voir db.py::seed_if_empty pour pourquoi). Reprend le même
# contenu que nexus-ui/src/data/mockPipeline.ts pour rester cohérent avec
# ce que l'UI montrait déjà, plus un 4e finding SANS relatedNodeId pour
# exercer le cas (a) — "non applicable" — documenté dans security.py.
_SEED_FINDINGS = [
    {
        "id": "f1", "tool": "CodeQL", "severity": "warning",
        "title": "Secret potentiel en variable d'environnement",
        "detail": "CWE-312 · main.py:14", "relatedNodeId": "payment-service",
    },
    {
        "id": "f2", "tool": "STRIDE", "severity": "critical",
        "title": "Injection possible sur /payments",
        "detail": "Tampering · aucune validation d'entrée détectée",
        "relatedNodeId": "payment-controller",
    },
    {
        "id": "f3", "tool": "STRIDE", "severity": "critical",
        "title": "Contournement d'authentification possible",
        "detail": "Spoofing · vérifier la validation du token JWT",
        "relatedNodeId": "auth-middleware",
    },
    {
        "id": "f4", "tool": "Semgrep", "severity": "info",
        "title": "Dépendance obsolète détectée",
        "detail": "requirements.txt · aucun composant du graphe de menaces associé",
        "relatedNodeId": None,
    },
]

_SEED_BRANCHES = [
    {
        "id": "b1", "label": "API", "agent": "crewAI", "status": "done",
        "files": [
            {"id": "f_types", "path": "payment_service/models.py",
             "summary": "Types Pydantic PaymentRequest / PaymentResponse",
             "linesAdded": 42, "linesRemoved": 0, "status": "accepted"},
            {"id": "f_controller", "path": "payment_service/main.py",
             "summary": "Endpoint POST /payments + dépendance verify_jwt",
             "linesAdded": 68, "linesRemoved": 3, "status": "pending"},
            {"id": "f_openapi", "path": "payment_service/openapi.yaml",
             "summary": "Schéma OpenAPI généré depuis les routes FastAPI",
             "linesAdded": 120, "linesRemoved": 0, "status": "pending"},
        ],
    },
    {
        "id": "b2", "label": "Tests", "agent": "OpenHands", "status": "running",
        "files": [
            {"id": "f_unit", "path": "tests/test_payments.py",
             "summary": "Tests unitaires du endpoint /payments",
             "linesAdded": 54, "linesRemoved": 0, "status": "accepted"},
            {"id": "f_integration", "path": "tests/test_integration_stripe.py",
             "summary": "Test d'intégration avec un mock Stripe",
             "linesAdded": 31, "linesRemoved": 0, "status": "needs-fix"},
        ],
    },
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.seed_if_empty(_SEED_FINDINGS, _SEED_BRANCHES)
    yield


app = FastAPI(title="Nexus Assistant API", lifespan=lifespan)

# Origines par défaut de `npm run dev` (Vite) pour nexus-ui. Ajouter ici
# toute autre origine de déploiement au besoin — volontairement pas de
# wildcard "*" avec allow_credentials, qui ne serait pas correct pour un
# navigateur.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(pipeline_router)
app.include_router(security_router)
app.include_router(codegen_router)
app.include_router(conversations_router)
app.include_router(providers_router)
app.include_router(registry_router)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
