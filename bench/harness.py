"""Run one disruption and measure what happened.

Every measurement in this module compares an observation the system produced
against a fact the system could not see. The ground truth lives on the
`Scenario` in `allaccess.disruptions`; nothing in `src/allaccess`
reads those fields.

Two rules kept this honest, and both are worth stating because they are easy to
break later:

* **No metric is computed from a value the system reported about itself.** The
  constraint-identification score is not "did the agent say it found
  C-SAFE-001"; it is the constraint registry's own verdict on the unchanged
  day, compared against the label the scenario carries.
* **A configuration flag never changes the scoring.** The ablations disable
  parts of the system. They do not relax what counts as correct.

The operational-systems family of the corpus declares faults — a duplicate
event, a stale event, a missing acknowledgment. Those declarations are inert in
`disruptions.py`, which only builds the event. This harness is what actually
injects them, and it records which ones it injected so `docs/BENCHMARK.md` can
say exactly what was exercised rather than implying all eight were.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any, Iterator

from allaccess.agents.coordinator import ProductionCoordinator, problem_blast
from allaccess.agents.core import build_reasoner
from allaccess.agents.experts import REQUIRED_ASSESSMENTS
from allaccess.constraints.registry import CONSTRAINTS, evaluate
from allaccess.contracts import Authority, Classification, EventType, TargetSystem
from allaccess.disruptions import Scenario, build_source_event, scenario_problem
from allaccess.execution import privacy
from allaccess.production import world as w
from allaccess.solver import engine
from allaccess.stream import governance
from allaccess.stream.bus import build_bus
from allaccess.systems import build_systems
from allaccess.twin import build_twin

#: Every constraint id the registry knows. Anything an agent cites that is not
#: in here is a fabricated constraint, and is counted as one.
KNOWN_CONSTRAINTS: frozenset[str] = frozenset(c.constraint_id for c in CONSTRAINTS)

#: Faults from the operational-systems family that this harness knows how to
#: inject. The rest are declared by the corpus and not exercised; the report
#: says so rather than counting them as passes.
INJECTABLE_FAULTS: frozenset[str] = frozenset({
    "duplicate_event",
    "late_event",
    "missing_acknowledgment",
    "partial_update",
    "schema_incompatibility",
})


@dataclass
class RunConfig:
    """A configuration of the system under test.

    The default is the whole system. Each flag removes one capability, which is
    what the ablation table in `docs/BENCHMARK.md` compares.
    """

    name: str = "full"
    #: Attach the production digital twin, so blast radius is available.
    twin: bool = True
    #: Run the robustness ensemble over each feasible plan.
    robustness: bool = True
    #: Let verification block readiness and require the blocker to be resolved.
    reconciliation: bool = True
    #: Re-run the constraint registry against every finished plan before
    #: publishing it as feasible. Off models a plan authored without a
    #: feasibility check — an LLM-written plan, or a spreadsheet.
    validation: bool = True
    scenarios: int = 60
    reasoning: str = "offline"

    def key(self) -> str:
        return self.name


@contextmanager
def _nullcontext() -> Iterator[None]:
    yield


@contextmanager
def _without_validation() -> Iterator[None]:
    """Publish plans without the independent feasibility recheck.

    `engine.publish` decides feasibility from `engine.validate`. Replacing that
    one function is the whole ablation: the search still runs, the plans are
    still built, and nothing re-reads the constraint registry before a plan is
    presented as feasible. It is the closest honest analogue in this codebase of
    a plan authored by a language model or a spreadsheet — a plan that looks
    right and was never checked.

    The scoring path deliberately does *not* go through `validate`; it calls
    `evaluate` itself, so the ablated run is still measured against the real
    registry.
    """
    original = engine.validate

    def unchecked(plan: Any, problem: Any) -> tuple[bool, dict[str, object]]:
        return True, {"ablated": "validation disabled", "constraints_checked": 0}

    engine.validate = unchecked  # type: ignore[assignment]
    try:
        yield
    finally:
        engine.validate = original  # type: ignore[assignment]


@dataclass
class Measurement:
    """One scenario's result. Every field is an observation, not a claim."""

    scenario_id: str
    family: str
    severity: str
    config: str

    # -- lifecycle
    qualified: bool = True
    qualification_reason: str = ""
    final_state: str = ""
    total_ms: float = 0.0
    solve_ms: float = 0.0
    error: str | None = None

    # -- impact analysis (§16.2)
    expected_constraints: list[str] = field(default_factory=list)
    detected_constraints: list[str] = field(default_factory=list)
    expected_departments: list[str] = field(default_factory=list)
    detected_departments: list[str] = field(default_factory=list)
    expected_access_at_risk: list[str] = field(default_factory=list)
    detected_access_at_risk: list[str] = field(default_factory=list)
    expected_scenes: list[str] = field(default_factory=list)
    detected_scenes: list[str] = field(default_factory=list)
    # The top band of the relevance ranking, scored separately so the recall of
    # the traversal and the precision of what a screen leads with are both on
    # the table rather than one standing in for the other.
    primary_departments: list[str] = field(default_factory=list)
    primary_access_at_risk: list[str] = field(default_factory=list)
    primary_scenes: list[str] = field(default_factory=list)
    blast_nodes: int = 0
    blast_primary: int = 0
    blast_depth: int = 0

    # -- planning quality (§16.3)
    feasible_plans: int = 0
    rejected_plans: int = 0
    distinct_strategies: int = 0
    hard_violations_published: int = 0
    unvalidated_published: int = 0
    rejected_without_conflict: int = 0
    non_minimal_conflicts: int = 0
    access_preserved: bool | None = None
    access_arrangements: int = 0

    # -- robustness (§16.4)
    on_time_probability: float | None = None
    expected_delay_minutes: float | None = None
    worst_credible_delay_minutes: float | None = None

    # -- agent quality (§16.5)
    findings: int = 0
    abstentions: int = 0
    missing_required_assessments: int = 0
    fabricated_constraints: int = 0
    blocking_findings_without_evidence: int = 0

    # -- execution quality (§16.6)
    commands: int = 0
    commands_completed: int = 0
    commands_rejected: int = 0
    acknowledgments_required: int = 0
    acknowledgments_received: int = 0

    # -- verification (§16.6)
    verification_ready: bool | None = None
    assertions_total: int = 0
    assertions_passed: int = 0
    blocked_then_resolved: bool = False
    #: What a system that trusted command acknowledgment alone would have said.
    naive_ready: bool = False
    #: Naive said ready, verification did not. This is the number the
    #: reconciliation ablation exists to produce.
    false_closure: bool = False

    # -- inclusion and privacy (§16.7)
    prohibited_field_hits: int = 0
    personal_events_to_unauthorised_audience: int = 0

    # -- stream platform (§16.8)
    events: int = 0
    topics: int = 0
    dead_letters: int = 0
    duplicates_suppressed: int = 0
    inbox_suppressed: int = 0
    chain_intact: bool = False
    replay_identical: bool = False
    lineage_nodes: int = 0
    lineage_depth: int = 0

    # -- injected fault, if any
    fault: str | None = None
    fault_injected: bool = False
    fault_handled: bool | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fault_of(scenario: Scenario) -> str | None:
    if scenario.family != "operational_systems":
        return None
    attributes = scenario.payload.get("attributes") or {}
    fault = attributes.get("fault")
    return str(fault) if fault else None


