"""The expert agents.

Each one reads the deterministic evidence for its domain and produces typed
findings. The division of labour is strict and worth stating plainly: the
*services* compute, the *agents* interpret and explain. The Accessibility agent
does not decide whether a route is step-free — the spatial twin does — it reads
that answer, checks it against the approved arrangements, and says what it means
for tonight in language the accessibility coordinator can act on.

Every agent may abstain. Several do, routinely: the Continuity agent abstains
when no continuity chain is touched, and that abstention is the correct answer
rather than a gap.
"""

from __future__ import annotations

from typing import Any

from ..constraints.registry import CONSTRAINTS_BY_ID
from ..contracts import Classification, ConstraintDomain, Finding, FindingStatus, Role
from ..production import spatial as sp
from ..production import world as w
from .core import Agent, AgentContext


def _violations_for(context: AgentContext, *constraint_ids: str) -> list[Any]:
    wanted = set(constraint_ids)
    return [v for v in context.violations if v.constraint_id in wanted]


def _blocking(rows: list[Any]) -> list[Any]:
    return [v for v in rows if v.severity == "blocking"]


class ScopeAndDependencyAgent(Agent):
    """Traverses the twin and reports what the disruption reaches."""

    name = "scope_and_dependency_agent"
    domain = ConstraintDomain.APPROVAL
    authority = Role.COORDINATOR

    def assess(self, context: AgentContext) -> list[Finding]:
        blast = context.blast
        if blast is None:
            return [self.finding(
                context, status=FindingStatus.ABSTAINED,
                headline="No dependency graph was available for this disruption.",
                confidence=0.0,
            )]
        facts = {
            "direct": len(blast.direct),
            "transitive": len(blast.transitive),
            "departments": len(blast.departments),
            "people": len(blast.people),
            "documents": len(blast.documents),
            "access": len(blast.access_requirements),
            "scenes": len(blast.scenes),
            "depth": blast.max_depth,
        }
        headline = context.reasoner.narrate(
            self.name, "summarise the blast radius", facts,
            "The disruption reaches {direct} entities directly and {transitive} through "
            "dependencies, across {departments} departments and {scenes} scenes, touching "
            "{access} approved access arrangement(s) and {documents} document(s).",
        )
        return [self.finding(
            context, status=FindingStatus.AT_RISK if blast.nodes else FindingStatus.CLEAR,
            headline=headline,
            scope=tuple(blast.scenes[:20]),
            evidence=(
                f"{len(blast.nodes)} entities reached at depth <= {blast.max_depth}",
                f"departments: {', '.join(sorted(blast.departments))}",
                f"access arrangements: {', '.join(sorted(blast.access_requirements))}",
            ),
            hints={"affected_scenes": list(blast.scenes),
                   "access_requirements": list(blast.access_requirements)},
        )]


class SafetyAgent(Agent):
    name = "safety_agent"
    domain = ConstraintDomain.SAFETY
    authority = Role.SAFETY_LEAD

    def assess(self, context: AgentContext) -> list[Finding]:
        rows = _violations_for(context, "C-SAFE-001", "C-SAFE-002", "C-SAFE-003", "C-SAFE-004")
        blocking = _blocking(rows)
        if not rows:
            return [self.finding(
                context, status=FindingStatus.CLEAR,
                headline="No configured safety control is breached by this plan.",
                evidence=("weather thresholds", "briefing currency", "egress routes"),
                constraints=("C-SAFE-001", "C-SAFE-003", "C-SAFE-004"),
            )]
        first = blocking[0] if blocking else rows[0]
        headline = context.reasoner.narrate(
            self.name, "explain the safety finding",
            {"message": first.message, "count": len(rows), "evidence": first.evidence},
            "{message}. {count} safety finding(s) in total.",
        )
        return [self.finding(
            context,
            status=FindingStatus.BLOCKING if blocking else FindingStatus.AT_RISK,
            headline=headline,
            scope=tuple(sorted({v.subject_id for v in rows})),
            evidence=tuple(v.evidence for v in rows if v.evidence)[:5]
            or (first.message,),
            constraints=tuple(sorted({v.constraint_id for v in rows})),
            # A safety finding is routed to the safety lead. The system reports;
            # it does not clear a safety condition and never approves an exception.
            assumptions=(
                "The safety lead retains authority over safety policy and any exception.",
            ),
        )]


