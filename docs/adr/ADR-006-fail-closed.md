# ADR-006 — No feasible plan is an outcome, not an error

**Status:** Accepted

## Context

39.5% of disruptions in the benchmark produce no feasible plan. A system can
present that as a failure, degrade to a best-effort plan, or present it as an
answer.

## Decision

It is an answer. The disruption closes with a **minimal conflict set**: the
smallest set of constraints that cannot be satisfied together, each naming its
source document and owning role, each with evidence.

Minimality is enforced and measured — `non_minimal_conflict_rate` is 0.000 across
2,612 rejected plans — because a conflict set containing everything that happened
to fail is a log, not an explanation.

## Rejected

**Degrade to a best-effort plan and flag the violations.** This is exactly what
removing validation does, and the ablation shows the cost: 2.412 hard violations
per published plan, 22% of approved plans dropping an access arrangement, and the
no-feasible-plan rate falling to 0.000 because it never fails closed. A flagged
violation on a screen at 19:00 on a running day is a violation.

**Return nothing and log an error.** The conflict set is the most useful output
the system can produce here. "The only alternative location has no step-free
route" is something a location manager can act on in ten minutes.

## Consequences

- The Infeasible Plan Explorer is a first-class view rather than an error state.
- **Inconvenient:** the headline "39.5% no feasible plan" reads badly out of
  context, and it will be quoted out of context. It is in the README's headline
  table anyway, with the explanation attached.
