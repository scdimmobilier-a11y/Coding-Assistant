# Nexus Core → Leon bridge

Replaces Leon's native NLU/brain with Nexus Core (`nexus_brain.core.brain.NexusCore`),
exactly per the integration mission — a bridge, not a rewrite. Leon keeps
owning voice (wake word, ASR, TTS, audio capture); Nexus Core takes over
decision, memory, and pulse, per the mission's own framing:

```
Micro → Wake word → ASR (Leon, inchangé)
  │  texte transcrit
  ▼
Pont HTTP local (this package)
  │
  ▼
NexusCore.handle_turn(texte, contexte, mode)
  │
  ▼
TurnResult { response, paused, mode_used }
  │
  ▼
Pont HTTP local → Leon
  │  texte à énoncer
  ▼
TTS (Leon, inchangé) → haut-parleur
```

## Layout

```
nexus_core_leon_bridge/
  bridge/                 # Python — the local HTTP bridge server
    server.py               FastAPI app: /handle_turn /resume_paused /pulse_tick /health
    core_factory.py          builds the one NexusCore instance the bridge serves
    skills.py                2-3 Leon skills bridged in (mission point #3)
    leon_client.py           HTTP client for Leon's existing POST /run-action
    memory_bridge.py         persist_fn + runtime-context loading (see docs/DECISIONS.md)
    llm_config.py             reuses nexus_compose's single NEXUS_LLM_* config (point #7)
    config.py                env-driven settings for this bridge itself
  leon_patch/              # the ONE Leon-side patch (mission point #2)
    server/src/core/nexus-bridge-client.ts   new file
    server/src/core/socket-server.ts          patched file (for reference/convenience)
    server/src/core/socket-server.patch       unified diff, apply this to your checkout
    PATCH_NOTES.md
  docs/
    DECISIONS.md            explicit memory & pulse decisions (mission points #5, #6)
  tests/                   # mission point #8 — all three required scenarios
    test_e2e_simulated.py
    test_pause_resume.py
    test_non_regression_voice_pipeline.py
    leon_protected_files.sha256.json
  requirements.txt
```

## Install & run

Place this folder next to your Nexus Assistant checkout (so `nexus_brain`,
`nexus_functor`, and — for full `NEXUS_LLM_*` reuse — `nexus_compose` are
importable):

```bash
pip install -e ../Nexus_Brain/nexus_functor -e ../Nexus_Brain
pip install -r requirements.txt
pip install pyperplan   # optional, see requirements.txt — needed for Nexus Brain's OWN test suite to be fully green, not needed by this bridge itself
export PYTHONPATH=/path/to/Nexus_Assistant:$PYTHONPATH   # so bridge/llm_config.py finds the real nexus_compose

uvicorn bridge.server:app --host 127.0.0.1 --port 8420
```

Then apply the Leon-side patch (either works):

```bash
# Option A — apply the diff
cd /path/to/leon-develop/leon-develop
patch -p1 < /path/to/nexus_core_leon_bridge/leon_patch/server/src/core/socket-server.patch
cp /path/to/nexus_core_leon_bridge/leon_patch/server/src/core/nexus-bridge-client.ts server/src/core/

# Option B — copy the already-patched file directly
cp /path/to/nexus_core_leon_bridge/leon_patch/server/src/core/socket-server.ts server/src/core/
cp /path/to/nexus_core_leon_bridge/leon_patch/server/src/core/nexus-bridge-client.ts server/src/core/
```

Then run Leon exactly as before (`pnpm start`, etc.) — the two new
optional env vars `NEXUS_BRIDGE_HOST` / `NEXUS_BRIDGE_PORT` default to
`127.0.0.1:8420`, matching the bridge's own defaults.

## Testing

```bash
cd nexus_core_leon_bridge
PYTHONPATH=. pytest tests/ -v
```

7 of the 9 tests need nothing beyond this package. The 3 non-regression
checks in `test_non_regression_voice_pipeline.py` need a real Leon
checkout to compare against and are correctly **skipped** (not silently
passed) without it:

```bash
LEON_REPO_ROOT=/path/to/leon-develop/leon-develop PYTHONPATH=. pytest tests/test_non_regression_voice_pipeline.py -v
```

All 9 were run in the sandbox this was prepared in — 7 passed directly,
and the 3 skip-by-default ones were separately verified against a real
extracted Leon checkout (including a deliberate tamper-and-confirm-it-
fails check, so this isn't a tautological test) — see PATCH_NOTES.md
"Validation performed" for exactly what was and wasn't verified.

## Mapping back to the mission's 8 delivery points

| # | Ask | Where |
|---|---|---|
| 1 | Bridge server exposing `handle_turn`/`resume_paused`/`pulse_tick` over local HTTP | `bridge/server.py` |
| 2 | Minimal patch at Leon's exact interception point | `leon_patch/` — one call site in `socket-server.ts`, one new file |
| 3 | 2-3 representative skills bridged bidirectionally | `bridge/skills.py` + `bridge/leon_client.py` (date/time, joke, introduction) |
| 4 | PAUSED ↔ Leon confirmation, resume from the human's reply | `nexus-bridge-client.ts`'s session-aware routing + `bridge/server.py`'s goal-key tracking |
| 5 | Memory: explicit decision, no silent divergence | `docs/DECISIONS.md` §Memory + `bridge/memory_bridge.py` |
| 6 | Pulse: explicit decision, no double-running | `docs/DECISIONS.md` §Pulse + `pulse=None` in `bridge/core_factory.py` |
| 7 | One shared `NEXUS_LLM_*` config, Leon included | `bridge/llm_config.py` (reuses `nexus_compose.llm_config.get_llm_config()` as-is) |
| 8 | 3 required test scenarios | `tests/test_e2e_simulated.py`, `tests/test_pause_resume.py`, `tests/test_non_regression_voice_pipeline.py` |

## Constraints checklist

- **Never rewrote/modified Leon's voice pipeline** — proven, not just
  claimed, by `test_non_regression_voice_pipeline.py`.
- **Patch stays minimal and localized** — one call site, ~25 changed
  lines, see `socket-server.patch`; `nlu.ts` deliberately left in place
  but unused (reversible), per `PATCH_NOTES.md`.
- **Nexus Core stays independently testable/usable** — `bridge/core_factory.py`
  has zero hard dependency on Leon's Node.js runtime; `LeonClient` only
  talks to Leon lazily, when a bridged skill actually runs, and every
  call site catches `LeonActionError` rather than assuming Leon is up.
  `tests/test_e2e_simulated.py` and `tests/test_pause_resume.py` both run
  with zero Leon process involved (a `FakeLeonClient` stands in).
- **No skill regresses during migration** — every Leon skill not yet
  bridged keeps working exactly as it does today, because Nexus Core
  simply doesn't intercept it: only utterances that match one of the 3
  bridged skill keys (or fall through to agent mode) go through Nexus
  Core's skill dispatch at all right now — see the note in `PATCH_NOTES.md`
  about what happens to `forcedSkillName`/`forcedToolName`, the one
  related edge case this delivery deliberately didn't try to solve.
- **Local bridge should not perceptibly hurt voice-response latency** —
  this is a loopback HTTP call between two local processes; not
  independently benchmarked here (that needs a running Leon with real
  audio hardware, out of scope for the sandbox this was built in) — flagged
  honestly rather than asserting a number nothing here measured.
