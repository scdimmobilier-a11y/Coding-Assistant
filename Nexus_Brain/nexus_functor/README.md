# Nexus Functor

The hierarchical dynamic functor at the center of Nexus Brain — the
component that continuously decides *which plan to run* and *whether now
is the moment to act proactively*, sitting between Nexus Planner's
candidate plans on one side and Nexus Exec's execution on the other.

Written from scratch, independent of the other five Nexus Brain modules.
Standard library only — no pip install required to run it.

```
pip install nothing  # seriously, just clone and run
python3 examples/demo.py
python3 -m unittest discover -s tests -v
```

## Why this exists

Nexus Planner produces a *set* of candidate plans, not one:
`P = {P1, P2, P3, ...}`. Nexus Proactive produces candidate
`(action, timing)` pairs, not a single command. Something has to turn
"here are several options" into "do this, now" — every tick, continuously,
as execution unfolds and drifts from what any plan expected. That's this
component.

It's organized as four layers, matching the Nexus Brain architecture doc:

```
                    ┌─────────────────────────────────────┐
                    │  F0 — Macro-strategy                 │
                    │  EXPLOIT / EXPLORE / RECOVER / CONSERVE │
                    └──────────────────┬────────────────────┘
                                       │ biases scoring weights
                    ┌──────────────────▼────────────────────┐
   Nexus Planner ──▶│  F1 — Plan selection +                │
   (PlanSet)        │       joint proactive (a*, τ*)         │◀── Nexus Proactive
                    │  weighted multi-criteria scoring        │    (ProactiveSignal)
                    └──────────────────┬────────────────────┘
                                       │ proposes
                    ┌──────────────────▼────────────────────┐
                    │  F3 — Stabilization                    │
                    │  hysteresis + cooldown, anti-oscillation │
                    └──────────────────┬────────────────────┘
                                       │ commits
                    ┌──────────────────▼────────────────────┐
                    │  F2 — Local adaptation                 │
                    │  CONTINUE / PATCH / ESCALATE            │
                    └──────────────────┬────────────────────┘
                                       │
                                  Nexus Exec
                                       │
                              FeedbackEvent (fast loop → F2)
                                       │
                              (slow loop, batched) → Nexus Harness
```

Two feedback loops, per the architecture doc: a **fast** loop where every
step's result feeds straight back into F2 for the next tick, and a
**slow** loop where results are batched and pushed to Nexus Harness so it
can update the learned macro-strategy prior F0 blends in.

### F0 — Macro-strategy

Picks a broad regime for the current tick: `EXPLOIT` (favor proven,
high-confidence plans), `EXPLORE` (favor novel/diverse plans, accept
risk), `RECOVER` (favor short, low-cost, high-certainty plans — damage
control), or `CONSERVE` (favor low-cost/low-interruption options). Blends
Nexus Harness's learned prior with the live deviation trend, with a hard
safety valve that forces `RECOVER` regardless of the prior if cumulative
deviation gets bad enough.

### F1 — Plan selection + joint proactive scoring

Two scoring problems, both conditioned on F0's regime:

- **Plans**: each candidate `Plan` gets a weighted score
  (`reward, confidence, novelty, cost` — weights differ per macro-strategy,
  see `config.py`). `EXPLOIT` weighs confidence heavily; `EXPLORE` weighs
  novelty; `RECOVER` and `CONSERVE` weigh cost/certainty.
- **Proactive**: for each `(action, timing)` candidate from Nexus
  Proactive, `J(a, τ) = utility(a) · receptivity(τ) − λ · cost(a, τ)`,
  argmax over candidates that clear a minimum-receptivity floor. This is
  where WHAT (utility) and WHEN (receptivity) actually get fused into one
  joint decision, rather than resolved by two separate heuristics.

F1 **proposes**; it does not commit — that's F3's job.

### F3 — Stabilization

Added specifically to counter the failure mode the architecture doc flags
for the fused proactive policy: over-anticipation and temporal
oscillation. Two independent hysteresis mechanisms:

