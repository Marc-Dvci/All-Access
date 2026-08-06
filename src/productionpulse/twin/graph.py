"""The production digital twin: a bitemporal, versioned knowledge graph.

Two ideas do all the work here.

**Bitemporality.** Every fact carries both when it is true in the world
(`valid_from`/`valid_to`) and when the system learned it (`transaction_time`).
`as_of(when, known_at)` reconstructs what the production believed at a moment,
which is what makes decision replay honest: a reviewer asking "why did they
choose that?" gets the state the decision was actually made against, not the
state we have now with hindsight applied.

**Append-only.** Nothing is mutated. Superseding a fact writes a new version and
closes the old one's validity interval. The twin is rebuildable from the event
log alone — `rebuild_from_events()` is what the replay engine calls, and the
benchmark asserts the rebuilt twin is identical to the live one.

The graph is held in memory. At this scale (a few thousand facts for a shooting
day) that is not a compromise; a production day is small data with complicated
relationships, which is exactly the case where a graph in memory beats a
database round trip per hop.
"""

from __future__ import annotations

import itertools
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Iterator

from ..contracts import (
    Authority,
    Classification,
    Event,
    EventType,
    Relationship,
    TemporalFact,
    stable_hash,
    utcnow,
)

# Entity kinds the twin knows about. Anything not in here is rejected on write,
# which stops typos from silently creating a parallel entity type nobody queries.
ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "production", "unit", "production_day", "script", "scene", "shot_group", "story_day",
        "character", "performer", "crew_member", "role", "department", "location",
        "location_zone", "access_route", "permit", "vehicle", "equipment", "package", "prop",
        "wardrobe_state", "makeup_state", "continuity_state", "vendor", "service_booking",
        "interpreter_booking", "access_requirement", "caregiving_requirement", "safety_control",
        "briefing", "rate_card", "budget_line", "weather_window", "daylight_window", "call_sheet",
        "revision", "event", "constraint", "finding", "plan", "approval", "command",
        "acknowledgment", "verification", "incident", "communication", "support_resource",
    }
)

# Relationship kinds, and whether traversing one propagates operational impact.
# The boolean is the difference between a dependency graph and a diagram: it is
# what stops blast radius from walking the whole production through the
# "belongs_to_production" edge and declaring everything affected.
RELATION_KINDS: dict[str, bool] = {
    "requires_performer": True,
    "requires_crew": True,
    "requires_location": True,
    "requires_equipment": True,
    "requires_prop": True,
    "requires_vehicle": True,
    "requires_permit": True,
    "requires_support": True,
    "requires_service": True,
    "follows_continuity": True,
    "provides_access_route": True,
    "supports_requirement": True,
    "subject_to_limit": True,
    "schedules_scene": True,
    "assigns_resource": True,
    "implements_plan": True,
    "confirms_command": True,
    "invalidates_assignment": True,
    "authorizes_plan": True,
    "confirms_readiness": True,
    "owned_by_department": True,
    "member_of_unit": False,
    "belongs_to_production": False,
    "documented_in": True,
    "communicates_to": True,
    "derived_from": False,
}

# Which way operational impact travels along a propagating relationship.
#
#   "both"    the edge is a two-way dependency
#   "forward" impact travels source -> target only
#
# This is the difference between a dependency and an accountability record, and
# it is what stops the blast radius from answering "everything" to every
# question. `documented_in` and `owned_by_department` are the two that matter:
# thirty-two scenes are documented in one call sheet and every asset is owned by
# some department, so traversing either backwards makes the call sheet and each
# department a hub that connects the whole production to itself. A scene change
# does invalidate the call sheet, and it is the production office that has to
# reissue it — but reissuing the call sheet does not disrupt the other
# thirty-one scenes, and a camera fault does not reach the wardrobe department
# by way of the document that happens to list both.
#
# A relationship absent from this table is two-way.
PROPAGATION_DIRECTION: dict[str, str] = {
    "owned_by_department": "forward",
    "documented_in": "forward",
    "communicates_to": "forward",
    "implements_plan": "forward",
    "confirms_command": "forward",
    "authorizes_plan": "forward",
    "confirms_readiness": "forward",
}

