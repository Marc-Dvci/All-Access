# ADR-003 — Feasibility is decided by a constraint registry, never by a model

**Status:** Accepted

## Context

The obvious build for this product is an agent that reads the situation and
proposes a plan. It demos well. It cannot be trusted to say a plan is safe.

## Decision

Feasibility is decided by `constraints.registry.evaluate` — 34 constraint records
over 28 predicates — run against the plan. The model plane produces typed
findings with evidence and narration; nothing on the feasibility path reads its
output.

This is enforced by the call graph rather than by policy. `engine.publish` takes
its verdict from `engine.validate`, which calls `evaluate`.

## Rejected

**A model that proposes and a checker that verifies, with the model's confidence
used to rank.** Ranking by model confidence reintroduces the model into the
decision through the back door: the plan a user sees first is the plan a user
approves.

**A model in the loop for "soft" judgements only.** The soft/hard boundary is
exactly where the pressure is applied when a day is running late.

## Consequences

- **Measured:** 0.000 hard-constraint violations across 1,629 published plans.
  With the independent recheck removed, 2.412 per plan.
- Every constraint must name a predicate that exists. `validate_registry()` runs
  at import and raises otherwise, which is what stops the registry from drifting
  into a list of good intentions. It also rejects a predicate no constraint
  references, because that is dead code that will rot.
- **Inconvenient:** the system can only enforce what has been formalised.
  Anything a production knows but has not written into the registry is invisible
  to it, and the registry is the bottleneck on how much of a real production this
  could model.
