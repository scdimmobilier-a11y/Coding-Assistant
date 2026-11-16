# Explicit decisions

The mission asks, twice, to *decide explicitly* rather than let two
subsystems quietly diverge. Both decisions below were made only after
reading the actual Leon source they concern (`memory-manager/`,
`pulse-manager.ts`) — not assumed from the mission text alone.

## Memory (mission point #5)

**Decision: Leon's own `server/src/core/memory-manager/` (SQL-backed,
with its own retrieval/summarizer) stays the single source of truth for
durable, cross-session memory. `LayeredMemory` is NOT a second copy of
it, and is not even trying to be.**

### Why

Leon already ships a real, substantial memory system — a SQL schema, a
memory-repository, retrieval, and a summarizer. That is not a stub the
mission's `LayeredMemory` needs to replace; it's a *more* capable
component for exactly the job "durable facts across sessions" describes.
Reimplementing that in Python inside this bridge would be strictly worse
(a second, weaker store) and would recreate precisely the "deux mémoires
divergent silencieusement" failure the mission explicitly warns against —
now with two SQL-shaped stores instead of one.

### What `LayeredMemory` is scoped to instead

Nexus Core's own in-process reasoning bookkeeping: self-model notes and
the current turn's/discussion's working memory. Concretely, by layer:

| Layer | Written by | Persisted? | Could it duplicate Leon's memory-manager? |
|---|---|---|---|
| `discussion` | ReAct trace bookkeeping, current turn only | No — cleared every `new_discussion()` | No — never written to disk, never leaves this process |
| `daily` / `persistent` | Nexus Core's own self-model/bookkeeping | Yes, to a local JSONL (`bridge/memory_bridge.py::bridge_persist_fn`) | No — this file holds bridge bookkeeping, not owner facts; nothing here has a matching field in Leon's SQL schema |

### The one read path, and the one write path

- **Write path**: exactly one — `bridge_persist_fn`, writing only the
  bridge's own bookkeeping. Leon's memory-manager is never written to by
  this integration.
- **Read path**: exactly one — Leon includes whatever short digest its
  own memory-manager/persona context assembly already produces for LLM
  prompts as `context["leon_memory_digest"]` on every `/handle_turn` call;
  `bridge/memory_bridge.py::apply_leon_context_digest` loads it as a
  `LayeredMemory` runtime-context file (documented as "consulted first").
  The bridge does not recompute this digest itself.

Because there is exactly one writer of durable facts (Leon) and exactly
one place that reads them (the digest Leon hands over each turn), nothing
can drift silently — there is no second copy of the same fact to drift
*from*.

### Wired up (D4, `MISSION_couple_leon_nexusbrain.md`)

`leon_memory_digest` is no longer just an interface point. `socket-server.ts`
now calls `MEMORY_MANAGER.buildPlanningMemoryPack(utterance)` before every
`processViaNexusBridge()` call and passes the result as
`leonMemoryDigest` — the exact same call `pulse-manager.ts` already made
for its own memory evidence (same defensive try/catch: a memory-recall
failure produces a reduced-context turn, not a broken one, same fallback
this section already described). No new memory-retrieval logic was
written; this is a second caller of a retrieval path Leon already had.

Proof this actually happened, not just documented: `leon_patch/socket-server.patch`
was regenerated and verified to reproduce the current file byte-for-byte
when re-applied to a reconstructed pristine (pre-Nexus) copy;
`tsc --noEmit` was run against both the real Leon checkout's copy and
`leon_patch/`'s mirror, confirming zero new errors in the edited region
(see `leon_patch/PATCH_NOTES.md`, "Validation performed"). A full Node
build/test run of Leon itself remains out of reach of this sandbox (no
installed dependency tree) — same limitation the rest of this patch
already had, not a new one D4 introduced.

## Pulse (mission point #6)

**Decision: Nexus Core's `PulseManager` is NOT used for the Leon
integration. `pulse=None` is passed to `NexusCore` in `bridge/core_factory.py`,
and Leon's own `pulse-manager.ts` keeps running exactly as it does today,
completely untouched.**

### Why