def _strip_prefix(values: Any, prefix: str) -> list[str]:
    return sorted({str(v)[len(prefix):] if str(v).startswith(prefix) else str(v)
                   for v in values})


def run_scenario(
    scenario: Scenario,
    config: RunConfig,
    twin: Any = None,
    injected_fault: str | None = None,
) -> Measurement:
    """One disruption, start to finish, measured.

    `injected_fault` overrides the fault the scenario declares. Two of the
    faults — a missing department acceptance and a partly-delivered
    notification — can only be exercised against a disruption that produces a
    plan and issues commands, and the operational-systems family produces
    neither: those scenarios describe a platform fault, so the day itself is
    unchanged and the correct plan is "change nothing". The runner therefore
    assigns those two across a deterministic slice of the whole corpus. Which
    faults were injected where is recorded per scenario, so nothing is credited
    to a fault that was never applied.
    """
    measurement = Measurement(
        scenario_id=scenario.scenario_id,
        family=scenario.family,
        severity=scenario.severity,
        config=config.key(),
        expected_constraints=sorted(scenario.expected_constraints),
        expected_departments=sorted(scenario.expected_departments),
        expected_access_at_risk=sorted(scenario.expected_access_at_risk),
        expected_scenes=sorted(scenario.disrupted_scenes),
    )
    fault = injected_fault or _fault_of(scenario)
    measurement.fault = fault
    measurement.fault_injected = bool(fault and fault in INJECTABLE_FAULTS)

    twin = twin if (twin is not None and config.twin) else (build_twin() if config.twin else None)
    problem = scenario_problem(scenario, twin=twin)

    # -- impact analysis, measured independently of any plan ----------------
    #
    # "Which constraints does this disruption trip" is answered by running the
    # registry against the *unchanged* day. That is a fact about the world, not
    # about which plan the search happened to like, so it is the only version of
    # this measurement that survives an ablation.
    unchanged = engine.strategy_preserve_original(problem)
    if unchanged is not None:
        measurement.detected_constraints = sorted({
            v.constraint_id for v in evaluate(unchanged, problem) if v.severity == "blocking"
        })

    bus = build_bus(w.PRODUCTION_ID)
    try:
        source = build_source_event(bus, scenario)
    except RuntimeError as exc:  # a source event the contract refuses
        measurement.error = str(exc)
        measurement.qualified = False
        measurement.dead_letters = len(bus.dead_letters)
        return measurement

    hold = "props" if (fault == "missing_acknowledgment" and measurement.fault_injected) else None
    # A recipient every plan writes to, so the fault is genuinely exercised
    # rather than aimed at somebody the plan never contacts.
    undeliverable = (
        ("CREW-TRANS",) if (fault == "partial_update" and measurement.fault_injected) else ()
    )
    systems = build_systems(w.PRODUCTION_ID, hold_department=hold, undeliverable=undeliverable)

    coordinator = ProductionCoordinator(
        bus, systems, reasoner=build_reasoner(config.reasoning)
    )

    # -- fault injection, before the run ---------------------------------------
    #
    # Only faults that leave no event in the log go here. A duplicate is
    # suppressed on write and a contract violation is dead-lettered, so neither
    # reaches the materialised views. An accepted event published before the
    # coordinator folds in the source event *would* change the order the views
    # see, which the replay proof would then correctly report as a mismatch —
    # so the stale-event injection happens after the run instead.
    if measurement.fault_injected and fault == "duplicate_event":
        before = bus.duplicates_suppressed
        build_source_event_duplicate(bus, scenario)
        measurement.fault_handled = bus.duplicates_suppressed > before
    elif measurement.fault_injected and fault == "schema_incompatibility":
        before = len(bus.dead_letters)
        broken = bus.make_event(
            EventType.SCOPE_ASSESSED,
            {"origin_ids": "not-a-list"},
            producer="system_monitor",
            idempotency_key=f"{scenario.scenario_id}:broken",
        )
        bus.publish(broken)
        measurement.fault_handled = len(bus.dead_letters) > before

    started = time.perf_counter()
    try:
        with _without_validation() if not config.validation else _nullcontext():
            outcome = coordinator.handle(
                problem, source,
                title=scenario.title,
                scenario_id=scenario.scenario_id,
                scenarios=config.scenarios,
                with_robustness=config.robustness,
                auto_resolve_blocking=config.reconciliation,
            )
    except Exception as exc:  # noqa: BLE001 - the benchmark records failures
        measurement.error = f"{type(exc).__name__}: {exc}"
        measurement.total_ms = round((time.perf_counter() - started) * 1000.0, 2)
        return measurement

    measurement.total_ms = outcome.timings.get(
        "total_ms", round((time.perf_counter() - started) * 1000.0, 2)
    )
    measurement.solve_ms = outcome.timings.get("solve_ms", 0.0)
    measurement.final_state = outcome.disruption.state.value
    measurement.qualified = outcome.disruption.state.value != "abandoned" or bool(outcome.plans)

    # -- fault injection, after the run ----------------------------------------
    if measurement.fault_injected and fault == "late_event":
        stale = bus.make_event(
            EventType.SOURCE_EVENT_RECEIVED,
            dict(scenario.payload) | {"summary": "stale duplicate report"},
            producer="system_monitor",
            authority=Authority.REPORTED,
            effective_time=scenario.at - timedelta(hours=9),
            classification=Classification.PRODUCTION_INTERNAL,
            idempotency_key=f"{scenario.scenario_id}:stale",
        )
        published = bus.publish(stale)
        qualified, _reason = coordinator._qualify(  # noqa: SLF001 - deliberate probe
            published.event or stale, problem.now
        )
        # Handled means two things, both required: the coordinator refuses to
        # act on a stale report, and the view counts it as late rather than
        # silently dropping or reordering it.
        measurement.fault_handled = not qualified and coordinator.views.late_events > 0

    _score_scope(measurement, problem, source, outcome)
    _score_planning(measurement, problem, outcome, config)
    _score_agents(measurement, outcome)
    _score_execution(measurement, outcome)
    _score_privacy(measurement, bus)
    _score_stream(measurement, bus, coordinator, source)

    if measurement.fault_injected and fault == "missing_acknowledgment":
        departments = systems[TargetSystem.DEPARTMENT_TASKS]
        issued_to_held = any(t.department == "props" for t in departments.tasks.values())
        # Not applicable if the plan never issued a props task — there was
        # nothing to withhold. Recorded as None rather than scored as a pass.
        measurement.fault_handled = (
            measurement.blocked_then_resolved if issued_to_held else None
        )
    elif measurement.fault_injected and fault == "partial_update":
        notification = systems[TargetSystem.NOTIFICATION]
        addressed = any(
            m.get("recipient_id") in notification.undeliverable
            for m in notification.sent
        )
        measurement.fault_handled = bool(notification.failed) if addressed else None

    return measurement


