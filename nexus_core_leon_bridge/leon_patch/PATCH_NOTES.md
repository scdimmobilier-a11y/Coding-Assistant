# Patch notes — Nexus Core interception point

## What changed, and where

Exactly one existing Leon file is touched, at exactly the interception
point specified in the mission ("l'endroit où le texte transcrit par
l'ASR est aujourd'hui passé au moteur NLU natif de Leon"):

- `server/src/core/socket-server.ts` — inside `handleOwnerMessage`, the
  single call site `const processedData = await NLU.process(utterance, {...})`
  is replaced by `const processedData = await processViaNexusBridge(utterance, {...})`.
  See `socket-server.patch` for the exact unified diff, all inside one
  function, plus 2 now-unused imports removed — see "Why two imports were
  removed" below. `socket-server.ts` in this folder is the full file,
  already patched, for convenience — apply either the `.patch` or copy
  this file over Leon's, whichever is easier for your workflow.
- `server/src/core/nexus-bridge-client.ts` — **new** file. The only logic
  Leon gains: carry text to the bridge and back, and remember per-session
  whether Nexus Core is mid-pause. It calls `BRAIN.talk()` exactly like
  the native NLU pipeline did, so the existing answer-queue/TTS pipeline
  needs no changes at all.

**D4 update (`MISSION_couple_leon_nexusbrain.md`):** `socket-server.ts`
now also builds `leonMemoryDigest` before calling `processViaNexusBridge`
— previously always left `undefined` (a known limitation, documented in
`docs/DECISIONS.md`'s "Memory" section). It reuses
`MEMORY_MANAGER.buildPlanningMemoryPack(utterance)`, the exact same call
`pulse-manager.ts` already makes for its own memory evidence (same
defensive try/catch — a memory-recall failure must not break the turn) —
no new memory-retrieval logic, no second way to query Leon's memory.
`socket-server.patch` was regenerated accordingly (reconstructed the
pristine pre-Nexus file by reverse-applying the previous patch, then
re-diffed against the new file — verified byte-for-byte: re-applying the
new patch to the reconstructed pristine file reproduces the current
`socket-server.ts` exactly).

Nothing else in Leon is touched. In particular:

- `server/src/core/nlp/nlu/nlu.ts` (the native NLU engine) is left in the
  repo, untouched, simply no longer called from this path. This is
  deliberate, not an oversight: deleting it is a bigger, riskier change
  than this patch's stated scope, and keeping it makes the change
  trivially reversible (revert `socket-server.ts`, done). Delete it once
  you're confident you don't want a fallback.
- ASR (`server/src/core/asr/`), TTS, wake word / hotword, audio capture,
  the socket/HTTP client protocols, and every native skill package are
  **not modified in any way** — see `tests/test_non_regression_voice_pipeline.py`
  for a checksum-based proof, since a full Node build wasn't practical in
  the sandbox this was prepared in (see "Validation performed" below).

## Why two imports were removed

`NLU` and `Telemetry` were only ever used, in this file, inside the block
that got replaced. Leaving them imported-but-unused would fail Leon's own
lint rules on the next `pnpm lint`/CI run — removing them is a direct,
necessary consequence of the interception-point change itself, not scope
creep.

`Telemetry.utterance(processedData)` specifically is not replaced with an
equivalent call: it expects Leon's native `NLUProcessResult` shape, and
Nexus Core returns its own `TurnResult` shape instead. Rather than ship a
call that either crashes or silently logs garbage, telemetry for this
path is intentionally skipped, with a comment pointing at this decision.
Wiring up equivalent telemetry for the Nexus Core path is a reasonable
next step once there's an agreed schema for it — deliberately left out
here to keep this patch to the one interception point.

## Pause/resume mapping (mission point #4)

Nexus Core's `PAUSED` state needs no separate "are you sure?" UI text —
the `response` string a `PAUSED` `TurnResult` carries (Nexus Core's
`paused_reason`, wrapped for you) already *is* the confirmation prompt, so
`processViaNexusBridge` just speaks it via `BRAIN.talk()` like any other
response. What actually changes on pause is invisible to the person: this
module remembers (`sessionsAwaitingResume`, keyed by `sessionId`) that the
next utterance in that session is the human's answer, and routes it to
`/resume_paused` instead of starting a fresh `/handle_turn`. Approval vs.
rejection is currently a small placeholder keyword check
(`looksLikeRejection`) — see the doc-comment above it in
`nexus-bridge-client.ts` for why, and what a real follow-up looks like.

## Configuration

Two new environment variables, both optional (sensible localhost
defaults), read the same way Leon reads its other runtime config:

```
NEXUS_BRIDGE_HOST=127.0.0.1
NEXUS_BRIDGE_PORT=8420
NEXUS_BRIDGE_TIMEOUT_MS=8000
```

## Validation performed

- Both `nexus-bridge-client.ts` and the patched `socket-server.ts` were
  syntax-checked with `esbuild` (parses real TypeScript syntax, no module
  resolution needed) — both pass.
- Field/type names used (`BRAIN.talk`'s `QueuedAnswer` shape,
  `CONFIG_STATE.getRoutingModeState().getRoutingMode()`,
  `RoutingMode.{Controlled,Agent,Smart}`, D4's
  `MEMORY_MANAGER.buildPlanningMemoryPack`) were confirmed against Leon's
  actual source (`brain.ts`, `nlu.ts`, `memory-manager.ts`,
  `pulse-manager.ts`'s existing call to the same method), not assumed.
- **D4 update:** `tsc --noEmit` (skipping module-resolution errors, which
  are expected without installing Leon's full dependency tree and
  `@types/node` — none of them are anywhere near the edited region) was
  actually run this time against both the full real Leon checkout's copy
  and this folder's mirror, confirming zero new errors introduced by the
  `leonMemoryDigest` change specifically. A full `pnpm typecheck`/CI run
  against Leon's real `tsconfig.json` and installed dependency tree is
  still the one remaining verification step this delivery could not
  perform for you (installing Leon's complete monorepo dependency graph
  wasn't practical in the sandbox this patch was prepared in) — run it
  after applying, before merging.
