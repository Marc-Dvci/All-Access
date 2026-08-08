"""End-to-end: twin, privacy, approvals, execution and the full disruption loop.

The tests that matter most here are the negative ones about authority and
disclosure. It is easy to demonstrate a system that works; the claims worth
testing are that it refuses to work in the ways it says it will refuse.
"""

from __future__ import annotations

import pytest

from productionpulse.agents.coordinator import ProductionCoordinator
from productionpulse.agents.core import OfflineReasoner
from productionpulse.constraints.registry import active_constraints, constraint_set_hash
from productionpulse.contracts import (
    DISRUPTION_TRANSITIONS,
    DisruptionState,
    Role,
    TargetSystem,
)
from productionpulse.disruptions import (
    STORM_SCENARIO,
    build_source_event,
    family_counts,
    generate,
    scenario_problem,
)
from productionpulse.execution import privacy
from productionpulse.execution.approvals import ApprovalError, ApprovalLedger
from productionpulse.production import world as w
from productionpulse.stream import governance
from productionpulse.systems import build_systems
from productionpulse.twin import blast_radius, build_twin, certify_baseline

# ---------------------------------------------------------------------------
# Twin
# ---------------------------------------------------------------------------


def test_baseline_certifies_ready(twin) -> None:
    report = certify_baseline(twin)
    assert report.state == "ready", [i.message for i in report.blocking]
    assert report.checked >= 12


def test_twin_invariants_hold(twin) -> None:
    assert twin.check_invariants() == []


def test_twin_is_deterministic() -> None:
    assert build_twin().state_hash() == build_twin().state_hash()


def test_bitemporal_knowledge_cut() -> None:
    """`known_at` hides facts recorded later, however true they turned out.

    Transaction times are pinned explicitly rather than taken from the wall
    clock. `datetime.now()` on Windows has roughly 15 ms of granularity, so a
    "before" captured immediately prior to a write can compare equal to the
    write's own timestamp — and a bitemporal test that passes or fails on clock
    resolution is testing the clock.
    """
    from datetime import timedelta

    local = build_twin()
    learned_at = w.at(16, 0)
    later = w.at(19, 30)

    local.assert_fact(
        "LOC-HARBOUR-WALL", "status", "closed",
        valid_from=w.at(19, 0), source="storm", transaction_time=later,
    )
    # What is true now.
    assert local.value("LOC-HARBOUR-WALL", "status", w.at(20, 0)) == "closed"
    # What we believed at 16:00, before anyone knew about the storm.
    assert local.value(
        "LOC-HARBOUR-WALL", "status", w.at(20, 0), known_at=learned_at
    ) == "available"
    # And the superseded version still records what replaced it.
    versions = local.facts["LOC-HARBOUR-WALL::status"]
    assert versions[0].superseded_by == versions[-1].fact_id
    assert versions[0].valid_to is None, (
        "superseding must not retroactively close the previous version's "
        "valid-time interval"
    )
    assert later - learned_at > timedelta(0)


def test_blast_radius_reaches_access_arrangements(twin) -> None:
    blast = blast_radius(twin, ["LOC-HARBOUR-WALL"], w.at(19, 0))
    assert blast.scenes
    assert blast.access_requirements
    assert blast.max_depth >= 2
    node = blast.reached(blast.scenes[0])
    assert node is not None and node.path, "every impact must be traceable to its source"


def test_blast_radius_does_not_walk_non_propagating_edges(twin) -> None:
    """Otherwise everything is always affected and the analysis is worthless."""
    blast = blast_radius(twin, ["LOC-CHANDLERY-BACK"], w.at(19, 0))
    assert len(blast.nodes) < len(twin.entities)


# ---------------------------------------------------------------------------
# Privacy
# ---------------------------------------------------------------------------


def test_executive_view_carries_no_personal_data() -> None:
    view = privacy.executive_summary({
        "delay_minutes": 0.0, "cost_delta": 9000.0,
        "person_id": "CREW-AC1", "name": "Ines Halla",
        "cast_calls": {"CAST-001": "20:45"},
    })
    assert "person_id" not in view
    assert "name" not in view
    assert "cast_calls" not in view
    assert view["_redaction"]["fields_removed"] >= 3