def build_source_event_duplicate(bus: Any, scenario: Scenario) -> None:
    """Republish the source event with the same idempotency key."""
    event = bus.make_event(
        scenario.event_type,
        dict(scenario.payload),
        producer="system_monitor",
        authority=scenario.authority,
        effective_time=scenario.at,
        classification=Classification.PRODUCTION_INTERNAL,
        idempotency_key=f"{scenario.scenario_id}:{scenario.event_type.value}",
    )
    bus.publish(event)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_scope(measurement: Measurement, problem: Any, source: Any, outcome: Any) -> None:
    blast = problem_blast(problem, source)
    if blast is None:
        return
    measurement.blast_nodes = len(blast.nodes)
    measurement.blast_primary = len(blast.primary)
    measurement.blast_depth = blast.max_depth
    # `blast.departments` and friends are the full traversal; `primary_*` is
    # the top band of the ranking. Both are scored against the same labels.
    measurement.detected_departments = _strip_prefix(blast.departments, "DEPT-")
    measurement.detected_scenes = sorted(blast.scenes)
    measurement.detected_access_at_risk = sorted(blast.access_requirements)
    measurement.primary_departments = _strip_prefix(blast.primary_departments, "DEPT-")
    measurement.primary_scenes = sorted(blast.primary_scenes)
    measurement.primary_access_at_risk = sorted(blast.primary_access_requirements)