`pulse-manager.ts` (Leon's own, ~48KB) already implements matters,
suppression policies with cooldowns, fingerprinting to avoid repeating a
rejected suggestion, tick scheduling, evidence-gathering from context
signals, and owner-reaction classification (`observeOwnerUtterance`,
`classifyOwnerReaction`) — a proactive/autonomous-suggestion engine that
is a strict superset of what `nexus_brain.core.pulse.PulseManager`
implements (which is explicitly the simplified reimplementation, per that
module's own docstring — Leon's is described there as "the original
inspiration"). It is also already wired into Leon's own conversation and
tool-execution internals in ways this integration's "no refactor étendu"
constraint should not reach into.

Running Nexus Core's `pulse_tick()` on a schedule alongside Leon's own
running pulse loop would be exactly the double-running on the same
territory the mission's point #6 says to avoid — two systems independently
decid­ing when to proactively surface a suggestion to the same person
through the same voice/chat surface, with no arbitration between them.

### What this means concretely

- `bridge/server.py` still exposes `POST /pulse_tick` (the mission's point
  #1 asks for it, and it's useful for testing `NexusCore` standalone /
  for any future non-Leon deployment) — but **nothing in `leon_patch/`
  calls it**. Leon's own scheduler is not modified to call it, by design.
- On a core built by `bridge/core_factory.py::build_nexus_core`,
  `core.pulse_tick()` always returns `None` — this is `NexusCore`'s own
  documented behaviour when `self.pulse is None`, not a bug introduced
  here.
- `nexus_brain.core.pulse.PulseManager` itself is untouched and fully
  functional (still covered by Nexus Brain's own 28-test suite) — this
  decision only concerns how `bridge/core_factory.py` wires *this specific
  integration*, not the class itself.

### If this should change later

If Leon's `pulse-manager.ts` is ever retired in favor of Nexus Core's
(the mission does list that as one of the two acceptable outcomes), the
change is localized to `bridge/core_factory.py` (pass a real
`PulseManager` instead of `None`) plus a new scheduled caller for
`POST /pulse_tick` on the Leon side — `pulse-manager.ts` itself would then
need to be removed from Leon's own tick loop to avoid reintroducing the
double-running this decision exists to prevent. Out of scope here, flagged
for a deliberate follow-up rather than done half-way.

## Nexus Functor delegation (not one of the 8 numbered points, but load-bearing for #4)

`bridge/core_factory.py` builds `NexusCore` with `post_objective=None`.
`pose_objective()` on such a core returns a clean
`{"posted": False, "reason": "...", "objective": ...}` rather than
crashing (this is `NexusCore`'s own documented, tested behaviour) — the
agent-mode executor in `core_factory.py` surfaces that honestly to the
person instead of pretending an objective was delegated.

This is a deliberate scope boundary, not an oversight: translating a
free-text spoken objective ("help me plan a demo for investors next
week") into the STRIPS-style `planning_problem` that
`nexus_brain.integration.loop.ObjectiveRunner` /
`NexusPlannerAdapter` need is a separate, real piece of NLU work.
Wiring in a real `post_objective` sink backed by `ObjectiveRunner` (see
Nexus Brain's own README quick start for the exact adapter wiring) is a
same-shaped follow-up once that translation step exists — not a redesign
of anything in this delivery.

**Update — this follow-up is now done.** See the "Post-objective wiring
(D1–D3)" and "Delivery callback (D2)" sections below.

## Post-objective wiring (D1–D3, `MISSION_couple_leon_nexusbrain.md`)

`post_objective` is no longer `None` by default. `build_nexus_core_and_runner()`
(`bridge/core_factory.py`) builds a real `nexus_brain.integration.loop.ObjectiveRunner`
— real `NexusPlannerAdapter`, a `NexusExecAdapter` extended for D3 (see
below), a real `NexusHarnessAdapter` — and wires it as the fire-and-forget
sink `NexusCore.pose_objective()` fires into. `build_nexus_core()` (the
single-value factory every pre-D1 call site uses) still works unchanged —
it just discards the `runner` half now, unless the caller switches to
`build_nexus_core_and_runner()` to get both.

**The NLU boundary from the previous section is intentionally still
there.** Turning "help me plan a demo for investors next week" into a
STRIPS `planning_problem` remains out of scope — nothing in D1–D3 attempts
it. What changed is the *destination* `pose_objective()` now reaches: a
real, ticking `ObjectiveRunner`, using `NexusPlannerAdapter`'s own
license-free fallback plan (a single `advance:<goal_id>` step) when no
`planning_problem` is present — same fallback the adapter already had,
unmodified, just actually reached now instead of dead-ending at
`post_objective=None`.

**D3 — reaching `nexus_compose`, without conflating it with Nexus Functor.**
M3 in the mission (verified: zero mention of `nexus_compose`/`crewai`/
`openhands`/`openmanus` anywhere under `Nexus_Brain/`, before this fix) is
the most severe gap: even a perfect `post_objective` wiring had nowhere to
send "go build/verify/ship this" — Nexus Functor's STRIPS planner and
`nexus_compose`'s 10-phase tool-orchestration pipeline are different
subsystems solving different problems, and forcing the former to *be* the
latter would have been wrong. The fix is a narrow, **opt-in** escape hatch:
if the `context` dict `pose_objective()` receives carries a
`"deliver_software"` key (a string instruction, or `True` to reuse the
objective's own description), `_make_post_objective()`
(`bridge/core_factory.py`) seeds the plan with a single `deliver_software`
action (via `available_actions=["deliver_software"]`, `NexusPlannerAdapter`'s
existing fallback path, unmodified) and registers that step's `step_id`
with the exec adapter (`NexusExecAdapter.register_deliver_software_step()`,
D3) — the *only* new capability added to `exec_adapter.py`. Without that
context key, everything behaves exactly as it did the moment `post_objective`
stopped being `None`: a generic single-step objective.

Why registration happens in the post-objective glue and not inside
`NexusExecAdapter.execute_step` itself: `ExecutorPort.execute_step(plan_id,
step_id, params)` (`nexus_functor/interfaces.py`, unmodified — Nexus
Functor is "fourni tel quel") never receives the step's `action` name, only
its `step_id`. The one piece of code that has both the `PlanSet` (with
each step's `.action`) *and* knows the caller asked for `deliver_software`
is the code that just called `runner.add_objective()` — so that's where the
step gets tagged, once, before any ticking starts. `NexusExecAdapter` never
reaches into the planner's output on its own (Invariant #1: adapters don't
call each other or reach past their own port).

`nexus_brain/adapters/codegen_adapter.py` (`CodegenAdapter`) is the actual
HTTP client — `POST {NEXUS_COMPOSE_API_URL}/api/pipeline/run` (default
`http://127.0.0.1:8000`, matching the root README's own dev invocation),
same shape as `bridge/leon_client.py` (dedicated exception, configurable
timeout). It deliberately does **not** import `nexus_compose` or
`unified_system` in Python — the `nexus_compose` container isn't
guaranteed to have crewAI installed (see `unified_system/bridge.py`'s own
docstring), and an in-process import would silently couple two
independently-deployed codebases, which is exactly what the port/adapter
seam (Invariant #1) exists to prevent.

**Caveat worth being explicit about, found while testing this (see
`tests/test_post_objective_wiring.py::test_objective_status_and_deliver_endpoints_end_to_end`):**
`NexusCore.resume_paused(goal_key, human_input, context)` runs the
step with a **fresh** `context` — it is not inherited from the
`/handle_turn` call that produced the PAUSED trace (see
`nexus_brain/core/brain.py`). Since `deliver_software`-routing steps are
always `requires_approval=True` (never skip the human confirmation gate —
same reasoning as the section above), the caller (Leon's
`nexus-bridge-client.ts`, D4) must resend `context.deliver_software` on the
`/resume_paused` call too, not only on the initial `/handle_turn`. This is
existing pause/resume behaviour, not something this delivery changed —
just previously never exercised by anything that cared what was in
`context` at resume time.

## Delivery callback (D2, `MISSION_couple_leon_nexusbrain.md`)

An objective posted via D1/D3 needs a way back to whoever asked for it.
`pulse=None` stays unchanged (see "Pulse" above) — a completed
objective's result deliberately does not flow through Nexus Core's own
pulse, so this needed its own, minimal mechanism:

- `nexus_brain/integration/loop.py::ObjectiveRunner` now retains the final
  `TickSummary` of every objective that reaches `"complete"`, queryable via
  `get_completed(goal_id)` (bounded retention, `_completed_max_entries=500`,
  so a long-running process backed by many one-off objectives doesn't grow
  this forever). Purely additive — no existing method's signature or
  return value changed; confirmed by Nexus Brain's own full suite staying
  green (28 -> 38 tests, all passing) after this change.
- `TickSummary` gained an optional `notes` field, carried from the last
  `FeedbackEvent.notes` (both on the "ticked" summary that produced it and
  on the terminal "complete" summary, which itself executes no step and so
  has no `FeedbackEvent` of its own to draw from otherwise) — this is what
  lets a delivery callback show something meaningful, e.g.
  `CodegenAdapter`'s own `"deliver_software started nexus_compose
  run_id=... for: ..."` note.
- `bridge/server.py` exposes `GET /objective/{goal_id}/status` (D1) and
  `POST /objective/{goal_id}/deliver` (D2, 404 while still active or
  unknown, 200 with `{status, outcome, report}` once complete).

**Chosen: a pull endpoint, not push/SSE.** The mission offered three
options: a new endpoint, an outbound call into an existing Leon
unsolicited-message entry point (flagged in the mission itself as
unverified — "à vérifier dans `server/src/core/http-server/` de Léon"),
or an SSE stream. Building against an unverified assumption about Leon's
internals risked a wrong foundation; a pull endpoint is fully self-
contained, fully testable without a real Leon process, and sufficient for
`nexus-bridge-client.ts` to poll once a paused/delegated turn is expected
to have produced something (it already knows to check back — it's the one
that got told "I've delegated that" in the first place). An outbound
push/SSE upgrade remains a well-defined, same-shaped follow-up once Leon's
actual entry point is confirmed — not a silent gap.

**What ticks the objectives forward:** `bridge/server.py`'s FastAPI
`lifespan` starts a background `asyncio` task (`_tick_loop`) that calls
`runner.tick_all()` (via `asyncio.to_thread`, since `tick_all()` is
synchronous and can block briefly on `CodegenAdapter`'s HTTP call) every
`BridgeConfig.objective_tick_interval_s` seconds (default `2.0`, env
`NEXUS_BRIDGE_TICK_INTERVAL_S`) — never inside a request handler, so
`/handle_turn`/`/resume_paused` stay fast, and never inside
`post_objective` itself, so Invariant #2 (Nexus Core never loops on
`functor.step()`) holds. The task only starts if `create_app()` was given
(or built) a real `ObjectiveRunner` — every pre-D1 test that calls
`create_app(core=core)` with no `runner` gets no background task and a
clean `501` from the two new endpoints, not a crash.

## Harness evolution (D6, `MISSION_couple_leon_nexusbrain.md`)

`evolve_harness_tool=harness.evolve_harness` is now passed to `NexusCore(...)`
— previously silently absent from the constructor call, with no documented
reason (unlike `pulse`/`post_objective`, which had explicit ones). It's the
same `NexusHarnessAdapter` instance the `ObjectiveRunner` already uses for
`HarnessPort` (`get_policy_prior`/`record_outcome`) — per Invariant #8
(`docs/INVARIANTS.md`), these are two genuinely separate data flows sharing
one module: `evolve_harness` (Nexus Core's own prompt/subagent/skill/memory
CRUD, driven by `NexusCore._maybe_evolve_harness` after every turn) never
touches F0's learned macro-strategy prior, and recording an F0 outcome
never triggers a harness evolution pass. Confirmed by
`tests/test_post_objective_wiring.py::test_evolve_harness_tool_is_wired_to_the_same_harness_instance`
and by Invariant #8's own existing coverage in Nexus Brain's suite being
unaffected.

No new tuning was done on `optimization_window_length` (still the
adapter's own default of 50 turns) — nothing in this mission asked for a
different cadence, and picking one without a real usage pattern to base it
on would be a guess dressed up as a decision.
