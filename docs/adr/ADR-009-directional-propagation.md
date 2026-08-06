# ADR-009 — Impact propagates along an edge's direction, not both ways

**Status:** Accepted (August 2026)

## Context

The blast-radius traversal originally walked every propagating relationship in
both directions. Thirty-two scenes are `documented_in` one call sheet, and every
asset is `owned_by_department` some department, so traversing either backwards
made those nodes hubs connecting the whole production to itself. A camera fault
"reached" the wardrobe department by way of the document that happens to list
both.

Separately, the traversal was not scoped to the day being planned. The twin holds
the whole 32-scene script; five scenes are on shooting day 14. Every disruption
returned all thirty-two, so the disrupted-scene precision was 0.022.

## Decision

Two changes.

**Direction.** `documented_in` and `owned_by_department` propagate forward only
(as do `communicates_to` and the plan and command confirmations). A scene change
does invalidate the call sheet, and it is the production office that has to
reissue it — but reissuing the call sheet does not disrupt the other thirty-one
scenes. A relationship absent from `PROPAGATION_DIRECTION` remains two-way.

**Scope.** `blast_radius` takes a `scene_scope`, normally the day's call sheet.
Scenes outside it are neither reported nor traversed through, so the resources
and departments that hang off next Tuesday do not come back with it. An origin is
always in scope: a disruption reported against a scene outside the day is still a
real disruption, and refusing to analyse it would be worse than analysing it
narrowly.

## Rejected

**Making departments and documents terminal sinks** — recorded but never
expanded. It breaks the useful path: a scene change reaches the production office
*through* the call sheet, and a sink stops at the document.

**A depth cut on the reported set.** Depth turns out not to align with the labels
— on a cast disruption the correct departments sit at depth 3 while an unlabelled
one sits at depth 2 — so a cut would be a tuned threshold, not a model of
anything.

## Consequences

- Disrupted-scene precision 0.022 → 0.142; mean blast radius 146 → 118 nodes.
- Paths are defensible individually, which matters because the UI lets a user
  expand a node and read the path that reached it.
- **Inconvenient:** the map is still broad. Department precision is 0.176 at
  recall 1.000. On a five-scene, three-location, two-unit day everything genuinely
  is connected within a few hops, and the honest description remains "a recall
  instrument, ranked by depth". The next real improvement is a relevance model,
  not more edges. See `docs/BENCHMARK.md` §7.2.
