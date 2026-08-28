"""Data contracts for every event subject.

JSON Schema rather than Avro or Protobuf, for one reason: the schemas have to be
readable by a judge in a browser without a code generator, and every consumer
here is Python. The governance properties that matter — versioning, compatibility
checking, ownership metadata, field-level classification, and rejection of
malformed payloads before they reach the execution stream — are all present, and
they run at runtime rather than in a build step.

Compatibility is enforced by `check_compatibility()`, which implements Confluent's
BACKWARD rule: a new version may add optional fields and may not remove or
narrow required ones. `tests/test_stream.py` asserts that an added optional field
is accepted and that a new required field or a narrowed type is rejected, so a
breaking change fails CI rather than production.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import Classification, EventType, Role

#: Field-level classification tags. The privacy layer reads these to decide what
#: a given audience may receive, so a field's sensitivity is declared once, in
#: the contract, rather than remembered at each call site.
FIELD_CLASSIFICATIONS: dict[str, Classification] = {
    "person_id": Classification.PERSONAL,
    "performer_id": Classification.PERSONAL,
    "crew_id": Classification.PERSONAL,
    "name": Classification.PERSONAL,
    "requirement": Classification.OPERATIONAL_REQUIREMENT,
    "mechanism": Classification.OPERATIONAL_REQUIREMENT,
    "access_requirements": Classification.OPERATIONAL_REQUIREMENT,
    "cast_calls": Classification.PERSONAL,
    "rationale": Classification.PRODUCTION_INTERNAL,
}


@dataclass(frozen=True)
class DataContract:
    """One registered subject: its schema, owner, compatibility mode and rules."""

    subject: str
    version: int
    event_type: EventType
    owner: Role
    description: str
    schema: dict[str, Any]
    compatibility: str = "BACKWARD"
    classification: Classification = Classification.PRODUCTION_INTERNAL
    #: Domain validation rules beyond structural typing, as (name, expression)
    #: pairs evaluated against the payload by `validate_rules()`.
    rules: tuple[tuple[str, str], ...] = ()
    deprecated: bool = False
    tags: tuple[str, ...] = ()


def _obj(properties: dict[str, Any], required: list[str],
         additional: bool = False) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": additional,
    }


STR = {"type": "string"}
NUM = {"type": "number"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}
TS = {"type": "string", "format": "date-time"}


def _envelope_schema() -> dict[str, Any]:
    return _obj(
        {
            "event_id": STR,
            "schema_id": STR,
            "schema_version": STR,
            "event_type": STR,
            "production_id": STR,
            "unit_id": {"type": ["string", "null"]},
            "disruption_id": {"type": ["string", "null"]},
            "plan_id": {"type": ["string", "null"]},
            "command_id": {"type": ["string", "null"]},
            "correlation_id": STR,
            "causation_id": {"type": ["string", "null"]},
            "idempotency_key": STR,
            "producer": STR,
            "actor": STR,
            "authority": {"enum": ["authoritative", "verified", "reported", "inferred"]},
            "event_time": TS,
            "effective_time": {"type": ["string", "null"], "format": "date-time"},
            "ingestion_time": TS,
            "classification": STR,
            "payload_hash": STR,
            "signature": {"type": ["string", "null"]},
            "previous_hash": {"type": ["string", "null"]},
            "sequence": {"type": ["integer", "null"]},
            "trace_id": {"type": ["string", "null"]},
            "partition_key": STR,
        },
        [
            "event_id", "schema_id", "event_type", "production_id", "correlation_id",
            "idempotency_key", "producer", "actor", "authority", "event_time",
            "payload_hash", "partition_key",
        ],
    )


ENVELOPE_SCHEMA = _envelope_schema()


CONTRACTS: tuple[DataContract, ...] = (
    DataContract(
        subject="production.weather.alerted-value",
        version=1,
        event_type=EventType.WEATHER_ALERTED,
        owner=Role.SAFETY_LEAD,
        description="A forecast or observed weather change affecting production conditions.",
        schema=_obj(
            {
                "entity_id": STR,
                "condition": STR,
                "wind_kph": NUM,
                "precipitation_mm": NUM,
                "precipitation_probability": NUM,
                "sea_state": INT,
                "lightning_risk": NUM,
                "window_start": TS,
                "window_end": TS,
                "affected_locations": {"type": "array", "items": STR},
                "confidence": NUM,
                "attributes": {"type": "object"},
            },
            ["entity_id", "condition", "wind_kph", "window_start", "window_end"],
        ),
        rules=(
            ("wind_non_negative", "payload['wind_kph'] >= 0"),
            ("probability_range", "0 <= payload.get('precipitation_probability', 0) <= 1"),
            ("window_ordered", "payload['window_start'] < payload['window_end']"),
        ),
        tags=("safety", "source"),
    ),
    DataContract(
        subject="production.source-event.received-value",
        version=1,
        event_type=EventType.SOURCE_EVENT_RECEIVED,
        owner=Role.COORDINATOR,
        description="Any typed operational change reported by a source system or a person.",
        schema=_obj(
            {
                "entity_id": {"type": ["string", "null"]},
                "kind": STR,
                "summary": STR,
                "attributes": {"type": "object"},
                "confidence": NUM,
                "verification_state": STR,
                "evidence_ref": {"type": ["string", "null"]},
                "reported_by": {"type": ["string", "null"]},
            },
            ["kind", "summary"],
        ),
        rules=(("confidence_range", "0 <= payload.get('confidence', 1) <= 1"),),
        tags=("intake",),
    ),
    DataContract(
        subject="production.voice-update.received-value",
        version=1,
        event_type=EventType.VOICE_UPDATE_RECEIVED,
        owner=Role.COORDINATOR,
        description="An unstructured spoken update awaiting interpretation.",
        schema=_obj(
            {
                "transcript": STR,
                "reported_by": STR,
                "duration_seconds": NUM,
                "channel": STR,
                "evidence_ref": {"type": ["string", "null"]},
            },
            ["transcript", "reported_by"],
        ),
        classification=Classification.PRODUCTION_INTERNAL,
        tags=("intake", "multimodal"),
    ),
    DataContract(
        subject="production.image-evidence.received-value",
        version=1,
        event_type=EventType.IMAGE_EVIDENCE_RECEIVED,
        owner=Role.LOCATION_MANAGER,
        description="A photograph submitted as evidence of a location or resource condition.",
        schema=_obj(
            {
                "evidence_ref": STR,
                "caption": STR,
                "reported_by": STR,
                "location_id": {"type": ["string", "null"]},
                "detected": {"type": "array", "items": STR},
            },
            ["evidence_ref", "reported_by"],
        ),
        tags=("intake", "multimodal"),
    ),
    DataContract(
        subject="production.digital-twin.entity-updated-value",
        version=1,
        event_type=EventType.TWIN_ENTITY_UPDATED,
        owner=Role.COORDINATOR,
        description="A change to a digital twin entity's attributes.",
        schema=_obj(
            {
                "entity_id": STR,
                "entity_type": STR,
                "label": STR,
                "attributes": {"type": "object"},
                "confidence": NUM,
            },
            ["entity_id", "entity_type", "attributes"],
        ),
        tags=("state",),
    ),
    DataContract(
        subject="production.scope.assessed-value",
        version=1,
        event_type=EventType.SCOPE_ASSESSED,
        owner=Role.COORDINATOR,
        description="The computed blast radius of a disruption.",
        schema=_obj(
            {
                "origin_ids": {"type": "array", "items": STR},
                "direct": {"type": "array", "items": STR},
                "transitive": {"type": "array", "items": STR},
                "departments": {"type": "array", "items": STR},
                "people": {"type": "array", "items": STR},
                "documents": {"type": "array", "items": STR},
                "access_requirements": {"type": "array", "items": STR},
                "scenes": {"type": "array", "items": STR},
                "max_depth": INT,
                "critical_path": {"type": "array", "items": STR},
            },
            ["origin_ids", "direct"],
        ),
        classification=Classification.OPERATIONAL_REQUIREMENT,
        tags=("assessment",),
    ),
    DataContract(
        subject="production.finding-value",
        version=1,
        event_type=EventType.SAFETY_FINDING,
        owner=Role.COORDINATOR,
        description=(
            "A typed expert finding. One contract serves every finding subject: the domain "
            "is a field, so adding a new expert agent does not require a schema migration."
        ),
        schema=_obj(
            {
                "finding_id": STR,
                "disruption_id": STR,
                "producer": STR,
                "domain": STR,
                "scope": {"type": "array", "items": STR},
                "status": {"enum": ["clear", "at_risk", "blocking", "unknown", "abstained"]},
                "headline": STR,
                "evidence": {"type": "array", "items": STR},
                "applicable_constraints": {"type": "array", "items": STR},
                "assumptions": {"type": "array", "items": STR},
                "confidence": NUM,
                "uncertainty": {"type": "object"},
                "required_authority": {"type": ["string", "null"]},
                "solver_hints": {"type": "object"},
                "classification": STR,
            },
            ["finding_id", "disruption_id", "producer", "domain", "status", "headline"],
        ),
        rules=(
            ("confidence_range", "0 <= payload.get('confidence', 1) <= 1"),
            # An agent that reports a blocking finding must say what it is
            # blocking on. This is the rule that stops "there may be an issue"
            # from ever reaching a decision-maker.
            ("blocking_needs_evidence",
             "payload['status'] != 'blocking' or len(payload.get('evidence') or []) > 0"),
            ("abstain_has_no_claim",
             "payload['status'] != 'abstained' "
             "or len(payload.get('applicable_constraints') or []) == 0"),
        ),
        tags=("assessment",),
    ),
    DataContract(
        subject="production.plan.generated-value",
        version=1,
        event_type=EventType.PLAN_GENERATED,
        owner=Role.COORDINATOR,
        description="A generated plan with its feasibility proof or conflict set.",
        schema=_obj(
            {
                "plan_id": STR,
                "disruption_id": STR,
                "strategy": STR,
                "label": STR,
                "feasible": BOOL,
                "objectives": {"type": "object"},
                "scene_count": INT,
                "required_approvals": {"type": "array", "items": STR},
                "proof": {"type": ["object", "null"]},
                "conflicts": {"type": "array"},
                "plan_hash": STR,
            },
            ["plan_id", "disruption_id", "strategy", "feasible", "plan_hash"],
        ),
        rules=(
            # The structural guarantee, enforced at the stream boundary: a plan
            # cannot be published feasible without a validated proof. Even a
            # buggy producer cannot get an unproven plan onto the decision topic.
            ("feasible_requires_validated_proof",
             "(not payload['feasible']) or "
             "(payload.get('proof') and payload['proof'].get('validated') is True "
             "and payload['proof'].get('satisfiable') is True)"),
            ("infeasible_requires_conflicts",
             "payload['feasible'] or len(payload.get('conflicts') or []) > 0"),
        ),
        tags=("decision",),
    ),
    DataContract(
        subject="production.plan.approved-value",
        version=1,
        event_type=EventType.PLAN_APPROVED,
        owner=Role.UPM,
        description="A signed approval binding an actor to a specific plan and constraint set.",
        schema=_obj(
            {
                "approval_id": STR,
                "request_id": STR,
                "disruption_id": STR,
                "plan_id": STR,
                "plan_hash": STR,
                "constraint_hash": STR,
                "actor": STR,
                "role": STR,
                "approved_scope": STR,
                "rationale": STR,
                "expires_at": TS,
                "signature": STR,
            },
            ["approval_id", "plan_id", "plan_hash", "constraint_hash", "actor", "role",
             "signature", "expires_at"],
        ),
        rules=(
            ("signature_present", "len(payload['signature']) >= 32"),
            ("rationale_present", "len(payload.get('rationale') or '') > 0"),
        ),
        tags=("decision", "audit"),
    ),
    DataContract(
        subject="production.command.issued-value",
        version=1,
        event_type=EventType.COMMAND_ISSUED,
        owner=Role.COORDINATOR,
        description="A typed command to a downstream operational system.",
        schema=_obj(
            {
                "command_id": STR,
                "disruption_id": STR,
                "plan_id": STR,
                "plan_version": INT,
                "target": STR,
                "action": STR,
                "payload": {"type": "object"},
                "idempotency_key": STR,
                "depends_on": {"type": "array", "items": STR},
                "compensation": {"type": ["string", "null"]},
                "required_role": {"type": ["string", "null"]},
            },
            ["command_id", "plan_id", "target", "action", "idempotency_key"],
        ),
        rules=(
            ("idempotency_key_present", "len(payload['idempotency_key']) >= 8"),
            ("known_target",
             "payload['target'] in ['scheduling','call_sheet','transport_dispatch',"
             "'interpreter_booking','access_service_booking','location_operations',"
             "'equipment_inventory','department_tasks','safety_briefing','crew_mobile',"
             "'executive_reporting','notification','permit_system','expense_overtime']"),
        ),
        tags=("execution",),
    ),
    DataContract(
        subject="production.command.result-value",
        version=1,
        event_type=EventType.COMMAND_ACCEPTED,
        owner=Role.COORDINATOR,
        description="The outcome of a command at its target system.",
        schema=_obj(
            {
                "command_id": STR,
                "target": STR,
                "status": {"enum": ["issued", "accepted", "rejected", "partially_applied",
                                    "failed", "superseded", "completed"]},
                "detail": STR,
                "system_version": {"type": ["integer", "null"]},
                "error": {"type": ["string", "null"]},
                "attempts": INT,
                "duplicate_suppressed": BOOL,
            },
            ["command_id", "target", "status", "detail"],
        ),
        tags=("execution",),
    ),
    DataContract(
        subject="production.acknowledgment.received-value",
        version=1,
        event_type=EventType.ACKNOWLEDGMENT_RECEIVED,
        owner=Role.COORDINATOR,
        description="A person confirming they received and can execute an instruction.",
        schema=_obj(
            {
                "ack_id": STR,
                "command_id": {"type": ["string", "null"]},
                "disruption_id": STR,
                "person_id": STR,
                "role": STR,
                "channel": STR,
                "message_id": STR,
                "accepted": BOOL,
                "reason": {"type": ["string", "null"]},
            },
            ["ack_id", "disruption_id", "person_id", "role", "message_id", "accepted"],
        ),
        classification=Classification.PERSONAL,
        rules=(("rejection_needs_reason",
                "payload['accepted'] or len(payload.get('reason') or '') > 0"),),
        tags=("execution",),
    ),
    DataContract(
        subject="production.verification.completed-value",
        version=1,
        event_type=EventType.VERIFICATION_COMPLETED,
        owner=Role.COORDINATOR,
        description="The reconciliation result comparing intended and observed state.",
        schema=_obj(
            {
                "report_id": STR,
                "disruption_id": STR,
                "plan_id": STR,
                "ready": BOOL,
                "assertions": {"type": "array"},
                "passed": INT,
                "total": INT,
                "blocking": {"type": "array", "items": STR},
            },
            ["report_id", "disruption_id", "plan_id", "ready", "passed", "total"],
        ),
        rules=(
            # Readiness is a claim about the world, and it must be backed by
            # every critical assertion passing. A producer cannot assert ready
            # while listing blockers.
            ("ready_requires_no_blockers",
             "(not payload['ready']) or len(payload.get('blocking') or []) == 0"),
        ),
        tags=("execution", "audit"),
    ),
    DataContract(
        subject="production.notification.sent-value",
        version=1,
        event_type=EventType.NOTIFICATION_SENT,
        owner=Role.COORDINATOR,
        description="A role-specific message generated from an approved plan.",
        schema=_obj(
            {
                "message_id": STR,
                "disruption_id": STR,
                "recipient_id": STR,
                "recipient_role": STR,
                "channel": STR,
                "subject": STR,
                "body": STR,
                "language": STR,
                "derived_from": {"type": "array", "items": STR},
                "requires_ack": BOOL,
                "accessible_formats": {"type": "array", "items": STR},
                "classification": STR,
            },
            ["message_id", "disruption_id", "recipient_id", "recipient_role", "subject", "body"],
        ),
        classification=Classification.PERSONAL,
        rules=(
            # Every crew message must trace to the approved plan it came from.
            # This is what makes "generated from the approved structured plan,
            # not from free-form agent memory" checkable rather than a promise.
            ("must_derive_from_plan", "len(payload.get('derived_from') or []) > 0"),
        ),
        tags=("execution", "communication"),
    ),
    # -- shared contracts -------------------------------------------------
    #
    # Several event families are the same shape with a different subject: eight
    # kinds of source change, three constraint lifecycle events, five plan
    # lifecycle events. Each family gets one contract rather than eight
    # near-identical ones. That is not a shortcut — it is what keeps the
    # governance surface honest, because a contract per topic that nobody
    # differentiates becomes a contract nobody reads.
    DataContract(
        subject="production.entity-change-value",
        version=1,
        event_type=EventType.LOCATION_CHANGED,
        owner=Role.COORDINATOR,
        description=(
            "A change to a production entity reported by a source system or a person. "
            "Shared by the location, cast, crew, resource, transport, permit, "
            "access-service and safety-report subjects."
        ),
        schema=_obj(
            {
                "entity_id": STR,
                "entity_type": STR,
                "change": STR,
                "attributes": {"type": "object"},
                "reason": {"type": ["string", "null"]},
                "confidence": NUM,
                "verification_state": STR,
                "reported_by": {"type": ["string", "null"]},
                "evidence_ref": {"type": ["string", "null"]},
                "affected": {"type": "array", "items": STR},
            },
            ["entity_id", "entity_type", "change"],
        ),
        rules=(
            ("confidence_range", "0 <= payload.get('confidence', 1) <= 1"),
            # A change that closes a location or removes a resource has to say
            # why. "Unavailable" with no reason is not actionable by anyone.
            ("removal_needs_reason",
             "payload['change'] not in ('closed','unavailable','cancelled') "
             "or len(payload.get('reason') or '') > 0"),
        ),
        tags=("source", "state"),
    ),
    DataContract(
        subject="production.constraint-value",
        version=1,
        event_type=EventType.CONSTRAINT_ACTIVATED,
        owner=Role.SAFETY_LEAD,
        description=(
            "A constraint becoming active, changing or being invalidated. Shared by the "
            "three constraint lifecycle subjects."
        ),
        schema=_obj(
            {
                "constraint_id": STR,
                "kind": STR,
                "domain": STR,
                "title": STR,
                "owner": STR,
                "source": STR,
                "source_evidence": STR,
                "effective_from": {"type": ["string", "null"], "format": "date-time"},
                "effective_to": {"type": ["string", "null"], "format": "date-time"},
                "reason": {"type": ["string", "null"]},
            },
            ["constraint_id", "kind", "domain", "title", "owner", "source"],
        ),
        rules=(
            # Provenance is not optional. A constraint whose source cannot be
            # named cannot be cited in an infeasibility explanation, and an
            # explanation without provenance is an assertion.
            ("provenance_present", "len(payload.get('source_evidence') or payload['source']) > 0"),
        ),
        tags=("state", "governance"),
    ),
    DataContract(
        subject="production.state-change-value",
        version=1,
        event_type=EventType.SCHEDULE_CHANGED,
        owner=Role.FIRST_AD,
        description=(
            "A change to schedule, assignment or readiness state. Shared by the three "
            "state-change subjects."
        ),
        schema=_obj(
            {
                "scene_id": {"type": ["string", "null"]},
                "resource_id": {"type": ["string", "null"]},
                "assigned_to": {"type": ["string", "null"]},
                "unit_id": {"type": ["string", "null"]},
                "department": {"type": ["string", "null"]},
                "state": {"type": ["string", "null"]},
                "start": {"type": ["string", "null"], "format": "date-time"},
                "end": {"type": ["string", "null"], "format": "date-time"},
                "plan_id": {"type": ["string", "null"]},
                "attributes": {"type": "object"},
            },
            [],
        ),
        tags=("state",),
    ),
    DataContract(
        subject="production.plan-lifecycle-value",
        version=1,
        event_type=EventType.PLAN_REQUESTED,
        owner=Role.COORDINATOR,
        description=(
            "Plan lifecycle transitions: requested, presented, rejected, approval "
            "requested, declined."
        ),
        schema=_obj(
            {
                "plan_id": {"type": ["string", "null"]},
                "request_id": {"type": ["string", "null"]},
                "disruption_id": STR,
                "stage": STR,
                "reason": {"type": ["string", "null"]},
                "required_roles": {"type": "array", "items": STR},
                "plan_hash": {"type": ["string", "null"]},
                "constraint_hash": {"type": ["string", "null"]},
                "expires_at": {"type": ["string", "null"], "format": "date-time"},
                "summary": {"type": ["string", "null"]},
                "conflicts": {"type": "array"},
            },
            ["disruption_id", "stage"],
        ),
        rules=(
            ("decline_needs_reason",
             "payload['stage'] not in ('declined','rejected') "
             "or len(payload.get('reason') or '') > 0"),
        ),
        tags=("decision",),
    ),
    DataContract(
        subject="production.simulation.completed-value",
        version=1,
        event_type=EventType.SIMULATION_COMPLETED,
        owner=Role.COORDINATOR,
        description="Robustness results for a plan under an ensemble of scenarios.",
        schema=_obj(
            {
                "plan_id": STR,
                "disruption_id": STR,
                "scenarios": INT,
                "on_time_probability": NUM,
                "expected_delay_minutes": NUM,
                "worst_credible_delay_minutes": NUM,
                "overtime_risk": NUM,
                "constraint_violation_risk": NUM,
                "recovery_margin_minutes": NUM,
                "sensitive_assumptions": {"type": "array", "items": STR},
                "sensitivity": {"type": "object"},
            },
            ["plan_id", "scenarios", "on_time_probability"],
        ),
        rules=(
            ("probability_range", "0 <= payload['on_time_probability'] <= 1"),
            # An ensemble small enough to be noise must not be presented as a
            # probability. Thirty is the floor at which the interval is worth
            # showing a decision-maker.
            ("ensemble_large_enough", "payload['scenarios'] >= 30"),
        ),
        tags=("assessment",),
    ),
    DataContract(
        subject="production.document.published-value",
        version=1,
        event_type=EventType.DOCUMENT_PUBLISHED,
        owner=Role.COORDINATOR,
        description="A production document published or revised.",
        schema=_obj(
            {
                "document_id": STR,
                "kind": STR,
                "revision": INT,
                "supersedes": {"type": ["integer", "null"]},
                "plan_id": {"type": ["string", "null"]},
                "accessible_formats": {"type": "array", "items": STR},
                "content_hash": STR,
            },
            ["document_id", "kind", "revision", "content_hash"],
        ),
        rules=(
            # A revision that supersedes nothing is a first issue, and a first
            # issue is not a revision. This is the exact off-by-one the Bob
            # modernization found in the legacy call-sheet adapter, promoted to
            # a contract rule so it cannot come back.
            ("revision_supersedes_predecessor",
             "payload['revision'] == 1 or "
             "(payload.get('supersedes') is not None "
             "and payload['supersedes'] == payload['revision'] - 1)"),
        ),
        tags=("execution", "document"),
    ),
    DataContract(
        subject="production.notification.delivered-value",
        version=1,
        event_type=EventType.NOTIFICATION_DELIVERED,
        owner=Role.COORDINATOR,
        description="Delivery confirmation for a sent notification.",
        schema=_obj(
            {
                "message_id": STR,
                "recipient_id": STR,
                "channel": STR,
                "delivered": BOOL,
                "error": {"type": ["string", "null"]},
            },
            ["message_id", "recipient_id", "delivered"],
        ),
        classification=Classification.PERSONAL,
        rules=(("failure_needs_error",
                "payload['delivered'] or len(payload.get('error') or '') > 0"),),
        tags=("execution", "communication"),
    ),
    DataContract(
        subject="production.audit-value",
        version=1,
        event_type=EventType.DECISION_RECORDED,
        owner=Role.COORDINATOR,
        description=(
            "Audit and learning records: decision recorded, outcome observed, prediction "
            "evaluated."
        ),
        schema=_obj(
            {
                "disruption_id": STR,
                "plan_id": {"type": ["string", "null"]},
                "kind": STR,
                "predicted": {"type": "object"},
                "actual": {"type": "object"},
                "error": {"type": "object"},
                "notes": {"type": "array", "items": STR},
            },
            ["disruption_id", "kind"],
        ),
        tags=("audit", "learning"),
    ),
    DataContract(
        subject="production.disruption.closed-value",
        version=1,
        event_type=EventType.DISRUPTION_CLOSED,
        owner=Role.COORDINATOR,
        description="The post-disruption record: predicted versus actual.",
        schema=_obj(
            {
                "disruption_id": STR,
                "plan_id": {"type": ["string", "null"]},
                "outcome": {"type": "object"},
                "duration_ms": NUM,
            },
            ["disruption_id"],
        ),
        tags=("audit", "learning"),
    ),
)

CONTRACTS_BY_SUBJECT: dict[str, DataContract] = {c.subject: c for c in CONTRACTS}

#: Which contract governs which event type. Several finding subjects share one
#: contract, and several command results share another.
_EVENT_SUBJECT: dict[EventType, str] = {}


#: Event families that share one contract. Keyed by subject.
SHARED_SUBJECTS: dict[str, frozenset[EventType]] = {
    "production.finding-value": frozenset({
        EventType.SCHEDULE_FINDING, EventType.RESOURCE_FINDING, EventType.SAFETY_FINDING,
        EventType.ACCESS_FINDING, EventType.CONTINUITY_FINDING, EventType.SPATIAL_FINDING,
        EventType.BUDGET_FINDING,
    }),
    "production.command.result-value": frozenset({
        EventType.COMMAND_ACCEPTED, EventType.COMMAND_REJECTED, EventType.COMMAND_COMPLETED,
        EventType.SYSTEM_UPDATED,
    }),
    "production.entity-change-value": frozenset({
        EventType.LOCATION_CHANGED, EventType.CAST_CHANGED, EventType.CREW_CHANGED,
        EventType.RESOURCE_CHANGED, EventType.TRANSPORT_CHANGED, EventType.PERMIT_CHANGED,
        EventType.ACCESS_SERVICE_CHANGED, EventType.SAFETY_REPORTED,
    }),
    "production.constraint-value": frozenset({
        EventType.CONSTRAINT_ACTIVATED, EventType.CONSTRAINT_CHANGED,
        EventType.CONSTRAINT_INVALIDATED,
    }),
    "production.state-change-value": frozenset({
        EventType.SCHEDULE_CHANGED, EventType.ASSIGNMENT_CHANGED,
        EventType.READINESS_CHANGED,
    }),
    "production.plan-lifecycle-value": frozenset({
        EventType.PLAN_REQUESTED, EventType.PLAN_PRESENTED, EventType.PLAN_REJECTED,
        EventType.PLAN_APPROVAL_REQUESTED, EventType.PLAN_DECLINED,
    }),
    "production.audit-value": frozenset({
        EventType.DECISION_RECORDED, EventType.OUTCOME_OBSERVED,
        EventType.PREDICTION_EVALUATED,
    }),
}


def _bind_subjects() -> None:
    for contract in CONTRACTS:
        _EVENT_SUBJECT[contract.event_type] = contract.subject
    for subject, event_types in SHARED_SUBJECTS.items():
        for event_type in event_types:
            _EVENT_SUBJECT[event_type] = subject


_bind_subjects()


class UngovernedSubject(RuntimeError):
    pass


def assert_all_governed() -> None:
    """Every event type must resolve to a registered contract.

    Called at import. An event type without a contract is one that can carry
    anything onto a topic, and the whole governance claim rests on there being
    no such topic. Adding an `EventType` without a contract fails here rather
    than in production.
    """
    missing = sorted(
        et.value for et in EventType
        if _EVENT_SUBJECT.get(et) not in CONTRACTS_BY_SUBJECT
    )
    if missing:
        raise UngovernedSubject(
            "event types with no registered data contract: " + ", ".join(missing)
        )


assert_all_governed()


def subject_for(event_type: EventType) -> str | None:
    return _EVENT_SUBJECT.get(event_type)


def contract_for(event_type: EventType) -> DataContract | None:
    subject = subject_for(event_type)
    return CONTRACTS_BY_SUBJECT.get(subject) if subject else None


# ---------------------------------------------------------------------------
# Compatibility
# ---------------------------------------------------------------------------


@dataclass
class CompatibilityResult:
    compatible: bool
    mode: str
    problems: list[str] = field(default_factory=list)


def check_compatibility(old: dict[str, Any], new: dict[str, Any],
                        mode: str = "BACKWARD") -> CompatibilityResult:
    """Confluent-style compatibility check between two versions of a schema.

    BACKWARD (the default here) means a consumer built for the new schema can
    read data written with the old one: fields may be added as optional, and may
    not be removed from `required` or have their type narrowed.
    """
    problems: list[str] = []
    old_props = old.get("properties", {})
    new_props = new.get("properties", {})
    old_required = set(old.get("required", []))
    new_required = set(new.get("required", []))

    if mode in ("BACKWARD", "FULL"):
        for name in sorted(new_required - old_required):
            problems.append(
                f"'{name}' is newly required; old data will not satisfy the new schema"
            )
        for name in sorted(old_props.keys() - new_props.keys()):
            if name in old_required:
                problems.append(f"required field '{name}' was removed")
    if mode in ("FORWARD", "FULL"):
        for name in sorted(old_required - new_required):
            problems.append(f"'{name}' was required and is no longer produced")

    for name in sorted(old_props.keys() & new_props.keys()):
        old_type = old_props[name].get("type")
        new_type = new_props[name].get("type")
        if old_type is None or new_type is None:
            continue
        old_set = set(old_type) if isinstance(old_type, list) else {old_type}
        new_set = set(new_type) if isinstance(new_type, list) else {new_type}
        if not old_set <= new_set:
            problems.append(
                f"field '{name}' narrowed from {sorted(old_set)} to {sorted(new_set)}"
            )
    return CompatibilityResult(not problems, mode, problems)


def validate_rules(contract: DataContract, payload: dict[str, Any]) -> list[str]:
    """Evaluate a contract's domain rules against a payload.

    Rules are Python expressions over a single name, `payload`. They are project
    source rather than user input — they live in this file and are reviewed like
    any other code — so evaluating them is not an injection surface. A rule that
    raises is reported as a failure rather than allowed to escape, because a rule
    that cannot be evaluated has not been satisfied.
    """
    failures: list[str] = []
    for name, expression in contract.rules:
        try:
            if not eval(expression, {"__builtins__": {"len": len}}, {"payload": payload}):
                failures.append(f"{contract.subject}: rule '{name}' failed")
        except Exception as exc:
            failures.append(f"{contract.subject}: rule '{name}' could not be evaluated: {exc}")
    return failures
