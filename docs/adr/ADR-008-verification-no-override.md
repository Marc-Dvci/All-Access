# ADR-008 — Verification blocks readiness and cannot be overridden

**Status:** Accepted

## Context

Every command completed. Every acknowledgment returned. Is the day ready?

Not necessarily. An acknowledgment means a message arrived, not that the world
changed.

## Decision

Verification compares **intended state against observed state** in each
downstream system. `ready` is false while any *critical* assertion fails, and
there is no override. The only route to ready is to fix the thing.

Critical and non-critical are distinguished deliberately, and that distinction is
the whole design: a missing executive metric is not a reason to stop a shooting
day; a missing department acceptance is — it means somebody has not confirmed
they can do what the plan assumes they will do.

## Rejected

**Ready with warnings.** Warnings are dismissed. The critical/non-critical
distinction is already where that judgement is made, and making it twice weakens
it.

**A supervisor override for time pressure.** Time pressure is when the override
would be used, which is when it is most dangerous.

## Consequences

- **Measured:** `false_closure_rate_without_verification` is 0.124. One execution
  in eight would have been declared complete with a critical step outstanding.
- Removing reconciliation drops fault handling from 1.000 to 0.762, entirely from
  the `missing_acknowledgment` fault going from 27/27 to 0/27.
- **Inconvenient:** a stuck non-response blocks readiness indefinitely, and the
  system offers no way out except resolving it. A real production needs an
  escalation path that this does not have.