- **Plan switching**: a candidate must beat the currently-committed plan's
  score by `plan_switch_margin` *and* the current plan must have run for
  at least `plan_min_dwell_ticks` before it's even eligible to be dropped.
- **Proactive timing**: an EMA-smoothed receptivity signal plus a
  `proactive_cooldown_s` cooldown after anything fires, so a borderline
  signal can't cause back-to-back interruptions.

F2 escalating (see below) calls `force_release()`, which drops the
hysteresis state outright — a plan that's actively failing shouldn't be
protected by "you haven't dwelled long enough to leave."

### F2 — Local adaptation

The fast, cheap layer. Reacts to the *previous* tick's `FeedbackEvent`
without going back up to F1/F0 for every little thing:

- **CONTINUE** — on track, advance to the next step.
- **PATCH** — this step drifted enough to need a local fix (the default
  implementation retries with a `_retry` flag; swap in real repair logic
  — substitute params, skip, etc. — as needed), but the plan as a whole is
  still worth continuing.
- **ESCALATE** — cumulative deviation on this plan has crossed the point
  where patching isn't enough; hand back to F1/F3 to pick again.

## Wiring in the real Nexus Brain modules

`nexus_functor/interfaces.py` defines four `typing.Protocol` ports:
`PlannerPort`, `ExecutorPort`, `HarnessPort`, `ProactivePort`. Structural
typing — anything with the right method signatures satisfies a port, so
you can plug in:

- an in-process adapter that calls into Nexus Planner / Nexus Exec /
  Nexus Harness / Nexus Proactive directly, or
- a subprocess/CLI wrapper, or
- an HTTP client hitting each module as its own service.

**This matters specifically for Nexus Planner.** It's GPLv3 (see its own
`NOTICE.md`). Keeping it behind `PlannerPort` — called out-of-process
rather than imported inline — is what lets Nexus Planner's copyleft stay
scoped to Nexus Planner, instead of potentially reaching into the rest of
Nexus Brain. This functor was written with zero dependency on any of the
five vendored modules for exactly this reason: it's clean-room Nexus IP
that can sit on either side of that boundary without carrying anyone
else's license with it.

`nexus_functor/testing.py` has trivial stdlib mocks for all four ports
(`MockPlanner`, `MockExecutor`, `MockHarness`, `MockProactive`) — that's
what `examples/demo.py` and the test suite run against, so the whole
package develops and tests in complete isolation.

## Usage

```python
from nexus_functor import NexusFunctor, Objective, ExecutionState
from nexus_functor.testing import MockPlanner, MockExecutor, MockHarness, MockProactive

functor = NexusFunctor(
    harness=MockHarness(),      # swap for a real Nexus Harness adapter
    planner=MockPlanner(),      # swap for a real Nexus Planner adapter
    proactive=MockProactive(),  # swap for a real Nexus Proactive adapter
)
executor = MockExecutor()       # swap for a real Nexus Exec adapter

objective = Objective(goal_id="obj-1", description="...")
state = ExecutionState(objective_id=objective.goal_id)

decision = functor.step(objective, plan_set=None, execution_state=state)
if decision.next_step is not None:
    event = executor.execute_step(
        decision.selected_plan_id, decision.next_step.step_id, decision.next_step.params
    )
    functor.on_feedback(objective, decision, state, event)
```

See `examples/demo.py` for a full 25-tick run with printed output, and
`tests/test_functor.py` for the behavioral guarantees each layer makes
(21 tests covering F0's safety valve, F1's per-strategy weighting, F2's
three-way branch, F3's hysteresis/cooldown/force-release, and a full
integration loop).

## Known limitation

When F2 escalates and `force_release()` drops F3's hysteresis state, the
very next `stabilize_plan()` call reports `plan_switched=True`
unconditionally — including in the (rare but possible) case where the
top-ranked plan turns out to be the same plan that was just escalated
away from. Functionally harmless (the system doesn't get stuck — see the
demo output, which recovers and holds plans normally), but if you're
using `plan_switched` for logging/telemetry, be aware it can technically
fire on a "switch" to an identical plan id right after a bad step.