def test_access_requirement_visibility_is_per_requirement() -> None:
    transport = privacy.access_view(Role.TRANSPORT_COORDINATOR)
    ids = {row["requirement_id"] for row in transport}
    assert "ACC-001" in ids, "transport needs the step-free arrangement"
    assert "ACC-004" not in ids, "transport has no reason to see a storage arrangement"


def test_no_prohibited_field_exists_anywhere() -> None:
    """The published figure for this is zero. This is what makes it checkable."""
    from productionpulse.production import world as world_module

    payloads = [
        {"requirement": r.requirement, "mechanism": r.mechanism,
         "category": r.category, "person_id": r.person_id}
        for r in world_module.ACCESS_REQUIREMENTS
    ]
    assert privacy.check_no_prohibited_fields(payloads) == []


def test_prohibited_field_would_be_stripped_if_it_appeared() -> None:
    """The tripwire fires. If a future change introduces one, it is removed."""
    audit = privacy.RedactionAudit()
    out = privacy.redact(
        {"requirement": "Step-free transport", "diagnosis": "should never exist"},
        Role.TRANSPORT_COORDINATOR, audit=audit,
    )
    assert "diagnosis" not in out
    assert audit.prohibited_removed == ["diagnosis"]
    assert not audit.clean


def test_crew_view_is_minimal() -> None:
    view = privacy.crew_view("CREW-AC1", {
        "call_time": "19:40", "location": "LOC-HARBOUR-WALL",
        "transport": "VEH-ACC-1", "required_action": "report",
        "safety_instruction": "read the briefing", "revision": 2,
    })
    assert set(view) == {
        "person_id", "call_time", "location", "transport", "required_action",
        "safety_instruction", "access_arrangement", "acknowledgment_required",
        "escalation_contact", "revision",
    }
    assert "cost" not in view
    for arrangement in view["access_arrangement"]:
        assert set(arrangement) == {"requirement", "mechanism"}


# ---------------------------------------------------------------------------
# Approvals
# ---------------------------------------------------------------------------


@pytest.fixture()
def approved(storm_problem):
    from productionpulse.solver import engine

    outcome = engine.solve(storm_problem, "DISR-A")
    plan = outcome.plans[0]
    ledger = ApprovalLedger()
    constraint_hash = constraint_set_hash(active_constraints())
    request = ledger.request(plan, constraint_hash, scope="test", summary="t")
    approval = ledger.grant(
        request.request_id, "CREW-UPM", plan.required_approvals[0],
        rationale="approved for test", production_id=storm_problem.production_id,
    )
    return ledger, plan, approval, constraint_hash


def test_valid_approval_verifies(approved) -> None:
    ledger, plan, approval, constraint_hash = approved
    ok, reason = ledger.verify(approval, plan, constraint_hash)
    assert ok, reason


def test_approval_is_single_use(approved) -> None:
    ledger, plan, approval, constraint_hash = approved
    ledger.consume(approval, plan, constraint_hash)
    with pytest.raises(ApprovalError, match="already been used"):
        ledger.consume(approval, plan, constraint_hash)


def test_approval_is_bound_to_the_constraint_set(approved) -> None:
    """An approval granted while a constraint was inactive cannot be replayed."""
    ledger, plan, approval, _hash = approved
    ok, reason = ledger.verify(approval, plan, "a-different-constraint-hash")
    assert not ok
    assert "constraint set has changed" in reason


def test_approval_is_bound_to_the_plan(approved) -> None:
    ledger, plan, approval, constraint_hash = approved
    other = plan.model_copy(update={"plan_id": "PLAN-OTHER"})
    ok, reason = ledger.verify(approval, other, constraint_hash)
    assert not ok


def test_wrong_role_cannot_approve(approved) -> None:
    ledger, plan, _approval, _hash = approved
    request_id = next(iter(ledger.requests))
    with pytest.raises(ApprovalError, match="not among the required authorities"):
        ledger.grant(request_id, "CREW-CATER", Role.CREW,
                     rationale="I would like to", production_id="P")


def test_approval_requires_a_rationale(approved) -> None:
    ledger, plan, _approval, _hash = approved
    request_id = next(iter(ledger.requests))
    with pytest.raises(ApprovalError, match="rationale"):
        ledger.grant(request_id, "CREW-UPM", plan.required_approvals[0],
                     rationale="   ", production_id="P")


