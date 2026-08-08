"""The web application: the twelve views of §14, over one live workflow run.

The server holds a `Session` — one disruption, taken from source event to
closure by exactly the same coordinator the CLI and the benchmark use. There is
no separate demonstration path and no fixture file. Everything the browser
renders is derived from the events that run produced, which is the only way the
Decision Replay view can be honest: it replays the real log.

Two boundaries are enforced here rather than in the browser:

* **Audience.** The crew and executive views are built through
  `execution/privacy.py`, so what a role cannot see is never serialised, let
  alone hidden with CSS. `/api/crew/{person_id}` returns the same minimal record
  the mobile client gets.
* **Authority.** Nothing in this API approves, executes or overrides anything.
  It is a read model over a completed decision, plus one endpoint that starts a
  new disruption from the scenario library.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agents.coordinator import DisruptionOutcome, ProductionCoordinator, problem_blast
from .agents.core import build_reasoner
from .constraints.registry import CONSTRAINTS, active_constraints, constraint_set_hash
from .contracts import Role, TargetSystem
from .disruptions import STORM_SCENARIO, Scenario, build_source_event, generate, scenario_problem
from .execution import privacy, verification
from .production import script as scr
from .production import spatial as sp
from .production import world as w
from .simulation import robust
from .stream import governance
from .stream.bus import build_bus
from .systems import build_systems
from .twin import build_twin, certify_baseline

WEB = Path(__file__).parent / "web"

#: The scenario library offered by the intake view. The storm is the hero; the
#: rest are drawn from the same generator the benchmark uses, so nothing in the
#: product is reachable only from a demonstration script.
LIBRARY: dict[str, Scenario] = {
    STORM_SCENARIO.scenario_id: STORM_SCENARIO,
    **{s.scenario_id: s for s in generate(40)[1:25]},
}


@dataclass
class ShiftEntry:
    """One handled disruption, kept after its session is replaced.

    The executive view is the only one that should not be about a single
    incident. A producer does not need to know that this storm cost 40 minutes;
    they need to know what the day cost, which arrangements came under pressure
    more than once, and which rules keep removing options — because that last
    one is a budget decision. A second interpreter, a ramp at the boatshed and a
    later permit curfew are things somebody can buy, and the only way to know
    which one to buy is to count how often each is what blocked the day.
    """

    scenario_id: str
    title: str
    family: str
    severity: str
    state: str
    feasible_plans: int
    rejected_plans: int
    delay_minutes: float
    cost_delta: float
    overtime_minutes: float
    access_total: int
    access_preserved: int
    verification_ready: bool
    blocked_then_resolved: bool
    decision_ms: float
    binding_constraints: tuple[str, ...]
    started_at: datetime


#: Every disruption handled by this process, oldest first. The executive view
#: reads it; nothing else does, and nothing reads it to make a decision.
_SHIFT: list[ShiftEntry] = []


def _record_shift(session: "Session") -> None:
    outcome = session.outcome
    selected = outcome.selected
    binding: list[str] = []
    for plan in outcome.rejected:
        for conflict in plan.conflicts:
            binding.extend(conflict.constraint_ids)
    _SHIFT.append(ShiftEntry(
        scenario_id=session.scenario.scenario_id,
        title=session.scenario.title,
        family=session.scenario.family,
        severity=session.scenario.severity,
        state=outcome.disruption.state.value,
        feasible_plans=len(outcome.plans),
        rejected_plans=len(outcome.rejected),
        delay_minutes=selected.objectives.delay_minutes if selected else 0.0,
        cost_delta=selected.objectives.cost_delta if selected else 0.0,
        overtime_minutes=selected.objectives.overtime_minutes if selected else 0.0,
        access_total=len(selected.access) if selected else 0,
        access_preserved=(
            sum(1 for a in selected.access if a.satisfied) if selected else 0
        ),
        verification_ready=bool(outcome.verification and outcome.verification.ready),
        blocked_then_resolved=outcome.blocked_then_resolved,
        decision_ms=outcome.timings.get("total_ms", 0.0),
        binding_constraints=tuple(binding),
        started_at=session.started_at,
    ))


class Session:
    """One disruption, run once, held for the views to read."""

    def __init__(self, scenario: Scenario = STORM_SCENARIO, *, scenarios: int = 200) -> None:
        self.scenario = scenario
        self.twin = build_twin()
        self.baseline = certify_baseline(self.twin)
        self.bus = build_bus(w.PRODUCTION_ID)
        self.systems = build_systems(w.PRODUCTION_ID, hold_department="props")
        self.problem = scenario_problem(scenario, twin=self.twin)
        self.source = build_source_event(self.bus, scenario)
        self.coordinator = ProductionCoordinator(
            self.bus, self.systems, reasoner=build_reasoner()
        )
        self.outcome: DisruptionOutcome = self.coordinator.handle(
            self.problem, self.source,
            title=scenario.title, scenario_id=scenario.scenario_id,
            scenarios=scenarios,
        )
        self.blast = problem_blast(self.problem, self.source)
        self.events = self.bus.all_events()
        self.started_at = datetime.now()


_lock = threading.Lock()
_session: Session | None = None


def session() -> Session:
    global _session
    with _lock:
        if _session is None:
            _session = Session()
            _record_shift(_session)
        return _session


def reset(scenario_id: str | None = None) -> Session:
    """Start a new disruption. The judge reset path — see docs/JUDGE.md."""
    global _session
    scenario = LIBRARY.get(scenario_id or "", STORM_SCENARIO)
    with _lock:
        _session = Session(scenario)
        _record_shift(_session)
        return _session


app = FastAPI(
    title="ProductionPulse Inclusive",
    description="Real-time production decision and execution infrastructure",
    version="0.1.0",
)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _dt(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _plan_row(plan: Any, outcome: DisruptionOutcome) -> dict[str, Any]:
    report = outcome.robustness.get(plan.plan_id)
    return {
        "plan_id": plan.plan_id,
        "strategy": plan.strategy,
        "label": plan.label,
        "rationale": plan.rationale,
        "feasible": plan.feasible,
        "on_pareto_front": plan.plan_id in outcome.pareto_front,
        "selected": plan.plan_id == outcome.disruption.selected_plan_id,
        "objectives": plan.objectives.model_dump(mode="json"),
        "scenes": len(plan.scenes),
        "deferred_scenes": list(plan.deferred_scenes),
        "required_approvals": [r.value for r in plan.required_approvals],
        "safety_controls": list(plan.safety_controls),
        "permits": list(plan.permits),
        "continuity_notes": list(plan.continuity_notes),
        "command_set": list(plan.command_set),
        "verification_checklist": list(plan.verification_checklist),
        "access": [a.model_dump(mode="json") for a in plan.access],
        "transport": [t.model_dump(mode="json") for t in plan.transport],
        "plan_hash": plan.content_hash(),
        "proof": plan.proof.model_dump(mode="json") if plan.proof else None,
        "conflicts": [c.model_dump(mode="json") for c in plan.conflicts],
        "robustness": (
            {
                "scenarios": report.scenarios,
                "expected_delay_minutes": report.expected_delay_minutes,
                "worst_credible_delay_minutes": report.worst_credible_delay_minutes,
                "recovery_margin_minutes": report.recovery_margin_minutes,
                "constraint_violation_risk": report.constraint_violation_risk,
                "overtime_risk": report.overtime_risk,
                # Reported for completeness and explicitly not a ranking signal;
                # see robust.compare() and docs/BENCHMARK.md §7.
                "on_time_probability": report.on_time_probability,
                "sensitive_assumptions": list(report.sensitive_assumptions),
                "sensitivity": report.sensitivity,
            }
            if report else None
        ),
    }


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


@app.get("/api/control-board")
def control_board() -> dict[str, Any]:
    """§14.1 — the production control board."""
    s = session()
    views = s.coordinator.views
    selected = s.outcome.selected
    now = s.problem.now
    scenes = sorted(
        (selected.scenes if selected else ()),
        key=lambda a: a.start,
    )
    weather = [
        {
            "start": _dt(win.start), "end": _dt(win.end), "condition": win.condition,
            "wind_kph": win.wind_kph, "precipitation_mm": win.precipitation_mm,
            "sea_state": win.sea_state, "lightning_risk": win.lightning_risk,
        }
        for win in (s.scenario.weather or w.BASELINE_WEATHER)
    ]
    return {
        "production": {
            "id": w.PRODUCTION_ID,
            "title": w.PRODUCTION_TITLE,
            "shoot_date": w.SHOOT_DATE.isoformat(),
            "unit": "UNIT-MAIN",
            "clock": _dt(now),
        },
        "baseline": {
            "state": s.baseline.state,
            "checks": s.baseline.checked,
            "issues": len(s.baseline.issues),
            "state_hash": s.baseline.state_hash,
        },
        "twin": {
            "entities": len(s.twin.entities),
            "relationships": len(s.twin.relationships),
            "temporal_facts": sum(len(v) for v in s.twin.facts.values()),
        },
        "constraints": {
            "count": len(CONSTRAINTS),
            "hash": constraint_set_hash(active_constraints()),
        },
        "disruption": {
            "id": s.outcome.disruption.disruption_id,
            "title": s.outcome.disruption.title,
            "state": s.outcome.disruption.state.value,
            "scenario_id": s.scenario.scenario_id,
            "history": [{"state": st, "detail": d}
                        for st, d in s.outcome.disruption.history],
        },
        "next_scenes": [
            {
                "scene_id": a.scene_id,
                "location_id": a.location_id,
                "location": w.LOCATIONS_BY_ID[a.location_id].name,
                "unit_id": a.unit_id,
                "crew_call": _dt(a.crew_call),
                "start": _dt(a.start),
                "end": _dt(a.end),
                "slugline": (
                    scr.SCENES_BY_ID[a.scene_id].slugline
                    if a.scene_id in scr.SCENES_BY_ID else a.scene_id
                ),
                "synopsis": (
                    scr.SCENES_BY_ID[a.scene_id].synopsis
                    if a.scene_id in scr.SCENES_BY_ID else ""
                ),
                "exterior": a.exterior,
            }
            for a in scenes[:8]
        ],
        "departments": [
            {
                "department": name,
                "tasks": row.tasks_issued,
                "accepted": row.tasks_accepted,
                "rejected": row.tasks_rejected,
                # `DepartmentReadiness.ready` and not a rule re-derived here.
                # The re-derived version read `issued == accepted`, which is
                # True for a department with no tasks at all, so the board
                # reported "ready" for a row that had never been populated —
                # while verification was blocking the day. One readiness rule,
                # owned by the read model.
                "ready": row.ready,
            }
            for name, row in sorted(views.departments.items())
        ],
        "exposure": {
            "delay_minutes": views.delay_exposure_minutes,
            "overtime_minutes": views.overtime_exposure_minutes,
            "access_at_risk": sorted(views.access_at_risk),
        },
        "weather": weather,
        "daylight": {
            "civil_dawn": _dt(w.CIVIL_DAWN),
            "sunrise": _dt(w.DAYLIGHT_SUNRISE),
            "sunset": _dt(w.DAYLIGHT_SUNSET),
            "civil_dusk": _dt(w.CIVIL_DUSK),
        },
        "kpis": views.kpis(),
        "awaiting_approval": sorted(views.pending_approvals.items()),
    }


@app.get("/api/intake")
def intake() -> dict[str, Any]:
    """§14.2 — disruption intake: the extracted event and its provenance."""
    s = session()
    env = s.source.envelope
    return {
        "library": [
            {"scenario_id": k, "title": v.title, "family": v.family,
             "severity": v.severity, "description": v.description}
            for k, v in LIBRARY.items()
        ],
        "active": s.scenario.scenario_id,
        "event": {
            "event_id": env.event_id,
            "event_type": env.event_type.value,
            "producer": env.producer,
            "actor": env.actor,
            "authority": env.authority.value,
            "classification": env.classification.value,
            "effective_time": _dt(env.effective_time),
            "event_time": _dt(env.event_time),
            "schema_version": env.schema_version,
            "partition_key": env.partition_key,
            "payload_hash": env.payload_hash,
            "signature": env.signature,
        },
        "payload": s.source.payload,
        "confidence": s.source.payload.get("confidence"),
        "requires_confirmation": env.authority.value in ("reported", "inferred"),
        "operational_consequence": (
            f"{len(s.blast.nodes) if s.blast else 0} entities reached, "
            f"{len(s.outcome.rejected)} plan(s) rejected on hard constraints"
        ),
    }


@app.get("/api/impact")
def impact() -> dict[str, Any]:
    """§14.3 — the impact map: every consequence, expandable to its source."""
    s = session()
    if s.blast is None:
        return {"origin_ids": [], "nodes": [], "by_depth": {}}
    return {
        "origin_ids": list(s.blast.origin_ids),
        "max_depth": s.blast.max_depth,
        "nodes": [
            {
                "entity_id": n.entity_id,
                "entity_type": n.entity_type,
                "label": n.label,
                "depth": n.depth,
                "path": list(n.path),
                "via": list(n.via),
                "critical": n.critical,
                "relevance": n.relevance,
            }
            for n in s.blast.nodes
        ],
        "departments": [d.replace("DEPT-", "") for d in s.blast.departments],
        "people": list(s.blast.people),
        "documents": list(s.blast.documents),
        "access_requirements": list(s.blast.access_requirements),
        "scenes": list(s.blast.scenes),
        # The ranked band. Everything above is the full traversal; the client
        # leads with these and keeps the rest one interaction away.
        "primary": {
            "departments": [
                d.replace("DEPT-", "") for d in s.blast.primary_departments
            ],
            "people": list(s.blast.primary_people),
            "documents": list(s.blast.primary_documents),
            "access_requirements": list(s.blast.primary_access_requirements),
            "scenes": list(s.blast.primary_scenes),
        },
        "counts_by_relevance": s.blast.counts_by_relevance(),
        "counts_by_depth": {
            str(depth): len(ids) for depth, ids in sorted(s.blast.by_depth.items())
        },
    }


@app.get("/api/plans")
def plans() -> dict[str, Any]:
    """§14.4 and §14.5 — plan comparison and the infeasible plan explorer."""
    s = session()
    return {
        "feasible": [_plan_row(p, s.outcome) for p in s.outcome.plans],
        "rejected": [_plan_row(p, s.outcome) for p in s.outcome.rejected],
        "pareto_front": list(s.outcome.pareto_front),
        "selected_plan_id": s.outcome.disruption.selected_plan_id,
        "robustness_ranking": robust.compare(s.outcome.robustness),
        # The comparison view has to render hard constraints differently from
        # objectives, so it is told which is which rather than inferring it.
        "hard_constraints": sorted(
            c.constraint_id for c in CONSTRAINTS if c.kind.value == "hard"
        ),
        "objectives": [
            "delay_minutes", "cost_delta", "overtime_minutes", "idle_crew_minutes",
            "travel_minutes", "setup_complexity", "weather_exposure",
            "continuity_risk", "operational_risk", "communication_burden",
            "changed_assignments",
        ],
    }


@app.get("/api/findings")
def findings() -> dict[str, Any]:
    """The parallel expert assessment, with abstentions kept visible."""
    s = session()
    return {
        "findings": [
            {
                "finding_id": f.finding_id,
                "producer": f.producer,
                "domain": f.domain.value,
                "status": f.status.value,
                "headline": f.headline,
                "evidence": list(f.evidence),
                "applicable_constraints": list(f.applicable_constraints),
                "assumptions": list(f.assumptions),
                "confidence": f.confidence,
                "uncertainty": f.uncertainty,
                "scope": list(f.scope),
                "required_authority": (
                    f.required_authority.value if f.required_authority else None
                ),
                "classification": f.classification.value,
            }
            for f in s.outcome.findings
        ],
        "reasoning_plane": s.coordinator.reasoner.plane,
        # What the reasoning plane actually did, including anything it said that
        # the facts did not support. On the offline plane these are all zero;
        # on the Gemini plane they are the record of the grounding gate.
        "reasoning": _reasoning_report(s.coordinator.reasoner),
    }


def _reasoning_report(reasoner: Any) -> dict[str, Any]:
    calls = list(reasoner.calls())
    rejected = [c for c in calls if getattr(c, "rejected_claims", ())]
    return {
        "plane": reasoner.plane,
        "calls": len(calls),
        "failed": sum(1 for c in calls if c.error),
        "responses_rejected_as_ungrounded": len(rejected),
        "rejected_claims": sorted({
            claim for c in rejected for claim in c.rejected_claims
        }),
        "degraded": bool(getattr(reasoner, "degraded", False)),
        "model": next((c.model for c in calls if c.model), None),
        "tokens_in": sum(c.tokens_in or 0 for c in calls) or None,
        "tokens_out": sum(c.tokens_out or 0 for c in calls) or None,
        "total_latency_ms": round(sum(c.latency_ms for c in calls), 2),
    }


@app.get("/api/spatial/{location_id}")
def spatial(location_id: str) -> dict[str, Any]:
    """§14.6 — the spatial location view."""
    assessment = sp.assess_location_access(location_id)
    if not assessment.get("modelled"):
        raise HTTPException(404, f"{location_id} is not spatially modelled")
    twin = sp.build_twin()
    location = w.LOCATIONS_BY_ID.get(location_id)
    return {
        "assessment": assessment,
        "location": {
            "location_id": location_id,
            "name": location.name if location else location_id,
            "noise_curfew": _dt(location.noise_curfew) if location else None,
        } if location else None,
        "nodes": [
            {"node_id": n.node_id, "kind": n.kind, "name": n.name,
             "location_id": n.location_id, "covered": n.covered,
             "capacity": n.capacity, "notes": n.notes}
            for n in twin.nodes.values() if n.location_id == location_id
        ],
        "edges": [
            {
                "edge_id": e.edge_id, "a": e.a, "b": e.b,
                "metres": e.metres, "surface": e.surface, "gradient": e.gradient,
                "clear_width_mm": e.clear_width_mm, "threshold_mm": e.threshold_mm,
                "steps": e.steps, "covered": e.covered, "notes": e.notes,
                # The measurement that decides it, not a category. This string is
                # what a location manager acts on.
                "step_free": e.step_free()[0],
                "step_free_reason": e.step_free()[1],
            }
            for e in twin.edges.values()
            if twin.nodes.get(e.a) is not None
            and twin.nodes[e.a].location_id == location_id
        ],
        "blocked_edges": sorted(twin.blocked),
        "locations": sorted({n.location_id for n in twin.nodes.values()}),
    }


@app.get("/api/approval")
def approval() -> dict[str, Any]:
    """§14.7 — the approval workspace."""
    s = session()
    selected = s.outcome.selected
    if selected is None:
        return {"selected": None, "approvals": []}
    return {
        "selected": _plan_row(selected, s.outcome),
        "constraint_hash": constraint_set_hash(active_constraints()),
        "approvals": [
            {
                "approval_id": a.approval_id,
                "role": a.role.value,
                "actor": a.actor,
                "rationale": a.rationale,
                "approved_scope": a.approved_scope,
                "plan_hash": a.plan_hash,
                "constraint_hash": a.constraint_hash,
                "expires_at": _dt(a.expires_at),
                "signature": a.signature,
            }
            for a in s.outcome.disruption.approvals
        ],
        "required_roles": [r.value for r in selected.required_approvals],
    }


@app.get("/api/execution")
def execution() -> dict[str, Any]:
    """§14.8 — the execution board, plus the verification result."""
    s = session()
    saga = s.outcome.saga
    report = s.outcome.verification
    return {
        "commands": [
            {
                "command_id": step.command.command_id,
                "target": step.command.target.value,
                "action": step.command.action,
                "status": step.status.value,
                "plan_version": step.command.plan_version,
                "depends_on": list(step.command.depends_on),
                "required_role": (
                    step.command.required_role.value
                    if step.command.required_role else None
                ),
                "idempotency_key": step.command.idempotency_key,
                "detail": step.result.detail if step.result else "",
                "error": step.result.error if step.result else None,
                "system_version": step.result.system_version if step.result else None,
            }
            for step in (saga.steps if saga else [])
        ],
        "compensations": list(saga.compensations) if saga else [],
        "inbox_suppressed": s.coordinator.saga.inbox.suppressed,
        "verification": (
            {
                "ready": report.ready,
                "passed": report.passed,
                "total": len(report.assertions),
                "blocking": list(report.blocking),
                "assertions": [a.model_dump(mode="json") for a in report.assertions],
                "summary": verification.readiness_summary(report),
            }
            if report else None
        ),
        "blocked_then_resolved": s.outcome.blocked_then_resolved,
        "systems": {
            target.value: adapter.state()
            for target, adapter in sorted(s.systems.items(), key=lambda kv: kv[0].value)
        },
    }


@app.get("/api/departments")
def departments() -> dict[str, Any]:
    """§14.9 — the department work queue."""
    s = session()
    tasks = s.systems[TargetSystem.DEPARTMENT_TASKS]
    return {
        "tasks": [
            {
                "task_id": t.task_id,
                "department": t.department,
                "what_changed": t.what_changed,
                "why": t.why,
                "action": t.action,
                "deadline": t.deadline,
                "accepted": t.accepted,
            }
            for t in sorted(tasks.tasks.values(), key=lambda t: t.department)
        ],
        "outstanding": [t.department for t in tasks.outstanding()],
        "messages": [
            {
                "message_id": m.message_id,
                "recipient_id": m.recipient_id,
                "recipient_role": m.recipient_role.value,
                "subject": m.subject,
                "body": m.body,
                "channel": m.channel,
                "language": m.language,
                "requires_ack": m.requires_ack,
                "accessible_formats": list(m.accessible_formats),
                "derived_from": list(m.derived_from),
                "classification": m.classification.value,
            }
            for m in s.outcome.messages
            if m.recipient_role in (Role.DEPARTMENT_HEAD, Role.COORDINATOR)
        ],
    }


@app.get("/api/crew/{person_id}")
def crew(person_id: str) -> dict[str, Any]:
    """§14.10 — the crew mobile view. Minimum necessary, by construction."""
    s = session()
    selected = s.outcome.selected
    if selected is None:
        raise HTTPException(404, "no approved plan")
    called = [a for a in selected.scenes if person_id in a.cast_calls]
    if not called and person_id not in {c.crew_id for c in w.CREW}:
        raise HTTPException(404, f"{person_id} is not called under this plan")
    first = min(called, key=lambda a: a.start) if called else min(
        selected.scenes, key=lambda a: a.start
    )
    row = {
        "call_time": first.cast_calls.get(person_id, first.crew_call).isoformat(),
        "location": w.LOCATIONS_BY_ID[first.location_id].name,
        "location_id": first.location_id,
        "scene_id": first.scene_id,
        "revision": 2,
    }
    message = next(
        (m for m in s.outcome.messages if m.recipient_id == person_id), None
    )
    return {
        "person_id": person_id,
        "view": privacy.crew_view(person_id, row),
        "message": (
            {
                "subject": message.subject, "body": message.body,
                "language": message.language,
                "accessible_formats": list(message.accessible_formats),
                "requires_ack": message.requires_ack,
            }
            if message else None
        ),
        "acknowledged": any(
            a.person_id == person_id for a in s.outcome.disruption.acknowledgments
        ),
        "people": sorted(
            {pid for a in selected.scenes for pid in a.cast_calls}
            | {m.recipient_id for m in s.outcome.messages
               if m.recipient_role is Role.CREW}
        ),
    }


_CONSTRAINTS_BY_ID = {c.constraint_id: c for c in CONSTRAINTS}


def _pressure_row(constraint_id: str, count: int) -> dict[str, Any]:
    """One rule, and how often it was what removed an option.

    Carries the owner and the source document because a producer reading this
    needs to know who to talk to and what to renegotiate. A constraint id with
    a count is a statistic; a constraint id with an owner and a permit number
    is a decision.
    """
    record = _CONSTRAINTS_BY_ID.get(constraint_id)
    return {
        "constraint_id": constraint_id,
        "times_binding": count,
        "title": record.title if record else constraint_id,
        "owner": record.owner.value if record and record.owner else None,
        "source": record.source if record else None,
        "kind": record.kind.value if record else None,
        "waivable": (record.kind.value != "hard") if record else None,
    }


@app.get("/api/executive")
def executive() -> dict[str, Any]:
    """§14.11 — the executive view. Aggregate only, enforced not styled."""
    s = session()
    views = s.coordinator.views
    selected = s.outcome.selected
    report = s.outcome.verification
    metrics = {
        "disruptions": len(views.disruptions),
        "disruptions_ready": sum(
            1 for d in views.disruptions.values() if d.verification_ready
        ),
        "decision_latency_ms": s.outcome.timings.get("total_ms", 0.0),
        "solver_latency_ms": s.outcome.timings.get("solve_ms", 0.0),
        "delay_minutes": selected.objectives.delay_minutes if selected else 0.0,
        "cost_delta": selected.objectives.cost_delta if selected else 0.0,
        "overtime_minutes": selected.objectives.overtime_minutes if selected else 0.0,
        "prevented_hard_constraint_violations": len(s.outcome.rejected),
        "access_arrangements_preserved": (
            sum(1 for a in selected.access if a.satisfied) if selected else 0
        ),
        "access_arrangements_total": len(selected.access) if selected else 0,
        "acknowledgment_completion": (
            len(s.outcome.disruption.acknowledgments)
            / max(1, sum(1 for m in s.outcome.messages if m.requires_ack))
        ),
        "assertions_passed": report.passed if report else 0,
        "assertions_total": len(report.assertions) if report else 0,
        "messages_sent": len(s.outcome.messages),
    }
    # -- the shift, not the incident ----------------------------------------
    shift = list(_SHIFT)
    handled = len(shift)
    access_total = sum(e.access_total for e in shift)
    access_kept = sum(e.access_preserved for e in shift)
    latencies = sorted(e.decision_ms for e in shift)
    pressure = Counter(c for e in shift for c in e.binding_constraints)

    portfolio = {
        "disruptions_handled": handled,
        "closed": sum(1 for e in shift if e.state == "closed"),
        "held_for_a_reason": sum(1 for e in shift if not e.feasible_plans),
        "blocked_then_resolved": sum(1 for e in shift if e.blocked_then_resolved),
        "total_delay_minutes": round(sum(e.delay_minutes for e in shift), 1),
        "total_cost_delta": round(sum(e.cost_delta for e in shift), 2),
        "total_overtime_minutes": round(sum(e.overtime_minutes for e in shift), 1),
        "options_refused": sum(e.rejected_plans for e in shift),
        "access_arrangements_checked": access_total,
        "access_arrangements_preserved": access_kept,
        "access_preservation_rate": (
            round(access_kept / access_total, 4) if access_total else 1.0
        ),
        "median_decision_ms": (
            round(latencies[len(latencies) // 2], 1) if latencies else 0.0
        ),
        "slowest_decision_ms": round(latencies[-1], 1) if latencies else 0.0,
        "by_family": dict(sorted(Counter(e.family for e in shift).items())),
    }

    return {
        # Passed through the executive redaction so any person-scoped key added
        # to this dictionary in future is dropped rather than published.
        "metrics": privacy.executive_summary(metrics),
        "prohibited_fields_found": privacy.check_no_prohibited_fields([metrics]),
        "portfolio": portfolio,
        # Which rules removed the most options across the shift. This is the
        # view's reason for existing: it converts "the day was hard" into a
        # ranked list of the things somebody could buy, hire or renegotiate.
        "constraint_pressure": [
            _pressure_row(cid, count) for cid, count in pressure.most_common(8)
        ],
        "timeline": [
            {
                "scenario_id": e.scenario_id,
                "title": e.title,
                "family": e.family,
                "severity": e.severity,
                "state": e.state,
                "feasible_plans": e.feasible_plans,
                "rejected_plans": e.rejected_plans,
                "delay_minutes": e.delay_minutes,
                "cost_delta": e.cost_delta,
                "access": f"{e.access_preserved}/{e.access_total}",
                "ready": e.verification_ready,
                "decision_ms": round(e.decision_ms, 1),
                "at": _dt(e.started_at),
            }
            for e in reversed(shift)
        ],
    }


@app.get("/api/replay")
def replay() -> dict[str, Any]:
    """§14.12 — decision replay, over the real event log."""
    s = session()
    check = governance.verify_replay(s.events, s.coordinator.views)
    lineage = governance.trace(s.events, s.source.envelope.event_id)
    chain_ok, problems = s.bus.verify_chain()
    return {
        "timeline": [
            {
                "sequence": e.envelope.sequence,
                "event_id": e.envelope.event_id,
                "event_type": e.envelope.event_type.value,
                "producer": e.envelope.producer,
                "actor": e.envelope.actor,
                "authority": e.envelope.authority.value,
                "classification": e.envelope.classification.value,
                # Both clocks. `event_time` is when the event was emitted and is
                # always present; `effective_time` is when the fact it records
                # became true in the world, and is set only where the two differ.
                # The replay view shows both, because a column of nulls is what
                # you get if you show only the second.
                "event_time": _dt(e.envelope.event_time),
                "effective_time": _dt(e.envelope.effective_time),
                "causation_id": e.envelope.causation_id,
                "plan_id": e.envelope.plan_id,
                "previous_hash": e.envelope.previous_hash,
                "summary": governance._summarise(e)[:160],  # noqa: SLF001
            }
            for e in s.events
        ],
        "lineage": {
            "root": lineage.root,
            "depth": lineage.depth,
            "nodes": len(lineage.nodes),
            "paths": lineage.path_summary()[:40],
        },
        "replay": {
            "identical": check.identical,
            "replayed_events": check.replayed_events,
            "differences": list(check.differences),
        },
        "hash_chain": {"intact": chain_ok, "problems": list(problems)},
        "steps": [
            {"state": st.state, "detail": st.detail, "elapsed_ms": st.elapsed_ms}
            for st in s.outcome.steps
        ],
    }


@app.get("/api/streams")
def streams() -> dict[str, Any]:
    """The Confluent plane: catalogue, contracts, dead letters, governance."""
    s = session()
    counts: dict[str, int] = {}
    for event in s.events:
        counts[event.envelope.event_type.value] = (
            counts.get(event.envelope.event_type.value, 0) + 1
        )
    return {
        "backbone": s.bus.name,
        "registry": s.bus.registry.name,
        "summary": governance.catalog_summary(),
        "catalog": [
            {
                "domain": c.domain, "topic": c.topic, "subject": c.subject,
                "owner": c.owner, "classification": c.classification,
                "compatibility": c.compatibility, "tags": list(c.tags),
                "description": c.description,
            }
            for c in governance.catalog()
        ],
        "event_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "dead_letters": [
            {"topic": d.topic, "reason": d.reason, "category": d.category}
            for d in s.bus.dead_letters
        ],
        "duplicates_suppressed": s.bus.duplicates_suppressed,
        "total_events": len(s.events),
    }


class NewDisruption(BaseModel):
    scenario_id: str = Field(default=STORM_SCENARIO.scenario_id)


@app.post("/api/disruptions")
def new_disruption(request: NewDisruption) -> dict[str, Any]:
    """Start a different disruption from the scenario library."""
    if request.scenario_id not in LIBRARY:
        raise HTTPException(404, f"unknown scenario {request.scenario_id}")
    s = reset(request.scenario_id)
    return {
        "scenario_id": s.scenario.scenario_id,
        "title": s.scenario.title,
        "state": s.outcome.disruption.state.value,
        "feasible_plans": len(s.outcome.plans),
        "rejected_plans": len(s.outcome.rejected),
        "events": len(s.events),
    }


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "production": w.PRODUCTION_ID}


@app.get("/api/about")
def about() -> dict[str, Any]:
    """What is running, so a judge never has to guess which plane is live."""
    s = session()
    return {
        "production": w.PRODUCTION_TITLE,
        "reasoning_plane": s.coordinator.reasoner.plane,
        "event_backbone": s.bus.name,
        "schema_registry": s.bus.registry.name,
        "constraints": len(CONSTRAINTS),
        "constraint_hash": constraint_set_hash(active_constraints()),
        "started_at": _dt(s.started_at),
        "scenario": s.scenario.scenario_id,
    }


if WEB.exists():
    app.mount("/static", StaticFiles(directory=str(WEB)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(WEB / "index.html"))


@app.exception_handler(HTTPException)
def _http_error(_request: Any, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)
