"""The problem representation the deterministic engine works on.

A `SchedulingProblem` is everything the solver is allowed to know: the scenes to
place, the resources available, the constraints in force, and the state hash of
the twin snapshot it came from. A `CandidatePlan` is an assignment of scenes to
(location, unit, time) plus the derived transport and access implementation.

Keeping this separate from `contracts.Plan` is deliberate. The solver works on a
mutable, cheap structure; a `Plan` is the immutable published artifact with a
feasibility proof attached. Converting one to the other is the point at which
validation happens, and there is exactly one function that does it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Iterable

from ..contracts import stable_hash
from ..production import script as scr
from ..production import world as w

#: Time granularity for scheduling decisions. Five minutes is the smallest unit
#: a first AD actually works in; finer resolution multiplies the search space
#: without changing any answer anyone would act on.
SLOT_MINUTES = 5


def snap(when: datetime) -> datetime:
    """Round a time down to the scheduling grid."""
    minute = (when.minute // SLOT_MINUTES) * SLOT_MINUTES
    return when.replace(minute=minute, second=0, microsecond=0)


def snap_up(when: datetime) -> datetime:
    snapped = snap(when)
    return snapped if snapped == when else snapped + timedelta(minutes=SLOT_MINUTES)


@dataclass(frozen=True)
class SceneRequirement:
    """What one scene needs, flattened out of the script and world records."""

    scene_id: str
    candidate_locations: tuple[str, ...]
    performer_ids: tuple[str, ...]
    equipment_ids: tuple[str, ...]
    setup_minutes: int
    shoot_minutes: int
    story_day: int
    exterior: bool
    night_required: bool
    daylight_required: bool
    weather_sensitivity: str
    special_requirements: tuple[str, ...]
    unit_preference: str
    page_eighths: int
    mandatory: bool = True

    @property
    def total_minutes(self) -> int:
        return self.setup_minutes + self.shoot_minutes


@dataclass(frozen=True)
class Assignment:
    """One scene, placed."""

    scene_id: str
    location_id: str
    unit_id: str
    setup_start: datetime
    start: datetime
    end: datetime
    equipment_ids: tuple[str, ...]
    cast_calls: dict[str, datetime] = field(default_factory=dict)
    crew_call: datetime | None = None
    pre_rigged: bool = False

    def overlaps(self, other: "Assignment") -> bool:
        return self.setup_start < other.end and other.setup_start < self.end

    def shoot_overlaps(self, other: "Assignment") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass
class CandidatePlan:
    """A mutable working plan. Becomes a `contracts.Plan` only after validation."""

    strategy: str
    label: str
    rationale: str
    assignments: list[Assignment] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    moved_to_next_day: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    interpreter_extensions: list[tuple[str, datetime, datetime]] = field(default_factory=list)
    support_moves: list[tuple[str, str]] = field(default_factory=list)
    vehicle_reassignments: list[tuple[str, str, str]] = field(default_factory=list)
    #: Unit id -> base location, when the plan moves a unit's base. Empty means
    #: every unit stays where `world.UNITS` says it is based.
    unit_bases: dict[str, str] = field(default_factory=dict)

    def by_scene(self, scene_id: str) -> Assignment | None:
        for a in self.assignments:
            if a.scene_id == scene_id:
                return a
        return None

    def by_unit(self, unit_id: str) -> list[Assignment]:
        return sorted((a for a in self.assignments if a.unit_id == unit_id),
                      key=lambda a: a.start)

    def locations(self) -> set[str]:
        return {a.location_id for a in self.assignments}

    def wrap_time(self, unit_id: str | None = None) -> datetime | None:
        rows = self.assignments if unit_id is None else self.by_unit(unit_id)
        return max((a.end for a in rows), default=None)

    def call_time(self, unit_id: str | None = None) -> datetime | None:
        rows = self.assignments if unit_id is None else self.by_unit(unit_id)
        calls = [a.crew_call for a in rows if a.crew_call is not None]
        return min(calls, default=None)

    def replace_assignment(self, scene_id: str, **changes: object) -> None:
        for i, a in enumerate(self.assignments):
            if a.scene_id == scene_id:
                self.assignments[i] = replace(a, **changes)  # type: ignore[arg-type]
                return
        raise KeyError(scene_id)

    def structure_key(self) -> tuple:
        """Identity for diversity filtering.

        Two plans are "the same shape" if they place the same scenes at the same
        locations with the same units *on the same days*, regardless of a few
        minutes' difference in timing. Without this the diverse-plan generator
        happily returns five variants of one idea.

        The day is part of the shape. "Shoot it tonight at the end of the night"
        and "shoot it tomorrow evening" place the same scene at the same location
        with the same unit and are not remotely the same plan — dropping the date
        silently collapsed them and cost the comparison two genuine options.
        """
        return tuple(sorted(
            (a.scene_id, a.location_id, a.unit_id, a.start.date().isoformat())
            for a in self.assignments
        )) + (tuple(sorted(self.deferred)), tuple(sorted(self.moved_to_next_day)))

    def content_hash(self) -> str:
        return stable_hash([
            self.strategy,
            [(a.scene_id, a.location_id, a.unit_id, a.start.isoformat(), a.end.isoformat())
             for a in sorted(self.assignments, key=lambda x: x.scene_id)],
            sorted(self.deferred),
            sorted(self.moved_to_next_day),
        ])

    def copy(self) -> "CandidatePlan":
        return CandidatePlan(
            strategy=self.strategy,
            label=self.label,
            rationale=self.rationale,
            assignments=list(self.assignments),
            deferred=list(self.deferred),
            moved_to_next_day=list(self.moved_to_next_day),
            notes=list(self.notes),
            interpreter_extensions=list(self.interpreter_extensions),
            support_moves=list(self.support_moves),
            vehicle_reassignments=list(self.vehicle_reassignments),
            unit_bases=dict(self.unit_bases),
        )


@dataclass
class SchedulingProblem:
    """Everything the solver may read. Nothing outside this is in scope."""

    production_id: str
    now: datetime
    horizon_start: datetime
    horizon_end: datetime
    requirements: dict[str, SceneRequirement]
    baseline: list[Assignment]
    frozen_scene_ids: frozenset[str] = frozenset()
    #: Scenes the disruption has directly invalidated. Never frozen, however far
    #: into setup or shooting they are.
    disrupted_scene_ids: frozenset[str] = frozenset()
    available_locations: tuple[str, ...] = ()
    available_equipment: tuple[str, ...] = ()
    available_vehicles: tuple[str, ...] = ()
    unavailable: dict[str, str] = field(default_factory=dict)   # entity -> reason
    weather: tuple[w.WeatherWindow, ...] = w.BASELINE_WEATHER
    state_sequence: int = 0
    state_hash: str = ""
    cover_scenes: tuple[str, ...] = ()

    def requirement(self, scene_id: str) -> SceneRequirement:
        return self.requirements[scene_id]

    def is_available(self, entity_id: str) -> bool:
        return entity_id not in self.unavailable

    def reason_unavailable(self, entity_id: str) -> str:
        return self.unavailable.get(entity_id, "")

    def scene_ids(self) -> tuple[str, ...]:
        return tuple(self.requirements)


def requirement_for(scene_id: str, *, mandatory: bool = True) -> SceneRequirement:
    """Flatten one scene's needs out of the script and the world records."""
    scene = scr.SCENES_BY_ID[scene_id]
    performers = tuple(
        w.PERFORMER_BY_CHARACTER[c].performer_id
        for c in scene.characters
        if c in w.PERFORMER_BY_CHARACTER
    )
    # Candidate locations: the scripted one, plus any location that could stand
    # in for it. A scene written for a specific practical set has exactly one
    # candidate; an interior that could play anywhere has several.
    scripted = scene.location_id
    candidates = [scripted]
    if scripted in ("LOC-HOUSE-KITCHEN", "LOC-HOUSE-HALL", "LOC-HARBOUR-OFFICE"):
        candidates.append("LOC-NET-LOFT")
    if scripted == "LOC-HARBOUR-WALL" and not scene.night_required:
        candidates.append("LOC-QUAYSIDE")
    if scripted == "LOC-HARBOUR-WALL" and scene.night_required:
        # Storm cover for the night exterior. Both are genuinely offered to the
        # solver; the constraints are what rule the boatshed out, not a
        # hand-placed exclusion.
        candidates.extend(["LOC-BOATSHED", "LOC-NET-LOFT"])
    return SceneRequirement(
        scene_id=scene_id,
        candidate_locations=tuple(dict.fromkeys(candidates)),
        performer_ids=performers,
        equipment_ids=scene.equipment_ids,
        setup_minutes=scene.setup_minutes,
        shoot_minutes=scene.shoot_minutes,
        story_day=scene.story_day,
        exterior=scene.exterior,
        night_required=scene.night_required,
        daylight_required=scene.daylight_required,
        weather_sensitivity=scene.weather_sensitivity,
        special_requirements=scene.special_requirements,
        unit_preference="UNIT-SECOND" if scene.unit == "second" else "UNIT-MAIN",
        page_eighths=scene.page_eighths,
        mandatory=mandatory,
    )