def _score_planning(measurement: Measurement, problem: Any, outcome: Any,
                    config: RunConfig) -> None:
    measurement.feasible_plans = len(outcome.plans)
    measurement.rejected_plans = len(outcome.rejected)
    measurement.distinct_strategies = len({p.strategy for p in outcome.plans})

    for plan in outcome.plans:
        # Independent recheck: the registry, run against the published plan,
        # from the plan object rather than the search's state.
        candidate = engine.candidate_from_plan(plan, problem)
        blocking = [v for v in evaluate(candidate, problem) if v.severity == "blocking"]
        measurement.hard_violations_published += len(blocking)
        if not (plan.proof and plan.proof.validated):
            measurement.unvalidated_published += 1

    for plan in outcome.rejected:
        if not plan.conflicts:
            measurement.rejected_without_conflict += 1
        measurement.non_minimal_conflicts += sum(
            1 for c in plan.conflicts if not c.minimal
        )

    selected = outcome.selected
    if selected is not None:
        measurement.access_arrangements = len(selected.access)
        measurement.access_preserved = all(a.satisfied for a in selected.access)
        report = outcome.robustness.get(selected.plan_id)
        if report is not None:
            measurement.on_time_probability = report.on_time_probability
            measurement.expected_delay_minutes = report.expected_delay_minutes
            measurement.worst_credible_delay_minutes = report.worst_credible_delay_minutes


