"""nexus_unified.openhands_client — client de l'API OpenHands V1 (corrige le lot 0).

Le constat a montré que les clients existants (`OpenHandsTask`,
`OpenHandsEnvironmentManager`) appellent l'API V0 (`/api/conversations`), absente
du serveur V1 fourni dans le système (point 6). Ce client parle les vraies
routes V1 :

- `POST /api/v1/app-conversations`            — démarre une conversation ;
  le message initial est un `SendMessageRequest` (role + content=[TextContent]) ;
- `GET  /api/v1/app-conversations/start-tasks`— attend READY/ERROR ;
- `POST /api/v1/app-conversations/{id}/send-message` — content = liste de blocs ;
- `GET  /api/v1/app-conversations`            — statut via `execution_status` ;
- `GET  /api/v1/conversation/{id}/events/search` — trajectoire ;
- `GET  /api/v1/app-conversations/{id}/git/diff`  — diff produit.

Le client est entièrement testable hors serveur via un transport httpx injecté.
Sans serveur joignable, il renvoie une erreur explicite (jamais un faux succès).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

try:
    import httpx
    _HTTPX = True
except Exception:  # pragma: no cover
    _HTTPX = False

V1 = "/api/v1"
_TERMINAL_EXEC = {"finished", "completed", "stopped", "error", "idle", "awaiting_user_input"}
_OK_EXEC = {"finished", "completed", "idle", "awaiting_user_input"}


@dataclass
class OHResult:
    ok: bool
    conversation_id: str = ""
    output: str = ""
    git_diff: str = ""
    events: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    execution_status: str = ""


class OpenHandsV1Client:
    def __init__(self, base_url: str = "http://localhost:3000", token: str = "",
                 timeout: int = 120, *, transport: Any = None, poll_interval: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._transport = transport        # httpx MockTransport en test
        if not _HTTPX:
            raise RuntimeError("httpx requis pour OpenHandsV1Client")

    # ── HTTP ────────────────────────────────────────────────────────────────
    def _client(self):
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return httpx.Client(base_url=self.base_url, headers=headers,
                            timeout=self.timeout, transport=self._transport)

    def _req(self, method: str, path: str, **kw) -> "httpx.Response":
        with self._client() as c:
            return c.request(method, path, **kw)

    # ── santé ─────────────────────────────────────────────────────────────────
    def health(self) -> Dict[str, Any]:
        try:
            r = self._req("GET", "/health")
            return {"ok": r.status_code // 100 == 2, "status_code": r.status_code}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    # ── primitives V1 ─────────────────────────────────────────────────────────
    @staticmethod
    def _message(text: str) -> Dict[str, Any]:
        """SendMessageRequest : role + content = liste de TextContent (défaut 1)."""
        return {"role": "user", "content": [{"type": "text", "text": text}], "run": True}

    def start_conversation(self, task: str) -> str:
        body = {"initial_message": self._message(task)}
        r = self._req("POST", f"{V1}/app-conversations", json=body)
        r.raise_for_status()
        data = r.json()
        cid = str(data.get("conversation_id") or data.get("id") or
                  (data.get("conversation") or {}).get("id") or "")
        if not cid:
            raise OHError("aucun conversation_id renvoyé par le serveur")
        return cid

    def wait_ready(self, conversation_id: str, timeout: Optional[int] = None) -> str:
        """Attend qu'une start-task atteigne READY/ERROR. Retourne le statut."""
        deadline = time.time() + (timeout or self.timeout)
        while time.time() < deadline:
            r = self._req("GET", f"{V1}/app-conversations/start-tasks",
                          params={"conversation_id": conversation_id})
            if r.status_code // 100 == 2:
                for task in _items(r.json()):
                    if str(task.get("conversation_id")) == conversation_id:
                        st = str(task.get("status", "")).upper()
                        if st in ("READY", "ERROR"):
                            return st
            time.sleep(self.poll_interval)
        return "TIMEOUT"

    def send_message(self, conversation_id: str, text: str) -> None:
        r = self._req("POST", f"{V1}/app-conversations/{conversation_id}/send-message",
                      json=self._message(text))
        r.raise_for_status()

    def get_conversation(self, conversation_id: str) -> Dict[str, Any]:
        r = self._req("GET", f"{V1}/app-conversations",
                      params={"conversation_id": conversation_id})
        r.raise_for_status()
        for c in _items(r.json()):
            if str(c.get("id") or c.get("conversation_id")) == conversation_id:
                return c
        data = r.json()
        return data if isinstance(data, dict) else {}

    def wait_execution(self, conversation_id: str, timeout: Optional[int] = None) -> str:
        deadline = time.time() + (timeout or self.timeout)
        last = ""
        while time.time() < deadline:
            conv = self.get_conversation(conversation_id)
            last = str(conv.get("execution_status") or "").lower()
            if last in _TERMINAL_EXEC:
                return last
            time.sleep(self.poll_interval)
        return last or "timeout"

    def events(self, conversation_id: str, limit: int = 200) -> List[Dict[str, Any]]:
        r = self._req("GET", f"{V1}/conversation/{conversation_id}/events/search",
                      params={"limit": limit})
        if r.status_code // 100 != 2:
            return []
        return _items(r.json())

    def git_diff(self, conversation_id: str) -> str:
        r = self._req("GET", f"{V1}/app-conversations/{conversation_id}/git/diff")
        if r.status_code // 100 != 2:
            return ""
        data = r.json()
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("diff") or data.get("patch") or ""
        return ""

    def last_agent_text(self, events: List[Dict[str, Any]]) -> str:
        for ev in reversed(events):
            src = ev.get("source") or ev.get("role")
            if src in ("agent", "assistant"):
                msg = ev.get("message") or ev.get("content") or ev.get("text")
                if isinstance(msg, list):
                    msg = " ".join(p.get("text", "") for p in msg if isinstance(p, dict))
                if msg:
                    return str(msg)
        return ""

    # ── haut niveau ───────────────────────────────────────────────────────────
    def run_task(self, instruction: str) -> OHResult:
        """Démarre une conversation, attend la fin, renvoie sortie + diff + trajectoire."""
        try:
            cid = self.start_conversation(instruction)
        except Exception as exc:  # noqa: BLE001
            return OHResult(False, error=f"démarrage impossible : {type(exc).__name__}: {exc}")
        ready = self.wait_ready(cid)
        if ready == "ERROR":
            return OHResult(False, conversation_id=cid, error="le sandbox a échoué au démarrage")
        exec_status = self.wait_execution(cid)
        evs = self.events(cid)
        res = OHResult(
            ok=exec_status in _OK_EXEC,
            conversation_id=cid,
            output=self.last_agent_text(evs),
            git_diff=self.git_diff(cid),
            events=evs,
            execution_status=exec_status,
        )
        if not res.ok and not res.error:
            res.error = f"statut d'exécution terminal : {exec_status}"
        return res


class OHError(RuntimeError):
    pass


def _items(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in ("items", "results", "events", "tasks", "conversations", "data"):
            if isinstance(data.get(k), list):
                return data[k]
        return [data]
    return []