class AccessibilityAgent(Agent):
    """Approved practical arrangements, and whether the plan preserves them.

    Reports on every arrangement, not only the ones that break — an arrangement
    nobody reports on is an arrangement nobody is tracking. Applies
    minimum-necessary disclosure: findings carry the requirement and the
    mechanism, never a reason.
    """

    name = "accessibility_and_accommodation_agent"
    domain = ConstraintDomain.ACCESS
    authority = Role.ACCESS_COORDINATOR
    classification = Classification.OPERATIONAL_REQUIREMENT

    def assess(self, context: AgentContext) -> list[Finding]:
        rows = _violations_for(
            context, "C-ACC-001", "C-ACC-002", "C-ACC-003", "C-ACC-004",
            "C-ACC-005", "C-ACC-006",
        )
        findings: list[Finding] = []
        by_requirement: dict[str, list[Any]] = {}
        for v in rows:
            rid = str(v.detail.get("requirement") or v.subject_id)
            by_requirement.setdefault(rid, []).append(v)

        for requirement in w.ACCESS_REQUIREMENTS:
            hits = by_requirement.get(requirement.requirement_id, [])
            blocking = _blocking(hits)
            if blocking:
                first = blocking[0]
                headline = context.reasoner.narrate(
                    self.name, "explain an access conflict",
                    {
                        "requirement": requirement.requirement,
                        "message": first.message,
                        "mechanism": requirement.mechanism,
                    },
                    "{message} The approved arrangement is: {requirement}",
                )
                findings.append(self.finding(
                    context, status=FindingStatus.BLOCKING, headline=headline,
                    scope=(requirement.requirement_id,),
                    evidence=tuple(
                        v.evidence or v.message for v in blocking
                    )[:4],
                    constraints=tuple(sorted({v.constraint_id for v in blocking})),
                    assumptions=(
                        "An approved arrangement is a hard constraint and is never traded "
                        "against cost or schedule.",
                    ),
                    hints={"requirement_id": requirement.requirement_id},
                ))
            elif hits:
                findings.append(self.finding(
                    context, status=FindingStatus.AT_RISK,
                    headline=(
                        f"{requirement.requirement} is at risk under this plan: "
                        f"{hits[0].message}"
                    ),
                    scope=(requirement.requirement_id,),
                    evidence=(hits[0].evidence or hits[0].message,),
                    constraints=tuple(sorted({v.constraint_id for v in hits})),
                ))
            else:
                findings.append(self.finding(
                    context, status=FindingStatus.CLEAR,
                    headline=f"Preserved: {requirement.requirement}",
                    scope=(requirement.requirement_id,),
                    evidence=(requirement.mechanism,),
                ))
        return findings


class SpatialOperationsAgent(Agent):
    name = "spatial_operations_agent"
    domain = ConstraintDomain.LOCATION
    authority = Role.LOCATION_MANAGER

    def assess(self, context: AgentContext) -> list[Finding]:
        plan = context.extra.get("candidate")
        locations = sorted(plan.locations()) if plan is not None else []
        if not locations:
            return [self.finding(
                context, status=FindingStatus.ABSTAINED,
                headline="No plan was provided to assess spatially.", confidence=0.0,
            )]
        findings: list[Finding] = []
        for location_id in locations:
            assessment = sp.assess_location_access(location_id)
            if not assessment.get("modelled"):
                findings.append(self.finding(
                    context, status=FindingStatus.ABSTAINED,
                    headline=(
                        f"{location_id} has no surveyed spatial model; no spatial claim "
                        "can be made about it."
                    ),
                    scope=(location_id,), confidence=0.0,
                ))
                continue
            location = w.LOCATIONS_BY_ID.get(location_id)
            step_free = bool(assessment.get("step_free_satisfied"))
            egress = int(assessment.get("egress_route_count", 0))
            facts = {
                "name": location.name if location else location_id,
                "step_free": "step-free" if step_free else "NOT step-free",
                "route": assessment.get("step_free_route"),
                "walk": assessment.get("walk_minutes"),
                "egress": egress,
            }
            headline = context.reasoner.narrate(
                self.name, "summarise a location survey", facts,
                "{name}: {step_free} from arrival to the working position, {walk} min walk, "
                "{egress} independent egress route(s).",
            )
            findings.append(self.finding(
                context,
                status=FindingStatus.CLEAR if step_free and egress >= 2
                else FindingStatus.AT_RISK,
                headline=headline,
                scope=(location_id,),
                evidence=(
                    str(assessment.get("step_free_route")),
                    f"egress routes: {egress}",
                    f"equipment route: {assessment.get('equipment_minutes')} min",
                ),
                hints=dict(assessment),
            ))
        return findings


