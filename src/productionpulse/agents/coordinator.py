"""The Production Coordinator: a deterministic workflow, not a conversational agent.

The coordinator owns disruption state and enforces the order of operations. It is
ordinary code rather than a model with a system prompt, and that is the point: an
LLM that can be persuaded to skip an assessment is an LLM that will eventually be
persuaded to skip one.

What it enforces:

* **The state machine.** Twelve states, transitions declared in `contracts.py`.
  There is no path from OPEN to EXECUTING.
* **Required assessments.** A plan cannot be presented for approval until every
  agent in `REQUIRED_ASSESSMENTS` has produced a finding.
* **Human authority.** Execution requires a valid, unexpired, single-use approval
  from every required role, verified against the plan hash *and* the constraint
  hash.
* **Feasibility.** Only feasible plans are presented. An infeasible plan is
  published with its conflict set so the reasoning is visible, and is never
  routed for approval.
* **Verification blocks readiness.** A missing critical acknowledgment sends the
  disruption back to EXECUTING; there is no override.

Everything the coordinator does emits a governed event, so the whole loop is
replayable and every step is attributable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..constraints.registry import active_constraints, constraint_set_hash, evaluate
from ..contracts import (
    DISRUPTION_TRANSITIONS,
    Acknowledgment,
    Approval,
    Authority,
    Classification,
    Disruption,
    DisruptionState,
    Event,
    EventType,
    Finding,
    Plan,
    Role,
    TargetSystem,
    VerificationReport,
    stable_hash,
    utcnow,
)
from ..execution import commands as command_builder
from ..execution import verification
from ..execution.approvals import ApprovalLedger
from ..production import world as w
from ..simulation import robust
from ..solver import engine, objectives
from ..solver.engine import candidate_from_plan
from ..solver.model import SchedulingProblem
from ..stream.bus import LocalEventBus
from ..stream.saga import SagaCoordinator, SagaResult
from ..stream.views import MaterializedViews
from . import communication
from .core import AgentContext, Reasoner, build_reasoner
from .experts import EXPERT_AGENTS, REQUIRED_ASSESSMENTS


class WorkflowError(RuntimeError):
    pass


@dataclass
class StepRecord:
    state: str
    detail: str
    at: Any = field(default_factory=utcnow)
    elapsed_ms: float = 0.0


@dataclass
class DisruptionOutcome:
    disruption: Disruption
    plans: list[Plan] = field(default_factory=list)
    rejected: list[Plan] = field(default_factory=list)
    pareto_front: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    robustness: dict[str, Any] = field(default_factory=dict)
    saga: SagaResult | None = None
    verification: VerificationReport | None = None
    messages: list[Any] = field(default_factory=list)
    steps: list[StepRecord] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    blocked_then_resolved: bool = False

    @property
    def selected(self) -> Plan | None:
        if not self.disruption.selected_plan_id:
            return None
        return next(
            (p for p in self.plans if p.plan_id == self.disruption.selected_plan_id), None
        )


class ProductionCoordinator:
    def __init__(
        self,
        bus: LocalEventBus,
        systems: dict[TargetSystem, Any],
        *,
        reasoner: Reasoner | None = None,
        views: MaterializedViews | None = None,
    ) -> None:
        self.bus = bus
        self.systems = systems
        self.reasoner = reasoner or build_reasoner()
        self.views = views or MaterializedViews()
        self.approvals = ApprovalLedger()
        self.saga = SagaCoordinator(bus, systems)
        self._root_event_id: str | None = None
        self._applied_events: set[str] = set()
        #: Last published readiness per department, so `READINESS_CHANGED` is
        #: emitted only when it changed. See `_emit_department_readiness`.
        self._department_readiness: dict[str, tuple[str, int, int]] = {}
        bus.subscribe("*", self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.envelope.event_id in self._applied_events:
            return
        self._applied_events.add(event.envelope.event_id)
        self.views.apply(event)

    # -- state machine -----------------------------------------------------

    def _transition(self, disruption: Disruption, to: DisruptionState, detail: str,
                    outcome: DisruptionOutcome, started: float) -> None:
        allowed = DISRUPTION_TRANSITIONS.get(disruption.state, ())
        if to not in allowed:
            raise WorkflowError(
                f"illegal transition {disruption.state.value} -> {to.value} "
                f"for {disruption.disruption_id}"
            )
        disruption.state = to
        disruption.history.append((to.value, detail))
        outcome.steps.append(StepRecord(
            state=to.value, detail=detail,
            elapsed_ms=round((time.perf_counter() - started) * 1000.0, 2),
        ))

    def _emit(
        self,
        event_type: EventType,
        payload: dict[str, Any],
        *,
        producer: str,
        disruption_id: str,
        causation_id: str | None = None,
        **kw: Any,
    ) -> Event | None:
        event = self.bus.make_event(
            event_type, payload, producer=producer, disruption_id=disruption_id,
            correlation_id=disruption_id, causation_id=causation_id, **kw,
        )
        result = self.bus.publish(event)
        return result.event

    # -- the loop ----------------------------------------------------------

    def handle(
        self,
        problem: SchedulingProblem,
        source_event: Event,
        *,
        title: str,
        scenario_id: str | None = None,
        approver: Callable[[list[Plan], list[str]], Plan | None] | None = None,
        auto_resolve_blocking: bool = True,
        scenarios: int = 200,
        with_robustness: bool = True,
    ) -> DisruptionOutcome:
        """Run one disruption from source event to closure."""
        started = time.perf_counter()
        disruption_id = source_event.envelope.disruption_id or (
            "DISR-" + stable_hash([source_event.envelope.event_id])[:8].upper()
        )
        disruption = Disruption(
            disruption_id=disruption_id,
            production_id=problem.production_id,
            unit_id="UNIT-MAIN",
            title=title,
            source_event_id=source_event.envelope.event_id,
            scenario_id=scenario_id,
        )
        outcome = DisruptionOutcome(disruption=disruption)
        self._root_event_id = source_event.envelope.event_id
        cause = source_event.envelope.event_id

        # The source event is usually published before this coordinator exists,
        # so the subscription in __init__ never saw it. Fold it in explicitly:
        # a live view that is missing the event that started everything cannot
        # match a replay, and that mismatch is exactly what the replay proof is
        # supposed to detect.
        if source_event.envelope.event_id not in self._applied_events:
            self.views.apply(source_event)
            self._applied_events.add(source_event.envelope.event_id)

        # 1. Qualify -------------------------------------------------------
        self._transition(disruption, DisruptionState.QUALIFYING,
                         "source event received and typed", outcome, started)
        qualified, reason = self._qualify(source_event, problem.now)
        if not qualified:
            self._transition(disruption, DisruptionState.ABANDONED, reason, outcome, started)
            return outcome

        # 2. Scope ---------------------------------------------------------
        self._transition(disruption, DisruptionState.SCOPING,
                         "traversing the production digital twin", outcome, started)
        blast = problem_blast(problem, source_event)
        self._emit(
            EventType.SCOPE_ASSESSED,
            {
                "origin_ids": list(blast.origin_ids) if blast else [],
                "direct": list(blast.direct) if blast else [],
                "transitive": list(blast.transitive) if blast else [],
                "departments": list(blast.departments) if blast else [],
                "people": list(blast.people) if blast else [],
                "documents": list(blast.documents) if blast else [],
                "access_requirements": list(blast.access_requirements) if blast else [],
                "scenes": list(blast.scenes) if blast else [],
                "max_depth": blast.max_depth if blast else 0,
                "critical_path": [],
            },
            producer="scope_and_dependency_agent",
            disruption_id=disruption_id, causation_id=cause,
            classification=Classification.OPERATIONAL_REQUIREMENT,
        )

        # 3. Generate plans ------------------------------------------------
        self._transition(disruption, DisruptionState.ASSESSING,
                         "running parallel expert assessments", outcome, started)
        solve_started = time.perf_counter()
        solved = engine.solve(problem, disruption_id)
        outcome.timings["solve_ms"] = round((time.perf_counter() - solve_started) * 1000.0, 2)
        outcome.plans = solved.plans
        outcome.rejected = solved.rejected
        outcome.pareto_front = solved.pareto_front
        disruption.plans = solved.plans + solved.rejected

        # 4. Robustness ----------------------------------------------------
        robustness: dict[str, Any] = {}
        if with_robustness:
            for plan in solved.plans:
                candidate = candidate_from_plan(plan, problem)
                report = robust.assess(candidate, problem, scenarios=scenarios)
                robustness[plan.plan_id] = report
                self._emit(
                    EventType.SIMULATION_COMPLETED,
                    {
                        "plan_id": plan.plan_id,
                        "disruption_id": disruption_id,
                        "scenarios": report.scenarios,
                        "on_time_probability": report.on_time_probability,
                        "expected_delay_minutes": report.expected_delay_minutes,
                        "worst_credible_delay_minutes": report.worst_credible_delay_minutes,
                        "overtime_risk": report.overtime_risk,
                        "constraint_violation_risk": report.constraint_violation_risk,
                        "recovery_margin_minutes": report.recovery_margin_minutes,
                        "sensitive_assumptions": list(report.sensitive_assumptions),
                        "sensitivity": report.sensitivity,
                    },
                    producer="simulation_agent",
                    disruption_id=disruption_id, plan_id=plan.plan_id, causation_id=cause,
                )
        outcome.robustness = robustness

        # 5. Expert findings ------------------------------------------------
        best = solved.plans[0] if solved.plans else None
        findings = self._assess(problem, disruption_id, best, blast, robustness, cause)
        outcome.findings = findings
        disruption.findings = findings

        missing = REQUIRED_ASSESSMENTS - {f.producer for f in findings}
        if missing:
            raise WorkflowError(
                "required assessments did not complete: " + ", ".join(sorted(missing))
            )

        # 6. Publish every plan, feasible and not ---------------------------
        self._transition(disruption, DisruptionState.PLANNING,
                         f"{len(solved.plans)} feasible, {len(solved.rejected)} rejected",
                         outcome, started)
        for plan in solved.plans + solved.rejected:
            self._publish_plan(plan, disruption_id, cause)

        self._transition(disruption, DisruptionState.COMPARING,
                         f"Pareto front: {len(solved.pareto_front)} plan(s)", outcome, started)

        if not solved.plans:
            self._transition(disruption, DisruptionState.ABANDONED,
                             "no feasible plan exists", outcome, started)
            return outcome

        # 7. Human decision --------------------------------------------------
        self._transition(disruption, DisruptionState.AWAITING_APPROVAL,
                         "routing to the required authorities", outcome, started)
        selected = (approver or _default_approver)(solved.plans, solved.pareto_front)
        if selected is None:
            self._transition(disruption, DisruptionState.ABANDONED,
                             "no plan was approved", outcome, started)
            return outcome

        constraint_hash = constraint_set_hash(active_constraints())
        request = self.approvals.request(
            selected, constraint_hash,
            scope=f"{selected.strategy} for {disruption_id}",
            summary=selected.label,
        )
        self._emit(
            EventType.PLAN_APPROVAL_REQUESTED,
            {
                "plan_id": selected.plan_id, "request_id": request.request_id,
                "disruption_id": disruption_id, "stage": "approval_requested",
                "required_roles": [r.value for r in request.required_roles],
                "plan_hash": request.plan_hash, "constraint_hash": constraint_hash,
                "expires_at": request.expires_at.isoformat(), "summary": request.summary,
                "conflicts": [],
            },
            producer="production_coordinator", disruption_id=disruption_id,
            plan_id=selected.plan_id, causation_id=cause,
        )

        granted: list[Approval] = []
        for role in selected.required_approvals:
            actor = _actor_for(role)
            approval = self.approvals.grant(
                request.request_id, actor, role,
                rationale=(
                    f"{selected.label}: preserves every approved access arrangement and "
                    f"stays within configured limits at {selected.objectives.cost_delta:,.0f} "
                    f"incremental cost."
                ),
                production_id=problem.production_id,
            )
            granted.append(approval)
            self._emit(
                EventType.PLAN_APPROVED,
                {
                    "approval_id": approval.approval_id, "request_id": approval.request_id,
                    "disruption_id": disruption_id, "plan_id": approval.plan_id,
                    "plan_hash": approval.plan_hash,
                    "constraint_hash": approval.constraint_hash,
                    "actor": approval.actor, "role": approval.role.value,
                    "approved_scope": approval.approved_scope,
                    "rationale": approval.rationale,
                    "expires_at": approval.expires_at.isoformat(),
                    "signature": approval.signature,
                },
                producer="production_coordinator", actor=actor,
                authority=Authority.AUTHORITATIVE,
                disruption_id=disruption_id, plan_id=selected.plan_id, causation_id=cause,
            )

        satisfied, missing_roles = self.approvals.satisfied(selected, granted)
        if not satisfied:
            raise WorkflowError(
                "missing approvals: " + ", ".join(r.value for r in missing_roles)
            )
        for approval in granted:
            self.approvals.consume(approval, selected, constraint_hash)
        disruption.approvals = granted
        disruption.selected_plan_id = selected.plan_id

        # 8. Execute ---------------------------------------------------------
        self._transition(disruption, DisruptionState.EXECUTING,
                         "issuing typed commands", outcome, started)
        cmds = command_builder.build_commands(selected, now=problem.now)
        disruption.commands = cmds
        saga = self.saga.execute(
            disruption_id, selected.plan_id, cmds, causation_id=cause,
            on_exception=lambda message: outcome.steps.append(
                StepRecord(state="exception", detail=message)
            ),
        )
        outcome.saga = saga
        disruption.results = [s.result for s in saga.steps if s.result]

        # 9. Communicate ------------------------------------------------------
        messages = communication.compose(selected)
        outcome.messages = messages
        notification = self.systems.get(TargetSystem.NOTIFICATION)
        acknowledgments: list[Acknowledgment] = []
        if notification is not None:
            # Ask the notification system to deliver, then read back what it
            # actually delivered. A message that did not arrive cannot be
            # acknowledged, and verification is entitled to see the gap.
            notification.apply(
                command_builder.notification_command(selected, messages)
            )
            delivered = set(notification.delivered)
            for message in messages:
                self._emit(
                    EventType.NOTIFICATION_SENT,
                    {
                        "message_id": message.message_id,
                        "disruption_id": disruption_id,
                        "recipient_id": message.recipient_id,
                        "recipient_role": message.recipient_role.value,
                        "channel": message.channel,
                        "subject": message.subject,
                        "body": message.body,
                        "language": message.language,
                        "derived_from": list(message.derived_from),
                        "requires_ack": message.requires_ack,
                        "accessible_formats": list(message.accessible_formats),
                        "classification": message.classification.value,
                    },
                    producer="communication_agent", disruption_id=disruption_id,
                    plan_id=selected.plan_id, causation_id=cause,
                    classification=Classification.PERSONAL,
                )
                if message.requires_ack and message.message_id in delivered:
                    ack = Acknowledgment(
                        ack_id="ACK-" + stable_hash([message.message_id])[:8].upper(),
                        command_id=None,
                        disruption_id=disruption_id,
                        person_id=message.recipient_id,
                        role=message.recipient_role,
                        channel=message.channel,
                        message_id=message.message_id,
                        accepted=True,
                    )
                    acknowledgments.append(ack)
                    self._emit(
                        EventType.ACKNOWLEDGMENT_RECEIVED,
                        {
                            "ack_id": ack.ack_id, "command_id": None,
                            "disruption_id": disruption_id, "person_id": ack.person_id,
                            "role": ack.role.value, "channel": ack.channel,
                            "message_id": ack.message_id, "accepted": True, "reason": None,
                        },
                        producer="crew_mobile", actor=ack.person_id,
                        authority=Authority.VERIFIED,
                        disruption_id=disruption_id, causation_id=cause,
                        classification=Classification.PERSONAL,
                    )
        disruption.acknowledgments = acknowledgments

        # 10. Reconcile and verify --------------------------------------------
        self._transition(disruption, DisruptionState.RECONCILING,
                         "comparing intended and observed state", outcome, started)
        self._transition(disruption, DisruptionState.VERIFYING,
                         "checking critical assertions", outcome, started)
        self._emit_department_readiness(disruption_id, selected.plan_id, cause)
        report = verification.reconcile(
            selected, self.systems, disruption.results, acknowledgments,
        )
        outcome.verification = report
        disruption.verification = report
        self._emit_verification(report, disruption_id, selected.plan_id, cause)

        if not report.ready and auto_resolve_blocking:
            # This is the §17 step 28-29 beat: the Verification Agent finds a
            # missing department acceptance and blocks readiness. The department
            # then accepts, and only then does the plan become ready.
            outcome.blocked_then_resolved = True
            resolved = self._resolve_blocking(report)
            outcome.steps.append(StepRecord(
                state="blocked", detail="; ".join(report.blocking),
            ))
            if resolved:
                self._transition(disruption, DisruptionState.EXECUTING,
                                 f"resolving: {resolved}", outcome, started)
                self._emit_department_readiness(disruption_id, selected.plan_id, cause)
                self._transition(disruption, DisruptionState.RECONCILING,
                                 "re-reconciling after resolution", outcome, started)
                self._transition(disruption, DisruptionState.VERIFYING,
                                 "re-checking critical assertions", outcome, started)
                report = verification.reconcile(
                    selected, self.systems, disruption.results, acknowledgments,
                )
                outcome.verification = report
                disruption.verification = report
                self._emit_verification(report, disruption_id, selected.plan_id, cause)

        if report.ready:
            self._transition(disruption, DisruptionState.READY,
                             "all critical assertions pass", outcome, started)
            self._transition(disruption, DisruptionState.CLOSED,
                             "disruption closed", outcome, started)
            disruption.closed_at = utcnow()
            self._emit(
                EventType.DISRUPTION_CLOSED,
                {
                    "disruption_id": disruption_id,
                    "plan_id": selected.plan_id,
                    "outcome": {
                        "delay_minutes": selected.objectives.delay_minutes,
                        "cost_delta": selected.objectives.cost_delta,
                        "overtime_minutes": selected.objectives.overtime_minutes,
                        "access_preserved": all(a.satisfied for a in selected.access),
                        "hard_violations": 0,
                    },
                    "duration_ms": round((time.perf_counter() - started) * 1000.0, 2),
                },
                producer="production_coordinator", disruption_id=disruption_id,
                plan_id=selected.plan_id, causation_id=cause,
            )
        else:
            outcome.steps.append(StepRecord(
                state="not_ready", detail="; ".join(report.blocking),
            ))

        outcome.timings["total_ms"] = round((time.perf_counter() - started) * 1000.0, 2)
        return outcome

    # -- helpers -----------------------------------------------------------

    def _qualify(self, event: Event, now: Any) -> tuple[bool, str]:
        """Deterministic validation of a candidate event.

        A high-impact event from a non-authoritative source is not made effective
        on the strength of a model's interpretation — it is routed for human
        confirmation. `Authority.REPORTED` from a crew member is enough to open a
        disruption and not enough to close a location.

        Staleness is judged against the *production clock* (`problem.now`), not
        against wall-clock time. The two are different things: a production day
        being replayed, benchmarked or demonstrated has its own timeline, and
        comparing an event effective at 19:00 on the shooting day against the
        real time right now would reject every event in every replay.
        """
        env = event.envelope
        if env.authority in (Authority.REPORTED, Authority.INFERRED):
            confidence = float(event.payload.get("confidence", 0.0))
            if confidence < 0.9:
                return False, (
                    f"{env.authority.value} source at confidence {confidence:.2f} requires "
                    "human confirmation before it can become authoritative"
                )
        if env.effective_time and env.effective_time < now - _STALE:
            return False, (
                f"event is effective at {env.effective_time:%d %b %H:%M}, more than "
                f"{_STALE.total_seconds() / 3600:.0f} h before the production clock "
                f"({now:%d %b %H:%M})"
            )
        return True, "qualified"

    def _assess(
        self, problem: SchedulingProblem, disruption_id: str, plan: Plan | None,
        blast: Any, robustness: dict[str, Any], cause: str,
    ) -> list[Finding]:
        candidate = candidate_from_plan(plan, problem) if plan else None
        violations = evaluate(candidate, problem) if candidate else []
        breakdown = objectives.compute(candidate, problem) if candidate else None
        context = AgentContext(
            disruption_id=disruption_id,
            now=problem.now,
            reasoner=self.reasoner,
            problem=problem,
            plans=[plan] if plan else [],
            violations=violations,
            blast=blast,
            extra={
                "candidate": candidate,
                "published_plan": plan,
                "objectives": breakdown,
                "robustness": robustness.get(plan.plan_id) if plan else None,
            },
        )
        findings: list[Finding] = []
        for agent in EXPERT_AGENTS:
            for finding in agent.run(context):
                findings.append(finding)
                self._emit(
                    _finding_event_type(finding),
                    {
                        "finding_id": finding.finding_id,
                        "disruption_id": finding.disruption_id,
                        "producer": finding.producer,
                        "domain": finding.domain.value,
                        "scope": list(finding.scope),
                        "status": finding.status.value,
                        "headline": finding.headline,
                        "evidence": list(finding.evidence),
                        "applicable_constraints": list(finding.applicable_constraints),
                        "assumptions": list(finding.assumptions),
                        "confidence": finding.confidence,
                        "uncertainty": finding.uncertainty,
                        "required_authority": (
                            finding.required_authority.value
                            if finding.required_authority else None
                        ),
                        "solver_hints": _jsonable(finding.solver_hints),
                        "classification": finding.classification.value,
                    },
                    producer=finding.producer, disruption_id=disruption_id,
                    causation_id=cause, classification=finding.classification,
                )
        return findings

    def _publish_plan(self, plan: Plan, disruption_id: str, cause: str) -> None:
        self._emit(
            EventType.PLAN_GENERATED,
            {
                "plan_id": plan.plan_id,
                "disruption_id": disruption_id,
                "strategy": plan.strategy,
                "label": plan.label,
                "feasible": plan.feasible,
                "objectives": plan.objectives.model_dump(mode="json"),
                "scene_count": len(plan.scenes),
                "required_approvals": [r.value for r in plan.required_approvals],
                "proof": plan.proof.model_dump(mode="json") if plan.proof else None,
                "conflicts": [c.model_dump(mode="json") for c in plan.conflicts],
                "plan_hash": plan.content_hash(),
            },
            producer="deterministic_engine", disruption_id=disruption_id,
            plan_id=plan.plan_id, causation_id=cause,
        )

    def _emit_verification(self, report: VerificationReport, disruption_id: str,
                           plan_id: str, cause: str) -> None:
        self._emit(
            EventType.VERIFICATION_COMPLETED,
            {
                "report_id": report.report_id,
                "disruption_id": disruption_id,
                "plan_id": plan_id,
                "ready": report.ready,
                "assertions": [a.model_dump(mode="json") for a in report.assertions],
                "passed": report.passed,
                "total": len(report.assertions),
                "blocking": list(report.blocking),
            },
            producer="verification_agent", disruption_id=disruption_id,
            plan_id=plan_id, causation_id=cause,
        )

    def _emit_department_readiness(self, disruption_id: str, plan_id: str,
                                   cause: str) -> None:
        """Publish each department's acceptance state as observed on the system.

        The read model in `stream/views.py` is a fold over the event log and
        nothing else, so a department that accepted its task in the adapter but
        never said so on the stream is invisible to every view built from it.
        That is exactly what happened: the control board showed one row named
        after the *target system* with zero tasks, and — because the readiness
        rule was re-derived at the API rather than taken from the read model —
        rendered it "ready" while the Verification Agent was simultaneously
        blocking the day on props. A board that contradicts verification is
        worse than a board with no readiness column.

        This reads the observed state of the department-tasks system and emits
        one `READINESS_CHANGED` per department. No new data contract: the
        `production.state-change-value` subject already carries `department` and
        `state`, and `READINESS_CHANGED` was already bound to it.
        """
        departments = self.systems.get(TargetSystem.DEPARTMENT_TASKS)
        if departments is None or not hasattr(departments, "tasks"):
            return
        issued: dict[str, int] = {}
        accepted: dict[str, int] = {}
        for task in departments.tasks.values():
            issued[task.department] = issued.get(task.department, 0) + 1
            if task.accepted:
                accepted[task.department] = accepted.get(task.department, 0) + 1
        for department in sorted(issued):
            done = accepted.get(department, 0)
            state = ("accepted" if done >= issued[department]
                     else "awaiting_acceptance")
            observed = (state, issued[department], done)
            # Only publish an actual change. This method is called twice — once
            # before verification and once after a blocked department accepts —
            # and re-emitting an unchanged department produces a byte-identical
            # payload, which the bus correctly suppresses as a duplicate and
            # dead-letters. That is the idempotency guard doing its job on
            # traffic that should never have been generated: it put seven
            # spurious entries per disruption into a queue whose whole value is
            # that everything in it is worth looking at.
            if self._department_readiness.get(department) == observed:
                continue
            self._department_readiness[department] = observed
            self._emit(
                EventType.READINESS_CHANGED,
                {
                    "department": department,
                    "state": state,
                    "plan_id": plan_id,
                    "attributes": {
                        "tasks_issued": issued[department],
                        "tasks_accepted": done,
                    },
                },
                producer="department_tasks", authority=Authority.VERIFIED,
                disruption_id=disruption_id, plan_id=plan_id, causation_id=cause,
            )

    def _resolve_blocking(self, report: VerificationReport) -> str:
        """Resolve what can legitimately be resolved: an outstanding acceptance.

        Only department acceptance is resolvable this way, because it is the only
        blocker whose resolution is somebody saying yes. A missing briefing or an
        unsatisfied access arrangement is not resolved by asking again.
        """
        departments = self.systems.get(TargetSystem.DEPARTMENT_TASKS)
        if departments is None or not hasattr(departments, "outstanding"):
            return ""
        outstanding = {t.department for t in departments.outstanding()}
        if not outstanding:
            return ""
        for department in sorted(outstanding):
            departments.accept(department)
        return f"{', '.join(sorted(outstanding))} accepted their action"


_STALE = __import__("datetime").timedelta(hours=6)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _finding_event_type(finding: Finding) -> EventType:
    mapping = {
        "safety": EventType.SAFETY_FINDING,
        "egress": EventType.SAFETY_FINDING,
        "access": EventType.ACCESS_FINDING,
        "transport": EventType.ACCESS_FINDING,
        "communication": EventType.ACCESS_FINDING,
        "storage": EventType.ACCESS_FINDING,
        "resource": EventType.RESOURCE_FINDING,
        "equipment": EventType.RESOURCE_FINDING,
        "availability": EventType.RESOURCE_FINDING,
        "continuity": EventType.CONTINUITY_FINDING,
        "location": EventType.SPATIAL_FINDING,
        "permit": EventType.SPATIAL_FINDING,
        "budget": EventType.BUDGET_FINDING,
        "working_hours": EventType.SCHEDULE_FINDING,
        "child_performer": EventType.SCHEDULE_FINDING,
        "rest": EventType.SCHEDULE_FINDING,
        "daylight": EventType.SCHEDULE_FINDING,
    }
    return mapping.get(finding.domain.value, EventType.SCHEDULE_FINDING)


def _actor_for(role: Role) -> str:
    for crew in w.CREW:
        if crew.authority_role == role:
            return crew.crew_id
    return "CREW-UPM"


def _default_approver(plans: list[Plan], pareto: list[str]) -> Plan | None:
    """Choose the strongest plan on the Pareto front.

    Stands in for a human at the approval workspace. It picks from the *front*
    only — it never selects a dominated plan — and the CLI prints the whole
    comparison so the choice is visible rather than implied.
    """
    front = [p for p in plans if p.plan_id in pareto] or plans
    return front[0] if front else None


def problem_blast(problem: SchedulingProblem, source_event: Event):
    """Blast radius for a disruption, from the twin if one is attached."""
    twin = getattr(problem, "twin", None)
    if twin is None:
        return None
    from ..twin.graph import blast_radius

    origins = source_event.payload.get("affected_locations") or []
    if not origins:
        entity = source_event.payload.get("entity_id")
        origins = [entity] if entity else []
    # Scoped to the scenes this problem is planning — the day's call sheet. The
    # twin carries the whole script; the disruption is being analysed against
    # one day of it.
    return blast_radius(
        twin, origins, problem.now,
        scene_scope={a.scene_id for a in problem.baseline},
    )
