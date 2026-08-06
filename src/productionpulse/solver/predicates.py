"""Constraint predicates: the functions that decide whether a plan is feasible.

Every `ConstraintRecord` in the registry names one of these by string. The
registry validates at import that every name resolves, so a constraint cannot
exist as documentation without an implementation — that check is what keeps the
registry honest as the system grows.

Each predicate takes a `CandidatePlan` and a `SchedulingProblem` and returns the
violations it finds, as `ConstraintViolation` records carrying the specific
measurement that failed. "The doorway is 760 mm where 850 mm is required" is
actionable; "accessibility concern" is not, and the difference is entirely in
what these functions bother to report.

No predicate consults a language model, and none of them is allowed to be
approximately right. A predicate that cannot decide must report a violation
rather than pass — failing closed is the only safe default when the subject is
a person's approved access arrangement or a safety control.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from ..contracts import ConstraintDomain, ConstraintKind, ConstraintViolation
from ..production import spatial as sp
from ..production import world as w
from .model import Assignment, CandidatePlan, SchedulingProblem

# Registry of predicate name -> function, populated by the decorator below.
PREDICATES: dict[str, object] = {}


def predicate(name: str):
    def wrap(fn):
        PREDICATES[name] = fn
        fn.predicate_name = name
        return fn
    return wrap


def _v(
    constraint_id: str,
    domain: ConstraintDomain,
    subject: str,
    message: str,
    evidence: str,
    *,
    kind: ConstraintKind = ConstraintKind.HARD,
    severity: str = "blocking",
    **detail: object,
) -> ConstraintViolation:
    return ConstraintViolation(
        constraint_id=constraint_id,
        domain=domain,
        kind=kind,
        subject_id=subject,
        message=message,
        evidence=evidence,
        severity=severity,  # type: ignore[arg-type]
        detail=detail,
    )


def _minutes(a: datetime, b: datetime) -> float:
    return (b - a).total_seconds() / 60.0


def _day_offset(assignment: Assignment) -> timedelta:
    """How many days after the shooting day an assignment falls.

    Daily availability windows — a driver's shift, a location's opening hours, a
    supervisor's roster — repeat each day. They are stored as times on the
    shooting day, so anything scheduled onto a later day has to compare against
    the window shifted by that many days. Without this, every scene deferred to
    tomorrow reports that tomorrow's crew are unavailable, which is both wrong
    and exactly the kind of wrong that looks like diligence.
    """
    return timedelta(days=(assignment.start.date() - w.SHOOT_DATE).days)


def _covers(window_start: datetime, window_end: datetime,
            need_start: datetime, need_end: datetime,
            offset: timedelta) -> bool:
    return (window_start + offset) <= need_start and need_end <= (window_end + offset)


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------


@predicate("safety.weather_threshold")
def weather_threshold(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Exterior work is prohibited when configured weather thresholds are crossed.

    Evaluated across the whole scene, not just its start: a scene that begins in
    a 40 kph window and runs into a 62 kph one is not a compliant scene.
    """
    policy = w.POLICIES["safety"]
    max_wind = float(policy["max_wind_speed_kph_exterior"])  # type: ignore[arg-type]
    prohibited = set(policy["prohibited_conditions"])  # type: ignore[arg-type]
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        req = problem.requirements.get(a.scene_id)
        loc = w.LOCATIONS_BY_ID.get(a.location_id)
        if req is None or loc is None:
            continue
        if not (req.exterior or loc.weather_exposed):
            continue
        cursor = a.start
        while cursor < a.end:
            win = w.weather_at(cursor, problem.weather)
            if win is not None:
                if win.condition in prohibited:
                    out.append(_v(
                        "C-SAFE-001", ConstraintDomain.SAFETY, a.scene_id,
                        f"{a.scene_id} is an exterior at {loc.name} during a "
                        f"{win.condition} window, which the safety plan prohibits",
                        f"weather window {win.start:%H:%M}-{win.end:%H:%M}: {win.condition}",
                        condition=win.condition, at=cursor.isoformat(),
                    ))
                    break
                if win.wind_kph > max_wind:
                    out.append(_v(
                        "C-SAFE-001", ConstraintDomain.SAFETY, a.scene_id,
                        f"{a.scene_id} is an exterior at {loc.name} in {win.wind_kph:.0f} kph "
                        f"wind, above the {max_wind:.0f} kph configured limit",
                        f"weather window {win.start:%H:%M}-{win.end:%H:%M}",
                        wind_kph=win.wind_kph, limit=max_wind,
                    ))
                    break
            cursor += timedelta(minutes=15)
    return out