class ResourceAgent(Agent):
    name = "resource_agent"
    domain = ConstraintDomain.RESOURCE
    authority = Role.UPM

    def assess(self, context: AgentContext) -> list[Finding]:
        rows = _violations_for(
            context, "C-RES-001", "C-RES-002", "C-RES-003", "C-RES-007",
        )
        if not rows:
            return [self.finding(
                context, status=FindingStatus.CLEAR,
                headline="Every resource this plan assigns is available and uncontended.",
                evidence=("exclusivity", "availability windows", "operator certification"),
                constraints=("C-RES-001", "C-RES-002"),
            )]
        blocking = _blocking(rows)
        first = blocking[0] if blocking else rows[0]
        substitutes: list[str] = []
        equipment = w.EQUIPMENT_BY_ID.get(first.subject_id)
        if equipment:
            substitutes = [
                w.EQUIPMENT_BY_ID[s].name for s in equipment.substitutes
                if s in w.EQUIPMENT_BY_ID
            ]
        headline = context.reasoner.narrate(
            self.name, "explain a resource conflict",
            {"message": first.message,
             "substitutes": ", ".join(substitutes) or "none catalogued"},
            "{message}. Catalogued substitutes: {substitutes}.",
        )
        return [self.finding(
            context,
            status=FindingStatus.BLOCKING if blocking else FindingStatus.AT_RISK,
            headline=headline,
            scope=tuple(sorted({v.subject_id for v in rows})),
            evidence=tuple(v.evidence for v in rows if v.evidence)[:4] or (first.message,),
            constraints=tuple(sorted({v.constraint_id for v in rows})),
            hints={"substitutes": substitutes},
        )]


class ScheduleAgent(Agent):
    name = "schedule_agent"
    domain = ConstraintDomain.WORKING_HOURS
    authority = Role.FIRST_AD

    def assess(self, context: AgentContext) -> list[Finding]:
        rows = _violations_for(
            context, "C-HOUR-001", "C-HOUR-002", "C-CHILD-001", "C-CHILD-002",
            "C-CHILD-003", "C-TIME-001", "C-TIME-002", "C-TIME-003",
        )
        if not rows:
            return [self.finding(
                context, status=FindingStatus.CLEAR,
                headline=(
                    "The revised day is within configured working hours, turnaround, "
                    "child performer and daylight limits."
                ),
                evidence=("working hours", "turnaround", "child performer window",
                          "daylight and darkness"),
                constraints=("C-HOUR-001", "C-CHILD-001", "C-TIME-001"),
            )]
        blocking = _blocking(rows)
        first = blocking[0] if blocking else rows[0]
        return [self.finding(
            context,
            status=FindingStatus.BLOCKING if blocking else FindingStatus.AT_RISK,
            headline=first.message + ".",
            scope=tuple(sorted({v.subject_id for v in rows})),
            evidence=tuple(v.evidence for v in rows if v.evidence)[:4] or (first.message,),
            constraints=tuple(sorted({v.constraint_id for v in rows})),
        )]