def test_infeasible_plan_cannot_be_routed_for_approval(storm_problem) -> None:
    from productionpulse.solver import engine

    outcome = engine.solve(storm_problem, "DISR-B")
    rejected = outcome.rejected[0]
    ledger = ApprovalLedger()
    with pytest.raises(ApprovalError, match="not feasible"):
        ledger.request(rejected, "hash", scope="s", summary="s")


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------


def test_no_path_from_open_to_executing() -> None:
    assert DisruptionState.EXECUTING not in DISRUPTION_TRANSITIONS[DisruptionState.OPEN]


def test_verifying_can_return_to_executing() -> None:
    """The path taken when verification blocks readiness."""
    assert DisruptionState.EXECUTING in DISRUPTION_TRANSITIONS[DisruptionState.VERIFYING]


def test_closed_is_terminal() -> None:
    assert DISRUPTION_TRANSITIONS[DisruptionState.CLOSED] == ()


# ---------------------------------------------------------------------------
# The full loop
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def hero_run():
    from productionpulse.stream.bus import LocalEventBus
    from productionpulse.stream.registry import LocalSchemaRegistry

    twin = build_twin()
    problem = scenario_problem(STORM_SCENARIO, twin=twin)
    bus = LocalEventBus(LocalSchemaRegistry(), w.PRODUCTION_ID)
    systems = build_systems(w.PRODUCTION_ID, hold_department="props")
    coordinator = ProductionCoordinator(bus, systems, reasoner=OfflineReasoner())
    source = build_source_event(bus, STORM_SCENARIO)
    outcome = coordinator.handle(
        problem, source, title=STORM_SCENARIO.title,
        scenario_id=STORM_SCENARIO.scenario_id, scenarios=40,
    )
    return bus, systems, coordinator, outcome, source


def test_disruption_reaches_ready_and_closed(hero_run) -> None:
    _bus, _systems, _coordinator, outcome, _source = hero_run
    assert outcome.disruption.state is DisruptionState.CLOSED
    assert outcome.verification is not None and outcome.verification.ready


def test_required_assessments_all_completed(hero_run) -> None:
    from productionpulse.agents.experts import REQUIRED_ASSESSMENTS

    _bus, _systems, _coordinator, outcome, _source = hero_run
    producers = {f.producer for f in outcome.findings}
    assert REQUIRED_ASSESSMENTS <= producers


def test_verification_blocked_before_it_passed(hero_run) -> None:
    """The missing department acceptance is real, not staged."""
    _bus, _systems, _coordinator, outcome, _source = hero_run
    assert outcome.blocked_then_resolved
    assert any(step.state == "blocked" for step in outcome.steps)


def test_every_command_completed(hero_run) -> None:
    _bus, _systems, _coordinator, outcome, _source = hero_run
    assert outcome.saga is not None
    assert outcome.saga.all_complete, outcome.saga.exceptions


def test_call_sheet_actually_changed(hero_run) -> None:
    _bus, systems, _coordinator, _outcome, _source = hero_run
    connector = systems[TargetSystem.CALL_SHEET]
    assert connector.current_revision == 2
    assert connector.current() is not None


def test_hash_chain_and_replay(hero_run) -> None:
    bus, _systems, coordinator, _outcome, _source = hero_run
    ok, problems = bus.verify_chain()
    assert ok, problems
    check = governance.verify_replay(bus.all_events(), coordinator.views)
    assert check.identical, check.differences


def test_lineage_reaches_execution(hero_run) -> None:
    bus, _systems, _coordinator, _outcome, source = hero_run
    lineage = governance.trace(bus.all_events(), source.envelope.event_id)
    domains = lineage.by_domain()
    assert "assessment" in domains
    assert "decision" in domains
    assert "execution" in domains


def test_decision_context_replays_what_was_known(hero_run) -> None:
    bus, _systems, _coordinator, outcome, _source = hero_run
    context = governance.decision_context(bus.all_events(), outcome.selected.plan_id)
    assert context["found"]
    assert context["findings"]
    assert context["options_considered"]
    assert context["approval"]


def test_no_personal_data_reached_the_executive_system(hero_run) -> None:
    _bus, systems, _coordinator, _outcome, _source = hero_run
    metrics = systems[TargetSystem.EXECUTIVE_REPORTING].metrics
    assert privacy.check_no_prohibited_fields([metrics]) == []
    for forbidden in ("cast_calls", "person_id", "name", "access_requirements"):
        assert forbidden not in metrics