@predicate("safety.marine_supervision")
def marine_supervision(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """On-water work requires the marine safety supervisor to be present."""
    out: list[ConstraintViolation] = []
    supervisor = w.CREW_BY_ID["CREW-MARINE"]
    for a in plan.assignments:
        req = problem.requirements.get(a.scene_id)
        if req is None or "marine_safety_supervision" not in req.special_requirements:
            continue
        if not problem.is_available("CREW-MARINE"):
            out.append(_v(
                "C-SAFE-002", ConstraintDomain.SAFETY, a.scene_id,
                f"{a.scene_id} requires marine safety supervision and "
                f"{supervisor.name} is unavailable",
                problem.reason_unavailable("CREW-MARINE"),
            ))
        elif not _covers(supervisor.call_time, supervisor.wrap_time,
                         a.setup_start, a.end, _day_offset(a)):
            out.append(_v(
                "C-SAFE-002", ConstraintDomain.SAFETY, a.scene_id,
                f"{a.scene_id} runs {a.setup_start:%H:%M}-{a.end:%H:%M}, outside the marine "
                f"safety supervisor's window {supervisor.call_time:%H:%M}-"
                f"{supervisor.wrap_time:%H:%M}",
                "CREW-MARINE availability",
            ))
    return out


@predicate("safety.briefing_current")
def briefing_current(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """A location the crew has not been briefed on requires a new briefing.

    This is the conditional constraint from §6.3: change the location, and a
    briefing becomes required. The plan discharges it by carrying a briefing
    note; a plan that quietly moves to a new location without one is infeasible.
    """
    briefed = {a.location_id for a in problem.baseline}
    # Note form is `briefing:<location_id> formats=a,b,c` — take the location id
    # only. Comparing the whole remainder against a location id never matches,
    # which silently rejected every plan that did include a briefing.
    issued = {
        n.split(":", 1)[1].strip().split()[0]
        for n in plan.notes
        if n.startswith("briefing:") and len(n.split(":", 1)) > 1 and n.split(":", 1)[1].strip()
    }
    out: list[ConstraintViolation] = []
    for loc_id in sorted(plan.locations() - briefed):
        if loc_id in issued:
            continue
        loc = w.LOCATIONS_BY_ID.get(loc_id)
        out.append(_v(
            "C-SAFE-003", ConstraintDomain.SAFETY, loc_id,
            f"The plan moves work to {loc.name if loc else loc_id}, which the issued safety "
            "briefing does not cover, and no revised briefing is included",
            "POLICIES['safety'].briefing_required_on_location_change",
        ))
    return out


@predicate("safety.egress")
def egress(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Two independent emergency egress routes from every working position."""
    out: list[ConstraintViolation] = []
    for loc_id in sorted(plan.locations()):
        assessment = sp.assess_location_access(loc_id)
        if not assessment.get("modelled"):
            continue
        count = int(assessment.get("egress_route_count", 0))
        loc = w.LOCATIONS_BY_ID.get(loc_id)
        declared = loc.egress_routes if loc else 0
        if min(count, declared) < 2 and loc_id != "LOC-OPEN-WATER":
            out.append(_v(
                "C-SAFE-004", ConstraintDomain.EGRESS, loc_id,
                f"{loc.name if loc else loc_id} has {min(count, declared)} independent egress "
                "route(s); the safety plan requires two",
                f"spatial twin: {count} distinct routes; location record: {declared}",
                severity="at_risk",
            ))
    return out


# ---------------------------------------------------------------------------
# Working hours, rest, child performers
# ---------------------------------------------------------------------------


@predicate("hours.crew_day_length")
def crew_day_length(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    policy = w.POLICIES["working_hours"]
    limit = float(policy["max_crew_day_minutes"])  # type: ignore[arg-type]
    hard_limit = float(policy["max_crew_day_with_approval_minutes"])  # type: ignore[arg-type]
    out: list[ConstraintViolation] = []
    for unit in w.UNITS:
        all_rows = plan.by_unit(unit.unit_id)
        if not all_rows:
            continue
        # Per calendar day. A plan that moves a scene to tomorrow night creates
        # two working days, not one thirty-three-hour day — measuring the span
        # from today's call to tomorrow's wrap makes every deferral look like a
        # gross working-hours breach, which is both wrong and the exact opposite
        # of the answer the production needs.
        by_day: dict[object, list] = {}
        for a in all_rows:
            by_day.setdefault(a.start.date(), []).append(a)
        for rows in by_day.values():
            calls = [a.crew_call for a in rows if a.crew_call is not None]
            call = min(calls) if calls else min(a.setup_start for a in rows)
            wrap = max(a.end for a in rows)
            span = _minutes(call, wrap)
            if span > hard_limit:
                out.append(_v(
                    "C-HOUR-001", ConstraintDomain.WORKING_HOURS, unit.unit_id,
                    f"{unit.name} would work {span:.0f} min on {call:%d %b} "
                    f"({call:%H:%M}-{wrap:%H:%M}), beyond the {hard_limit:.0f} min maximum "
                    "even with approval",
                    str(policy["source"]),
                    span=span, limit=hard_limit,
                ))
            elif span > limit:
                out.append(_v(
                    "C-HOUR-001", ConstraintDomain.WORKING_HOURS, unit.unit_id,
                    f"{unit.name} would work {span:.0f} min on {call:%d %b} "
                    f"({call:%H:%M}-{wrap:%H:%M}), beyond the {limit:.0f} min standard day; "
                    "UPM approval required",
                    str(policy["source"]),
                    kind=ConstraintKind.APPROVAL, severity="at_risk",
                    span=span, limit=limit, requires_approval="unit_production_manager",
                ))
    return out


@predicate("hours.turnaround")
def turnaround(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Minimum rest between wrap and the next call, including next-day calls."""
    policy = w.POLICIES["working_hours"]
    minimum = float(policy["minimum_turnaround_hours"]) * 60.0  # type: ignore[arg-type]
    out: list[ConstraintViolation] = []
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        if not rows:
            continue
        today = [a for a in rows if a.end.date() == w.SHOOT_DATE]
        tomorrow = [a for a in rows if a.end.date() > w.SHOOT_DATE]
        if not today or not tomorrow:
            continue
        wrap = max(a.end for a in today)
        next_call = min((a.crew_call or a.setup_start) for a in tomorrow)
        gap = _minutes(wrap, next_call)
        if gap < minimum:
            out.append(_v(
                "C-HOUR-002", ConstraintDomain.REST, unit.unit_id,
                f"{unit.name} wraps at {wrap:%H:%M} and would be called back at "
                f"{next_call:%H:%M} the following day — {gap / 60:.1f} h turnaround against a "
                f"{minimum / 60:.0f} h minimum",
                str(policy["source"]),
                gap_hours=gap / 60.0, minimum_hours=minimum / 60.0,
            ))
    return out


@predicate("hours.child_performer")
def child_performer(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Configured child-performer limits: window, total on set, and chaperone."""
    policy = w.POLICIES["child_performer"]
    earliest: datetime = policy["earliest_call"]  # type: ignore[assignment]
    latest: datetime = policy["latest_wrap"]  # type: ignore[assignment]
    max_total = float(policy["max_on_set_minutes"])  # type: ignore[arg-type]
    out: list[ConstraintViolation] = []

    for performer in w.PERFORMERS:
        if not performer.minor:
            continue
        rows = [a for a in plan.assignments if performer.performer_id in a.cast_calls]
        if not rows:
            continue
        first_call = min(a.cast_calls[performer.performer_id] for a in rows)
        last_wrap = max(a.end for a in rows)

        # The window is per calendar day: a scene moved to the following morning
        # is compared against that morning's window, not the original day's.
        for a in rows:
            call = a.cast_calls[performer.performer_id]
            day_offset = (call.date() - w.SHOOT_DATE).days
            day_earliest = earliest + timedelta(days=day_offset)
            day_latest = latest + timedelta(days=day_offset)
            if call < day_earliest:
                out.append(_v(
                    "C-CHILD-001", ConstraintDomain.CHILD_PERFORMER, performer.performer_id,
                    f"{performer.name} would be called at {call:%H:%M} on "
                    f"{call:%d %b}, before the configured earliest call "
                    f"{day_earliest:%H:%M}",
                    str(policy["source"]), scene=a.scene_id,
                ))
            if a.end > day_latest:
                out.append(_v(
                    "C-CHILD-001", ConstraintDomain.CHILD_PERFORMER, performer.performer_id,
                    f"{performer.name} would work until {a.end:%H:%M} on {a.end:%d %b} for "
                    f"{a.scene_id}, past the configured latest wrap {day_latest:%H:%M}",
                    str(policy["source"]), scene=a.scene_id,
                ))

        total = _minutes(first_call, last_wrap)
        if total > max_total:
            out.append(_v(
                "C-CHILD-002", ConstraintDomain.CHILD_PERFORMER, performer.performer_id,
                f"{performer.name} would be on set {total:.0f} min "
                f"({first_call:%H:%M}-{last_wrap:%H:%M}) against a configured "
                f"{max_total:.0f} min maximum",
                str(policy["source"]), total=total, limit=max_total,
            ))

        if policy["chaperone_required"]:
            chaperone = w.CREW_BY_ID["CREW-CHAP"]
            chap_offset = timedelta(days=(first_call.date() - w.SHOOT_DATE).days)
            if not _covers(chaperone.call_time, chaperone.wrap_time,
                           first_call, last_wrap, chap_offset):
                out.append(_v(
                    "C-CHILD-003", ConstraintDomain.CHILD_PERFORMER, performer.performer_id,
                    f"{performer.name} is called {first_call:%H:%M}-{last_wrap:%H:%M} but the "
                    f"chaperone is available {chaperone.call_time:%H:%M}-"
                    f"{chaperone.wrap_time:%H:%M}",
                    "POLICIES['child_performer'].chaperone_required",
                ))
    return out


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


@predicate("resource.exclusivity")
def resource_exclusivity(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """An exclusive resource cannot be in two places at once.

    Includes prep time. A lighting package that needs 110 minutes of prep is
    genuinely unavailable during those 110 minutes, and a plan that ignores prep
    is a plan that discovers at 20:00 that the truck has not been unloaded.
    """
    out: list[ConstraintViolation] = []
    raw: dict[str, list[Assignment]] = {}
    for a in plan.assignments:
        for eq_id in a.equipment_ids:
            eq = w.EQUIPMENT_BY_ID.get(eq_id)
            if eq is None or not eq.exclusive:
                continue
            raw.setdefault(eq_id, []).append(a)

    for eq_id, rows in raw.items():
        eq = w.EQUIPMENT_BY_ID[eq_id]
        rows.sort(key=lambda a: a.setup_start)
        spans: list[tuple[datetime, datetime, str, bool]] = []
        for index, a in enumerate(rows):
            # Prep is the once-a-day cost of building the package out of its
            # cases. It is owed before first use and not again: moving a built
            # camera to the next location costs travel and scene setup, both of
            # which are modelled separately. Charging prep on every move
            # double-counts it and manufactures conflicts with the scene that
            # just wrapped.
            needs_prep = index == 0
            start = a.setup_start - timedelta(minutes=eq.prep_minutes if needs_prep else 0)
            spans.append((start, a.end, a.scene_id, needs_prep))
        for i, (s1, e1, sc1, p1) in enumerate(spans):
            for s2, e2, sc2, p2 in spans[i + 1:]:
                if s1 < e2 and s2 < e1:
                    prep_note = (
                        f" (includes {eq.prep_minutes} min prep)" if (p1 or p2) else ""
                    )
                    out.append(_v(
                        "C-RES-001", ConstraintDomain.RESOURCE, eq_id,
                        f"{eq.name} is required by {sc1} and {sc2} at the same time",
                        f"{sc1} {s1:%H:%M}-{e1:%H:%M} overlaps {sc2} {s2:%H:%M}-{e2:%H:%M}"
                        + prep_note,
                        equipment=eq_id, scenes=[sc1, sc2],
                    ))
    return out


@predicate("resource.availability")
def resource_availability(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Equipment must exist, be available, and be within its window."""
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        for eq_id in a.equipment_ids:
            eq = w.EQUIPMENT_BY_ID.get(eq_id)
            if eq is None:
                out.append(_v("C-RES-002", ConstraintDomain.EQUIPMENT, eq_id,
                              f"{a.scene_id} requires unknown equipment {eq_id}", ""))
                continue
            if not problem.is_available(eq_id):
                out.append(_v(
                    "C-RES-002", ConstraintDomain.EQUIPMENT, eq_id,
                    f"{eq.name} is required by {a.scene_id} but is unavailable",
                    problem.reason_unavailable(eq_id),
                    equipment=eq_id, scene=a.scene_id,
                ))
                continue
            prep_start = a.setup_start - timedelta(minutes=eq.prep_minutes)
            if not _covers(eq.available_from, eq.available_to, prep_start, a.end,
                           _day_offset(a)):
                out.append(_v(
                    "C-RES-002", ConstraintDomain.EQUIPMENT, eq_id,
                    f"{eq.name} is needed from {prep_start:%H:%M} to {a.end:%H:%M} for "
                    f"{a.scene_id} but is available "
                    f"{eq.available_from:%H:%M}-{eq.available_to:%H:%M}",
                    "equipment availability window",
                    equipment=eq_id, scene=a.scene_id,
                ))
    return out


@predicate("resource.certified_operator")
def certified_operator(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Equipment needing a certification needs a certified, available operator."""
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        for eq_id in a.equipment_ids:
            eq = w.EQUIPMENT_BY_ID.get(eq_id)
            if eq is None or not eq.requires_certification:
                continue
            for cert in eq.requires_certification:
                offset = _day_offset(a)
                holders = [
                    c for c in w.CREW
                    if cert in c.certifications
                    and problem.is_available(c.crew_id)
                    and _covers(c.call_time, c.wrap_time, a.setup_start, a.end, offset)
                ]
                if not holders:
                    out.append(_v(
                        "C-RES-003", ConstraintDomain.RESOURCE, eq_id,
                        f"{eq.name} on {a.scene_id} requires a '{cert}' certified operator and "
                        f"none is available {a.setup_start:%H:%M}-{a.end:%H:%M}",
                        f"certification: {cert}",
                        equipment=eq_id, certification=cert,
                    ))
    return out


@predicate("resource.performer_availability")
def performer_availability(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        req = problem.requirements.get(a.scene_id)
        if req is None:
            continue
        for pid in req.performer_ids:
            performer = w.PERFORMERS_BY_ID.get(pid)
            if performer is None:
                continue
            if not problem.is_available(pid):
                out.append(_v(
                    "C-RES-004", ConstraintDomain.AVAILABILITY, pid,
                    f"{performer.name} is required by {a.scene_id} but is unavailable",
                    problem.reason_unavailable(pid), scene=a.scene_id,
                ))
                continue
            call = a.cast_calls.get(pid, a.start - timedelta(minutes=performer.prep_minutes))
            offset = _day_offset(a)
            if not _covers(performer.available_from, performer.available_to,
                           call, a.end, offset):
                out.append(_v(
                    "C-RES-004", ConstraintDomain.AVAILABILITY, pid,
                    f"{performer.name} is needed {call:%H:%M}-{a.end:%H:%M} for {a.scene_id} "
                    f"but is available {performer.available_from:%H:%M}-"
                    f"{performer.available_to:%H:%M}",
                    "performer availability", scene=a.scene_id,
                ))
            if _minutes(call, a.start) < performer.prep_minutes:
                out.append(_v(
                    "C-RES-005", ConstraintDomain.AVAILABILITY, pid,
                    f"{performer.name} has {_minutes(call, a.start):.0f} min before "
                    f"{a.scene_id} against a {performer.prep_minutes} min prep requirement",
                    "prep allowance", severity="at_risk", kind=ConstraintKind.SOFT,
                ))
    return out


@predicate("resource.performer_exclusivity")
def performer_exclusivity(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """A performer cannot shoot two scenes at once, or teleport between them."""
    out: list[ConstraintViolation] = []
    by_person: dict[str, list[Assignment]] = {}
    for a in plan.assignments:
        req = problem.requirements.get(a.scene_id)
        if req is None:
            continue
        for pid in req.performer_ids:
            by_person.setdefault(pid, []).append(a)
    for pid, rows in by_person.items():
        performer = w.PERFORMERS_BY_ID.get(pid)
        rows.sort(key=lambda a: a.start)
        for a, b in zip(rows, rows[1:]):
            if a.shoot_overlaps(b):
                out.append(_v(
                    "C-RES-006", ConstraintDomain.AVAILABILITY, pid,
                    f"{performer.name if performer else pid} is required by {a.scene_id} and "
                    f"{b.scene_id} at the same time",
                    f"{a.scene_id} {a.start:%H:%M}-{a.end:%H:%M}, "
                    f"{b.scene_id} {b.start:%H:%M}-{b.end:%H:%M}",
                ))
            elif a.location_id != b.location_id:
                need = w.travel_minutes(a.location_id, b.location_id)
                gap = _minutes(a.end, b.start)
                if gap < need:
                    out.append(_v(
                        "C-RES-006", ConstraintDomain.AVAILABILITY, pid,
                        f"{performer.name if performer else pid} cannot reach {b.scene_id} "
                        f"from {a.scene_id}: {need} min travel, {gap:.0f} min available",
                        f"{a.location_id} -> {b.location_id}",
                    ))
    return out


@predicate("resource.critical_crew")
def critical_crew(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Critical crew must be available for the whole of their unit's work."""
    out: list[ConstraintViolation] = []
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        if not rows:
            continue
        for crew in w.CREW:
            if not crew.critical or unit.unit_id not in crew.units:
                continue
            if not problem.is_available(crew.crew_id):
                out.append(_v(
                    "C-RES-007", ConstraintDomain.AVAILABILITY, crew.crew_id,
                    f"{crew.name} ({crew.role_title}) is critical for {unit.name} "
                    "and is unavailable",
                    problem.reason_unavailable(crew.crew_id), unit=unit.unit_id,
                ))
    return out


# ---------------------------------------------------------------------------
# Locations and permits
# ---------------------------------------------------------------------------


@predicate("location.availability")
def location_availability(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        loc = w.LOCATIONS_BY_ID.get(a.location_id)
        if loc is None:
            out.append(_v("C-LOC-001", ConstraintDomain.LOCATION, a.location_id,
                          f"{a.scene_id} is placed at unknown location {a.location_id}", ""))
            continue
        if not problem.is_available(a.location_id):
            out.append(_v(
                "C-LOC-001", ConstraintDomain.LOCATION, a.location_id,
                f"{loc.name} is closed but {a.scene_id} is scheduled there",
                problem.reason_unavailable(a.location_id), scene=a.scene_id,
            ))
            continue
        # Availability windows repeat daily: a location open 06:00-23:00 is open
        # 06:00-23:00 tomorrow too.
        offset = (a.setup_start.date() - w.SHOOT_DATE).days
        if loc.available_from and a.setup_start < loc.available_from + timedelta(days=offset):
            out.append(_v(
                "C-LOC-001", ConstraintDomain.LOCATION, a.location_id,
                f"{a.scene_id} sets up at {a.setup_start:%H:%M} but {loc.name} opens at "
                f"{loc.available_from:%H:%M}",
                "location availability", scene=a.scene_id,
            ))
        end_offset = (a.end.date() - w.SHOOT_DATE).days
        if loc.available_to and a.end > loc.available_to + timedelta(days=end_offset):
            out.append(_v(
                "C-LOC-001", ConstraintDomain.LOCATION, a.location_id,
                f"{a.scene_id} runs to {a.end:%H:%M} but {loc.name} closes at "
                f"{loc.available_to:%H:%M}",
                "location availability", scene=a.scene_id,
            ))
        if loc.noise_curfew and a.end > loc.noise_curfew + timedelta(days=end_offset):
            out.append(_v(
                "C-LOC-002", ConstraintDomain.LOCATION, a.location_id,
                f"{a.scene_id} runs to {a.end:%H:%M}, past the {loc.noise_curfew:%H:%M} "
                f"noise curfew at {loc.name}",
                "location noise curfew", severity="at_risk", kind=ConstraintKind.SOFT,
            ))
    return out


@predicate("location.capacity")
def location_capacity(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        loc = w.LOCATIONS_BY_ID.get(a.location_id)
        if loc is None:
            continue
        departments = {
            w.EQUIPMENT_BY_ID[e].department.value
            for e in a.equipment_ids if e in w.EQUIPMENT_BY_ID
        }
        party = 2 + 2 * len(departments)
        if party > loc.capacity_crew:
            out.append(_v(
                "C-LOC-003", ConstraintDomain.LOCATION, a.location_id,
                f"{a.scene_id} needs a {party}-person working party at {loc.name}, "
                f"which holds {loc.capacity_crew}",
                f"departments: {', '.join(sorted(departments))}",
                severity="at_risk", kind=ConstraintKind.SOFT,
            ))
    return out


@predicate("permit.validity")
def permit_validity(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Every permit a location needs must be valid and cover the working window."""
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        loc = w.LOCATIONS_BY_ID.get(a.location_id)
        if loc is None:
            continue
        offset = (a.setup_start.date() - w.SHOOT_DATE).days
        for permit_id in loc.permits:
            permit = w.PERMITS_BY_ID.get(permit_id)
            if permit is None:
                continue
            if not problem.is_available(permit_id) or permit.status != "valid":
                out.append(_v(
                    "C-PERM-001", ConstraintDomain.PERMIT, permit_id,
                    f"{permit.name} is required for {a.scene_id} at {loc.name} and is not valid",
                    problem.reason_unavailable(permit_id) or f"status: {permit.status}",
                    scene=a.scene_id,
                ))
                continue
            valid_from = permit.valid_from + timedelta(days=offset)
            valid_to = permit.valid_to + timedelta(days=offset)
            if a.setup_start < valid_from or a.end > valid_to:
                out.append(_v(
                    "C-PERM-001", ConstraintDomain.PERMIT, permit_id,
                    f"{permit.name} covers {valid_from:%H:%M}-{valid_to:%H:%M} but "
                    f"{a.scene_id} runs {a.setup_start:%H:%M}-{a.end:%H:%M}",
                    "permit validity window", scene=a.scene_id,
                ))
            if permit.prohibits_setup_after:
                cutoff = permit.prohibits_setup_after + timedelta(days=offset)
                if a.setup_start > cutoff:
                    out.append(_v(
                        "C-PERM-002", ConstraintDomain.PERMIT, permit_id,
                        f"{permit.name} prohibits setup after {cutoff:%H:%M}; {a.scene_id} "
                        f"would set up at {a.setup_start:%H:%M} at {loc.name}",
                        "; ".join(permit.conditions), scene=a.scene_id,
                    ))
            if permit.max_crew is not None:
                heads = w.head_count(a.unit_id)
                if heads > permit.max_crew:
                    out.append(_v(
                        "C-PERM-003", ConstraintDomain.PERMIT, permit_id,
                        f"{permit.name} allows {permit.max_crew} persons; {a.unit_id} has "
                        f"{heads}",
                        "permit condition", severity="at_risk",
                    ))
    return out


# ---------------------------------------------------------------------------
# Approved access arrangements — the constraints this project exists for
# ---------------------------------------------------------------------------


def _unit_base(assignment: Assignment, plan: CandidatePlan) -> str:
    """The base a unit is operating from while shooting an assignment.

    The base is where the trucks, the tent, the fridge and the quiet room are.
    It does not follow the camera around: a unit that shoots ninety minutes at a
    shopfront fifteen minutes away is still based where it was that morning.

    So the base is the unit's declared base, and it changes only when a plan
    explicitly moves it. That distinction matters a great deal here — it is
    precisely the boatshed plan's *explicit base move* that takes the refrigerated
    storage and the quiet room away from the people whose approved arrangements
    depend on them.
    """
    declared = plan.unit_bases.get(assignment.unit_id)
    if declared:
        return declared
    for unit in w.UNITS:
        if unit.unit_id == assignment.unit_id:
            return unit.base_location
    return assignment.location_id


def _person_working(plan: CandidatePlan, problem: SchedulingProblem,
                    person_id: str) -> list[Assignment]:
    """Assignments during which a given person is working.

    Cast are named per scene. Crew are matched by unit membership, which is the
    honest reading: if the unit is working, its critical crew are working.
    """
    if person_id in w.PERFORMERS_BY_ID:
        return [a for a in plan.assignments
                if person_id in (problem.requirements[a.scene_id].performer_ids
                                 if a.scene_id in problem.requirements else ())]
    crew = w.CREW_BY_ID.get(person_id)
    if crew is None:
        return []
    return [a for a in plan.assignments if a.unit_id in crew.units]


@predicate("access.step_free_route")
def step_free_route(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Every location a person with an approved step-free requirement works at
    must have a step-free route from arrival to working position.

    The failure message carries the measurement from the spatial twin, because
    a location manager can act on "the main door has a 140 mm cill" and cannot
    act on "not accessible".
    """
    out: list[ConstraintViolation] = []
    for req in w.ACCESS_REQUIREMENTS:
        if req.category != "mobility":
            continue
        for a in _person_working(plan, problem, req.person_id):
            assessment = sp.assess_location_access(a.location_id)
            if not assessment.get("modelled"):
                continue
            # Satisfied either by a step-free route to the working position or
            # by a surveyed step-free alternate position that the same job can
            # be done from.
            if assessment.get("step_free_satisfied"):
                continue
            loc = w.LOCATIONS_BY_ID.get(a.location_id)
            blockers = assessment.get("step_free_blockers") or []
            detail = blockers[0] if blockers else "no step-free route in the access survey"
            out.append(_v(
                "C-ACC-001", ConstraintDomain.ACCESS, req.requirement_id,
                f"{loc.name if loc else a.location_id} has no step-free route from arrival to "
                f"the working position and no surveyed step-free alternate position, which "
                f"{req.requirement_id} requires for {a.scene_id} -- {detail}",
                f"spatial twin: {assessment.get('step_free_route')}",
                requirement=req.requirement_id, scene=a.scene_id,
                location=a.location_id, blockers=blockers,
            ))
    return out


@predicate("access.accessible_transport")
def accessible_transport(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """A step-free transport requirement needs a step-free vehicle that can
    actually reach the location before the call."""
    out: list[ConstraintViolation] = []
    for req in w.ACCESS_REQUIREMENTS:
        if req.category != "mobility":
            continue
        rows = _person_working(plan, problem, req.person_id)
        if not rows:
            continue
        vehicles = [
            v for v in w.VEHICLES
            if v.step_free and problem.is_available(v.vehicle_id)
            and req.requirement_id in v.supports_requirements
        ]
        if not vehicles:
            out.append(_v(
                "C-ACC-002", ConstraintDomain.TRANSPORT, req.requirement_id,
                f"No step-free vehicle is available to satisfy {req.requirement_id}",
                "; ".join(
                    f"{v.vehicle_id}: {problem.reason_unavailable(v.vehicle_id)}"
                    for v in w.VEHICLES if v.step_free
                ) or "no step-free vehicle in the fleet",
                requirement=req.requirement_id,
            ))
            continue
        vehicle = vehicles[0]
        for a in rows:
            arrive_by = min([a.crew_call or a.setup_start, a.setup_start])
            travel = w.travel_minutes("LOC-HARBOUR-WALL", a.location_id)
            depart = arrive_by - timedelta(minutes=travel + vehicle.load_minutes)
            offset = _day_offset(a)
            if not _covers(vehicle.available_from, vehicle.available_to,
                           depart, a.end, offset):
                out.append(_v(
                    "C-ACC-002", ConstraintDomain.TRANSPORT, req.requirement_id,
                    f"{vehicle.name} would need to depart at {depart:%H:%M} to reach "
                    f"{a.location_id} for {a.scene_id} and return by {a.end:%H:%M}; it is "
                    f"available {vehicle.available_from:%H:%M}-{vehicle.available_to:%H:%M}",
                    f"{travel} min travel plus {vehicle.load_minutes} min loading",
                    requirement=req.requirement_id, scene=a.scene_id,
                ))
            driver = w.CREW_BY_ID.get(vehicle.driver_id)
            if driver and not _covers(driver.call_time, driver.wrap_time,
                                      depart, a.end, offset):
                out.append(_v(
                    "C-ACC-002", ConstraintDomain.TRANSPORT, req.requirement_id,
                    f"The driver for {vehicle.name} is available "
                    f"{driver.call_time:%H:%M}-{driver.wrap_time:%H:%M}, which does not cover "
                    f"the {depart:%H:%M}-{a.end:%H:%M} run for {a.scene_id}",
                    "driver availability",
                    requirement=req.requirement_id, scene=a.scene_id,
                ))
    return out


@predicate("access.interpreter_coverage")
def interpreter_coverage(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Interpretation must cover every minute the person is called.

    Coverage is by the *union* of confirmed bookings plus any extension the plan
    explicitly includes. A plan may satisfy this by extending a booking, but only
    if it does so with enough notice — which is itself checked, because an
    extension nobody could actually book is not a solution.
    """
    out: list[ConstraintViolation] = []
    for req in w.ACCESS_REQUIREMENTS:
        if req.category != "communication" or "interpret" not in req.mechanism.lower():
            continue
        rows = _person_working(plan, problem, req.person_id)
        if not rows:
            continue

        spans: list[tuple[datetime, datetime]] = []
        for booking in w.SERVICE_BOOKINGS:
            if req.requirement_id not in booking.supports_requirements:
                continue
            if not problem.is_available(booking.booking_id) or booking.status != "confirmed":
                continue
            # A confirmed booking whose interpreter cannot come is not coverage.
            # Checking only the booking id treated the reservation as the
            # service: with the registered interpreter reported unavailable, the
            # booking record still said 09:00-17:00 and the plan was published
            # claiming interpretation nobody was going to provide.
            if any(not problem.is_available(pid) for pid in booking.person_ids):
                continue
            spans.append((booking.start, booking.end))
        for booking_id, start, end in plan.interpreter_extensions:
            booking = w.BOOKINGS_BY_ID.get(booking_id)
            if booking is None:
                continue
            notice = _minutes(problem.now, start)
            if notice < booking.extension_notice_minutes:
                out.append(_v(
                    "C-ACC-003", ConstraintDomain.COMMUNICATION, req.requirement_id,
                    f"The plan extends {booking_id} to {end:%H:%M} on {end:%d %b} but that "
                    f"needs {booking.extension_notice_minutes} min notice and only "
                    f"{notice:.0f} min is available",
                    f"booking extension notice: {booking.extension_notice_minutes} min",
                    requirement=req.requirement_id,
                ))
                continue
            if booking.extendable_to and end > booking.extendable_to:
                out.append(_v(
                    "C-ACC-003", ConstraintDomain.COMMUNICATION, req.requirement_id,
                    f"The plan extends {booking_id} to {end:%H:%M} but the provider can only "
                    f"extend to {booking.extendable_to:%H:%M}",
                    "booking extension limit", requirement=req.requirement_id,
                ))
                continue
            spans.append((start, end))

        merged = _merge(spans)
        for a in rows:
            need_from = a.cast_calls.get(req.person_id, a.setup_start)
            need_to = a.end
            gap = _uncovered(need_from, need_to, merged)
            if gap is not None:
                covered = ", ".join(f"{s:%d %b %H:%M}-{e:%H:%M}" for s, e in merged) or "none"
                out.append(_v(
                    "C-ACC-003", ConstraintDomain.COMMUNICATION, req.requirement_id,
                    f"{a.scene_id} requires interpretation from {need_from:%H:%M} to "
                    f"{need_to:%H:%M} on {need_to:%d %b}; {gap[0]:%H:%M}-{gap[1]:%H:%M} is "
                    "not covered by any confirmed booking",
                    f"confirmed coverage: {covered}",
                    requirement=req.requirement_id, scene=a.scene_id,
                    gap_start=gap[0].isoformat(), gap_end=gap[1].isoformat(),
                ))
    return out


@predicate("access.accessible_briefing")
def accessible_briefing(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """A required briefing must exist in the approved accessible formats."""
    required = set(w.POLICIES["communication"]["accessible_formats_required"])  # type: ignore[arg-type]
    briefed = {a.location_id for a in problem.baseline}
    new_locations = plan.locations() - briefed
    if not new_locations:
        return []
    out: list[ConstraintViolation] = []
    people = {
        req.person_id for req in w.ACCESS_REQUIREMENTS
        if req.category == "communication"
    }
    working = any(_person_working(plan, problem, pid) for pid in people)
    if not working:
        return []
    for loc_id in sorted(new_locations):
        formats = set()
        for note in plan.notes:
            if note.startswith(f"briefing:{loc_id}"):
                formats = (
                    set(note.split("formats=")[-1].split(","))
                    if "formats=" in note else set()
                )
        missing = required - formats
        if missing:
            loc = w.LOCATIONS_BY_ID.get(loc_id)
            out.append(_v(
                "C-ACC-004", ConstraintDomain.COMMUNICATION, "ACC-003",
                f"The revised briefing for {loc.name if loc else loc_id} is not available in "
                f"{', '.join(sorted(missing))} format, which ACC-003 requires",
                "POLICIES['communication'].accessible_formats_required",
                location=loc_id, missing_formats=sorted(missing),
            ))
    return out


@predicate("access.support_resource")
def support_resource(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Refrigerated storage, quiet space and similar must exist where the work is.

    A portable resource can be moved, but only if the plan says so and only if
    there is time to set it up. Assuming a fridge will simply be there is how an
    approved arrangement quietly disappears.
    """
    out: list[ConstraintViolation] = []
    moved = dict(plan.support_moves)
    for req in w.ACCESS_REQUIREMENTS:
        if req.category not in ("storage", "rest"):
            continue
        rows = _person_working(plan, problem, req.person_id)
        if not rows:
            continue
        # These arrangements live at the *unit base*, not at every working
        # position. Requiring refrigerated storage inside a boat engine space
        # is not what ACC-004 says and not what anyone would set up; what
        # matters is that the base the unit is operating from has it.
        bases = {_unit_base(a, plan) for a in rows}
        for base in sorted(bases):
            satisfied = False
            evidence = ""
            for dep in req.depends_on:
                res = w.SUPPORT_BY_ID.get(dep)
                if res is None or not problem.is_available(dep):
                    evidence = problem.reason_unavailable(dep) or f"{dep} not found"
                    continue
                effective_location = moved.get(dep, res.location_id)
                if effective_location == base:
                    satisfied = True
                    break
                # A same-kind resource already at the base also satisfies it.
                alternatives = [
                    r for r in w.SUPPORT_RESOURCES
                    if r.kind == res.kind and r.location_id == base
                    and problem.is_available(r.resource_id)
                ]
                if alternatives:
                    satisfied = True
                    break
                evidence = f"{res.name} is at {effective_location}, not {base}"
            if not satisfied:
                loc = w.LOCATIONS_BY_ID.get(base)
                out.append(_v(
                    "C-ACC-005", ConstraintDomain.STORAGE, req.requirement_id,
                    f"{req.requirement} is not satisfied at "
                    f"{loc.name if loc else base}",
                    evidence or req.mechanism,
                    requirement=req.requirement_id, location=base,
                ))
    return out


@predicate("access.caregiving_window")
def caregiving_window(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Approved caregiving release times are hard constraints, not preferences."""
    out: list[ConstraintViolation] = []
    for req in w.ACCESS_REQUIREMENTS:
        if req.category != "caregiving" or req.window is None:
            continue
        start, end = req.window
        for a in _person_working(plan, problem, req.person_id):
            if a.end > end + _day_offset(a):
                crew = w.CREW_BY_ID.get(req.person_id)
                out.append(_v(
                    "C-ACC-006", ConstraintDomain.ACCESS, req.requirement_id,
                    f"{crew.name if crew else req.person_id} must be released by "
                    f"{end:%H:%M} ({req.requirement}) but {a.scene_id} runs to {a.end:%H:%M}",
                    req.mechanism, requirement=req.requirement_id, scene=a.scene_id,
                ))
    return out


# ---------------------------------------------------------------------------
# Continuity, daylight, temporal coherence
# ---------------------------------------------------------------------------


@predicate("continuity.story_day_order")
def story_day_order(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Scenes carrying state forward must shoot after the scene that set it."""
    chains = (
        ("SC-008", "SC-009"), ("SC-009", "SC-014"), ("SC-014", "SC-017"),
        ("SC-017", "SC-018"), ("SC-018", "SC-022"), ("SC-025", "SC-026"),
        ("SC-026", "SC-027"), ("SC-027", "SC-029"), ("SC-029", "SC-030"),
        ("SC-021", "SC-025"), ("SC-023", "SC-025"),
    )
    out: list[ConstraintViolation] = []
    for earlier, later in chains:
        a = plan.by_scene(earlier)
        b = plan.by_scene(later)
        if a is None or b is None:
            continue
        if b.start < a.end:
            out.append(_v(
                "C-CONT-001", ConstraintDomain.CONTINUITY, later,
                f"{later} carries continuity state from {earlier} but is scheduled first "
                f"({b.start:%H:%M} before {a.end:%H:%M})",
                "continuity chain", earlier=earlier, later=later,
            ))
    return out


@predicate("continuity.wet_down")
def wet_down(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Irreversible makeup and wardrobe states constrain what can follow.

    Once SC-025 plays wet, no dry day-3 exterior can be shot after it on the
    same day. This is the kind of constraint that is obvious to a continuity
    supervisor and invisible to a scheduling tool.
    """
    wet_scene = plan.by_scene("SC-025")
    if wet_scene is None:
        return []
    out: list[ConstraintViolation] = []
    dry_day3_exteriors = {"SC-019", "SC-021", "SC-023", "SC-017", "SC-028"}
    for a in plan.assignments:
        if a.scene_id not in dry_day3_exteriors:
            continue
        if a.start >= wet_scene.end and a.start.date() == wet_scene.end.date():
            out.append(_v(
                "C-CONT-002", ConstraintDomain.CONTINUITY, a.scene_id,
                f"{a.scene_id} plays dry but is scheduled after the SC-025 wet-down on the "
                "same day; the wet-down is irreversible within the day",
                "SC-025 continuity note", scene=a.scene_id,
            ))
    return out


@predicate("temporal.daylight")
def daylight(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Day scenes need daylight; night scenes need darkness."""
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        req = problem.requirements.get(a.scene_id)
        if req is None or not req.exterior:
            continue
        offset = (a.start.date() - w.SHOOT_DATE).days
        sunrise = w.DAYLIGHT_SUNRISE + timedelta(days=offset)
        sunset = w.DAYLIGHT_SUNSET + timedelta(days=offset)
        dusk = w.CIVIL_DUSK + timedelta(days=offset)
        dawn = w.CIVIL_DAWN + timedelta(days=offset)
        if req.daylight_required and not (sunrise <= a.start and a.end <= sunset):
            out.append(_v(
                "C-TIME-001", ConstraintDomain.DAYLIGHT, a.scene_id,
                f"{a.scene_id} needs daylight but runs {a.start:%H:%M}-{a.end:%H:%M}; "
                f"daylight is {sunrise:%H:%M}-{sunset:%H:%M}",
                "almanac", scene=a.scene_id,
            ))
        if req.night_required and not (a.start >= dusk or a.end <= dawn):
            out.append(_v(
                "C-TIME-001", ConstraintDomain.DAYLIGHT, a.scene_id,
                f"{a.scene_id} needs darkness but runs {a.start:%H:%M}-{a.end:%H:%M}; "
                f"civil dusk is {dusk:%H:%M}",
                "almanac", scene=a.scene_id,
            ))
    return out


@predicate("temporal.travel")
def travel(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """A unit must be able to reach its next location."""
    out: list[ConstraintViolation] = []
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        for a, b in zip(rows, rows[1:]):
            if a.location_id == b.location_id:
                if b.start < a.end:
                    out.append(_v(
                        "C-TIME-002", ConstraintDomain.LOCATION, unit.unit_id,
                        f"{unit.name} has {a.scene_id} and {b.scene_id} overlapping at the "
                        "same location",
                        f"{a.end:%H:%M} / {b.start:%H:%M}",
                    ))
                continue
            need = w.travel_minutes(a.location_id, b.location_id)
            gap = _minutes(a.end, b.start)
            if gap < need:
                out.append(_v(
                    "C-TIME-002", ConstraintDomain.LOCATION, unit.unit_id,
                    f"{unit.name} cannot move from {a.scene_id} at {a.location_id} to "
                    f"{b.scene_id} at {b.location_id}: {need} min needed, {gap:.0f} min available",
                    "travel matrix", unit=unit.unit_id,
                ))
    return out


@predicate("temporal.setup_window")
def setup_window(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Enough time must exist between setup opening and the first shot."""
    out: list[ConstraintViolation] = []
    for a in plan.assignments:
        req = problem.requirements.get(a.scene_id)
        if req is None:
            continue
        available = _minutes(a.setup_start, a.start)
        if available < req.setup_minutes:
            out.append(_v(
                "C-TIME-003", ConstraintDomain.RESOURCE, a.scene_id,
                f"{a.scene_id} allows {available:.0f} min of setup against a "
                f"{req.setup_minutes} min requirement",
                "scene setup estimate", scene=a.scene_id,
            ))
        duration = _minutes(a.start, a.end)
        if duration < req.shoot_minutes:
            out.append(_v(
                "C-TIME-003", ConstraintDomain.RESOURCE, a.scene_id,
                f"{a.scene_id} allows {duration:.0f} min of shooting against a "
                f"{req.shoot_minutes} min estimate",
                "scene duration estimate", scene=a.scene_id,
            ))
    return out


@predicate("scope.mandatory_scenes")
def mandatory_scenes(plan: CandidatePlan,
                    problem: SchedulingProblem) -> list[ConstraintViolation]:
    """Scenes from the published day must be placed, deferred or explicitly moved.

    Silently dropping a scene is the easiest way to make an infeasible day look
    feasible, so it is checked explicitly.
    """
    placed = {a.scene_id for a in plan.assignments}
    accounted = placed | set(plan.deferred) | set(plan.moved_to_next_day)
    out: list[ConstraintViolation] = []
    for sid, req in problem.requirements.items():
        if not req.mandatory:
            continue
        if sid not in accounted:
            out.append(_v(
                "C-SCOPE-001", ConstraintDomain.APPROVAL, sid,
                f"{sid} is on the published day but the plan neither schedules, defers nor "
                "moves it",
                "published call sheet", scene=sid,
            ))
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _merge(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    if not spans:
        return []
    ordered = sorted(spans)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _uncovered(
    start: datetime, end: datetime, covered: list[tuple[datetime, datetime]]
) -> tuple[datetime, datetime] | None:
    """The first uncovered sub-interval of [start, end), or None."""
    cursor = start
    for span_start, span_end in covered:
        if span_end <= cursor:
            continue
        if span_start > cursor:
            return (cursor, min(span_start, end))
        cursor = max(cursor, span_end)
        if cursor >= end:
            return None
    return (cursor, end) if cursor < end else None