class ContinuityAgent(Agent):
    name = "continuity_agent"
    domain = ConstraintDomain.CONTINUITY
    authority = Role.DEPARTMENT_HEAD

    def assess(self, context: AgentContext) -> list[Finding]:
        rows = _violations_for(context, "C-CONT-001", "C-CONT-002")
        plan = context.extra.get("candidate")
        if plan is None:
            return [self.finding(
                context, status=FindingStatus.ABSTAINED,
                headline="No plan was provided to assess for continuity.", confidence=0.0,
            )]
        touched = {a.scene_id for a in plan.assignments}
        chains = {"SC-018", "SC-022", "SC-025", "SC-026", "SC-027", "SC-029", "SC-030"}
        if not rows and not (touched & chains):
            # Correct abstention: nothing this plan changes is on a continuity
            # chain, so there is no continuity claim to make either way.
            return [self.finding(
                context, status=FindingStatus.ABSTAINED,
                headline=(
                    "No scene in this plan carries or establishes continuity state; "
                    "no continuity assessment applies."
                ),
                confidence=1.0,
            )]
        if not rows:
            return [self.finding(
                context, status=FindingStatus.CLEAR,
                headline="Continuity order and irreversible states are preserved.",
                scope=tuple(sorted(touched & chains)),
                evidence=("continuity chain order", "wet-down irreversibility"),
                constraints=("C-CONT-001", "C-CONT-002"),
            )]
        first = rows[0]
        return [self.finding(
            context,
            status=FindingStatus.BLOCKING if _blocking(rows) else FindingStatus.AT_RISK,
            headline=first.message + ".",
            scope=tuple(sorted({v.subject_id for v in rows})),
            evidence=tuple(v.evidence for v in rows if v.evidence) or (first.message,),
            constraints=tuple(sorted({v.constraint_id for v in rows})),
        )]


class BudgetAgent(Agent):
    name = "budget_agent"
    domain = ConstraintDomain.BUDGET
    authority = Role.UPM

    def assess(self, context: AgentContext) -> list[Finding]:
        breakdown = context.extra.get("objectives")
        if breakdown is None:
            return [self.finding(
                context, status=FindingStatus.ABSTAINED,
                headline="No costed plan was provided.", confidence=0.0,
            )]
        objectives = breakdown.objectives
        threshold = float(w.POLICIES["budget"]["overtime_approval_threshold"])  # type: ignore[arg-type]
        contingency = float(w.POLICIES["budget"]["contingency"])  # type: ignore[arg-type]
        facts = {
            "cost": f"{objectives.cost_delta:,.0f}",
            "overtime": objectives.overtime_minutes,
            "contingency": f"{contingency:,.0f}",
            "share": f"{100 * objectives.cost_delta / contingency:.1f}",
        }
        headline = context.reasoner.narrate(
            self.name, "summarise the cost of a plan", facts,
            "Incremental cost {cost}, which is {share}% of the {contingency} contingency, "
            "with {overtime} minutes of overtime exposure.",
        )
        status = FindingStatus.AT_RISK if objectives.cost_delta > threshold else FindingStatus.CLEAR
        return [self.finding(
            context, status=status, headline=headline,
            evidence=tuple(
                f"{line.label}: {line.amount:,.0f} ({line.basis})"
                for line in breakdown.lines
            )[:6] or ("no incremental cost",),
            assumptions=tuple(breakdown.assumptions),
            # The budget agent cannot rank cost above a hard constraint, and says
            # so in every finding it produces.
            constraints=(),
            hints={"cost_delta": objectives.cost_delta,
                   "requires_upm_approval": objectives.cost_delta > threshold},
        )]


class PermitAgent(Agent):
    name = "permit_agent"
    domain = ConstraintDomain.PERMIT
    authority = Role.LOCATION_MANAGER

    def assess(self, context: AgentContext) -> list[Finding]:
        rows = _violations_for(context, "C-PERM-001", "C-PERM-002", "C-PERM-003")
        if not rows:
            return [self.finding(
                context, status=FindingStatus.CLEAR,
                headline="Every location in this plan is covered by a valid permit.",
                evidence=("permit validity windows", "setup cutoffs", "occupancy limits"),
                constraints=("C-PERM-001",),
            )]
        first = _blocking(rows)[0] if _blocking(rows) else rows[0]
        return [self.finding(
            context,
            status=FindingStatus.BLOCKING if _blocking(rows) else FindingStatus.AT_RISK,
            headline=first.message + ".",
            scope=tuple(sorted({v.subject_id for v in rows})),
            evidence=tuple(v.evidence for v in rows if v.evidence)[:4] or (first.message,),
            constraints=tuple(sorted({v.constraint_id for v in rows})),
        )]