def _score_agents(measurement: Measurement, outcome: Any) -> None:
    findings = outcome.findings
    measurement.findings = len(findings)
    measurement.abstentions = sum(1 for f in findings if f.status.value == "abstained")
    producers = {f.producer for f in findings}
    measurement.missing_required_assessments = len(REQUIRED_ASSESSMENTS - producers)
    for finding in findings:
        measurement.fabricated_constraints += sum(
            1 for cid in finding.applicable_constraints if cid not in KNOWN_CONSTRAINTS
        )
        if finding.status.value == "blocking" and not finding.evidence:
            measurement.blocking_findings_without_evidence += 1


def _score_execution(measurement: Measurement, outcome: Any) -> None:
    saga = outcome.saga
    if saga is not None:
        measurement.commands = len(saga.steps)
        measurement.commands_completed = sum(
            1 for s in saga.steps if s.status.value == "completed"
        )
        measurement.commands_rejected = sum(
            1 for s in saga.steps if s.status.value == "rejected"
        )
    messages = outcome.messages
    measurement.acknowledgments_required = sum(1 for m in messages if m.requires_ack)
    measurement.acknowledgments_received = len(outcome.disruption.acknowledgments)

    report = outcome.verification
    if report is not None:
        measurement.verification_ready = report.ready
        measurement.assertions_total = len(report.assertions)
        measurement.assertions_passed = report.passed

    # The counterfactual: a system with no reconciliation step declares the
    # disruption handled once every command has been acknowledged.
    measurement.blocked_then_resolved = outcome.blocked_then_resolved
    measurement.naive_ready = bool(
        measurement.commands and measurement.commands_completed == measurement.commands
    )
    measurement.false_closure = bool(
        measurement.naive_ready
        and (measurement.blocked_then_resolved or measurement.verification_ready is False)
    )


def _score_privacy(measurement: Measurement, bus: Any) -> None:
    payloads = [e.payload for e in bus.all_events()]
    measurement.prohibited_field_hits = len(privacy.check_no_prohibited_fields(payloads))
    # A personal-classification event may only be produced by a component that
    # is entitled to handle personal data. The executive reporting path is not.
    measurement.personal_events_to_unauthorised_audience = sum(
        1 for e in bus.all_events()
        if e.envelope.classification == Classification.PERSONAL
        and e.envelope.producer == "executive_reporting"
    )


def _score_stream(measurement: Measurement, bus: Any, coordinator: Any, source: Any) -> None:
    events = bus.all_events()
    measurement.events = len(events)
    measurement.topics = len(bus.topics)
    measurement.dead_letters = len(bus.dead_letters)
    measurement.duplicates_suppressed = bus.duplicates_suppressed
    measurement.inbox_suppressed = coordinator.saga.inbox.suppressed

    chain_ok, _problems = bus.verify_chain()
    measurement.chain_intact = chain_ok

    replay = governance.verify_replay(events, coordinator.views)
    measurement.replay_identical = replay.identical

    lineage = governance.trace(events, source.envelope.event_id)
    measurement.lineage_nodes = len(lineage.nodes)
    measurement.lineage_depth = lineage.depth
