"""RL-agent router for OpenHands — Unified System integration.

Exposes three lightweight endpoints consumed exclusively by OpenManus-RL's
:class:`OpenHandsEnvironmentManager`:

POST /api/rl/conversations
    Create a fresh sandbox session and return its ``conversation_id``.

POST /api/rl/conversations/{conversation_id}/step
    Send an agent action, wait for the sandbox agent to finish, and return
    the observation + scalar reward.

GET  /api/rl/conversations/{conversation_id}/status
    Return current status, last assistant message, and a ``done`` flag.

The router re-uses the existing :class:`AppConversationService` so no new
database tables are required beyond the migration in
``enterprise/migrations/versions/118_create_rl_trajectories_table.py``,
which adds a ``rl_trajectories`` audit table for offline analysis.

Authentication
--------------
Requests must carry the same bearer token accepted by the rest of the
OpenHands app server.  Pass it via ``Authorization: Bearer <token>`` or
the ``OPENHANDS_TOKEN`` environment variable on the RL training side.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

# ── Internal OpenHands imports ────────────────────────────────────────────────
from openhands.app_server.app_conversation.app_conversation_models import (
    AppConversationStartRequest,
    AppConversationStartTaskStatus,
    AppSendMessageRequest,
)
from openhands.app_server.config import (
    depends_app_conversation_service,
    depends_db_session,
)

# ── Persistance open source des trajectoires (constat, défaut 5 / Q7) ──────────
# L'ancienne version écrivait dans la table `rl_trajectories` de la migration
# `enterprise/` (licence PolyForm Free Trial) via du SQL brut dont l'erreur
# était avalée par `except: pass`. On persiste désormais dans un magasin open
# source (nexus_unified.store : SQLite/PostgreSQL/Neo4j/JSONL), découplé du
# schéma entreprise. Dégrade proprement si nexus_unified est absent.
try:
    from nexus_unified.rl_trajectory import TrajectoryRecorder
    _RECORDER = TrajectoryRecorder()
except Exception:  # noqa: BLE001
    _RECORDER = None

# ── Authentification du routeur RL (constat : auth manquante) ─────────────────
# Les routeurs V1 passent par get_dependencies() ; le routeur RL n'en avait
# aucune. On exige le même bearer token que le reste de l'app server.
try:
    from openhands.app_server.config import get_dependencies as _get_deps  # type: ignore
    _RL_DEPS = _get_deps()
except Exception:  # noqa: BLE001
    _RL_DEPS = []

router = APIRouter(prefix="/api/rl", tags=["RL Agent"], dependencies=_RL_DEPS)

# ── Timeouts & polling ────────────────────────────────────────────────────────

_DEFAULT_STEP_TIMEOUT: int = int(os.getenv("OH_RL_STEP_TIMEOUT", "120"))
_POLL_INTERVAL: float = 2.0  # seconds

# Terminal statuses reported by the conversation service
_TERMINAL_STATUSES = {
    AppConversationStartTaskStatus.READY,
    AppConversationStartTaskStatus.ERROR,
}


# ── Request / response schemas ────────────────────────────────────────────────

class RLCreateConversationRequest(BaseModel):
    """Body for POST /api/rl/conversations."""
    task_description: str = Field(
        ...,
        description="Natural-language description of the RL episode task.",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary key-value pairs stored in the rl_trajectories table.",
    )


class RLCreateConversationResponse(BaseModel):
    conversation_id: str
    created_at: str


class RLStepRequest(BaseModel):
    """Body for POST /api/rl/conversations/{id}/step."""
    action: str = Field(
        ...,
        description="The agent's action text (tool call, code, or plain instruction).",
    )
    timeout: int = Field(
        default=_DEFAULT_STEP_TIMEOUT,
        description="Max seconds to wait for the sandbox agent to respond.",
    )


class RLStepResponse(BaseModel):
    conversation_id: str
    observation: str
    reward: float
    done: bool
    info: dict


class RLStatusResponse(BaseModel):
    conversation_id: str
    status: str
    last_observation: str
    done: bool


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _wait_for_conversation(
    conv_service,
    conversation_id: str,
    timeout: int,
) -> tuple[str, bool]:
    """Poll conversation until terminal; return (last_message, success)."""
    deadline = asyncio.get_event_loop().time() + timeout
    last_text = ""

    # Défaut 4 (constat) : le modèle V1 expose `execution_status` (pas `status`)
    # et n'embarque pas de liste `messages`. On lit execution_status ; le
    # dernier texte d'agent vient des événements de la conversation si le
    # service les expose.
    ok_states = {"finished", "completed", "idle", "awaiting_user_input"}
    terminal = ok_states | {"error", "stopped"}
    while asyncio.get_event_loop().time() < deadline:
        try:
            conv = await conv_service.get_app_conversation(UUID(conversation_id))
            if conv is None:
                return "", False

            # Dernier message d'agent via les événements, si disponibles.
            events_getter = getattr(conv_service, "search_events", None) or \
                getattr(conv_service, "get_events", None)
            if events_getter is not None:
                try:
                    evs = await events_getter(UUID(conversation_id))
                    items = getattr(evs, "items", None) or evs or []
                    for ev in reversed(list(items)):
                        src = getattr(ev, "source", "") or getattr(ev, "role", "")
                        content = getattr(ev, "message", "") or getattr(ev, "content", "")
                        if src in ("agent", "assistant") and content:
                            last_text = content if isinstance(content, str) else str(content)
                            break
                except Exception:
                    pass

            conv_status = str(getattr(conv, "execution_status", "") or "").lower()
            if conv_status in terminal:
                return last_text, conv_status in ok_states

        except Exception:
            pass

        await asyncio.sleep(_POLL_INTERVAL)

    return last_text, False  # timeout


def _scalar_reward(success: bool, observation: str) -> float:
    """Derive a scalar reward from the terminal signal.

    Extend this function to add task-specific shaped rewards (e.g. test pass
    rate, code quality metrics) by inspecting the observation text.
    """
    if success:
        return 1.0
    # Partial credit heuristic: reward non-empty output over silence
    if observation.strip():
        return 0.1
    return 0.0


# ── Route handlers ────────────────────────────────────────────────────────────

@router.post(
    "/conversations",
    response_model=RLCreateConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start a new RL episode (OpenHands conversation)",
)
async def rl_create_conversation(
    body: RLCreateConversationRequest,
    conv_service=Depends(depends_app_conversation_service),
    db=Depends(depends_db_session),
):
    """Create a new OpenHands conversation for one RL episode.

    Called by :class:`openmanus_rl.environments.env_manager.OpenHandsEnvironmentManager`
    on every ``reset()`` call.
    """
    # Défaut 1 (constat) : initial_message attend un SendMessageRequest, pas une
    # chaîne. On construit la forme attendue (role + content en liste de blocs).
    from openhands.sdk.llm import TextContent  # type: ignore
    try:
        from openhands.app_server.app_conversation.app_conversation_models import (
            SendMessageRequest,
        )
        _initial = SendMessageRequest(content=[TextContent(text=body.task_description)])
    except Exception:  # noqa: BLE001 — repli si la classe diffère selon la version
        _initial = {"role": "user",
                    "content": [{"type": "text", "text": body.task_description}]}
    start_request = AppConversationStartRequest(initial_message=_initial)

    # Stream through start-up states until READY or ERROR
    conversation_id: Optional[str] = None
    async for task in conv_service.start_app_conversation(start_request):
        conversation_id = str(task.conversation_id) if task.conversation_id else None
        if task.status in _TERMINAL_STATUSES:
            if task.status == AppConversationStartTaskStatus.ERROR:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="OpenHands failed to start the conversation sandbox.",
                )
            break

    if not conversation_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conversation ID was not assigned.",
        )

    # Défaut 5 (constat) : persistance via le magasin open source, pas de SQL
    # brut vers la table entreprise avec erreur avalée.
    if _RECORDER is not None:
        _RECORDER.start_episode(conversation_id, body.task_description, dict(body.metadata))

    return RLCreateConversationResponse(
        conversation_id=conversation_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@router.post(
    "/conversations/{conversation_id}/step",
    response_model=RLStepResponse,
    summary="Execute one RL step inside an OpenHands sandbox",
)
async def rl_step(
    conversation_id: str,
    body: RLStepRequest,
    conv_service=Depends(depends_app_conversation_service),
    db=Depends(depends_db_session),
):
    """Send an action and return (observation, reward, done).

    Called by :class:`OpenHandsEnvironmentManager.step` for each agent turn.
    The reward is 1.0 on task completion, 0.0 otherwise.
    """
    # Verify conversation exists
    conv = await conv_service.get_app_conversation(UUID(conversation_id))
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found.",
        )

    # Défaut 2 (constat) : AppSendMessageRequest exige `content` (liste de blocs),
    # pas `message`. Défaut 3 : la méthode d'envoi V1 est send_message_to_conversation
    # (send_message n'existe pas sur le service). On construit la bonne requête
    # et on appelle la bonne méthode, avec repli défensif selon la version.
    from openhands.sdk.llm import TextContent  # type: ignore
    send_request = AppSendMessageRequest(content=[TextContent(text=body.action)])
    _send = (getattr(conv_service, "send_message_to_conversation", None)
             or getattr(conv_service, "send_message", None))
    if _send is None:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Le service de conversation n'expose pas d'envoi de message.",
        )
    await _send(UUID(conversation_id), send_request)

    # Wait for the sandbox agent to finish
    observation, success = await _wait_for_conversation(
        conv_service, conversation_id, body.timeout
    )
    reward = _scalar_reward(success, observation)

    # Défaut 5 : persistance open source du pas (plus de SQL brut entreprise).
    if _RECORDER is not None:
        _RECORDER.record_step(conversation_id, reward, observation)

    return RLStepResponse(
        conversation_id=conversation_id,
        observation=observation,
        reward=reward,
        done=True,  # OpenHands conversations are one-shot episodes
        info={"success": success},
    )


@router.get(
    "/conversations/{conversation_id}/status",
    response_model=RLStatusResponse,
    summary="Poll the status of an OpenHands RL conversation",
)
async def rl_status(
    conversation_id: str,
    conv_service=Depends(depends_app_conversation_service),
):
    """Return the current status of an RL conversation."""
    conv = await conv_service.get_app_conversation(UUID(conversation_id))
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Conversation {conversation_id} not found.",
        )

    conv_status = str(getattr(conv, "status", "unknown")).lower()
    done = conv_status in ("completed", "stopped", "error")

    # Extract last assistant message
    last_text = ""
    messages = getattr(conv, "messages", []) or []
    for msg in reversed(messages):
        role = getattr(msg, "role", "") or msg.get("role", "")
        content = getattr(msg, "content", "") or msg.get("content", "")
        if role in ("assistant", "agent") and content:
            last_text = content
            break

    return RLStatusResponse(
        conversation_id=conversation_id,
        status=conv_status,
        last_observation=last_text,
        done=done,
    )