class PolicyAndAuthorityAgent(Agent):
    """Which authorities must approve, and whether anything is prohibited outright."""

    name = "policy_and_authority_agent"
    domain = ConstraintDomain.APPROVAL
    authority = Role.COORDINATOR

    def assess(self, context: AgentContext) -> list[Finding]:
        plan = context.extra.get("published_plan")
        if plan is None:
            return [self.finding(
                context, status=FindingStatus.ABSTAINED,
                headline="No plan was provided for a policy assessment.", confidence=0.0,
            )]
        roles = [r.value for r in plan.required_approvals]
        prohibited = [
            c.required_change for c in plan.conflicts
            if c.change_permitted is False and c.required_change
        ]
        if prohibited:
            return [self.finding(
                context, status=FindingStatus.BLOCKING,
                headline=(
                    "This plan can only proceed through a change nobody in the system is "
                    "permitted to make."
                ),
                evidence=tuple(prohibited)[:3],
                constraints=tuple(sorted({
                    cid for c in plan.conflicts for cid in c.constraint_ids
                })),
            )]
        return [self.finding(
            context, status=FindingStatus.CLEAR,
            headline=(
                f"Required authorities: {', '.join(roles) if roles else 'none'}."
            ),
            evidence=tuple(
                f"{cid}: {CONSTRAINTS_BY_ID[cid].owner.value}"
                for cid in sorted({
                    cid for c in plan.conflicts for cid in c.constraint_ids
                })[:4] if cid in CONSTRAINTS_BY_ID
            ) or ("approval matrix",),
            hints={"required_roles": roles},
        )]


class SimulationAgent(Agent):
    name = "simulation_agent"
    domain = ConstraintDomain.APPROVAL
    authority = Role.COORDINATOR

    def assess(self, context: AgentContext) -> list[Finding]:
        report = context.extra.get("robustness")
        if report is None:
            return [self.finding(
                context, status=FindingStatus.ABSTAINED,
                headline="No simulation ensemble was run for this plan.", confidence=0.0,
            )]
        facts = {
            "scenarios": report.scenarios,
            "on_time": f"{report.on_time_probability:.0%}",
            "expected": f"{report.expected_delay_minutes:.0f}",
            "worst": f"{report.worst_credible_delay_minutes:.0f}",
            "margin": f"{report.recovery_margin_minutes:.0f}",
        }
        headline = context.reasoner.narrate(
            self.name, "summarise plan robustness", facts,
            "Across {scenarios} simulated runs the plan completes on time {on_time} of the "
            "time, with {expected} min expected delay, {worst} min worst credible delay and "
            "{margin} min of recovery margin.",
        )
        return [self.finding(
            context,
            status=FindingStatus.CLEAR if report.on_time_probability >= 0.8
            else FindingStatus.AT_RISK,
            headline=headline,
            evidence=tuple(report.sensitive_assumptions)[:4] or ("ensemble simulation",),
            confidence=min(1.0, report.scenarios / 200.0),
            uncertainty={
                "on_time_probability": report.on_time_probability,
                "expected_delay_minutes": report.expected_delay_minutes,
                "worst_credible_delay_minutes": report.worst_credible_delay_minutes,
                "overtime_risk": report.overtime_risk,
            },
        )]


#: The agents the coordinator runs, in the order their findings are presented.
EXPERT_AGENTS: tuple[Agent, ...] = (
    ScopeAndDependencyAgent(),
    SafetyAgent(),
    AccessibilityAgent(),
    SpatialOperationsAgent(),
    ResourceAgent(),
    ScheduleAgent(),
    ContinuityAgent(),
    PermitAgent(),
    BudgetAgent(),
    SimulationAgent(),
    PolicyAndAuthorityAgent(),
)

#: Assessments that must complete before a plan may be presented for approval.
#: The coordinator refuses to advance without them — an assessment that is
#: optional is an assessment that will be skipped on the day it matters.
REQUIRED_ASSESSMENTS: frozenset[str] = frozenset({
    "safety_agent",
    "accessibility_and_accommodation_agent",
    "resource_agent",
    "schedule_agent",
    "permit_agent",
    "policy_and_authority_agent",
})
