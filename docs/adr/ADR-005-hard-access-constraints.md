# ADR-005 — Access arrangements are hard constraints with no soft weight

**Status:** Accepted

## Context

An approved access arrangement is either a requirement or a preference. Most
scheduling systems make it a preference by making it a weighted term.

## Decision

`C-ACC-001` through `C-ACC-006` are `ConstraintKind.HARD` and appear in no weight
table. `SOFT_WEIGHTS` has eleven entries; none is an access term. The objective
function cannot trade a step-free route against a saved hour because there is no
exchange rate to trade at.

`remove_access_arrangement` is in `PROHIBITED_CHANGES`: no role can approve it.
Changing an arrangement is a separate decision owned by the accessibility
coordinator and the person concerned, not a scheduling action.

## Rejected

**A very high soft weight.** A very high weight is still a price. Under enough
delay pressure the arithmetic finds it, and the failure is silent — which is
precisely the failure mode this product exists to make impossible.

**Hard, with a documented override for emergencies.** An override is used, and
then it is used routinely. Emergencies are handled by the safety lead outside the
system, which is where that authority already lives.

## Consequences

- **Measured:** access preservation 1.000 across 3,630 arrangements in approved
  plans. Without the independent recheck, 0.780 — 22% of approved plans silently
  drop one.
- Access constraints are frequent members of the minimal conflict sets in the
  39.5% of disruptions with no feasible plan. That is the intended behaviour: the
  system says "not without breaking this" and names it.
- **Inconvenient:** a production genuinely unable to satisfy an arrangement gets
  no plan from this system at all. It gets a conflict set and a human decision to
  make — the correct place for that decision, and still a real cost.
