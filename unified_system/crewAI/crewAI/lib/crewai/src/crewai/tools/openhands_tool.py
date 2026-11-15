"""crewAI ↔ OpenHands integration tool.

Exposes the OpenHands conversation API as a first-class crewAI BaseTool so
that any Crew can delegate software-development tasks (coding, testing, file
editing, shell commands) to an isolated OpenHands sandbox.

HTTP requests are routed through crewAI's SSRF-protected session
(:mod:`crewai_tools.security.safe_requests`) so that LLM-generated URLs
cannot reach internal networks.

Usage::

    from crewai import Agent, Crew, Task
    from crewai.tools.openhands_tool import OpenHandsTask

    oh_tool = OpenHandsTask(
        openhands_base_url="http://localhost:3000",
        openhands_token="",          # set if auth is enabled
        timeout=120,
    )

    coder = Agent(
        role="Software engineer",
        goal="Implement the requested feature",
        tools=[oh_tool],
    )
    task = Task(
        description="Write a Python script that prints Fibonacci numbers up to 100.",
        agent=coder,
    )
    crew = Crew(agents=[coder], tasks=[task])
    result = crew.kickoff()
"""

from __future__ import annotations

import time
import uuid
from typing import Any, Optional, Type

from pydantic import BaseModel, Field

from crewai.tools.base_tool import BaseTool


def _first_conv(body: Any, conv_id: str) -> dict:
    """Extrait la conversation ciblée d'une réponse V1 (liste/items/objet)."""
    items = body if isinstance(body, list) else (
        (body.get("items") or body.get("conversations") or [body])
        if isinstance(body, dict) else [])
    for c in items:
        if isinstance(c, dict) and str(c.get("id") or c.get("conversation_id")) == conv_id:
            return c
    return items[0] if items and isinstance(items[0], dict) else {}


def _last_agent_text(body: Any) -> str:
    """Dernier message d'agent d'une recherche d'événements V1."""
    items = body if isinstance(body, list) else (
        (body.get("items") or body.get("events") or [])
        if isinstance(body, dict) else [])
    for ev in reversed(items):
        if isinstance(ev, dict) and (ev.get("source") or ev.get("role")) in ("agent", "assistant"):
            msg = ev.get("message") or ev.get("content") or ev.get("text") or ""
            if isinstance(msg, list):
                msg = " ".join(p.get("text", "") for p in msg if isinstance(p, dict))
            if msg:
                return str(msg)
    return ""

try:
    from crewai_tools.security.safe_requests import create_safe_session
    _SAFE_SESSION_FACTORY = create_safe_session
except ImportError:
    import requests as _requests
    _SAFE_SESSION_FACTORY = _requests.Session  # type: ignore[assignment]


# ── Input schema ──────────────────────────────────────────────────────────────

class OpenHandsTaskInput(BaseModel):
    """Input for the OpenHandsTask tool."""

    instruction: str = Field(
        ...,
        description=(
            "The full natural-language instruction to send to the OpenHands agent. "
            "Be specific: include the programming language, expected output format, "
            "and any constraints."
        ),
    )
    conversation_id: Optional[str] = Field(
        default=None,
        description=(
            "Resume an existing OpenHands conversation. "
            "Leave blank to start a fresh sandbox session."
        ),
    )


# ── Tool implementation ───────────────────────────────────────────────────────