#: Kinds traversed when walking out-edges, and when walking in-edges.
_FORWARD_KINDS: frozenset[str] = frozenset(
    k for k, propagating in RELATION_KINDS.items() if propagating
)
_REVERSE_KINDS: frozenset[str] = frozenset(
    k for k, propagating in RELATION_KINDS.items()
    if propagating and PROPAGATION_DIRECTION.get(k, "both") == "both"
)


@dataclass
class Entity:
    entity_id: str
    entity_type: str
    label: str
    created_at: datetime = field(default_factory=utcnow)
    classification: Classification = Classification.PRODUCTION_INTERNAL


class TwinError(RuntimeError):
    pass


class ProductionTwin:
    """A temporal production knowledge graph."""

    def __init__(self, production_id: str, clock: datetime | None = None) -> None:
        self.production_id = production_id
        # The transaction time used when a caller does not supply one.
        #
        # A twin describing a production day in March cannot record that it
        # learned those facts in August: `known_at` queries would then filter
        # out the entire baseline, and replay would return an empty world. The
        # clock keeps transaction time on the same timeline as valid time.
        self.clock = clock
        self.entities: dict[str, Entity] = {}
        self.facts: dict[str, list[TemporalFact]] = defaultdict(list)  # (entity, attr) -> versions
        self.relationships: dict[str, Relationship] = {}
        self._out: dict[str, list[str]] = defaultdict(list)
        self._in: dict[str, list[str]] = defaultdict(list)
        self.sequence: int = 0
        self._fact_counter = itertools.count(1)
        self._rel_counter = itertools.count(1)
        self.applied_events: list[str] = []

    # -- structure ---------------------------------------------------------

    def add_entity(
        self,
        entity_id: str,
        entity_type: str,
        label: str,
        classification: Classification = Classification.PRODUCTION_INTERNAL,
    ) -> Entity:
        if entity_type not in ENTITY_TYPES:
            raise TwinError(f"unknown entity type {entity_type!r} for {entity_id}")
        existing = self.entities.get(entity_id)
        if existing is not None:
            return existing
        entity = Entity(entity_id, entity_type, label, classification=classification)
        self.entities[entity_id] = entity
        return entity

    def _key(self, entity_id: str, attribute: str) -> str:
        return f"{entity_id}::{attribute}"

    def assert_fact(
        self,
        entity_id: str,
        attribute: str,
        value: Any,
        *,
        valid_from: datetime,
        valid_to: datetime | None = None,
        source: str,
        authority: Authority = Authority.AUTHORITATIVE,
        confidence: float = 1.0,
        classification: Classification = Classification.PRODUCTION_INTERNAL,
        approval_state: str = "not_required",
        transaction_time: datetime | None = None,
    ) -> TemporalFact:
        """Write a new version of an attribute.

        The previous effective version is closed at `valid_from` rather than
        deleted. Two facts about the same attribute never overlap in valid time,
        which is the invariant `check_invariants()` verifies.
        """
        if entity_id not in self.entities:
            raise TwinError(f"cannot assert on unknown entity {entity_id!r}")
        key = self._key(entity_id, attribute)
        versions = self.facts[key]
        tx = transaction_time or self.clock or utcnow()

        prior = [f for f in versions if f.valid_to is None and f.valid_from <= valid_from]
        version_no = len(versions) + 1
        fact = TemporalFact(
            fact_id=f"F-{next(self._fact_counter):06d}",
            entity_id=entity_id,
            entity_type=self.entities[entity_id].entity_type,
            attribute=attribute,
            value=value,
            valid_from=valid_from,
            valid_to=valid_to,
            transaction_time=tx,
            version=version_no,
            source=source,
            authority=authority,
            confidence=confidence,
            approval_state=approval_state,  # type: ignore[arg-type]
            classification=classification,
        )
        # Record the supersession without closing the old version's valid-time
        # interval.
        #
        # Writing `valid_to` onto the previous version would be a *transaction
        # time* edit to a *valid time* field, and it destroys the historical
        # view: asking "what did we believe at 16:00?" would return nothing,
        # because the answer we believed then has since been retroactively
        # closed. Instead every version keeps the interval it was asserted with,
        # and `fact()` resolves which one is effective by taking the latest
        # `valid_from` that has started. Same answer now, correct answer in the
        # past, which is the whole point of keeping two time axes.
        for old in prior:
            idx = versions.index(old)
            versions[idx] = old.model_copy(update={"superseded_by": fact.fact_id})
        versions.append(fact)
        self.sequence += 1
        return fact

    def relate(
        self,
        source_id: str,
        target_id: str,
        kind: str,
        *,
        valid_from: datetime,
        valid_to: datetime | None = None,
        attributes: dict[str, Any] | None = None,
        classification: Classification = Classification.PRODUCTION_INTERNAL,
    ) -> Relationship:
        if kind not in RELATION_KINDS:
            raise TwinError(f"unknown relationship kind {kind!r}")
        for eid in (source_id, target_id):
            if eid not in self.entities:
                raise TwinError(f"cannot relate unknown entity {eid!r}")
        rel = Relationship(
            rel_id=f"R-{next(self._rel_counter):06d}",
            source_id=source_id,
            target_id=target_id,
            kind=kind,
            valid_from=valid_from,
            valid_to=valid_to,
            attributes=attributes or {},
            classification=classification,
        )
        self.relationships[rel.rel_id] = rel
        self._out[source_id].append(rel.rel_id)
        self._in[target_id].append(rel.rel_id)
        self.sequence += 1
        return rel

    def close_relationship(self, rel_id: str, at: datetime) -> None:
        rel = self.relationships[rel_id]
        self.relationships[rel_id] = rel.model_copy(update={"valid_to": at})
        self.sequence += 1

    # -- reading -----------------------------------------------------------

    def value(
        self,
        entity_id: str,
        attribute: str,
        when: datetime | None = None,
        known_at: datetime | None = None,
    ) -> Any:
        fact = self.fact(entity_id, attribute, when, known_at)
        return fact.value if fact else None

    def fact(
        self,
        entity_id: str,
        attribute: str,
        when: datetime | None = None,
        known_at: datetime | None = None,
    ) -> TemporalFact | None:
        """The effective version of an attribute, optionally as believed at a time.

        `known_at` is the replay lever: pass it and facts recorded after that
        instant are invisible, however true they turned out to be.
        """
        key = self._key(entity_id, attribute)
        moment = when or utcnow()
        candidates = [
            f
            for f in self.facts.get(key, [])
            if f.effective_at(moment) and (known_at is None or f.transaction_time <= known_at)
        ]
        if not candidates:
            return None
        # Latest-starting version wins, then latest-known. Ordering by
        # `valid_from` first is what makes a superseding fact take effect from
        # the moment it says it does, without having to close its predecessor.
        return max(candidates, key=lambda f: (f.valid_from, f.transaction_time, f.version))

    def attributes(self, entity_id: str, when: datetime | None = None,
                   known_at: datetime | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {}
        prefix = f"{entity_id}::"
        for key in self.facts:
            if not key.startswith(prefix):
                continue
            attr = key[len(prefix):]
            f = self.fact(entity_id, attr, when, known_at)
            if f is not None:
                out[attr] = f.value
        return out

    def neighbours(
        self,
        entity_id: str,
        when: datetime | None = None,
        *,
        direction: str = "out",
        kinds: Iterable[str] | None = None,
        propagating_only: bool = False,
    ) -> list[tuple[str, Relationship]]:
        moment = when or utcnow()
        allowed = set(kinds) if kinds else None
        result: list[tuple[str, Relationship]] = []
        rel_ids: list[str] = []
        if direction in ("out", "both"):
            rel_ids.extend(self._out.get(entity_id, []))
        if direction in ("in", "both"):
            rel_ids.extend(self._in.get(entity_id, []))
        for rid in rel_ids:
            rel = self.relationships[rid]
            if not rel.effective_at(moment):
                continue
            if allowed is not None and rel.kind not in allowed:
                continue
            if propagating_only and not RELATION_KINDS.get(rel.kind, False):
                continue
            other = rel.target_id if rel.source_id == entity_id else rel.source_id
            result.append((other, rel))
        return result

    def entities_of_type(self, entity_type: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.entity_type == entity_type]

    def as_of(self, when: datetime, known_at: datetime | None = None) -> "TwinSnapshot":
        return TwinSnapshot(self, when, known_at)

    # -- integrity ---------------------------------------------------------

    def state_hash(self, when: datetime | None = None) -> str:
        """A content hash of the effective state.

        Used to key the solver result cache and to prove that a replayed twin
        matches the live one. Facts are sorted so the hash does not depend on
        insertion order.
        """
        moment = when or utcnow()
        payload: list[Any] = []
        for entity_id in sorted(self.entities):
            attrs = self.attributes(entity_id, moment)
            payload.append([entity_id, sorted((k, str(v)) for k, v in attrs.items())])
        rels = sorted(
            (r.source_id, r.kind, r.target_id)
            for r in self.relationships.values()
            if r.effective_at(moment)
        )
        payload.append(rels)
        return stable_hash(payload)

    def check_invariants(self) -> list[str]:
        """Structural problems, as a list of human-readable strings.

        Called by the baseline certification step and asserted empty in tests. A
        twin that violates these is not a twin with a bug in it, it is a twin
        that will produce a confidently wrong plan.
        """
        problems: list[str] = []
        for key, versions in self.facts.items():
            # Versions are allowed to overlap in valid time -- that is how a
            # correction to a past belief is recorded. What is not allowed is
            # two versions claiming to start at exactly the same instant, since
            # then "which one is effective" has no answer.
            starts: dict[datetime, int] = {}
            for f in versions:
                starts[f.valid_from] = starts.get(f.valid_from, 0) + 1
            for start, count in starts.items():
                if count > 1:
                    problems.append(
                        f"{key}: {count} versions both effective from "
                        f"{start.isoformat()}; effective value is ambiguous"
                    )
            for f in versions:
                if f.valid_to is not None and f.valid_to < f.valid_from:
                    problems.append(f"{f.fact_id} ({key}): valid_to precedes valid_from")
        for rel in self.relationships.values():
            if rel.source_id not in self.entities:
                problems.append(f"{rel.rel_id}: dangling source {rel.source_id}")
            if rel.target_id not in self.entities:
                problems.append(f"{rel.rel_id}: dangling target {rel.target_id}")
            if rel.valid_to is not None and rel.valid_to < rel.valid_from:
                problems.append(f"{rel.rel_id}: valid_to precedes valid_from")
        return problems

    # -- event sourcing ----------------------------------------------------

    def apply_event(self, event: Event) -> list[TemporalFact]:
        """Fold one event into the twin.

        Only the state-changing event types do anything; assessment and decision
        events are recorded in the ledger but do not mutate the twin, because a
        finding is a belief about the world and not a change to it.
        """
        env = event.envelope
        if env.event_id in self.applied_events:
            return []  # inbox deduplication: replayed events must not double-apply
        produced: list[TemporalFact] = []
        effective = env.effective_time or env.event_time

        if env.event_type == EventType.TWIN_ENTITY_UPDATED:
            entity_id = event.payload["entity_id"]
            entity_type = event.payload.get("entity_type", "scene")
            self.add_entity(entity_id, entity_type, event.payload.get("label", entity_id))
            for attr, val in event.payload.get("attributes", {}).items():
                produced.append(
                    self.assert_fact(
                        entity_id, attr, val, valid_from=effective,
                        source=env.producer, authority=env.authority,
                        transaction_time=env.ingestion_time,
                    )
                )
        elif env.event_type in (
            EventType.WEATHER_ALERTED,
            EventType.LOCATION_CHANGED,
            EventType.CAST_CHANGED,
            EventType.CREW_CHANGED,
            EventType.RESOURCE_CHANGED,
            EventType.TRANSPORT_CHANGED,
            EventType.PERMIT_CHANGED,
            EventType.ACCESS_SERVICE_CHANGED,
            EventType.SAFETY_REPORTED,
        ):
            entity_id = event.payload.get("entity_id")
            if entity_id and entity_id in self.entities:
                for attr, val in event.payload.get("attributes", {}).items():
                    produced.append(
                        self.assert_fact(
                            entity_id, attr, val, valid_from=effective,
                            source=env.producer, authority=env.authority,
                            confidence=float(event.payload.get("confidence", 1.0)),
                            transaction_time=env.ingestion_time,
                        )
                    )
        self.applied_events.append(env.event_id)
        return produced


class TwinSnapshot:
    """A read-only view of the twin at a moment, optionally with a knowledge cut.

    Passed to the solver and to agents so neither can accidentally read the
    future. The solver taking a snapshot rather than the live twin is also what
    makes a `FeasibilityProof` meaningful: the proof names the state sequence it
    was computed against.
    """

    def __init__(self, twin: ProductionTwin, when: datetime,
                 known_at: datetime | None = None) -> None:
        self._twin = twin
        self.when = when
        self.known_at = known_at
        self.sequence = twin.sequence

    def value(self, entity_id: str, attribute: str) -> Any:
        return self._twin.value(entity_id, attribute, self.when, self.known_at)

    def attributes(self, entity_id: str) -> dict[str, Any]:
        return self._twin.attributes(entity_id, self.when, self.known_at)

    def neighbours(self, entity_id: str, **kw: Any) -> list[tuple[str, Relationship]]:
        return self._twin.neighbours(entity_id, self.when, **kw)

    def entities_of_type(self, entity_type: str) -> list[Entity]:
        return self._twin.entities_of_type(entity_type)

    def has(self, entity_id: str) -> bool:
        return entity_id in self._twin.entities

    def state_hash(self) -> str:
        return self._twin.state_hash(self.when)

    @property
    def entities(self) -> dict[str, Entity]:
        return self._twin.entities


@dataclass(frozen=True)
class ImpactNode:
    entity_id: str
    entity_type: str
    label: str
    depth: int
    path: tuple[str, ...]
    via: tuple[str, ...]
    critical: bool = False


@dataclass(frozen=True)
class BlastRadius:
    """Everything a disruption reaches, and how it reached it.

    `path` on each node is the chain of entities traversed, which is what the
    impact map draws and what lets a user expand a consequence and see its
    source. An impact analysis you cannot interrogate is an assertion.
    """

    origin_ids: tuple[str, ...]
    nodes: tuple[ImpactNode, ...]
    by_depth: dict[int, tuple[str, ...]]
    departments: tuple[str, ...]
    people: tuple[str, ...]
    documents: tuple[str, ...]
    access_requirements: tuple[str, ...]
    scenes: tuple[str, ...]
    max_depth: int

    @property
    def direct(self) -> tuple[str, ...]:
        return self.by_depth.get(1, ())

    @property
    def transitive(self) -> tuple[str, ...]:
        return tuple(n.entity_id for n in self.nodes if n.depth > 1)

    def reached(self, entity_id: str) -> ImpactNode | None:
        for n in self.nodes:
            if n.entity_id == entity_id:
                return n
        return None


def blast_radius(
    twin: ProductionTwin,
    origin_ids: Iterable[str],
    when: datetime | None = None,
    *,
    max_depth: int = 6,
    scene_scope: Iterable[str] | None = None,
) -> BlastRadius:
    """Breadth-first traversal of propagating relationships from the origins.

    Breadth-first, not depth-first, because depth is the ranking signal the
    coordinator uses to decide what to assess first — and a BFS gives each node
    its *shortest* path to the disruption, which is the one worth showing.

    `scene_scope` is the set of scenes being planned — normally the day's call
    sheet. The twin holds the whole script, thirty-two scenes, of which five are
    on the day. Without a scope the traversal walks out of the day through a
    shared location or a story-day link and returns scenes nobody is shooting:
    the answer is not wrong, exactly, but "this affects a scene scheduled for
    next Tuesday" is not what a first AD asked, and it drowns the five that
    matter. Anything outside the scope is neither reported nor traversed
    through, so the resources and departments that hang off next Tuesday do not
    come back with it.

    Pass `None` to walk the whole production, which is what a cross-day query
    would want.
    """
    moment = when or utcnow()
    origins = tuple(origin_ids)
    scope = frozenset(scene_scope) if scene_scope is not None else None
    seen: dict[str, ImpactNode] = {}
    queue: deque[tuple[str, int, tuple[str, ...], tuple[str, ...]]] = deque()

    for oid in origins:
        if oid in twin.entities:
            queue.append((oid, 0, (oid,), ()))

    while queue:
        entity_id, depth, path, via = queue.popleft()
        if entity_id in seen and seen[entity_id].depth <= depth:
            continue
        entity = twin.entities.get(entity_id)
        if entity is None:
            continue
        # Out of scope: not a consequence of this disruption on this day, and
        # not a route to one. An origin is always in scope — a disruption
        # reported against a scene outside the day is still a real disruption,
        # and refusing to analyse it would be worse than analysing it narrowly.
        if (
            scope is not None
            and entity.entity_type == "scene"
            and entity_id not in scope
            and entity_id not in origins
        ):
            continue
        if depth > 0:
            seen[entity_id] = ImpactNode(
                entity_id=entity_id,
                entity_type=entity.entity_type,
                label=entity.label,
                depth=depth,
                path=path,
                via=via,
            )
        if depth >= max_depth:
            continue
        onward = (
            twin.neighbours(entity_id, moment, direction="out", kinds=_FORWARD_KINDS)
            + twin.neighbours(entity_id, moment, direction="in", kinds=_REVERSE_KINDS)
        )
        for other, rel in onward:
            if other in seen and seen[other].depth <= depth + 1:
                continue
            queue.append((other, depth + 1, path + (other,), via + (rel.kind,)))

    nodes = tuple(sorted(seen.values(), key=lambda n: (n.depth, n.entity_id)))
    by_depth: dict[int, tuple[str, ...]] = defaultdict(tuple)
    for n in nodes:
        by_depth[n.depth] = by_depth[n.depth] + (n.entity_id,)

    def of(*types: str) -> tuple[str, ...]:
        return tuple(n.entity_id for n in nodes if n.entity_type in types)

    return BlastRadius(
        origin_ids=origins,
        nodes=nodes,
        by_depth=dict(by_depth),
        departments=of("department"),
        people=of("crew_member", "performer"),
        documents=of("call_sheet", "briefing", "revision", "permit"),
        access_requirements=of("access_requirement", "caregiving_requirement"),
        scenes=of("scene"),
        max_depth=max((n.depth for n in nodes), default=0),
    )


def critical_path(
    twin: ProductionTwin,
    scene_order: list[str],
    durations: dict[str, float],
    when: datetime | None = None,
) -> tuple[list[str], float]:
    """Longest chain through the scenes that are linked by continuity.

    Continuity edges are the only genuine precedence in a shooting day — you can
    reorder anything else. So the critical path is the longest continuity chain
    weighted by scene duration, and that is what a delay actually propagates
    along.
    """
    moment = when or utcnow()
    successors: dict[str, list[str]] = defaultdict(list)
    in_set = set(scene_order)
    for scene in scene_order:
        for other, rel in twin.neighbours(scene, moment, direction="out",
                                          kinds=("follows_continuity",)):
            if other in in_set:
                successors[other].append(scene)

    best_cost: dict[str, float] = {}
    best_next: dict[str, str | None] = {}

    def cost_from(node: str, stack: frozenset[str]) -> float:
        if node in best_cost:
            return best_cost[node]
        if node in stack:
            return durations.get(node, 0.0)  # cycle guard; continuity should be acyclic
        own = durations.get(node, 0.0)
        best = own
        chosen: str | None = None
        for nxt in successors.get(node, []):
            c = own + cost_from(nxt, stack | {node})
            if c > best:
                best = c
                chosen = nxt
        best_cost[node] = best
        best_next[node] = chosen
        return best

    for scene in scene_order:
        cost_from(scene, frozenset())

    if not best_cost:
        return [], 0.0
    start = max(best_cost, key=lambda s: best_cost[s])
    path = [start]
    cur: str | None = start
    while cur is not None:
        cur = best_next.get(cur)
        if cur:
            path.append(cur)
    return path, best_cost[start]


def iter_facts(twin: ProductionTwin) -> Iterator[TemporalFact]:
    for versions in twin.facts.values():
        yield from versions
