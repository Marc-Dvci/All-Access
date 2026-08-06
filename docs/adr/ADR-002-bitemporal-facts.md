# ADR-002 — Facts carry valid time and transaction time

**Status:** Accepted

## Context

"Why did they choose that?" is the question a post-incident review asks. It can
only be answered against the state the decision was actually made in.

## Decision

Every fact carries `valid_from`/`valid_to` (when it is true in the world) and
`transaction_time` (when the system learned it). `as_of(when, known_at)`
reconstructs belief at a moment: facts recorded after `known_at` are invisible,
however true they turned out to be.

A superseding fact does **not** close its predecessor's valid-time interval.
Writing `valid_to` onto the old version would be a transaction-time edit to a
valid-time field, and it destroys the historical view — asking "what did we
believe at 16:00?" would return nothing, because the answer we believed then had
since been retroactively closed. Instead every version keeps the interval it was
asserted with, and `fact()` resolves which is effective by taking the latest
`valid_from` that has started.

## Rejected

**Single-axis versioning.** Cheaper, and it cannot distinguish "the storm arrived
at 18:30" from "we learned at 17:00 that the storm would arrive at 18:30". The
solver's snapshot depends on that distinction: a `FeasibilityProof` names the
state sequence it was computed against, and the proof is meaningless if the state
can be re-read with hindsight.

## Consequences

- Replay is honest.
- Two versions may not both claim to start at the same instant — then "which is
  effective" has no answer. `check_invariants()` enforces it.
- **Inconvenient:** every read is a resolution rather than a lookup, and the
  ordering rule is subtle enough that it needs the long comment it has in
  `twin/graph.py`.
