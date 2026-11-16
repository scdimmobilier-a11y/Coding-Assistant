"""
bridge.skills
===============

Deliverable #3 ("Mapping des skills"), option (a): 2-3 REPRESENTATIVE
existing Leon skills, bridged (not migrated) into `NexusCore.skills` as
native Python callables that call back into Leon over HTTP to run the real
action. Per the mission this is deliberately a small starting set to
validate the end-to-end mechanism — NOT a bulk migration of Leon's whole
skill catalog, which stays exactly as-is and keeps working through this
same bridge path for every skill not yet ported.

Chosen skills (all parameter-less "logic"/"dialog" actions — the simplest
possible round trip, on purpose, to validate plumbing before tackling
skills with slot-filling):

  - `date_time:current_time`  (skills/native/date_time_skill)
  - `joke:run`                 (skills/native/joke_skill)
  - `introduction:introduce_leon` (skills/native/introduction_skill)

Each returned callable matches NexusCore's `Skill = Callable[[dict], Any]`
signature and is looked up via `NexusCore._match_native_skill`, which does
a case-insensitive substring match of the *dict key* against the raw
utterance — so keys below are chosen to be words a person would actually
say, not the underlying Leon skill/action identifiers.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from .leon_client import LeonActionError, LeonClient

Skill = Callable[[dict[str, Any]], Any]


def _speeches_or_fallback(result: dict[str, Any], fallback: str) -> str:
    speeches = (result.get("result") or {}).get("speeches")
    if isinstance(speeches, list) and speeches:
        return " ".join(str(s) for s in speeches)
    return fallback


def _session_id(context: dict[str, Any]) -> Optional[str]:
    return context.get("session_id")


def make_leon_bridged_skills(client: LeonClient) -> dict[str, Skill]:
    """Builds the skills dict to hand to `NexusCore(skills=...)`. Kept as
    a factory (rather than module-level constants) so tests can inject a
    fake/mock `LeonClient` without monkeypatching."""

    def current_time(context: dict[str, Any]) -> str:
        try:
            result = client.run_action("date_time:current_time", {}, session_id=_session_id(context))
        except LeonActionError as e:
            return f"I couldn't reach Leon's date/time skill: {e}"
        return _speeches_or_fallback(result, "I ran the date/time skill but got no speech back.")

    def tell_joke(context: dict[str, Any]) -> str:
        try:
            result = client.run_action("joke:run", {}, session_id=_session_id(context))
        except LeonActionError as e:
            return f"I couldn't reach Leon's joke skill: {e}"
        return _speeches_or_fallback(result, "I ran the joke skill but got no speech back.")

    def introduce(context: dict[str, Any]) -> str:
        try:
            result = client.run_action("introduction:introduce_leon", {}, session_id=_session_id(context))
        except LeonActionError as e:
            return f"I couldn't reach Leon's introduction skill: {e}"
        return _speeches_or_fallback(result, "I ran the introduction skill but got no speech back.")

    return {
        "time": current_time,
        "joke": tell_joke,
        "who are you": introduce,
    }
