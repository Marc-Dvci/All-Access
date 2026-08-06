"""Typed contracts for every record that crosses an agent, stream or system boundary.

Nothing in ProductionPulse passes free-form text between components. Every source
event, twin fact, constraint, finding, plan, approval, command, acknowledgment and
verification assertion is a validated model with an explicit schema version.
Malformed records are rejected at the boundary rather than interpreted by a
language model.

Two rules are enforced structurally rather than by convention:

1. A plan carries a `FeasibilityProof` or it is not a plan. There is no code path
   that marks a plan feasible without a solver result and an independent
   validation record.
2. A record that describes a person carries a `Classification`. The redaction
   layer in `privacy.py` refuses to serialise a record for an audience whose
   clearance does not cover it, so a leak requires deleting code rather than
   forgetting a check.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = "1.0.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def stable_hash(payload: Any) -> str:
    """Content hash used for plan identity, constraint sets and the audit chain.

    Sorted keys and a fixed separator so the same logical content hashes the same
    across processes and Python versions. `default=str` covers datetimes and
    enums, both of which appear in hashed payloads.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Mutable(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """Production roles that hold decision authority. Crew is deliberately last:
    it is the only role that receives instructions rather than making decisions."""

    UPM = "unit_production_manager"
    FIRST_AD = "first_assistant_director"
    COORDINATOR = "production_coordinator"
    DEPARTMENT_HEAD = "department_head"
    SAFETY_LEAD = "safety_lead"
    ACCESS_COORDINATOR = "accessibility_coordinator"
    LOCATION_MANAGER = "location_manager"
    TRANSPORT_COORDINATOR = "transport_coordinator"
    EXECUTIVE = "production_executive"
    CREW = "crew_member"
    SYSTEM = "system"


class Department(str, Enum):
    CAMERA = "camera"
    LIGHTING = "lighting"
    GRIP = "grip"
    SOUND = "sound"
    ART = "art"
    WARDROBE = "wardrobe"
    MAKEUP = "makeup"
    PROPS = "props"
    TRANSPORT = "transport"
    LOCATIONS = "locations"
    PRODUCTION = "production"
    SAFETY = "safety"
    ACCESS = "access_services"
    CATERING = "catering"
    VFX = "vfx"


class Classification(str, Enum):
    """Data classification. Ordered from least to most restricted; the ordering is
    used by `privacy.py` to decide whether an audience may see a field."""

    PUBLIC = "public"
    PRODUCTION_INTERNAL = "production_internal"
    OPERATIONAL_REQUIREMENT = "operational_requirement"
    PERSONAL = "personal"
    RESTRICTED_PERSONAL = "restricted_personal"


CLASSIFICATION_ORDER: dict[Classification, int] = {
    Classification.PUBLIC: 0,
    Classification.PRODUCTION_INTERNAL: 1,
    Classification.OPERATIONAL_REQUIREMENT: 2,
    Classification.PERSONAL: 3,
    Classification.RESTRICTED_PERSONAL: 4,
}


class Authority(str, Enum):
    """How much weight a source carries. Only AUTHORITATIVE sources may make a
    high-impact event effective without human confirmation."""

    AUTHORITATIVE = "authoritative"
    VERIFIED = "verified"
    REPORTED = "reported"
    INFERRED = "inferred"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class EventType(str, Enum):
    """Every stream subject in the system. The string values are the Confluent
    topic names, so this enum is the single source of truth for topic naming."""

    # Source
    SOURCE_EVENT_RECEIVED = "production.source-event.received"
    VOICE_UPDATE_RECEIVED = "production.voice-update.received"
    IMAGE_EVIDENCE_RECEIVED = "production.image-evidence.received"
    WEATHER_ALERTED = "production.weather.alerted"
    LOCATION_CHANGED = "production.location.changed"
    CAST_CHANGED = "production.cast.changed"
    CREW_CHANGED = "production.crew.changed"
    RESOURCE_CHANGED = "production.resource.changed"
    TRANSPORT_CHANGED = "production.transport.changed"
    PERMIT_CHANGED = "production.permit.changed"
    SAFETY_REPORTED = "production.safety.reported"
    ACCESS_SERVICE_CHANGED = "production.access-service.changed"

    # State
    TWIN_ENTITY_UPDATED = "production.digital-twin.entity-updated"
    CONSTRAINT_ACTIVATED = "production.constraint.activated"
    CONSTRAINT_CHANGED = "production.constraint.changed"
    CONSTRAINT_INVALIDATED = "production.constraint.invalidated"
    READINESS_CHANGED = "production.readiness.changed"
    SCHEDULE_CHANGED = "production.schedule.changed"
    ASSIGNMENT_CHANGED = "production.assignment.changed"

    # Assessment
    SCOPE_ASSESSED = "production.scope.assessed"
    SCHEDULE_FINDING = "production.schedule.finding"
    RESOURCE_FINDING = "production.resource.finding"
    SAFETY_FINDING = "production.safety.finding"
    ACCESS_FINDING = "production.access.finding"
    CONTINUITY_FINDING = "production.continuity.finding"
    SPATIAL_FINDING = "production.spatial.finding"
    BUDGET_FINDING = "production.budget.finding"
    SIMULATION_COMPLETED = "production.simulation.completed"

    # Decision
    PLAN_REQUESTED = "production.plan.requested"
    PLAN_GENERATED = "production.plan.generated"
    PLAN_REJECTED = "production.plan.rejected"
    PLAN_PRESENTED = "production.plan.presented"
    PLAN_APPROVAL_REQUESTED = "production.plan.approval-requested"
    PLAN_APPROVED = "production.plan.approved"
    PLAN_DECLINED = "production.plan.declined"

    # Execution
    COMMAND_ISSUED = "production.command.issued"
    COMMAND_ACCEPTED = "production.command.accepted"
    COMMAND_REJECTED = "production.command.rejected"
    COMMAND_COMPLETED = "production.command.completed"
    SYSTEM_UPDATED = "production.system.updated"
    DOCUMENT_PUBLISHED = "production.document.published"
    NOTIFICATION_SENT = "production.notification.sent"
    NOTIFICATION_DELIVERED = "production.notification.delivered"
    ACKNOWLEDGMENT_RECEIVED = "production.acknowledgment.received"
    VERIFICATION_COMPLETED = "production.verification.completed"

    # Audit and learning
    DECISION_RECORDED = "production.decision.recorded"
    OUTCOME_OBSERVED = "production.outcome.observed"
    PREDICTION_EVALUATED = "production.prediction.evaluated"
    DISRUPTION_CLOSED = "production.disruption.closed"


SOURCE_EVENT_TYPES: frozenset[EventType] = frozenset(
    {
        EventType.SOURCE_EVENT_RECEIVED,
        EventType.VOICE_UPDATE_RECEIVED,
        EventType.IMAGE_EVIDENCE_RECEIVED,
        EventType.WEATHER_ALERTED,
        EventType.LOCATION_CHANGED,
        EventType.CAST_CHANGED,
        EventType.CREW_CHANGED,
        EventType.RESOURCE_CHANGED,
        EventType.TRANSPORT_CHANGED,
        EventType.PERMIT_CHANGED,
        EventType.SAFETY_REPORTED,
        EventType.ACCESS_SERVICE_CHANGED,
    }
)


class DisruptionState(str, Enum):
    """The twelve states a disruption passes through. Transitions are enforced by
    `execution/state_machine.py`; there is no path from OPEN to EXECUTING."""

    OPEN = "open"
    QUALIFYING = "qualifying"
    SCOPING = "scoping"
    ASSESSING = "assessing"
    PLANNING = "planning"
    COMPARING = "comparing"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    RECONCILING = "reconciling"
    VERIFYING = "verifying"
    READY = "ready"
    CLOSED = "closed"
    ABANDONED = "abandoned"


DISRUPTION_TRANSITIONS: dict[DisruptionState, tuple[DisruptionState, ...]] = {
    DisruptionState.OPEN: (DisruptionState.QUALIFYING, DisruptionState.ABANDONED),
    DisruptionState.QUALIFYING: (DisruptionState.SCOPING, DisruptionState.ABANDONED),
    DisruptionState.SCOPING: (DisruptionState.ASSESSING, DisruptionState.ABANDONED),
    DisruptionState.ASSESSING: (DisruptionState.PLANNING, DisruptionState.ABANDONED),
    DisruptionState.PLANNING: (DisruptionState.COMPARING, DisruptionState.ABANDONED),
    DisruptionState.COMPARING: (
        DisruptionState.AWAITING_APPROVAL,
        DisruptionState.PLANNING,
        DisruptionState.ABANDONED,
    ),
    DisruptionState.AWAITING_APPROVAL: (
        DisruptionState.EXECUTING,
        DisruptionState.COMPARING,
        DisruptionState.ABANDONED,
    ),
    DisruptionState.EXECUTING: (DisruptionState.RECONCILING, DisruptionState.ABANDONED),
    DisruptionState.RECONCILING: (
        DisruptionState.VERIFYING,
        DisruptionState.EXECUTING,
        DisruptionState.ABANDONED,
    ),
    # VERIFYING can fall back to EXECUTING: this is the path taken when the
    # Verification Agent finds a missing acknowledgment and blocks "ready".
    DisruptionState.VERIFYING: (
        DisruptionState.READY,
        DisruptionState.EXECUTING,
        DisruptionState.ABANDONED,
    ),
    DisruptionState.READY: (DisruptionState.CLOSED,),
    DisruptionState.CLOSED: (),
    DisruptionState.ABANDONED: (),
}


class ConstraintKind(str, Enum):
    HARD = "hard"
    SOFT = "soft"
    CONDITIONAL = "conditional"
    APPROVAL = "approval"
    PRIVACY = "privacy"


class ConstraintDomain(str, Enum):
    SAFETY = "safety"
    WORKING_HOURS = "working_hours"
    CHILD_PERFORMER = "child_performer"
    REST = "rest"
    LOCATION = "location"
    PERMIT = "permit"
    RESOURCE = "resource"
    AVAILABILITY = "availability"
    ACCESS = "access"
    TRANSPORT = "transport"
    COMMUNICATION = "communication"
    STORAGE = "storage"
    EQUIPMENT = "equipment"
    EGRESS = "egress"
    WEATHER = "weather"
    CONTINUITY = "continuity"
    APPROVAL = "approval"
    PRIVACY = "privacy"
    BUDGET = "budget"
    DAYLIGHT = "daylight"


class FindingStatus(str, Enum):
    CLEAR = "clear"
    AT_RISK = "at_risk"
    BLOCKING = "blocking"
    UNKNOWN = "unknown"
    ABSTAINED = "abstained"


class CommandStatus(str, Enum):
    ISSUED = "issued"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIALLY_APPLIED = "partially_applied"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    COMPLETED = "completed"


class TargetSystem(str, Enum):
    SCHEDULING = "scheduling"
    CALL_SHEET = "call_sheet"
    TRANSPORT_DISPATCH = "transport_dispatch"
    INTERPRETER_BOOKING = "interpreter_booking"
    ACCESS_SERVICE = "access_service_booking"
    LOCATION_OPS = "location_operations"
    EQUIPMENT_INVENTORY = "equipment_inventory"
    DEPARTMENT_TASKS = "department_tasks"
    SAFETY_BRIEFING = "safety_briefing"
    CREW_MOBILE = "crew_mobile"
    EXECUTIVE_REPORTING = "executive_reporting"
    NOTIFICATION = "notification"
    PERMIT = "permit_system"
    EXPENSE = "expense_overtime"


# ---------------------------------------------------------------------------
# Event envelope
# ---------------------------------------------------------------------------


class EventEnvelope(Frozen):
    """The common envelope carried by every event on every stream.

    `payload_hash` and `signature` together make the stream tamper-evident:
    `stream/ledger.py` chains `previous_hash` across the whole log, so altering a
    historical event invalidates every event after it.
    """

    event_id: str
    schema_id: str
    schema_version: str = SCHEMA_VERSION
    event_type: EventType
    production_id: str
    unit_id: str | None = None
    disruption_id: str | None = None
    plan_id: str | None = None
    command_id: str | None = None
    correlation_id: str
    causation_id: str | None = None
    idempotency_key: str
    producer: str
    actor: str
    authority: Authority
    event_time: datetime
    effective_time: datetime | None = None
    ingestion_time: datetime = Field(default_factory=utcnow)
    classification: Classification = Classification.PRODUCTION_INTERNAL
    payload_hash: str
    signature: str | None = None
    previous_hash: str | None = None
    sequence: int | None = None
    trace_id: str | None = None
    partition_key: str

    @field_validator("idempotency_key")
    @classmethod
    def _key_present(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("idempotency_key must not be empty")
        return v


class Event(Frozen):
    """An envelope plus its typed payload. The payload is a plain dict because it
    is validated against the registered JSON Schema for `event_type` at the
    boundary — see `stream/registry.py`. Once validated it is never re-parsed."""

    envelope: EventEnvelope
    payload: dict[str, Any]

    def key(self) -> str:
        return self.envelope.partition_key

    def digest(self) -> str:
        return stable_hash({
            "envelope": self.envelope.model_dump(mode="json"),
            "payload": self.payload,
        })


# ---------------------------------------------------------------------------
# Twin facts
# ---------------------------------------------------------------------------


class TemporalFact(Frozen):
    """A bitemporal assertion about the production.

    The distinction the whole replay feature rests on: `valid_from`/`valid_to` is
    when the fact is true in the world; `transaction_time` is when the system
    learned it. "The vehicle was unavailable from 14:00" and "we found out at
    16:20" are different questions, and a post-incident review needs both.
    """

    fact_id: str
    entity_id: str
    entity_type: str
    attribute: str
    value: Any
    valid_from: datetime
    valid_to: datetime | None = None
    transaction_time: datetime = Field(default_factory=utcnow)
    version: int = 1
    source: str
    authority: Authority
    confidence: float = 1.0
    approval_state: Literal["approved", "pending", "not_required", "rejected"] = "not_required"
    classification: Classification = Classification.PRODUCTION_INTERNAL
    superseded_by: str | None = None

    @field_validator("confidence")
    @classmethod
    def _confidence_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        return v

    def effective_at(self, when: datetime) -> bool:
        if when < self.valid_from:
            return False
        return self.valid_to is None or when < self.valid_to


class Relationship(Frozen):
    rel_id: str
    source_id: str
    target_id: str
    kind: str
    valid_from: datetime
    valid_to: datetime | None = None
    transaction_time: datetime = Field(default_factory=utcnow)
    attributes: dict[str, Any] = Field(default_factory=dict)
    classification: Classification = Classification.PRODUCTION_INTERNAL

    def effective_at(self, when: datetime) -> bool:
        if when < self.valid_from:
            return False
        return self.valid_to is None or when < self.valid_to


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------


class ConstraintRecord(Frozen):
    """A constraint with its provenance. `solver_encoding` names the predicate in
    `solver/predicates.py` that evaluates it, which is what stops the registry
    from drifting into documentation: a constraint whose encoding does not resolve
    fails registry validation at import time."""

    constraint_id: str
    kind: ConstraintKind
    domain: ConstraintDomain
    title: str
    description: str
    owner: Role
    source: str
    source_evidence: str
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    priority: int = 100
    approval_state: Literal["approved", "pending", "not_required"] = "approved"
    disclosure: Classification = Classification.PRODUCTION_INTERNAL
    solver_encoding: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    last_validated: datetime | None = None
    subject_ids: tuple[str, ...] = ()

    def is_hard(self) -> bool:
        return self.kind in (ConstraintKind.HARD, ConstraintKind.CONDITIONAL)


class ConstraintViolation(Frozen):
    constraint_id: str
    domain: ConstraintDomain
    kind: ConstraintKind
    subject_id: str
    message: str
    evidence: str
    severity: Literal["blocking", "at_risk"] = "blocking"
    detail: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------


class Finding(Frozen):
    """The typed output of an expert agent or deterministic service.

    Agents cannot return prose. A finding that cannot be supported by evidence
    must use `FindingStatus.ABSTAINED`; the benchmark measures how often agents
    correctly abstain rather than guess.
    """

    finding_id: str
    disruption_id: str
    producer: str
    domain: ConstraintDomain
    scope: tuple[str, ...]
    status: FindingStatus
    headline: str
    evidence: tuple[str, ...] = ()
    applicable_constraints: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    confidence: float = 1.0
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    required_authority: Role | None = None
    solver_hints: dict[str, Any] = Field(default_factory=dict)
    classification: Classification = Classification.PRODUCTION_INTERNAL
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


class SceneAssignment(Frozen):
    scene_id: str
    location_id: str
    start: datetime
    end: datetime
    unit_id: str
    setup_start: datetime
    crew_call: datetime
    cast_calls: dict[str, datetime] = Field(default_factory=dict)
    equipment_ids: tuple[str, ...] = ()
    vehicle_ids: tuple[str, ...] = ()
    story_day: int = 1
    exterior: bool = False


class TransportLeg(Frozen):
    leg_id: str
    vehicle_id: str
    from_location: str
    to_location: str
    depart: datetime
    arrive: datetime
    passengers: tuple[str, ...] = ()
    step_free: bool = False
    purpose: str = "crew_move"


class AccessImplementation(Frozen):
    """How a plan discharges one approved practical requirement.

    Deliberately carries no diagnosis and no medical history — only the practical
    arrangement and whether the plan satisfies it. See docs/PRIVACY.md §2.
    """

    requirement_id: str
    person_id: str
    requirement: str
    satisfied: bool
    mechanism: str
    evidence: str
    at_risk: bool = False


class PlanObjectives(Frozen):
    """The measurable consequences of a plan. Every field is minimised. Safety and
    approved access requirements are absent by construction: they are hard
    constraints, not objectives, so no weighting can trade them away."""

    delay_minutes: float = 0.0
    cost_delta: float = 0.0
    overtime_minutes: float = 0.0
    idle_crew_minutes: float = 0.0
    travel_minutes: float = 0.0
    setup_complexity: float = 0.0
    weather_exposure: float = 0.0
    continuity_risk: float = 0.0
    operational_risk: float = 0.0
    communication_burden: float = 0.0
    changed_assignments: int = 0

    def vector(self) -> tuple[float, ...]:
        return (
            self.delay_minutes,
            self.cost_delta,
            self.overtime_minutes,
            self.idle_crew_minutes,
            self.travel_minutes,
            self.setup_complexity,
            self.weather_exposure,
            self.continuity_risk,
            self.operational_risk,
            self.communication_burden,
            float(self.changed_assignments),
        )

    @staticmethod
    def labels() -> tuple[str, ...]:
        return (
            "delay_minutes",
            "cost_delta",
            "overtime_minutes",
            "idle_crew_minutes",
            "travel_minutes",
            "setup_complexity",
            "weather_exposure",
            "continuity_risk",
            "operational_risk",
            "communication_burden",
            "changed_assignments",
        )


class RobustnessReport(Frozen):
    scenarios: int
    on_time_probability: float
    expected_delay_minutes: float
    worst_credible_delay_minutes: float
    overtime_risk: float
    constraint_violation_risk: float
    recovery_margin_minutes: float
    sensitive_assumptions: tuple[str, ...] = ()
    sensitivity: dict[str, float] = Field(default_factory=dict)


class FeasibilityProof(Frozen):
    """Why a plan is believed feasible, in enough detail to re-check it.

    `constraint_set_hash` binds the proof to the exact constraints that were
    active. An approval signed against one constraint hash cannot be replayed
    against a different one — see `approvals.py`.
    """

    solver_version: str
    model_version: str
    constraint_set_hash: str
    input_state_sequence: int
    objective_weights: dict[str, float]
    variable_assignments: dict[str, Any]
    satisfiable: bool
    solution_quality: float
    optimality_gap: float | None = None
    search_nodes: int = 0
    propagations: int = 0
    solve_ms: float = 0.0
    incremental: bool = False
    frozen_decisions: int = 0
    repaired_decisions: int = 0
    validated: bool = False
    validator_report: dict[str, Any] = Field(default_factory=dict)


class ConflictSet(Frozen):
    """A minimal (or near-minimal) set of constraints that cannot hold together.

    Produced by QuickXplain in `solver/infeasibility.py`. `minimal` records
    whether the reduction actually ran to completion or was cut short by the node
    budget, because claiming minimality you did not verify is exactly the kind of
    thing this project does not do.
    """

    constraint_ids: tuple[str, ...]
    explanation: str
    production_language: str
    evidence: dict[str, str] = Field(default_factory=dict)
    minimal: bool = True
    #: Every constraint this plan breaks, not just the minimal explanatory set.
    #: A minimal conflict answers "why is this rejected"; the full set answers
    #: "what would I have to fix", and a location that fails on four separate
    #: counts should not look like it fails on one.
    all_blocking_ids: tuple[str, ...] = ()
    required_change: str | None = None
    change_permitted: bool | None = None
    change_authority: Role | None = None


class Plan(Frozen):
    plan_id: str
    disruption_id: str
    strategy: str
    label: str
    rationale: str
    feasible: bool
    scenes: tuple[SceneAssignment, ...]
    transport: tuple[TransportLeg, ...] = ()
    access: tuple[AccessImplementation, ...] = ()
    safety_controls: tuple[str, ...] = ()
    permits: tuple[str, ...] = ()
    continuity_notes: tuple[str, ...] = ()
    objectives: PlanObjectives = Field(default_factory=PlanObjectives)
    robustness: RobustnessReport | None = None
    proof: FeasibilityProof | None = None
    conflicts: tuple[ConflictSet, ...] = ()
    required_approvals: tuple[Role, ...] = ()
    command_set: tuple[str, ...] = ()
    verification_checklist: tuple[str, ...] = ()
    deferred_scenes: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utcnow)

    def content_hash(self) -> str:
        return stable_hash(
            {
                "strategy": self.strategy,
                "scenes": [s.model_dump(mode="json") for s in self.scenes],
                "transport": [t.model_dump(mode="json") for t in self.transport],
                "access": [a.model_dump(mode="json") for a in self.access],
                "objectives": self.objectives.model_dump(mode="json"),
                "deferred": list(self.deferred_scenes),
            }
        )


# ---------------------------------------------------------------------------
# Approvals, commands, verification
# ---------------------------------------------------------------------------


class ApprovalRequest(Frozen):
    request_id: str
    disruption_id: str
    plan_id: str
    plan_hash: str
    constraint_hash: str
    required_roles: tuple[Role, ...]
    scope: str
    summary: str
    expires_at: datetime
    created_at: datetime = Field(default_factory=utcnow)


class Approval(Frozen):
    """A signed, single-use, hash-bound authorisation.

    Bound to `plan_hash` *and* `constraint_hash`: an approval granted while a
    constraint was inactive cannot be replayed after that constraint returns.
    `approvals.py` enforces single use.
    """

    approval_id: str
    request_id: str
    disruption_id: str
    plan_id: str
    plan_hash: str
    constraint_hash: str
    actor: str
    role: Role
    production_id: str
    approved_scope: str
    rationale: str
    granted_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    signature: str
    consumed: bool = False


class Command(Frozen):
    command_id: str
    disruption_id: str
    plan_id: str
    plan_version: int
    target: TargetSystem
    action: str
    payload: dict[str, Any]
    idempotency_key: str
    depends_on: tuple[str, ...] = ()
    compensation: str | None = None
    required_role: Role | None = None
    issued_at: datetime = Field(default_factory=utcnow)
    classification: Classification = Classification.PRODUCTION_INTERNAL


class CommandResult(Frozen):
    command_id: str
    target: TargetSystem
    status: CommandStatus
    detail: str
    system_version: int | None = None
    error: str | None = None
    attempts: int = 1
    duplicate_suppressed: bool = False
    completed_at: datetime = Field(default_factory=utcnow)


class Acknowledgment(Frozen):
    ack_id: str
    command_id: str | None
    disruption_id: str
    person_id: str
    role: Role
    channel: str
    message_id: str
    accepted: bool
    reason: str | None = None
    received_at: datetime = Field(default_factory=utcnow)


class VerificationAssertion(Frozen):
    assertion_id: str
    name: str
    critical: bool
    passed: bool
    expected: str
    observed: str
    evidence: str = ""
    remedy: str | None = None


class VerificationReport(Frozen):
    report_id: str
    disruption_id: str
    plan_id: str
    assertions: tuple[VerificationAssertion, ...]
    ready: bool
    blocking: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utcnow)

    @property
    def passed(self) -> int:
        return sum(1 for a in self.assertions if a.passed)


