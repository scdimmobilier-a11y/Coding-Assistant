"""nexus_unified.llm.gateway — LLM global, tout fournisseur, externe à la pipeline.

Points 3 et 4 : un seul LLM pour tout le système, de n'importe quel fournisseur,
et extérieur à cette pipeline — le cerveau n'est jamais embarqué, c'est un
endpoint + une clé résolus par le point de configuration unique existant
(`nexus_compose.llm_config.get_llm_config`). La passerelle ne connaît aucun
modèle en dur ; elle route un appel de chat vers le fournisseur actif.

Deux schémas d'API couverts nativement :
- **chat_completions** (OpenAI, OpenRouter, Groq, Mistral, vLLM, Ollama,
  LM Studio, NVIDIA NIM…) ;
- **messages** (Anthropic) via `api_type="messages"`.

La passerelle sert aussi l'orchestrateur maître (point 5) : `plan_tasks`
transforme un but en une liste de tâches d'agents, en demandant au LLM une
sortie JSON stricte puis en la validant.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

try:
    import httpx
    _HTTPX = True
except Exception:  # pragma: no cover
    _HTTPX = False

# Résolution de la config unique (externe, tout fournisseur).
try:
    from nexus_compose.llm_config import get_llm_config, LLMConfig
except Exception:  # package utilisable seul dans les tests
    LLMConfig = Any  # type: ignore

    def get_llm_config(overrides=None):  # type: ignore
        class _C:
            provider = os.getenv("NEXUS_LLM_PROVIDER", "openai")
            model = os.getenv("NEXUS_LLM_MODEL", "gpt-4o-mini")
            api_key = os.getenv("NEXUS_LLM_API_KEY", "")
            base_url = os.getenv("NEXUS_LLM_BASE_URL") or None
            endpoint = None
            api_type = "chat_completions"
            auth_type = "bearer"
            extra_headers: dict = {}
            timeout = 60
            max_retries = 3
        c = _C()
        for k, v in (overrides or {}).items():
            setattr(c, k, v)
        return c


@dataclass
class ChatResult:
    ok: bool
    text: str = ""
    error: Optional[str] = None
    status_code: Optional[int] = None
    model: str = ""
    provider: str = ""
    usage: Dict[str, Any] = field(default_factory=dict)
    attempts: int = 1


class LLMGateway:
    """Passerelle d'appel LLM unique. `config_overrides` permet de forcer
    ponctuellement un modèle/fournisseur sans toucher la config globale."""

    def __init__(self, config_overrides: Optional[Dict[str, Any]] = None) -> None:
        self._overrides = config_overrides or {}

    def config(self) -> Any:
        return get_llm_config(self._overrides or None)

    def describe(self) -> Dict[str, Any]:
        c = self.config()
        return {"provider": c.provider, "model": c.model,
                "api_type": getattr(c, "api_type", "chat_completions"),
                "has_key": bool(c.api_key),
                "base_url": getattr(c, "base_url", None),
                "external": True}

    # ── chat générique ────────────────────────────────────────────────────
    def chat(self, messages: List[Dict[str, str]], *, system: Optional[str] = None,
             max_tokens: int = 1024, temperature: float = 0.2,
             json_mode: bool = False, stop: Optional[List[str]] = None) -> ChatResult:
        c = self.config()
        if not _HTTPX:
            return ChatResult(False, error="httpx indisponible")
        api_type = getattr(c, "api_type", "chat_completions") or "chat_completions"
        url = self._endpoint(c, api_type)
        if not url:
            return ChatResult(False, error="endpoint LLM non résolu", provider=c.provider)
        headers = self._headers(c)
        if api_type == "messages":
            body = self._anthropic_body(c, messages, system, max_tokens, temperature, stop)
            headers.setdefault("anthropic-version", "2023-06-01")
        else:
            body = self._openai_body(c, messages, system, max_tokens, temperature, json_mode, stop)

        last_err = None
        attempts = max(1, int(getattr(c, "max_retries", 3)))
        for attempt in range(1, attempts + 1):
            try:
                with httpx.Client(timeout=getattr(c, "timeout", 60)) as client:
                    r = client.post(url, headers=headers, json=body)
                if r.status_code // 100 == 2:
                    text = self._parse(api_type, r.json())
                    return ChatResult(True, text=text or "", status_code=r.status_code,
                                      model=c.model, provider=c.provider,
                                      usage=self._usage(r.json()), attempts=attempt)
                last_err = f"HTTP {r.status_code}: {r.text[:200]}"
                if r.status_code in (400, 401, 403, 404, 422):
                    break  # inutile de retenter une erreur cliente
            except Exception as exc:  # noqa: BLE001
                last_err = f"{type(exc).__name__}: {exc}"
        return ChatResult(False, error=last_err, model=c.model, provider=c.provider, attempts=attempts)

    def complete(self, prompt: str, **kw) -> ChatResult:
        return self.chat([{"role": "user", "content": prompt}], **kw)

    # ── planification de tâches (orchestrateur maître, point 5) ─────────────
    def plan_tasks(self, goal: str, *, available_actions: List[str],
                   context: Optional[str] = None, max_tasks: int = 12) -> "TaskPlan":
        """Demande au LLM de décomposer un but en tâches d'agents, limitées aux
        actions disponibles. Sortie JSON stricte, validée ; repli déterministe
        si le LLM est injoignable."""
        actions_desc = "\n".join(f"- {a}" for a in available_actions)
        sys = (
            "Tu es l'orchestrateur maître d'un système d'agents. On te donne un BUT et "
            "la liste des ACTIONS disponibles (identifiants de nœuds). Découpe le but en "
            "tâches ordonnées, chacune affectée à UNE action de la liste, et rien d'autre. "
            "Réponds UNIQUEMENT par un objet JSON de la forme "
            '{"tasks":[{"id":"t1","action":"<id>","goal":"...","inputs":{},"depends_on":[]}]}'
            ". Aucune action hors de la liste. Pas de texte hors du JSON.")
        user = f"BUT:\n{goal}\n\nACTIONS DISPONIBLES:\n{actions_desc}"
        if context:
            user += f"\n\nCONTEXTE:\n{context}"
        res = self.chat([{"role": "user", "content": user}], system=sys,
                        max_tokens=1500, temperature=0.0, json_mode=True)
        if res.ok and res.text:
            plan = TaskPlan.parse(res.text, set(available_actions), max_tasks)
            if plan.tasks:
                plan.source = "llm"
                return plan
        # Repli : une tâche par action nommée dans le but, sinon la première action.
        return TaskPlan.fallback(goal, available_actions, max_tasks)

    # ── interne ────────────────────────────────────────────────────────────
    def _endpoint(self, c: Any, api_type: str) -> Optional[str]:
        ep = getattr(c, "endpoint", None)
        if ep:
            return ep
        base = getattr(c, "base_url", None)
        if not base:
            base = {"openai": "https://api.openai.com/v1",
                    "anthropic": "https://api.anthropic.com/v1",
                    "groq": "https://api.groq.com/openai/v1",
                    "openrouter": "https://openrouter.ai/api/v1",
                    "mistral": "https://api.mistral.ai/v1"}.get(c.provider)
        if not base:
            return None
        base = base.rstrip("/")
        if api_type == "messages":
            return base + "/messages"
        if base.endswith(("/chat/completions", "/messages", "/responses")):
            return base
        return base + "/chat/completions"

    def _headers(self, c: Any) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        h.update(getattr(c, "extra_headers", {}) or {})
        auth = (getattr(c, "auth_type", "bearer") or "bearer").lower()
        key = c.api_key
        if key:
            if c.provider == "anthropic" or getattr(c, "api_type", "") == "messages":
                h.setdefault("x-api-key", key)
            elif auth == "api_key":
                h.setdefault("x-api-key", key)
            else:
                h.setdefault("Authorization", f"Bearer {key}")
        return h

    def _openai_body(self, c, messages, system, max_tokens, temperature, json_mode, stop):
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        body: Dict[str, Any] = {"model": c.model, "messages": msgs,
                                "max_tokens": max_tokens, "temperature": temperature}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if stop:
            body["stop"] = stop
        return body

    def _anthropic_body(self, c, messages, system, max_tokens, temperature, stop):
        body: Dict[str, Any] = {"model": c.model, "max_tokens": max_tokens,
                                "temperature": temperature,
                                "messages": [{"role": m["role"], "content": m["content"]}
                                             for m in messages if m["role"] != "system"]}
        sys_parts = [m["content"] for m in messages if m["role"] == "system"]
        if system:
            sys_parts.insert(0, system)
        if sys_parts:
            body["system"] = "\n\n".join(sys_parts)
        if stop:
            body["stop_sequences"] = stop
        return body

    def _parse(self, api_type: str, data: Any) -> Optional[str]:
        if not isinstance(data, dict):
            return None
        try:
            if api_type == "messages":
                parts = data.get("content", [])
                return "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

    def _usage(self, data: Any) -> Dict[str, Any]:
        if isinstance(data, dict) and isinstance(data.get("usage"), dict):
            return data["usage"]
        return {}


@dataclass
class AgentTask:
    id: str
    action: str
    goal: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    depends_on: List[str] = field(default_factory=list)


@dataclass
class TaskPlan:
    goal: str
    tasks: List[AgentTask] = field(default_factory=list)
    source: str = "llm"      # "llm" | "fallback"

    @classmethod
    def parse(cls, text: str, allowed: set, max_tasks: int) -> "TaskPlan":
        obj = _extract_json(text)
        tasks: List[AgentTask] = []
        if isinstance(obj, dict):
            for t in obj.get("tasks", [])[:max_tasks]:
                if not isinstance(t, dict):
                    continue
                action = str(t.get("action", "")).strip()
                if action not in allowed:
                    continue  # jamais une action hors du registre
                tasks.append(AgentTask(
                    id=str(t.get("id") or f"t{len(tasks)+1}"),
                    action=action, goal=str(t.get("goal", "")),
                    inputs=t.get("inputs") if isinstance(t.get("inputs"), dict) else {},
                    depends_on=[str(d) for d in t.get("depends_on", []) if isinstance(d, (str, int))]))
        return cls(goal="", tasks=tasks)

    @classmethod
    def fallback(cls, goal: str, actions: List[str], max_tasks: int) -> "TaskPlan":
        named = [a for a in actions if a.lower() in goal.lower()][:max_tasks]
        picked = named or actions[:1]
        tasks = [AgentTask(id=f"t{i+1}", action=a, goal=goal) for i, a in enumerate(picked)]
        return cls(goal=goal, tasks=tasks, source="fallback")

    def to_dict(self) -> Dict[str, Any]:
        return {"goal": self.goal, "source": self.source,
                "tasks": [vars(t) for t in self.tasks]}


def _extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None