class OpenHandsTask(BaseTool):
    """crewAI tool that runs a task inside an OpenHands sandbox.

    The tool creates (or resumes) an OpenHands conversation, sends the agent's
    instruction as a user message, polls until the sandbox agent finishes, and
    returns the final assistant message as a plain string.

    Args:
        openhands_base_url: Base URL of the OpenHands server.
        openhands_token: Bearer token for authentication (empty string = no auth).
        timeout: Maximum seconds to wait for the sandbox agent to finish.
        poll_interval: Seconds between status polls.
    """

    # ── crewAI BaseTool metadata ──────────────────────────────────────────

    name: str = "openhands_task"
    description: str = (
        "Delegate a software-development task to an isolated OpenHands sandbox. "
        "Useful for writing code, running shell commands, editing files, or "
        "executing tests in a controlled environment. "
        "Provide a precise instruction; the tool returns the sandbox agent's output."
    )
    args_schema: Type[BaseModel] = OpenHandsTaskInput

    # ── Configuration (set via __init__ kwargs) ───────────────────────────

    openhands_base_url: str = "http://localhost:3000"
    openhands_token: str = ""
    timeout: int = 120
    poll_interval: int = 2

    # ── Internals ─────────────────────────────────────────────────────────

    _session: Any = None  # requests.Session (SSRF-safe)

    def model_post_init(self, __context: Any) -> None:
        """Build the HTTP session after Pydantic initialisation."""
        session = _SAFE_SESSION_FACTORY()
        session.headers["Content-Type"] = "application/json"
        if self.openhands_token:
            session.headers["Authorization"] = f"Bearer {self.openhands_token}"
        self._session = session

    # ── BaseTool interface ────────────────────────────────────────────────

    def _run(
        self,
        instruction: str,
        conversation_id: Optional[str] = None,
        **_: Any,
    ) -> str:
        """Execute synchronously and return the sandbox output.

        API OpenHands V1 (corrigé — constat lot 0). L'ancien code appelait
        /api/conversations (V0), absente du serveur V1 : création via
        /api/v1/app-conversations (message initial = SendMessageRequest avec
        content en liste), envoi via .../send-message, statut via
        execution_status, sortie via la recherche d'événements.
        """
        base = self.openhands_base_url.rstrip("/")

        def _msg(text):
            return {"role": "user", "content": [{"type": "text", "text": text}], "run": True}

        # 1. Create or reuse conversation (tâche transmise dès la création)
        if not conversation_id:
            resp = self._session.post(
                f"{base}/api/v1/app-conversations",
                json={"initial_message": _msg(instruction)},
            )
            resp.raise_for_status()
            data = resp.json()
            conversation_id = (
                data.get("conversation_id")
                or data.get("id")
                or (data.get("conversation") or {}).get("id")
                or str(uuid.uuid4())
            )
        else:
            # 2. Send the instruction to an existing conversation
            self._session.post(
                f"{base}/api/v1/app-conversations/{conversation_id}/send-message",
                json=_msg(instruction),
            ).raise_for_status()

        # 3. Poll until the sandbox agent completes
        deadline = time.monotonic() + self.timeout
        last_output = ""
        _ok = ("finished", "completed", "idle", "awaiting_user_input")
        _terminal = _ok + ("error", "stopped")

        while time.monotonic() < deadline:
            try:
                poll = self._session.get(
                    f"{base}/api/v1/app-conversations",
                    params={"conversation_id": conversation_id},
                )
                poll.raise_for_status()
                body = poll.json()
                conv = _first_conv(body, conversation_id)

                # Dernier message agent via la recherche d'événements V1
                try:
                    ev = self._session.get(
                        f"{base}/api/v1/conversation/{conversation_id}/events/search",
                        params={"limit": 100},
                    ).json()
                    last_output = _last_agent_text(ev) or last_output
                except Exception:  # noqa: BLE001
                    pass

                status = str(conv.get("execution_status", "")).lower()
                if status in _terminal:
                    status = "completed" if status in _ok else status
                    if status == "error":
                        return (
                            f"[OpenHands] Task failed.\n"
                            f"Conversation: {conversation_id}\n"
                            f"Last output:\n{last_output}"
                        )
                    return (
                        f"[OpenHands] Task completed.\n"
                        f"Conversation: {conversation_id}\n"
                        f"Output:\n{last_output}"
                    )
            except Exception as exc:  # noqa: BLE001
                last_output = f"[Poll error: {exc}]"

            time.sleep(self.poll_interval)

        # Timeout
        return (
            f"[OpenHands] Timeout after {self.timeout}s.\n"
            f"Conversation: {conversation_id}\n"
            f"Last known output:\n{last_output}"
        )

    async def _arun(
        self,
        instruction: str,
        conversation_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """Async variant — runs the sync implementation in a thread pool."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._run(instruction, conversation_id, **kwargs),
        )
