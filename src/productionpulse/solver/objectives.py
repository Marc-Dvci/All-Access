"""Measuring what a plan costs.

Every figure here is computed from the plan and the rate card, and every one can
be traced back to the assignments that produced it. `explain()` returns the
working, because a budget number a UPM cannot interrogate is a number they will
not act on.

Safety and approved access arrangements are deliberately absent. They are hard
constraints, so there is no weight that could trade them away and no line in the
objective vector where they could appear. That is a structural guarantee rather
than a policy: you cannot weight what is not in the vector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..contracts import PlanObjectives
from ..production import world as w
from .model import Assignment, CandidatePlan, SchedulingProblem


@dataclass
class CostLine:
    label: str
    amount: float
    basis: str


@dataclass
class ObjectiveBreakdown:
    objectives: PlanObjectives
    lines: list[CostLine] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)

    def explain(self) -> str:
        rows = [f"{line.label}: {line.amount:,.0f} ({line.basis})" for line in self.lines]
        return "; ".join(rows)


def _minutes(a: datetime, b: datetime) -> float:
    return max(0.0, (b - a).total_seconds() / 60.0)


def _baseline_index(problem: SchedulingProblem) -> dict[str, Assignment]:
    return {a.scene_id: a for a in problem.baseline}


def compute(plan: CandidatePlan, problem: SchedulingProblem) -> ObjectiveBreakdown:
    """Score a plan against the published day."""
    base = _baseline_index(problem)
    lines: list[CostLine] = []
    assumptions: list[str] = []

    # -- delay: work that does not happen tonight -------------------------
    lost_minutes = 0.0
    for scene_id in list(plan.deferred) + list(plan.moved_to_next_day):
        req = problem.requirements.get(scene_id)
        if req is not None:
            lost_minutes += req.shoot_minutes
    # Scenes that slip later in the same day also cost, but only by how much
    # they slip beyond the published finish.
    baseline_wrap = max((a.end for a in problem.baseline), default=None)
    plan_wrap = plan.wrap_time()
    slip = 0.0
    if baseline_wrap and plan_wrap and plan_wrap.date() == baseline_wrap.date():
        slip = _minutes(baseline_wrap, plan_wrap)
    delay_minutes = lost_minutes + slip
    if lost_minutes:
        lines.append(CostLine("deferred shooting time", lost_minutes,
                              f"{len(plan.deferred) + len(plan.moved_to_next_day)} scene(s)"))

    # -- overtime ----------------------------------------------------------
    policy = w.POLICIES["working_hours"]
    standard = float(policy["max_crew_day_minutes"])  # type: ignore[arg-type]
    overtime_minutes = 0.0
    overtime_cost = 0.0
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        if not rows:
            continue
        by_day: dict[object, list[Assignment]] = {}
        for a in rows:
            by_day.setdefault(a.end.date(), []).append(a)
        for day_rows in by_day.values():
            call = min((a.crew_call or a.setup_start) for a in day_rows)
            wrap = max(a.end for a in day_rows)
            span = _minutes(call, wrap)
            if span > standard:
                over = span - standard
                overtime_minutes += over
                heads = w.head_count(unit.unit_id)
                rate = sum(c.hourly_rate for c in w.crew_for_unit(unit.unit_id)) / max(heads, 1)
                cost = (over / 60.0) * rate * heads * w.RATE_CARD["crew_overtime_multiplier"]
                overtime_cost += cost
                lines.append(CostLine(
                    f"{unit.name} crew overtime", cost,
                    f"{over:.0f} min over {standard:.0f}, {heads} crew at "
                    f"{rate:.0f}/h x {w.RATE_CARD['crew_overtime_multiplier']}",
                ))

    # Cast overtime, per performer, per calendar day.
    #
    # Comparing a performer's latest finish across the whole plan against their
    # latest finish in the baseline charges a full twenty-four hours of overtime
    # for every scene deferred to tomorrow. Work moved to another day is a
    # different day's work: its cost is delay and changed assignments, both of
    # which are counted elsewhere. Only finishing later *on a day they were
    # already working* is overtime.
    for performer in w.PERFORMERS:
        rows = [a for a in plan.assignments if performer.performer_id in a.cast_calls]
        baseline_rows = [a for a in problem.baseline if performer.performer_id in a.cast_calls]
        if not rows or not baseline_rows or not performer.overtime_rate:
            continue
        baseline_by_day: dict[object, datetime] = {}
        for a in baseline_rows:
            day = a.end.date()
            baseline_by_day[day] = max(baseline_by_day.get(day, a.end), a.end)
        plan_by_day: dict[object, datetime] = {}
        for a in rows:
            day = a.end.date()
            plan_by_day[day] = max(plan_by_day.get(day, a.end), a.end)
        for day, actual_wrap in plan_by_day.items():
            planned_wrap = baseline_by_day.get(day)
            if planned_wrap is None or actual_wrap <= planned_wrap:
                continue
            over = _minutes(planned_wrap, actual_wrap)
            cost = (over / 60.0) * performer.overtime_rate
            overtime_cost += cost
            overtime_minutes += over
            lines.append(CostLine(
                f"{performer.name} overtime", cost,
                f"{over:.0f} min past {planned_wrap:%H:%M} on {planned_wrap:%d %b} "
                f"at {performer.overtime_rate:.0f}/h",
            ))

    # -- travel and company moves -----------------------------------------
    travel_minutes = 0.0
    company_moves = 0
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        for a, b in zip(rows, rows[1:]):
            if a.location_id != b.location_id:
                travel_minutes += w.travel_minutes(a.location_id, b.location_id)
                company_moves += 1
    move_cost = company_moves * w.RATE_CARD["company_move_fixed"]
    if company_moves:
        lines.append(CostLine("company moves", move_cost,
                              f"{company_moves} move(s) at "
                              f"{w.RATE_CARD['company_move_fixed']:,.0f} each"))

    # A base move is a bigger deal than a company move: the trucks, the tent,
    # catering and every support resource go with it.
    base_move_cost = 0.0
    for unit_id, new_base in plan.unit_bases.items():
        original = next((u.base_location for u in w.UNITS if u.unit_id == unit_id), None)
        if original and new_base != original:
            base_move_cost += w.RATE_CARD["company_move_fixed"] * 2.5
            lines.append(CostLine(
                "unit base relocation", w.RATE_CARD["company_move_fixed"] * 2.5,
                f"{unit_id} base moved to {new_base}",
            ))

    # -- interpreter and support service changes --------------------------
    service_cost = 0.0
    for booking_id, start, end in plan.interpreter_extensions:
        booking = w.BOOKINGS_BY_ID.get(booking_id)
        if booking is None:
            continue
        hours = _minutes(start, end) / 60.0
        cost = hours * booking.hourly_rate * 1.5
        service_cost += cost
        lines.append(CostLine(
            "interpreter cover", cost,
            f"{hours:.1f} h at {booking.hourly_rate:.0f}/h x 1.5 out-of-hours",
        ))
    for resource_id, destination in plan.support_moves:
        service_cost += 120.0
        lines.append(CostLine("support resource relocation", 120.0,
                              f"{resource_id} to {destination}"))

    # -- idle crew ---------------------------------------------------------
    idle_minutes = 0.0
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        for a, b in zip(rows, rows[1:]):
            gap = _minutes(a.end, b.setup_start)
            need = w.travel_minutes(a.location_id, b.location_id)
            idle = max(0.0, gap - need)
            idle_minutes += idle
    idle_cost = 0.0
    if idle_minutes:
        heads = sum(w.head_count(u.unit_id) for u in w.UNITS) / max(len(w.UNITS), 1)
        idle_cost = (idle_minutes / 60.0) * 45.0 * heads * 0.35
        lines.append(CostLine("idle crew", idle_cost,
                              f"{idle_minutes:.0f} min at reduced charge"))

    # -- cancellation and deferral costs ----------------------------------
    cancellation = 0.0
    baseline_locations = {a.location_id for a in problem.baseline}
    dropped_locations = baseline_locations - plan.locations()
    for loc_id in dropped_locations:
        cancellation += w.RATE_CARD["location_cancellation_fee"]
        loc = w.LOCATIONS_BY_ID.get(loc_id)
        lines.append(CostLine("location cancellation", w.RATE_CARD["location_cancellation_fee"],
                              loc.name if loc else loc_id))

    # -- changed assignments and communication burden ---------------------
    changed = 0
    for a in plan.assignments:
        original = base.get(a.scene_id)
        if original is None:
            changed += 1
        elif (original.start != a.start or original.location_id != a.location_id
              or original.unit_id != a.unit_id):
            changed += 1
    changed += len(plan.deferred) + len(plan.moved_to_next_day)

    people_affected: set[str] = set()
    for a in plan.assignments:
        people_affected.update(a.cast_calls)
        for crew in w.crew_for_unit(a.unit_id):
            people_affected.add(crew.crew_id)
    for scene_id in plan.deferred + plan.moved_to_next_day:
        original = base.get(scene_id)
        if original:
            people_affected.update(original.cast_calls)
    communication_burden = float(len(people_affected)) if changed else 0.0

    # -- exposure and risk -------------------------------------------------
    weather_exposure = 0.0
    for a in plan.assignments:
        req = problem.requirements.get(a.scene_id)
        loc = w.LOCATIONS_BY_ID.get(a.location_id)
        if req is None or loc is None or not (req.exterior or loc.weather_exposed):
            continue
        cursor = a.start
        while cursor < a.end:
            win = w.weather_at(cursor, problem.weather)
            if win is not None:
                weather_exposure += (
                    win.precipitation_probability * 10.0 + max(0.0, win.wind_kph - 20.0) * 0.4
                ) * (15.0 / 60.0)
            cursor += timedelta(minutes=15)

    setup_complexity = sum(
        problem.requirements[a.scene_id].setup_minutes
        for a in plan.assignments if a.scene_id in problem.requirements
    ) / 60.0

    continuity_risk = 0.0
    for scene_id in plan.deferred + plan.moved_to_next_day:
        req = problem.requirements.get(scene_id)
        if req is not None:
            # Deferring a scene others depend on is riskier than deferring a leaf.
            continuity_risk += 4.0 if req.story_day >= 3 else 2.0

    operational_risk = (
        company_moves * 2.0
        + len(plan.unit_bases) * 6.0
        + len(plan.interpreter_extensions) * 3.0
        + len(plan.support_moves) * 2.5
        + (4.0 if overtime_minutes > 0 else 0.0)
    )

    total_cost = (
        overtime_cost + move_cost + base_move_cost + service_cost + idle_cost + cancellation
    )

    assumptions.append(
        "Overtime is charged against the configured standard day and each performer's "
        "published finish, not against actual hours worked, which are not known until wrap."
    )
    assumptions.append(
        "Location cancellation fees assume the published rate card; a location released "
        "before its notice period may cost less."
    )
    if plan.interpreter_extensions:
        assumptions.append(
            "Interpreter cover is charged at 1.5x for out-of-hours booking, per the rate card."
        )

    objectives = PlanObjectives(
        delay_minutes=round(delay_minutes, 1),
        cost_delta=round(total_cost, 2),
        overtime_minutes=round(overtime_minutes, 1),
        idle_crew_minutes=round(idle_minutes, 1),
        travel_minutes=round(travel_minutes, 1),
        setup_complexity=round(setup_complexity, 2),
        weather_exposure=round(weather_exposure, 2),
        continuity_risk=round(continuity_risk, 2),
        operational_risk=round(operational_risk, 2),
        communication_burden=round(communication_burden, 1),
        changed_assignments=changed,
    )
    return ObjectiveBreakdown(objectives=objectives, lines=lines, assumptions=assumptions)


def dominates(a: PlanObjectives, b: PlanObjectives) -> bool:
    """True if `a` is at least as good as `b` everywhere and better somewhere.

    All objectives are minimised, so this is plain Pareto dominance.
    """
    va, vb = a.vector(), b.vector()
    return all(x <= y for x, y in zip(va, vb)) and any(x < y for x, y in zip(va, vb))


def pareto_front(items: list[tuple[str, PlanObjectives]]) -> list[str]:
    """Ids of the non-dominated plans."""
    front: list[str] = []
    for plan_id, objectives in items:
        if not any(dominates(other, objectives)
                   for other_id, other in items if other_id != plan_id):
            front.append(plan_id)
    return front


def scalarize(objectives: PlanObjectives, weights: dict[str, float]) -> float:
    """A single ranking score, for ordering the presentation only.

    The Pareto front is the honest comparison; this exists so the plan list has a
    stable default order. The weights are published in the constraint registry so
    a UPM can see what the ordering is assuming.
    """
    total = 0.0
    for label, value in zip(PlanObjectives.labels(), objectives.vector()):
        total += weights.get(label, 0.0) * value
    return round(total, 3)
