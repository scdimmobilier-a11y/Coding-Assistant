"""Minimal OpenAI chat wrapper.

Provides a small surface compatible with internal code paths that expect
`ChatOpenAI` with a callable interface. Supports OpenAI-compatible backends
such as vLLM by honoring `OPENAI_BASE_URL`.
"""

from typing import Optional, List, Dict, Any, Type
import json
import re
try:
    from pydantic import BaseModel  # type: ignore
except Exception:  # pragma: no cover
    BaseModel = object  # type: ignore
import os

try:
    from openai import OpenAI  # type: ignore
except Exception as exc:  # pragma: no cover
    OpenAI = None  # type: ignore


class ChatOpenAI:
    """Thin wrapper around OpenAI's Chat Completions API.

    The instance is callable and returns plain text. Images are not sent as
    binary by design to remain compatible with OpenAI-compatible servers that
    do not support multimodal content; image paths are appended as text hints.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        temperature: float = 0.0,
    ) -> None:
        if OpenAI is None:
            raise RuntimeError("openai package is not installed")

        self.model = model
        self.temperature = temperature
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "EMPTY")
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def __call__(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        system: Optional[str] = None,
        response_format: Optional[Type] = None,
        **_: Any,
    ) -> Any:
        messages: List[Dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})

        if not images:
            messages.append({"role": "user", "content": prompt})
        else:
            # Safe multimodal fallback: append image paths as text hints.
            content = prompt
            for p in images:
                content += f"\n[Image: {p}]"
            messages.append({"role": "user", "content": content})

        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            n=1,
        )
        text = (resp.choices[0].message.content or "").strip()

        # Best-effort structured parsing when a pydantic model is requested
        try:
            if response_format and isinstance(response_format, type) and issubclass(response_format, BaseModel):
                # Try JSON first
                try:
                    data = json.loads(text)
                    if isinstance(data, dict):
                        return response_format(**data)
                    if isinstance(data, list):
                        # Common pattern: patch list
                        payload: Dict[str, Any] = {}
                        if hasattr(response_format, "model_fields") and "patch" in response_format.model_fields:  # pydantic v2
                            payload["patch"] = data
                        elif hasattr(response_format, "__fields__") and "patch" in getattr(response_format, "__fields__"):
                            payload["patch"] = data
                        if payload:
                            return response_format(**payload)
                except Exception:
                    pass

                # Special-case: AnswerVerification(analysis: str, true_false: bool)
                if getattr(response_format, "__name__", "") == "AnswerVerification":
                    analysis = ""
                    tf = False
                    m = re.search(r"<analysis>\s*(.*?)\s*</analysis>", text, re.DOTALL)
                    if m:
                        analysis = m.group(1).strip()
                    m2 = re.search(r"<true_false>\s*(.*?)\s*</true_false>", text, re.DOTALL)
                    if m2:
                        val = m2.group(1).strip().lower()
                        tf = val in ("true", "1", "yes")
                    if not analysis:
                        analysis = text
                    return response_format(analysis=analysis, true_false=tf)

                # Fallback: try to populate known common fields
                payload: Dict[str, Any] = {}
                for field in ("analysis", "text"):
                    if (hasattr(response_format, "model_fields") and field in response_format.model_fields) or (
                        hasattr(response_format, "__fields__") and field in getattr(response_format, "__fields__")
                    ):
                        payload[field] = text
                if payload:
                    return response_format(**payload)
        except Exception:
            # Swallow parsing errors and return raw text
            pass

        return text


# ──────────────────────────────────────────────────────────────────────────────
# UNIFIED SYSTEM — crewAI engine
# Wraps a crewAI Crew as a drop-in policy backend for OpenManus-RL rollouts.
# The crew replaces the raw LLM call: it receives the observation as a task
# description and returns the agent's action text.
# ──────────────────────────────────────────────────────────────────────────────

class CrewAIEngine:
    """Use a crewAI Crew as the policy engine in OpenManus-RL.

    Instead of calling an LLM directly, this engine delegates every prompt to
    a crewAI Crew.  The crew is expected to contain a single agent whose task
    is constructed from the RL observation at runtime.

    Args:
        crew_factory: Callable[[], Crew] — a zero-argument factory that returns
            a fresh crewAI Crew instance.  A factory is used (rather than a
            shared instance) so each rollout thread gets an isolated crew.
        crew_input_key: The key passed to ``crew.kickoff(inputs={key: obs})``.
            Defaults to ``"observation"``.

    Usage::

        from crewai import Agent, Crew, Task
        from openmanus_rl.engines.openai import CrewAIEngine

        def my_crew():
            agent = Agent(role="RL actor", goal="Complete the task", ...)
            task  = Task(description="Solve: {observation}", agent=agent)
            return Crew(agents=[agent], tasks=[task], verbose=False)

        engine = CrewAIEngine(crew_factory=my_crew)
        action = engine(prompt="You are in a room. You see a key.")
    """

    def __init__(
        self,
        crew_factory,
        crew_input_key: str = "observation",
    ) -> None:
        try:
            from crewai import Crew  # noqa: F401 — import check only
        except ImportError as exc:
            raise ImportError(
                "crewai is not installed. "
                "Install it with: pip install crewai"
            ) from exc

        self._crew_factory = crew_factory
        self._crew_input_key = crew_input_key

    # ── Public interface matching ChatOpenAI.__call__ ──────────────────────

    def __call__(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        system: Optional[str] = None,
        response_format: Optional[type] = None,
        **_: Any,
    ) -> str:
        """Run the crew and return the final output as a plain string.

        *images* and *system* are accepted for API compatibility but ignored —
        crewAI crews manage their own system prompts via Agent definitions.
        """
        crew = self._crew_factory()
        inputs = {self._crew_input_key: prompt}
        if images:
            # Surface image paths as text hints in the observation
            image_hints = "\n".join(f"[Image: {p}]" for p in images)
            inputs[self._crew_input_key] = f"{prompt}\n{image_hints}"

        result = crew.kickoff(inputs=inputs)

        # crewAI returns a CrewOutput object; `.raw` holds the plain string
        if hasattr(result, "raw"):
            return str(result.raw).strip()
        return str(result).strip()

    # ── Async variant (mirrors ChatOpenAI pattern) ─────────────────────────

    async def acall(
        self,
        prompt: str,
        images: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> str:
        """Async wrapper — crewAI's kickoff_async when available."""
        crew = self._crew_factory()
        inputs = {self._crew_input_key: prompt}
        if images:
            inputs[self._crew_input_key] += "\n" + "\n".join(
                f"[Image: {p}]" for p in images
            )

        if hasattr(crew, "kickoff_async"):
            result = await crew.kickoff_async(inputs=inputs)
        else:
            import asyncio
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, lambda: crew.kickoff(inputs=inputs)
            )

        return str(getattr(result, "raw", result)).strip()
