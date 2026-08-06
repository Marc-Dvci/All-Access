# Architecture decision records

One file per decision that would be expensive to reverse. Each states the
decision, what was rejected and why, and the consequences — including the
inconvenient ones. An ADR that lists only the upside is a press release.

| # | Decision | Status |
|---|---|---|
| [001](ADR-001-event-sourced-twin.md) | The twin is a fold over the event log, not a database | Accepted |
| [002](ADR-002-bitemporal-facts.md) | Facts carry valid time and transaction time | Accepted |
| [003](ADR-003-deterministic-feasibility.md) | Feasibility is decided by a constraint registry, never by a model | Accepted |
| [004](ADR-004-plane-separation.md) | Three planes, deployed separately | Accepted |
| [005](ADR-005-hard-access-constraints.md) | Access arrangements are hard constraints with no soft weight | Accepted |
| [006](ADR-006-fail-closed.md) | No feasible plan is an outcome, not an error | Accepted |
| [007](ADR-007-approval-binding.md) | Approvals are signed, hash-bound, single-use and expiring | Accepted |
| [008](ADR-008-verification-no-override.md) | Verification blocks readiness and cannot be overridden | Accepted |
| [009](ADR-009-directional-propagation.md) | Impact propagates along an edge's direction, not both ways | Accepted |
| [010](ADR-010-committed-benchmark-results.md) | Benchmark results are committed to the repository | Accepted |
| [011](ADR-011-bob-scope.md) | IBM Bob implements the approved formal model; it does not choose it | Accepted |