def test_every_crew_message_derives_from_the_plan(hero_run) -> None:
    _bus, _systems, _coordinator, outcome, _source = hero_run
    assert outcome.messages
    for message in outcome.messages:
        assert message.derived_from, message.subject
        assert outcome.selected.plan_id in message.derived_from


def test_communication_cap_respected(hero_run) -> None:
    _bus, _systems, _coordinator, outcome, _source = hero_run
    cap = int(w.POLICIES["communication"]["max_messages_per_person_per_disruption"])
    counts: dict[str, int] = {}
    for message in outcome.messages:
        counts[message.recipient_id] = counts.get(message.recipient_id, 0) + 1
    assert max(counts.values()) <= cap


def test_replaying_the_command_set_books_nothing_twice(hero_run) -> None:
    """A duplicated approval must not book two vehicles."""
    from productionpulse.execution import commands as command_builder

    _bus, systems, coordinator, outcome, _source = hero_run
    connector = systems[TargetSystem.CALL_SHEET]
    revision_before = connector.current_revision
    transport_before = dict(systems[TargetSystem.TRANSPORT_DISPATCH].bookings)

    replay = command_builder.build_commands(outcome.selected, now=w.at(19, 0))
    saga = coordinator.saga.execute(
        outcome.disruption.disruption_id, outcome.selected.plan_id, replay,
    )
    assert connector.current_revision == revision_before
    assert systems[TargetSystem.TRANSPORT_DISPATCH].bookings == transport_before
    assert saga.duplicates_suppressed > 0


# ---------------------------------------------------------------------------
# Disruption library
# ---------------------------------------------------------------------------


def test_library_covers_every_family() -> None:
    scenarios = generate(400)
    counts = family_counts(scenarios)
    for family in ("weather", "cast_crew", "location", "equipment",
                   "access_communication", "continuity", "operational_systems"):
        assert counts.get(family, 0) > 0, family


def test_library_is_reproducible() -> None:
    first = [s.scenario_id for s in generate(120, seed=7)]
    second = [s.scenario_id for s in generate(120, seed=7)]
    assert first == second


def test_every_scenario_produces_a_valid_source_event(bus) -> None:
    """A scenario that cannot emit a schema-valid event is a broken scenario."""
    for scenario in generate(60):
        event = build_source_event(bus, scenario)
        assert event.envelope.signature


# ---------------------------------------------------------------------------
# Department readiness in the read model
#
# These exist because a browser found the defect and nothing else could have.
# The read model reported a single row keyed on the *target system* name with
# zero counts, and the control board's own readiness rule (`issued == accepted`)
# called that row ready — so the board asserted every department was ready in
# the same run where verification refused to close the day on props. Every API
# endpoint returned 200 throughout. See tools/ui_smoke.py.
# ---------------------------------------------------------------------------


def test_department_readiness_is_keyed_by_department(hero_run) -> None:
    _bus, _systems, coordinator, _outcome, _source = hero_run
    departments = coordinator.views.departments

    assert departments, "no department readiness was folded from the stream"
    # The target system is not a department, and used to be the only key here.
    assert "department_tasks" not in departments
    assert {"props", "camera", "wardrobe"} <= set(departments)
    for name, row in departments.items():
        assert row.department == name
        assert row.tasks_issued > 0, f"{name} was folded with no tasks issued"


def test_readiness_is_never_claimed_for_a_department_with_no_tasks() -> None:
    """`issued == accepted` is True at 0 == 0. The domain rule is not."""
    from productionpulse.stream.views import DepartmentReadiness

    assert DepartmentReadiness("props").ready is False
    assert DepartmentReadiness("props", tasks_issued=2, tasks_accepted=1).ready is False
    assert DepartmentReadiness("props", tasks_issued=2, tasks_accepted=2).ready is True


def test_control_board_readiness_agrees_with_verification(hero_run) -> None:
    """The board and the Verification Agent must never contradict each other.

    Before the fix the board reported every department ready while verification
    was blocking on a missing props acceptance — inside the same run.
    """
    _bus, systems, coordinator, _outcome, _source = hero_run
    outstanding = {
        t.department for t in systems[TargetSystem.DEPARTMENT_TASKS].outstanding()
    }
    not_ready = {n for n, r in coordinator.views.departments.items() if not r.ready}
    assert not_ready == outstanding