class CommunicationMessage(Frozen):
    """A message generated from the approved structured plan.

    `derived_from` names the plan and command it came from. There is no path that
    lets an agent compose a crew message from its own memory: `communication.py`
    takes a plan and a recipient, never a conversation.
    """

    message_id: str
    disruption_id: str
    recipient_id: str
    recipient_role: Role
    channel: str
    subject: str
    body: str
    language: str = "en"
    derived_from: tuple[str, ...] = ()
    classification: Classification = Classification.PRODUCTION_INTERNAL
    requires_ack: bool = True
    accessible_formats: tuple[str, ...] = ()
    created_at: datetime = Field(default_factory=utcnow)


class Disruption(Mutable):
    disruption_id: str
    production_id: str
    unit_id: str
    title: str
    state: DisruptionState = DisruptionState.OPEN
    opened_at: datetime = Field(default_factory=utcnow)
    source_event_id: str | None = None
    scenario_id: str | None = None
    findings: list[Finding] = Field(default_factory=list)
    plans: list[Plan] = Field(default_factory=list)
    selected_plan_id: str | None = None
    approvals: list[Approval] = Field(default_factory=list)
    commands: list[Command] = Field(default_factory=list)
    results: list[CommandResult] = Field(default_factory=list)
    acknowledgments: list[Acknowledgment] = Field(default_factory=list)
    verification: VerificationReport | None = None
    closed_at: datetime | None = None
    history: list[tuple[str, str]] = Field(default_factory=list)


class OutcomeRecord(Frozen):
    """Predicted versus actual, recorded after the fact. This is what makes the
    calibration numbers in docs/BENCHMARK.md checkable rather than asserted."""

    disruption_id: str
    plan_id: str
    predicted_delay_minutes: float
    actual_delay_minutes: float
    predicted_overtime_minutes: float
    actual_overtime_minutes: float
    predicted_cost_delta: float
    actual_cost_delta: float
    access_preserved: bool
    safety_preserved: bool
    hard_violations: int
    acknowledgment_completeness: float
    time_to_first_plan_ms: float
    time_to_approval_ms: float
    time_to_ready_ms: float
    manual_steps_avoided: int
    observed_at: datetime = Field(default_factory=utcnow)


DEFAULT_APPROVAL_TTL = timedelta(minutes=45)
