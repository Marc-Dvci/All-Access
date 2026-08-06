"""Stream governance: catalogue, lineage and replay.

Three judge-facing capabilities.

**Catalogue.** Every topic with its owner, business description, classification
and the contract that governs it. Built from the contract registry rather than
maintained by hand, so it cannot describe a topic that does not exist or miss one
that does.

**Lineage.** `trace()` walks `causation_id` backwards from any event to the
source event that caused it, and forwards to everything it caused. This is what
shows the path from the weather alert through the assessments, the plan, the
approval, the commands and the acknowledgments — as data derived from the log,
not a diagram drawn separately and hoped to be accurate.

**Replay.** `replay_to()` rebuilds the materialised state at any sequence number.
`verify_replay()` asserts that a full replay reproduces the live state exactly,
which is the property that makes the audit trail worth having.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..contracts import Event, EventType
from .schemas import CONTRACTS, contract_for
from .views import MaterializedViews


@dataclass(frozen=True)
class CatalogEntry:
    topic: str
    subject: str | None
    owner: str
    description: str
    classification: str
    compatibility: str
    tags: tuple[str, ...]
    domain: str


def _domain_of(event_type: EventType) -> str:
    value = event_type.value
    if any(k in value for k in ("source-event", "voice", "image", "weather", "reported")):
        return "source"
    if any(k in value for k in ("digital-twin", "constraint", "readiness", "schedule.changed",
                                "assignment")):
        return "state"
    if any(k in value for k in ("finding", "scope", "simulation")):
        return "assessment"
    if ".plan." in value:
        return "decision"
    if any(k in value for k in ("command", "system.updated", "document", "notification",
                                "acknowledgment", "verification")):
        return "execution"
    return "audit"


def catalog() -> list[CatalogEntry]:
    """Every stream subject, described. One entry per event type."""
    entries: list[CatalogEntry] = []
    for event_type in EventType:
        contract = contract_for(event_type)
        entries.append(CatalogEntry(
            topic=event_type.value,
            subject=contract.subject if contract else None,
            owner=contract.owner.value if contract else "production_coordinator",
            description=(
                contract.description if contract
                else f"{event_type.name.replace('_', ' ').capitalize()}."
            ),
            classification=(
                contract.classification.value if contract else "production_internal"
            ),
            compatibility=contract.compatibility if contract else "BACKWARD",
            tags=contract.tags if contract else (),
            domain=_domain_of(event_type),
        ))
    return sorted(entries, key=lambda e: (e.domain, e.topic))


def catalog_summary() -> dict[str, Any]:
    entries = catalog()
    by_domain: dict[str, int] = defaultdict(int)
    for entry in entries:
        by_domain[entry.domain] += 1
    governed = sum(1 for e in entries if e.subject)
    return {
        "topics": len(entries),
        "governed_by_contract": governed,
        "ungoverned": [e.topic for e in entries if not e.subject],
        "by_domain": dict(sorted(by_domain.items())),
        "contracts": len(CONTRACTS),
    }


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


@dataclass
class LineageNode:
    event_id: str
    event_type: str
    producer: str
    actor: str
    at: str
    summary: str
    depth: int = 0
    caused_by: str | None = None


@dataclass
class Lineage:
    root: str
    nodes: list[LineageNode] = field(default_factory=list)
    edges: list[tuple[str, str]] = field(default_factory=list)

    @property
    def depth(self) -> int:
        return max((n.depth for n in self.nodes), default=0)

    def by_domain(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = defaultdict(list)
        for node in self.nodes:
            try:
                domain = _domain_of(EventType(node.event_type))
            except ValueError:
                domain = "audit"
            out[domain].append(node.event_id)
        return dict(out)

    def path_summary(self) -> list[str]:
        """One line per hop, in depth order. What the demo shows on screen."""
        return [
            f"{'  ' * n.depth}{n.event_type} <- {n.producer}: {n.summary}"
            for n in sorted(self.nodes, key=lambda x: (x.depth, x.event_id))
        ]


def _summarise(event: Event) -> str:
    p = event.payload
    for key in ("headline", "summary", "label", "detail", "subject", "condition", "action"):
        if key in p and p[key]:
            return str(p[key])[:120]
    for key in ("plan_id", "command_id", "message_id", "constraint_id"):
        if key in p and p[key]:
            return f"{key}={p[key]}"
    return event.envelope.event_type.name.lower()


def trace(events: Iterable[Event], root_event_id: str) -> Lineage:
    """Everything downstream of one event, by causation."""
    index = {e.envelope.event_id: e for e in events}
    children: dict[str, list[str]] = defaultdict(list)
    for e in index.values():
        if e.envelope.causation_id:
            children[e.envelope.causation_id].append(e.envelope.event_id)

    lineage = Lineage(root=root_event_id)
    if root_event_id not in index:
        return lineage

    queue: list[tuple[str, int]] = [(root_event_id, 0)]
    seen: set[str] = set()
    while queue:
        event_id, depth = queue.pop(0)
        if event_id in seen:
            continue
        seen.add(event_id)
        event = index[event_id]
        lineage.nodes.append(LineageNode(
            event_id=event_id,
            event_type=event.envelope.event_type.value,
            producer=event.envelope.producer,
            actor=event.envelope.actor,
            at=event.envelope.event_time.isoformat(),
            summary=_summarise(event),
            depth=depth,
            caused_by=event.envelope.causation_id,
        ))
        for child in sorted(children.get(event_id, [])):
            lineage.edges.append((event_id, child))
            queue.append((child, depth + 1))
    return lineage


def upstream(events: Iterable[Event], event_id: str) -> list[LineageNode]:
    """The causation chain from an event back to its source."""
    index = {e.envelope.event_id: e for e in events}
    chain: list[LineageNode] = []
    current = index.get(event_id)
    depth = 0
    seen: set[str] = set()
    while current is not None and current.envelope.event_id not in seen:
        seen.add(current.envelope.event_id)
        chain.append(LineageNode(
            event_id=current.envelope.event_id,
            event_type=current.envelope.event_type.value,
            producer=current.envelope.producer,
            actor=current.envelope.actor,
            at=current.envelope.event_time.isoformat(),
            summary=_summarise(current),
            depth=depth,
            caused_by=current.envelope.causation_id,
        ))
        depth += 1
        cause = current.envelope.causation_id
        current = index.get(cause) if cause else None
    return chain


def correlation_group(events: Iterable[Event], correlation_id: str) -> list[Event]:
    return sorted(
        (e for e in events if e.envelope.correlation_id == correlation_id),
        key=lambda e: e.envelope.sequence or 0,
    )


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def replay_to(events: Iterable[Event], sequence: int | None = None) -> MaterializedViews:
    """Rebuild materialised state from the log, optionally up to a sequence."""
    views = MaterializedViews()
    for event in sorted(events, key=lambda e: e.envelope.sequence or 0):
        if sequence is not None and (event.envelope.sequence or 0) > sequence:
            break
        views.apply(event)
    return views


@dataclass
class ReplayCheck:
    identical: bool
    live_events: int
    replayed_events: int
    differences: list[str] = field(default_factory=list)


def verify_replay(events: Iterable[Event], live: MaterializedViews) -> ReplayCheck:
    """Assert that a full replay reproduces the live state exactly."""
    materialised = list(events)
    replayed = replay_to(materialised)
    live_snapshot = live.snapshot()
    replay_snapshot = replayed.snapshot()
    differences: list[str] = []

    def compare(path: str, a: Any, b: Any) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                compare(f"{path}.{key}", a.get(key), b.get(key))
        elif a != b:
            differences.append(f"{path}: live={a!r} replay={b!r}")

    compare("state", live_snapshot, replay_snapshot)
    return ReplayCheck(
        identical=not differences,
        live_events=live.events_applied,
        replayed_events=replayed.events_applied,
        differences=differences,
    )


def decision_context(events: Iterable[Event], plan_id: str) -> dict[str, Any]:
    """Everything that was known when a plan was decided.

    The §5.5 requirement: a reviewer picks a plan and sees which facts existed,
    which constraints were active, which agents produced findings, which solver
    version ran, which options were feasible and which decision was approved —
    reconstructed from the log rather than from a summary written afterwards.
    """
    ordered = sorted(events, key=lambda e: e.envelope.sequence or 0)
    decision_seq: int | None = None
    for event in ordered:
        if (event.envelope.event_type == EventType.PLAN_APPROVED
                and event.payload.get("plan_id") == plan_id):
            decision_seq = event.envelope.sequence
            break
    if decision_seq is None:
        for event in ordered:
            if (event.envelope.event_type == EventType.PLAN_GENERATED
                    and event.payload.get("plan_id") == plan_id):
                decision_seq = event.envelope.sequence
                break
    if decision_seq is None:
        return {"plan_id": plan_id, "found": False}

    prior = [e for e in ordered if (e.envelope.sequence or 0) <= decision_seq]
    findings = [
        {
            "producer": e.envelope.producer,
            "domain": e.payload.get("domain"),
            "status": e.payload.get("status"),
            "headline": e.payload.get("headline"),
            "evidence": e.payload.get("evidence", []),
        }
        for e in prior if str(e.envelope.event_type.value).endswith(".finding")
    ]
    options = [
        {
            "plan_id": e.payload.get("plan_id"),
            "strategy": e.payload.get("strategy"),
            "feasible": e.payload.get("feasible"),
            "objectives": e.payload.get("objectives"),
            "conflicts": e.payload.get("conflicts"),
        }
        for e in prior if e.envelope.event_type == EventType.PLAN_GENERATED
    ]
    approval = next(
        (e.payload for e in prior
         if e.envelope.event_type == EventType.PLAN_APPROVED
         and e.payload.get("plan_id") == plan_id),
        None,
    )
    chosen = next((o for o in options if o["plan_id"] == plan_id), None)
    return {
        "plan_id": plan_id,
        "found": True,
        "decision_sequence": decision_seq,
        "events_before_decision": len(prior),
        "state": replay_to(prior).snapshot(),
        "findings": findings,
        "options_considered": options,
        "selected": chosen,
        "solver_version": (chosen or {}).get("proof", {}).get("solver_version")
        if isinstance((chosen or {}).get("proof"), dict) else None,
        "approval": approval,
        "lineage": [n.__dict__ for n in upstream(prior, ordered[0].envelope.event_id)][:1],
    }
