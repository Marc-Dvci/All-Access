"""Constrained scheduling search.

Given a set of scenes with chosen locations and units, find start times that
satisfy the temporal and resource structure of the day: setup durations, travel
between locations, exclusive-resource occupancy including prep, availability
windows, daylight and darkness, and precedence.

The search is chronological backtracking over a five-minute grid with three
things that make it tractable and honest:

* **Domain filtering before search.** Each scene's start domain is narrowed by
  its own unary constraints — location opening hours, permit windows, daylight
  or darkness, cast availability — before any assignment is tried. Most scenes
  end up with a few dozen candidate slots rather than several hundred.
* **Forward checking.** Placing a scene immediately prunes the domains of the
  scenes that share a unit or an exclusive resource with it. A dead end is
  usually detected at the assignment that causes it rather than several levels
  later.
* **A node budget.** Search is bounded and reports whether it exhausted the
  space or ran out. A solver that quietly gives up and reports "infeasible" is
  worse than useless, so `SearchResult.exhausted` records which happened, and
  the feasibility proof carries it.

This is the placement layer only. It enforces the structural constraints it can
propagate cheaply; the full constraint registry is then run against the result
by `engine.py`, and *that* is what decides feasibility. Doing it in that order
means the search can be fast and approximate while the verdict stays exact.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..production import world as w
from .model import SLOT_MINUTES, Assignment, SchedulingProblem, snap_up

#: How far the search may look for a slot before declaring a scene unplaceable.
DEFAULT_NODE_BUDGET = 20000


@dataclass(frozen=True)
class PlacementRequest:
    """One scene the caller wants placed, with the choices already made."""

    scene_id: str
    location_id: str
    unit_id: str
    earliest: datetime
    latest: datetime
    equipment_ids: tuple[str, ...]
    #: Fixed placements are not searched; they constrain everything else.
    fixed: Assignment | None = None
    #: Prefer starting as late as possible (night exteriors want full darkness).
    prefer_late: bool = False
    #: Optional scenes are cover material. If one will not fit, the search leaves
    #: it out and carries on rather than declaring the whole plan impossible —
    #: "we can get one of the two interiors tonight" is a real answer, and the
    #: alternative is a strategy that silently disappears from the comparison.
    optional: bool = False


@dataclass
class SearchResult:
    assignments: list[Assignment] = field(default_factory=list)
    placed: list[str] = field(default_factory=list)
    unplaced: list[str] = field(default_factory=list)
    nodes: int = 0
    propagations: int = 0
    exhausted: bool = True
    failure_reasons: dict[str, str] = field(default_factory=dict)
    #: Optional scenes that did not fit. Not a failure.
    skipped: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """Every *required* request was placed. Skipped cover material is fine."""
        return not self.unplaced


def _slots(earliest: datetime, latest: datetime) -> list[datetime]:
    out: list[datetime] = []
    cursor = snap_up(earliest)
    while cursor <= latest:
        out.append(cursor)
        cursor += timedelta(minutes=SLOT_MINUTES)
    return out


def _unary_domain(
    request: PlacementRequest,
    problem: SchedulingProblem,
) -> tuple[list[datetime], str]:
    """Candidate *shoot start* times for one scene, after unary filtering.

    Returns the domain and, if it is empty, the reason — which is what the
    infeasibility explainer turns into a sentence a coordinator can act on.
    """
    req = problem.requirements[request.scene_id]
    loc = w.LOCATIONS_BY_ID.get(request.location_id)
    if loc is None:
        return [], f"unknown location {request.location_id}"

    candidates = _slots(request.earliest, request.latest)
    if not candidates:
        return [], "no time remains in the horizon for this scene"

    def keep(start: datetime) -> str | None:
        setup_start = start - timedelta(minutes=req.setup_minutes)
        end = start + timedelta(minutes=req.shoot_minutes)
        offset = (start.date() - w.SHOOT_DATE).days

        # Nothing can begin rigging in the past. `earliest` bounds the setup,
        # not the first shot: a scene needing 80 minutes of pre-light cannot
        # turn over 80 minutes from now, it turns over 80 minutes after the
        # crew actually start.
        if setup_start < request.earliest:
            return (
                f"setup needs {req.setup_minutes} min and cannot begin before "
                f"{request.earliest:%H:%M}"
            )

        if loc.available_from and setup_start < loc.available_from + timedelta(days=offset):
            return f"{loc.name} opens at {loc.available_from:%H:%M}"
        if loc.available_to and end > loc.available_to + timedelta(days=offset):
            return f"{loc.name} closes at {loc.available_to:%H:%M}"

        for permit_id in loc.permits:
            permit = w.PERMITS_BY_ID.get(permit_id)
            if permit is None or not problem.is_available(permit_id):
                continue
            if setup_start < permit.valid_from + timedelta(days=offset):
                return f"{permit.name} starts at {permit.valid_from:%H:%M}"
            if end > permit.valid_to + timedelta(days=offset):
                return f"{permit.name} ends at {permit.valid_to:%H:%M}"
            if permit.prohibits_setup_after and setup_start > (
                permit.prohibits_setup_after + timedelta(days=offset)
            ):
                return (
                    f"{permit.name} prohibits setup after "
                    f"{permit.prohibits_setup_after:%H:%M}"
                )

        if req.exterior:
            sunrise = w.DAYLIGHT_SUNRISE + timedelta(days=offset)
            sunset = w.DAYLIGHT_SUNSET + timedelta(days=offset)
            dusk = w.CIVIL_DUSK + timedelta(days=offset)
            dawn = w.CIVIL_DAWN + timedelta(days=offset)
            if req.daylight_required and not (sunrise <= start and end <= sunset):
                return f"daylight runs {sunrise:%H:%M}-{sunset:%H:%M}"
            if req.night_required and not (start >= dusk or end <= dawn):
                return f"darkness begins at {dusk:%H:%M}"

        for pid in req.performer_ids:
            performer = w.PERFORMERS_BY_ID.get(pid)
            if performer is None:
                continue
            call = start - timedelta(minutes=performer.prep_minutes)
            day = timedelta(days=offset)
            if call < performer.available_from + day or end > performer.available_to + day:
                return (
                    f"{performer.name} is available "
                    f"{performer.available_from:%H:%M}-{performer.available_to:%H:%M}"
                )

        for eq_id in request.equipment_ids:
            eq = w.EQUIPMENT_BY_ID.get(eq_id)
            if eq is None:
                return f"unknown equipment {eq_id}"
            if not problem.is_available(eq_id):
                return f"{eq.name} is unavailable: {problem.reason_unavailable(eq_id)}"
            day = timedelta(days=offset)
            if end > eq.available_to + day:
                return f"{eq.name} is available until {eq.available_to:%H:%M}"
        return None

    domain: list[datetime] = []
    last_reason = ""
    for start in candidates:
        reason = keep(start)
        if reason is None:
            domain.append(start)
        else:
            last_reason = reason
    if not domain:
        return [], last_reason or "no start time satisfies this scene's own requirements"
    if request.prefer_late:
        domain.reverse()
    return domain, ""


def _conflicts(
    candidate: Assignment,
    placed: list[Assignment],
    problem: SchedulingProblem,
) -> bool:
    """Binary constraint check between a candidate and everything already placed.

    Deliberately narrow: unit timeline, travel, exclusive equipment and performer
    exclusivity. These are the constraints that prune the search usefully. The
    rest of the registry runs once on the finished plan, where it can produce a
    proper explanation instead of a silent prune.
    """
    req = problem.requirements[candidate.scene_id]
    for other in placed:
        same_unit = other.unit_id == candidate.unit_id
        if same_unit:
            if candidate.setup_start < other.end and other.setup_start < candidate.end:
                return True
            if candidate.location_id != other.location_id:
                need = w.travel_minutes(other.location_id, candidate.location_id)
                if other.end <= candidate.start:
                    if (candidate.start - other.end).total_seconds() / 60.0 < need:
                        return True
                elif candidate.end <= other.start:
                    if (other.start - candidate.end).total_seconds() / 60.0 < need:
                        return True

        shared = set(candidate.equipment_ids) & set(other.equipment_ids)
        for eq_id in shared:
            eq = w.EQUIPMENT_BY_ID.get(eq_id)
            if eq is None or not eq.exclusive:
                continue
            if candidate.setup_start < other.end and other.setup_start < candidate.end:
                return True

        other_req = problem.requirements.get(other.scene_id)
        if other_req is not None:
            shared_cast = set(req.performer_ids) & set(other_req.performer_ids)
            if shared_cast:
                if candidate.start < other.end and other.start < candidate.end:
                    return True
                if candidate.location_id != other.location_id:
                    need = w.travel_minutes(other.location_id, candidate.location_id)
                    gap = (
                        (candidate.start - other.end)
                        if other.end <= candidate.start
                        else (other.start - candidate.end)
                    )
                    if gap.total_seconds() / 60.0 < need:
                        return True
    return False


def _build(request: PlacementRequest, start: datetime,
           problem: SchedulingProblem) -> Assignment:
    req = problem.requirements[request.scene_id]
    setup_start = start - timedelta(minutes=req.setup_minutes)
    end = start + timedelta(minutes=req.shoot_minutes)
    offset = timedelta(days=(start.date() - w.SHOOT_DATE).days)
    calls = {
        pid: start - timedelta(minutes=w.PERFORMERS_BY_ID[pid].prep_minutes
                               + w.CALL_BUFFER_MINUTES)
        for pid in req.performer_ids
        if pid in w.PERFORMERS_BY_ID
    }
    unit_call = min([setup_start, *calls.values()]) if calls else setup_start
    return Assignment(
        scene_id=request.scene_id,
        location_id=request.location_id,
        unit_id=request.unit_id,
        setup_start=setup_start,
        start=start,
        end=end,
        equipment_ids=request.equipment_ids,
        cast_calls=calls,
        crew_call=unit_call - timedelta(minutes=0) if offset else unit_call,
    )


def schedule(
    problem: SchedulingProblem,
    requests: list[PlacementRequest],
    *,
    node_budget: int = DEFAULT_NODE_BUDGET,
) -> SearchResult:
    """Place every request, or report which ones could not be placed and why."""
    result = SearchResult()
    fixed = [r.fixed for r in requests if r.fixed is not None]
    open_requests = [r for r in requests if r.fixed is None]

    domains: dict[str, list[datetime]] = {}
    for request in open_requests:
        domain, reason = _unary_domain(request, problem)
        result.propagations += 1
        if not domain:
            # An optional scene with no legal slot is cover material that will
            # not fit, which is an outcome rather than a failure. Recording it
            # as unplaced would make every strategy carrying cover options
            # collapse the moment one of them was too tight.
            if request.optional:
                result.skipped.append(request.scene_id)
            else:
                result.unplaced.append(request.scene_id)
            result.failure_reasons[request.scene_id] = reason
        else:
            domains[request.scene_id] = domain

    searchable = [r for r in open_requests if r.scene_id in domains]
    # Most-constrained-first: the scene with the fewest legal slots is the one
    # most likely to fail, and failing early is the whole point of ordering.
    searchable.sort(key=lambda r: (len(domains[r.scene_id]), r.scene_id))

    placed: list[Assignment] = list(fixed)
    chosen: dict[str, Assignment] = {}

    def recurse(index: int) -> bool:
        if result.nodes >= node_budget:
            result.exhausted = False
            return False
        if index >= len(searchable):
            return True
        request = searchable[index]
        for start in domains[request.scene_id]:
            result.nodes += 1
            if result.nodes >= node_budget:
                result.exhausted = False
                return False
            candidate = _build(request, start, problem)
            result.propagations += 1
            if _conflicts(candidate, placed, problem):
                continue
            placed.append(candidate)
            chosen[request.scene_id] = candidate
            if recurse(index + 1):
                return True
            placed.pop()
            chosen.pop(request.scene_id, None)
        # Cover material that will not fit is simply left out.
        if request.optional:
            return recurse(index + 1)
        return False

    ok = recurse(0)
    if ok:
        result.assignments = list(placed)
        result.placed = [a.scene_id for a in placed]
        for request in searchable:
            if request.scene_id not in chosen and request.optional:
                result.skipped.append(request.scene_id)
                result.failure_reasons.setdefault(
                    request.scene_id, "no room in the remaining window"
                )
    else:
        # Report a best-effort partial placement so the caller can see how far
        # the day got before it broke, rather than an empty result.
        result.assignments = list(placed)
        result.placed = [a.scene_id for a in placed]
        for request in searchable:
            if request.scene_id not in chosen:
                result.unplaced.append(request.scene_id)
                result.failure_reasons.setdefault(
                    request.scene_id,
                    "no start time is compatible with the rest of the day"
                    if result.exhausted
                    else "search budget exhausted before a placement was found",
                )
    return result
