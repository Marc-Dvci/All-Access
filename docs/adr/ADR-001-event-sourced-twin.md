# ADR-001 — The twin is a fold over the event log

**Status:** Accepted

## Context

The production digital twin has to answer two different questions: "what is true
now" and "what did we believe when that decision was made". A mutable store
answers the first and destroys the second.

## Decision

The event log is the record. The twin is a fold over it. Nothing is mutated:
superseding a fact writes a new version, and `rebuild_from_events()` reconstructs
the twin from the log alone.

## Rejected

**A relational store with an audit table.** The audit table is a second source of
truth that drifts from the first, and nothing forces them to agree. Here the
agreement is asserted: `verify_replay()` runs on every benchmark scenario and
reads **1.000** across 1,000 of them.

**Snapshots with periodic checkpoints.** Worth it at a scale this is not. A
shooting day is a few thousand facts; a full rebuild is milliseconds.

## Consequences

- Decision replay is exact rather than approximate, which is what makes the audit
  trail worth having.
- The twin is held in memory. At this scale that is not a compromise — a
  production day is small data with complicated relationships, exactly the case
  where an in-memory graph beats a database round trip per hop.
- **Inconvenient:** it does not scale to a whole production's history in one
  process, and nothing here demonstrates that it would. A multi-day deployment
  needs a different storage decision, and this ADR does not make it.