def baseline_assignments() -> list[Assignment]:
    return [
        Assignment(
            scene_id=s.scene_id,
            location_id=s.location_id,
            unit_id=s.unit_id,
            setup_start=s.setup_start,
            start=s.start,
            end=s.end,
            equipment_ids=s.equipment_ids,
            cast_calls=dict(s.cast_calls),
            crew_call=s.crew_call,
        )
        for s in w.BASELINE_SCHEDULE
    ]


def build_problem(
    *,
    now: datetime | None = None,
    unavailable: dict[str, str] | None = None,
    weather: tuple[w.WeatherWindow, ...] | None = None,
    extra_scenes: Iterable[str] = (),
    disrupted_scene_ids: Iterable[str] = (),
    state_sequence: int = 0,
    state_hash: str = "",
) -> SchedulingProblem:
    """Assemble the problem from the world plus whatever the disruption changed."""
    moment = now or w.at(19, 0)
    scene_ids = [a.scene_id for a in baseline_assignments()]
    cover = tuple(w.COVER_SET_SCENES)
    requirements = {sid: requirement_for(sid) for sid in scene_ids}
    for sid in list(cover) + list(extra_scenes):
        if sid not in requirements:
            requirements[sid] = requirement_for(sid, mandatory=False)
    return SchedulingProblem(
        production_id=w.PRODUCTION_ID,
        now=moment,
        horizon_start=w.at(5, 0),
        horizon_end=w.at(12, 0, 1),
        requirements=requirements,
        baseline=baseline_assignments(),
        available_locations=tuple(loc.location_id for loc in w.LOCATIONS),
        available_equipment=tuple(e.equipment_id for e in w.EQUIPMENT),
        available_vehicles=tuple(v.vehicle_id for v in w.VEHICLES),
        unavailable=dict(unavailable or {}),
        weather=weather or w.BASELINE_WEATHER,
        state_sequence=state_sequence,
        state_hash=state_hash,
        cover_scenes=cover,
        disrupted_scene_ids=frozenset(disrupted_scene_ids),
    )
