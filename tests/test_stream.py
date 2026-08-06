"""The event backbone: contracts, validation, idempotency, chaining, replay.

The guarantees tested here are the ones the production workflow depends on. Each
one is stated as a property that must hold rather than as a call that must
succeed, because "the function returned" is not the claim being made.
"""

from __future__ import annotations

import pytest

from productionpulse.contracts import Authority, EventType
from productionpulse.production import world as w
from productionpulse.stream import governance
from productionpulse.stream.schemas import (
    CONTRACTS,
    CONTRACTS_BY_SUBJECT,
    assert_all_governed,
    check_compatibility,
    contract_for,
    subject_for,
)
from productionpulse.stream.views import FLINK_STATEMENTS, MaterializedViews


def _weather_payload(**overrides):
    payload = {
        "entity_id": "WEATHER-04",
        "condition": "storm_force",
        "wind_kph": 68.0,
        "precipitation_mm": 9.5,
        "precipitation_probability": 0.95,
        "sea_state": 6,
        "lightning_risk": 0.4,
        "window_start": w.at(18, 30).isoformat(),
        "window_end": w.at(23, 59).isoformat(),
        "affected_locations": ["LOC-HARBOUR-WALL"],
        "confidence": 0.97,
        "attributes": {},
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Governance
# ---------------------------------------------------------------------------


def test_every_event_type_is_governed() -> None:
    assert_all_governed()
    summary = governance.catalog_summary()
    assert summary["ungoverned"] == []
    assert summary["governed_by_contract"] == summary["topics"]


def test_every_contract_declares_an_owner_and_description() -> None:
    for contract in CONTRACTS:
        assert contract.owner is not None, contract.subject
        assert len(contract.description) > 20, contract.subject


def test_backward_compatibility_accepts_an_added_optional_field() -> None:
    contract = CONTRACTS_BY_SUBJECT["production.weather.alerted-value"]
    evolved = dict(contract.schema)
    evolved["properties"] = {**contract.schema["properties"], "gust_kph": {"type": "number"}}
    result = check_compatibility(contract.schema, evolved)
    assert result.compatible, result.problems


def test_backward_compatibility_rejects_a_new_required_field() -> None:
    contract = CONTRACTS_BY_SUBJECT["production.weather.alerted-value"]
    evolved = dict(contract.schema)
    evolved["properties"] = {**contract.schema["properties"], "gust_kph": {"type": "number"}}
    evolved["required"] = list(contract.schema["required"]) + ["gust_kph"]
    result = check_compatibility(contract.schema, evolved)
    assert not result.compatible
    assert any("newly required" in p for p in result.problems)


def test_backward_compatibility_rejects_a_narrowed_type() -> None:
    contract = CONTRACTS_BY_SUBJECT["production.plan.generated-value"]
    evolved = dict(contract.schema)
    evolved["properties"] = {
        **contract.schema["properties"], "proof": {"type": "object"},
    }
    result = check_compatibility(contract.schema, evolved)
    assert not result.compatible


# ---------------------------------------------------------------------------
# Validation at the boundary
# ---------------------------------------------------------------------------


def test_valid_event_publishes(bus) -> None:
    event = bus.make_event(EventType.WEATHER_ALERTED, _weather_payload(),
                           producer="weather_service")
    result = bus.publish(event)
    assert result.published
    assert result.event.envelope.signature


def test_malformed_payload_is_dead_lettered(bus) -> None:
    event = bus.make_event(
        EventType.WEATHER_ALERTED, _weather_payload(wind_kph=-5.0),
        producer="weather_service",
    )
    result = bus.publish(event)
    assert not result.published
    assert result.category == "invalid_schema"
    assert bus.dead_letters and "wind_non_negative" in bus.dead_letters[0].reason


def test_missing_required_field_is_rejected(bus) -> None:
    payload = _weather_payload()
    del payload["condition"]
    event = bus.make_event(EventType.WEATHER_ALERTED, payload, producer="weather_service")
    assert not bus.publish(event).published


def test_feasible_plan_without_a_validated_proof_is_refused(bus) -> None:
    """The structural guarantee, enforced at the stream boundary.

    Even a buggy producer cannot get an unproven feasible plan onto the decision
    topic, because the contract rule refuses it.
    """
    event = bus.make_event(
        EventType.PLAN_GENERATED,
        {
            "plan_id": "PLAN-X", "disruption_id": "D1", "strategy": "s", "label": "l",
            "feasible": True, "objectives": {}, "scene_count": 1,
            "required_approvals": [], "proof": None, "conflicts": [], "plan_hash": "abc",
        },
        producer="solver",
    )
    result = bus.publish(event)
    assert not result.published
    assert "feasible_requires_validated_proof" in result.reason


def test_infeasible_plan_without_conflicts_is_refused(bus) -> None:
    event = bus.make_event(
        EventType.PLAN_GENERATED,
        {
            "plan_id": "PLAN-Y", "disruption_id": "D1", "strategy": "s", "label": "l",
            "feasible": False, "objectives": {}, "scene_count": 1,
            "required_approvals": [], "proof": None, "conflicts": [], "plan_hash": "abc",
        },
        producer="solver",
    )
    assert not bus.publish(event).published


def test_ready_verification_with_blockers_is_refused(bus) -> None:
    event = bus.make_event(
        EventType.VERIFICATION_COMPLETED,
        {
            "report_id": "V1", "disruption_id": "D1", "plan_id": "P1", "ready": True,
            "assertions": [], "passed": 3, "total": 4,
            "blocking": ["every department accepted its action"],
        },
        producer="verification_agent",
    )
    result = bus.publish(event)
    assert not result.published
    assert "ready_requires_no_blockers" in result.reason


def test_crew_message_must_derive_from_a_plan(bus) -> None:
    """No message may be composed from agent memory rather than the plan."""
    event = bus.make_event(
        EventType.NOTIFICATION_SENT,
        {
            "message_id": "M1", "disruption_id": "D1", "recipient_id": "CREW-AC1",
            "recipient_role": "crew_member", "channel": "app", "subject": "s",
            "body": "b", "language": "en", "derived_from": [], "requires_ack": True,
            "accessible_formats": [], "classification": "personal",
        },
        producer="communication_agent",
    )
    result = bus.publish(event)
    assert not result.published
    assert "must_derive_from_plan" in result.reason


def test_blocking_finding_without_evidence_is_refused(bus) -> None:
    event = bus.make_event(
        EventType.SAFETY_FINDING,
        {
            "finding_id": "F1", "disruption_id": "D1", "producer": "safety_agent",
            "domain": "safety", "scope": [], "status": "blocking", "headline": "h",
            "evidence": [], "applicable_constraints": [], "assumptions": [],
            "confidence": 1.0, "uncertainty": {}, "required_authority": None,
            "solver_hints": {}, "classification": "production_internal",
        },
        producer="safety_agent",
    )
    assert not bus.publish(event).published


# ---------------------------------------------------------------------------
# Idempotency and integrity
# ---------------------------------------------------------------------------


def test_duplicate_idempotency_key_is_suppressed(bus) -> None:
    event = bus.make_event(EventType.WEATHER_ALERTED, _weather_payload(),
                           producer="weather_service")
    assert bus.publish(event).published
    second = bus.publish(event)
    assert not second.published
    assert second.duplicate
    assert bus.duplicates_suppressed == 1


def test_hash_chain_is_intact_and_detects_tampering(bus) -> None:
    for i in range(5):
        bus.publish(bus.make_event(
            EventType.WEATHER_ALERTED,
            _weather_payload(entity_id=f"WEATHER-{i:02d}"),
            producer="weather_service",
        ))
    ok, problems = bus.verify_chain()
    assert ok, problems

    # Tamper with a payload in place. The chain must notice.
    topic = EventType.WEATHER_ALERTED.value
    for partition in bus.topics[topic]:
        if partition:
            original = partition[0]
            partition[0] = original.__class__(
                envelope=original.envelope,
                payload={**original.payload, "wind_kph": 1.0},
            )
            break
    ok_after, problems_after = bus.verify_chain()
    assert not ok_after
    assert any("payload hash mismatch" in p for p in problems_after)


def test_partition_key_is_stable(bus) -> None:
    assert bus.partition_for("DISR-1") == bus.partition_for("DISR-1")


# ---------------------------------------------------------------------------
# Views and replay
# ---------------------------------------------------------------------------


def test_replay_reproduces_state_exactly(bus) -> None:
    views = MaterializedViews()
    bus.subscribe("*", views.apply)
    for i in range(6):
        bus.publish(bus.make_event(
            EventType.WEATHER_ALERTED,
            _weather_payload(entity_id=f"WEATHER-{i:02d}"),
            producer="weather_service", disruption_id="DISR-T",
        ))
    check = governance.verify_replay(bus.all_events(), views)
    assert check.identical, check.differences


def test_out_of_order_event_is_counted_not_dropped() -> None:
    """A late event is applied and counted, not silently discarded."""
    from productionpulse.contracts import Event, EventEnvelope, stable_hash, utcnow

    views = MaterializedViews()
    late_time = w.at(2, 0)
    for i, effective in enumerate([w.at(20, 0), late_time]):
        payload = _weather_payload()
        views.apply(Event(
            envelope=EventEnvelope(
                event_id=f"EV-{i}", schema_id="s", event_type=EventType.WEATHER_ALERTED,
                production_id="P", correlation_id="C", idempotency_key=f"k{i}",
                producer="weather_service", actor="a", authority=Authority.AUTHORITATIVE,
                event_time=utcnow(), effective_time=effective,
                payload_hash=stable_hash(payload), partition_key="P", sequence=i,
            ),
            payload=payload,
        ))
    assert views.events_applied == 2
    assert views.late_events == 1


def test_flink_statements_exist_for_the_python_views() -> None:
    """Every materialised view has a committed SQL equivalent."""
    for name in ("disruption_state", "open_commands", "unacknowledged",
                 "operational_kpis", "access_at_risk"):
        assert name in FLINK_STATEMENTS
        assert "SELECT" in FLINK_STATEMENTS[name]


def test_lineage_traces_causation(bus) -> None:
    root = bus.publish(bus.make_event(
        EventType.WEATHER_ALERTED, _weather_payload(),
        producer="weather_service", disruption_id="DISR-L",
    )).event
    child = bus.publish(bus.make_event(
        EventType.SCOPE_ASSESSED,
        {"origin_ids": ["LOC-HARBOUR-WALL"], "direct": ["SC-025"]},
        producer="scope_and_dependency_agent", disruption_id="DISR-L",
        causation_id=root.envelope.event_id,
    )).event
    lineage = governance.trace(bus.all_events(), root.envelope.event_id)
    assert len(lineage.nodes) == 2
    assert lineage.depth == 1
    chain = governance.upstream(bus.all_events(), child.envelope.event_id)
    assert [n.event_id for n in chain] == [
        child.envelope.event_id, root.envelope.event_id
    ]


@pytest.mark.parametrize("event_type", list(EventType))
def test_every_event_type_resolves_to_a_contract(event_type: EventType) -> None:
    assert subject_for(event_type) is not None
    assert contract_for(event_type) is not None