def test_board_shows_the_department_verification_blocked_on() -> None:
    """The same check, in the state where it can actually fail.

    `hero_run` resolves the block, so by the end nothing is outstanding and the
    assertion above holds with both sides empty — it would pass against a board
    that never populated at all. This run leaves the block in place, so the
    board has to name props specifically while verification is blocking on it.
    Against the old read model this sees no `props` key and fails.
    """
    from productionpulse.stream.bus import LocalEventBus
    from productionpulse.stream.registry import LocalSchemaRegistry

    problem = scenario_problem(STORM_SCENARIO, twin=build_twin())
    bus = LocalEventBus(LocalSchemaRegistry(), w.PRODUCTION_ID)
    systems = build_systems(w.PRODUCTION_ID, hold_department="props")
    coordinator = ProductionCoordinator(bus, systems, reasoner=OfflineReasoner())
    outcome = coordinator.handle(
        problem, build_source_event(bus, STORM_SCENARIO),
        title=STORM_SCENARIO.title, scenario_id=STORM_SCENARIO.scenario_id,
        scenarios=40, auto_resolve_blocking=False,
    )

    assert outcome.verification is not None and not outcome.verification.ready
    departments = coordinator.views.departments
    assert departments["props"].ready is False
    assert departments["props"].tasks_accepted < departments["props"].tasks_issued
    assert {n for n, r in departments.items() if not r.ready} == {"props"}


def test_department_readiness_survives_replay(hero_run) -> None:
    """Readiness is a fold, so replaying the log must rebuild it identically."""
    from productionpulse.stream.views import MaterializedViews

    bus, _systems, coordinator, _outcome, _source = hero_run
    rebuilt = MaterializedViews().apply_all(bus.all_events())
    assert {n: (r.tasks_issued, r.tasks_accepted, r.ready)
            for n, r in rebuilt.departments.items()} == \
           {n: (r.tasks_issued, r.tasks_accepted, r.ready)
            for n, r in coordinator.views.departments.items()}


def test_readiness_is_published_only_when_it_changes(hero_run) -> None:
    """`READINESS_CHANGED` means changed.

    Readiness is published twice per disruption — once before verification and
    once after a held department accepts. Emitting every department both times
    produces a byte-identical payload for the ones that did not move, which the
    bus suppresses as a duplicate and dead-letters. The guard works; the traffic
    should not exist. Seven spurious entries per disruption in a dead-letter
    queue is how a queue stops being read.
    """
    from productionpulse.contracts import EventType

    bus, _systems, coordinator, _outcome, _source = hero_run
    readiness = [
        e for e in bus.all_events()
        if e.envelope.event_type is EventType.READINESS_CHANGED
    ]
    departments = set(coordinator.views.departments)

    # One per department, plus one for the department that actually changed.
    assert len(readiness) == len(departments) + 1
    assert not any(
        d.topic == EventType.READINESS_CHANGED.value for d in bus.dead_letters
    )

    changed = [e for e in readiness if e.payload["state"] == "awaiting_acceptance"]
    assert len(changed) == 1 and changed[0].payload["department"] == "props"


def test_a_clean_run_dead_letters_nothing() -> None:
    """The dead-letter queue is only worth reading if everything in it is real.

    Its own run rather than the module fixture: `hero_run` is module-scoped and
    a later test deliberately replays a command set to exercise idempotency,
    which legitimately puts duplicates on that bus. Asserting an empty queue
    against shared state would pass or fail on test ordering.
    """
    from productionpulse.stream.bus import LocalEventBus
    from productionpulse.stream.registry import LocalSchemaRegistry

    bus = LocalEventBus(LocalSchemaRegistry(), w.PRODUCTION_ID)
    coordinator = ProductionCoordinator(
        bus, build_systems(w.PRODUCTION_ID, hold_department="props"),
        reasoner=OfflineReasoner(),
    )
    coordinator.handle(
        scenario_problem(STORM_SCENARIO, twin=build_twin()),
        build_source_event(bus, STORM_SCENARIO),
        title=STORM_SCENARIO.title, scenario_id=STORM_SCENARIO.scenario_id,
        scenarios=40,
    )
    assert bus.dead_letters == [], [
        (d.topic, d.category, d.reason) for d in bus.dead_letters
    ]
