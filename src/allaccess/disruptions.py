"""The parameterised disruption library.

Each `Scenario` describes a change to the world and carries its own ground truth:
which scenes it invalidates, which constraints it should trip, which access
arrangements it puts at risk. The agents never see the ground truth — it lives
here so the benchmark can score them against it, which is the only way the
detection and recall numbers in `docs/BENCHMARK.md` mean anything.

`generate(n)` expands the templates by varying severity, timing and subject into
a reproducible corpus. The templates cover the seven families from §15.3:
weather, cast and crew, location, equipment, access and communication,
continuity, and operational-systems faults.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .contracts import Authority, Classification, Event, EventType
from .production import script as scr
from .production import world as w
from .solver.model import SchedulingProblem, build_problem
from .stream.bus import LocalEventBus


@dataclass(frozen=True)
class Scenario:
    """One disruption, with the ground truth the agents cannot see."""

    scenario_id: str
    family: str
    title: str
    description: str
    event_type: EventType
    payload: dict[str, Any]
    authority: Authority = Authority.AUTHORITATIVE
    at: datetime = field(default_factory=lambda: w.at(19, 0))
    #: World changes the disruption causes.
    unavailable: dict[str, str] = field(default_factory=dict)
    weather: tuple[w.WeatherWindow, ...] | None = None
    disrupted_scenes: tuple[str, ...] = ()
    #: Ground truth, for scoring only.
    expected_constraints: tuple[str, ...] = ()
    expected_access_at_risk: tuple[str, ...] = ()
    expected_departments: tuple[str, ...] = ()
    expected_feasible: bool = True
    severity: str = "high"


def _storm_weather(wind: float = 68.0, condition: str = "storm_force",
                   start_hour: int = 18, start_minute: int = 30) -> tuple[w.WeatherWindow, ...]:
    """Replace the evening window with a storm, leaving the rest of the day intact."""
    replacement = w.WeatherWindow(
        w.at(start_hour, start_minute), w.at(23, 59), condition, wind,
        9.5, 0.95, 6, lightning_risk=0.4,
    )
    kept = tuple(
        win for win in w.BASELINE_WEATHER
        if win.end <= replacement.start or win.start >= w.at(0, 0, 1)
    )
    return tuple(sorted(kept + (replacement,), key=lambda win: win.start))


STORM_SCENARIO = Scenario(
    scenario_id="SC-STORM-001",
    family="weather",
    title="Storm closes the night exterior",
    description=(
        "A verified storm front reaches the harbour at 18:30, an hour before the night "
        "exterior on the wall is due to turn over. Sixty-eight kilometre-per-hour winds and "
        "sea state six put the scene outside every configured safety threshold."
    ),
    event_type=EventType.WEATHER_ALERTED,
    payload={
        "entity_id": "WEATHER-04",
        "condition": "storm_force",
        "wind_kph": 68.0,
        "precipitation_mm": 9.5,
        "precipitation_probability": 0.95,
        "sea_state": 6,
        "lightning_risk": 0.4,
        "window_start": w.at(18, 30).isoformat(),
        "window_end": w.at(23, 59).isoformat(),
        "affected_locations": ["LOC-HARBOUR-WALL", "LOC-OPEN-WATER", "LOC-SLIPWAY"],
        "confidence": 0.97,
        "attributes": {"source": "national forecast, amber warning"},
    },
    weather=_storm_weather(),
    disrupted_scenes=("SC-025",),
    expected_constraints=("C-SAFE-001",),
    expected_access_at_risk=("ACC-001", "ACC-002", "ACC-004", "ACC-005"),
    expected_departments=("lighting", "camera", "grip", "production"),
    expected_feasible=True,
)


# ---------------------------------------------------------------------------
# Scenario templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Template:
    family: str
    key: str
    build: Callable[[random.Random, int], Scenario]


def _weather_template(rng: random.Random, index: int) -> Scenario:
    condition, wind, severity = rng.choice([
        ("storm_force", rng.uniform(55, 85), "high"),
        ("lightning", rng.uniform(30, 50), "high"),
        ("flood", rng.uniform(25, 45), "high"),
        ("rain", rng.uniform(46, 60), "medium"),
        ("wind", rng.uniform(46, 58), "medium"),
        ("heat", rng.uniform(10, 20), "low"),
    ])
    hour = rng.choice([14, 16, 17, 18, 19])
    return Scenario(
        scenario_id=f"SC-WEA-{index:04d}",
        family="weather",
        title=f"{condition.replace('_', ' ').title()} affecting exterior work",
        description=f"{condition} at {wind:.0f} kph from {hour:02d}:00.",
        event_type=EventType.WEATHER_ALERTED,
        payload={
            "entity_id": f"WEATHER-{index:02d}",
            "condition": condition,
            "wind_kph": round(wind, 1),
            "precipitation_mm": round(rng.uniform(0, 12), 1),
            "precipitation_probability": round(rng.uniform(0.2, 0.99), 2),
            "sea_state": rng.randint(1, 6),
            "lightning_risk": round(rng.uniform(0, 0.5), 2),
            "window_start": w.at(hour, 0).isoformat(),
            "window_end": w.at(23, 59).isoformat(),
            "affected_locations": ["LOC-HARBOUR-WALL"],
            "confidence": round(rng.uniform(0.85, 0.99), 2),
            "attributes": {},
        },
        weather=_storm_weather(wind, condition, hour, 0),
        at=w.at(max(6, hour - 1), 0),
        disrupted_scenes=("SC-025",),
        expected_constraints=("C-SAFE-001",) if (
            condition in ("storm_force", "lightning", "flood") or wind > 45
        ) else (),
        expected_departments=("lighting", "camera", "production"),
        severity=severity,
    )


#: Performers actually called on the shooting day. One of the six is not, and
#: reporting them unavailable changes nothing: no scene loses a performer, so no
#: availability constraint can be breached. Those scenarios were still declaring
#: C-RES-004 as ground truth and being scored as misses for it.
_CALLED_PERFORMERS: tuple[w.Performer, ...] = tuple(
    p for p in w.PERFORMERS
    if any(p.performer_id in s.cast_calls for s in w.BASELINE_SCHEDULE)
)


def _cast_template(rng: random.Random, index: int) -> Scenario:
    performer = rng.choice(_CALLED_PERFORMERS)
    kind = rng.choice(["late_arrival", "illness", "unavailable", "travel_delay"])
    delay = rng.choice([30, 45, 60, 90, 120])
    return Scenario(
        scenario_id=f"SC-CAST-{index:04d}",
        family="cast_crew",
        title=f"{performer.name} {kind.replace('_', ' ')}",
        description=f"{performer.name} reported {kind.replace('_', ' ')} ({delay} min).",
        event_type=EventType.CAST_CHANGED,
        payload={
            "entity_id": performer.performer_id,
            "entity_type": "performer",
            "change": "unavailable" if kind in ("illness", "unavailable") else "delayed",
            "attributes": {"delay_minutes": delay},
            "reason": kind.replace("_", " "),
            "confidence": round(rng.uniform(0.9, 1.0), 2),
            "verification_state": "confirmed",
            "reported_by": "CREW-COORD",
            "affected": [performer.performer_id],
        },
        unavailable=(
            {performer.performer_id: f"{kind.replace('_', ' ')} reported"}
            if kind in ("illness", "unavailable") else {}
        ),
        disrupted_scenes=tuple(
            a.scene_id for a in w.BASELINE_SCHEDULE
            if performer.performer_id in a.cast_calls
        ),
        expected_constraints=("C-RES-004",) if kind in ("illness", "unavailable") else (),
        expected_departments=("production", "wardrobe", "makeup"),
        severity="high" if performer.minor or kind == "unavailable" else "medium",
    )


def _crew_template(rng: random.Random, index: int) -> Scenario:
    crew = rng.choice([c for c in w.CREW if c.critical])
    return Scenario(
        scenario_id=f"SC-CREW-{index:04d}",
        family="cast_crew",
        title=f"{crew.role_title} unavailable",
        description=f"{crew.name} ({crew.role_title}) reported unavailable.",
        event_type=EventType.CREW_CHANGED,
        payload={
            "entity_id": crew.crew_id,
            "entity_type": "crew_member",
            "change": "unavailable",
            "attributes": {"department": crew.department.value},
            "reason": "reported unavailable",
            "confidence": 1.0,
            "verification_state": "confirmed",
            "reported_by": "CREW-COORD",
            "affected": [crew.crew_id],
        },
        unavailable={crew.crew_id: "reported unavailable"},
        # A critical crew member's absence stops their unit (C-RES-007), and can
        # breach two further constraints depending on who they are: an
        # interpreter takes their booking's coverage with them (C-ACC-003), and
        # the sole holder of a certification leaves the equipment that requires
        # it with no operator (C-RES-003). All three are separate breaches and
        # the corpus declares all of them; it previously declared only the first.
        expected_constraints=tuple(sorted(
            {"C-RES-007"}
            | ({"C-ACC-003"} if "interpret" in crew.role_title.lower() else set())
            | ({"C-RES-003"} if crew.crew_id in _SOLE_CERTIFICATIONS else set())
            | ({"C-SAFE-002"} if crew.crew_id == "CREW-MARINE" and _MARINE_WORK else set())
        )),
        expected_access_at_risk=(
            ("ACC-002",) if crew.crew_id in ("CREW-INTERP", "CREW-INTERP-2")
            else ("ACC-001",) if crew.crew_id == "CREW-DRIVER-A"
            else ()
        ),
        expected_departments=(crew.department.value,),
        severity="high",
    )


def _location_template(rng: random.Random, index: int) -> Scenario:
    location = rng.choice([
        loc for loc in w.LOCATIONS
        if loc.location_id in {a.location_id for a in w.BASELINE_SCHEDULE}
    ])
    kind = rng.choice([
        "closure", "access_route_failure", "power_failure", "permit_restriction",
        "noise_restriction", "loading_zone_loss", "unsafe_area", "egress_problem",
    ])
    return Scenario(
        scenario_id=f"SC-LOC-{index:04d}",
        family="location",
        title=f"{location.name}: {kind.replace('_', ' ')}",
        description=f"{location.name} reported {kind.replace('_', ' ')}.",
        event_type=EventType.LOCATION_CHANGED,
        payload={
            "entity_id": location.location_id,
            "entity_type": "location",
            "change": "closed" if kind == "closure" else "restricted",
            "attributes": {"issue": kind},
            "reason": kind.replace("_", " "),
            "confidence": round(rng.uniform(0.9, 1.0), 2),
            "verification_state": "confirmed",
            "reported_by": "CREW-LOC",
            "affected": [location.location_id],
        },
        unavailable=(
            {location.location_id: kind.replace("_", " ")} if kind == "closure" else {}
        ),
        disrupted_scenes=tuple(
            a.scene_id for a in w.BASELINE_SCHEDULE
            if a.location_id == location.location_id
        ),
        expected_constraints=("C-LOC-001",) if kind == "closure" else (),
        expected_access_at_risk=("ACC-001",) if kind == "access_route_failure" else (),
        expected_departments=("locations", "production", "transport"),
        severity="high" if kind in ("closure", "unsafe_area") else "medium",
    )


#: What each equipment fault means for the day, in the words the inventory
#: system would use. Every one of them ends with the package not being usable,
#: which is the only world change this corpus can express — `unavailable` is a
#: binary per-entity fact.
#:
#: This replaces an earlier version in which three of the four kinds injected no
#: world change at all while still declaring `C-RES-001` as ground truth. Nothing
#: changed, so no predicate could fire, and the benchmark counted a false
#: negative against the detector for a defect in the corpus. See
#: docs/BENCHMARK.md §7.
#: Equipment the published day actually calls for.
_SCHEDULED_EQUIPMENT: frozenset[str] = frozenset(
    eq_id for s in w.BASELINE_SCHEDULE for eq_id in s.equipment_ids
)

#: Certifications that scheduled equipment requires and exactly one crew member
#: holds. Losing that person leaves the package with no operator. Two people
#: hold `marine_safety`, so losing either of them does not, which is why this is
#: computed rather than listed.
_SOLE_CERTIFICATIONS: dict[str, str] = {
    holders[0]: cert
    for cert, holders in (
        (cert, [c.crew_id for c in w.CREW if cert in c.certifications])
        for cert in {
            cert
            for eq_id in _SCHEDULED_EQUIPMENT
            for cert in w.EQUIPMENT_BY_ID[eq_id].requires_certification
        }
    )
    if len(holders) == 1
}

#: Whether the published day contains on-water work. The marine operations
#: permit names one supervisor, so if it does, losing them breaches C-SAFE-002
#: as well as stopping the unit.
_MARINE_WORK: bool = any(
    "marine_safety_supervision" in scr.SCENES_BY_ID[s.scene_id].special_requirements
    for s in w.BASELINE_SCHEDULE
    if s.scene_id in scr.SCENES_BY_ID
)

_EQUIPMENT_FAULTS: dict[str, str] = {
    "failure": "reported failed in service; not repairable today",
    "late_vendor": "vendor delivery failed; the package will not be on site today",
    "duplicate_assignment": (
        "claimed by both units for the same window; released to the other claimant"
    ),
    "incompatible": "incompatible with the rigged configuration; cannot be used today",
}


def _equipment_template(rng: random.Random, index: int) -> Scenario:
    equipment = rng.choice(w.EQUIPMENT)
    kind = rng.choice(sorted(_EQUIPMENT_FAULTS))
    reason = _EQUIPMENT_FAULTS[kind]
    return Scenario(
        scenario_id=f"SC-EQP-{index:04d}",
        family="equipment",
        title=f"{equipment.name}: {kind.replace('_', ' ')}",
        description=f"{equipment.name} reported {kind.replace('_', ' ')}.",
        event_type=EventType.RESOURCE_CHANGED,
        payload={
            "entity_id": equipment.equipment_id,
            "entity_type": "equipment",
            "change": "unavailable",
            "attributes": {"issue": kind, "department": equipment.department.value},
            "reason": reason,
            "confidence": 1.0,
            "verification_state": "confirmed",
            "reported_by": "CREW-GAFFER",
            "affected": [equipment.equipment_id],
        },
        unavailable={equipment.equipment_id: reason},
        # Only if the package is on the day's call sheet. Three of the twelve are
        # spares that no scheduled scene calls for, and losing a spare breaches
        # nothing — those scenarios are the negative control for this family.
        expected_constraints=(
            ("C-RES-002",) if equipment.equipment_id in _SCHEDULED_EQUIPMENT else ()
        ),
        expected_departments=(equipment.department.value,),
        severity="high" if equipment.exclusive else "low",
    )


#: Access requirements this template can inject a failure against: the ones
#: whose approved mechanism is a bookable thing that can become unavailable.
#:
#: ACC-006 is excluded and the exclusion is the point. Its mechanism is a hard
#: release time, not a service — there is no provider to withdraw, so an
#: "ACCESS_SERVICE_CHANGED, provider unavailable" event about it would describe
#: something that cannot happen. The earlier version of this template fell back
#: to SVC-BRIEFING for it, which published an event asserting that the briefing
#: service supports the caregiving arrangement. It does not; it supports ACC-003.
#: The scenario then declared C-ACC-006 as ground truth, which nothing in the
#: injected change could ever trip. C-ACC-006 is exercised instead by any
#: scenario that pushes the chaperone's unit past 17:30, which the schedule
#: families do.
_ACCESS_INJECTABLE: tuple[w.AccessRequirement, ...] = tuple(
    req for req in w.ACCESS_REQUIREMENTS if req.depends_on
)


def _access_expected_constraints(dependency: str) -> tuple[str, ...]:
    """Which constraints the loss of this specific mechanism actually trips.

    Derived from what the dependency *is*, not from the requirement's category.
    The category is the wrong key: ACC-002 and ACC-003 are both `communication`
    but one depends on interpreters and the other on the briefing service, and
    those fail into different constraints.
    """
    out: list[str] = []
    if dependency in w.VEHICLES_BY_ID:
        out.append("C-ACC-002")
    if dependency in w.BOOKINGS_BY_ID:
        out.append("C-ACC-003")
    if dependency in w.CREW_BY_ID:
        # An interpreter who cannot come takes their booking's coverage with
        # them, and a critical crew member's absence stops their unit.
        if "interpret" in w.CREW_BY_ID[dependency].role_title.lower():
            out.append("C-ACC-003")
        if w.CREW_BY_ID[dependency].critical:
            out.append("C-RES-007")
    if dependency in w.SUPPORT_BY_ID:
        out.append("C-ACC-005")
    # SVC-BRIEFING deliberately yields nothing. Losing the briefing service does
    # not breach ACC-003 on the unchanged day: BRIEFING-1 was already issued in
    # written and captioned form, and C-ACC-004 is conditional on a plan
    # introducing a location the issued briefing does not cover. The arrangement
    # is reachable and at risk — which is why ACC-003 stays in
    # `expected_access_at_risk` — but no hard constraint is breached until a plan
    # moves the work.
    return tuple(sorted(set(out)))


def _access_template(rng: random.Random, index: int) -> Scenario:
    requirement = rng.choice(_ACCESS_INJECTABLE)
    dependency = rng.choice(requirement.depends_on)
    return Scenario(
        scenario_id=f"SC-ACC-{index:04d}",
        family="access_communication",
        title=f"{requirement.category} arrangement at risk",
        description=(
            f"The mechanism supporting an approved {requirement.category} arrangement "
            f"({dependency}) has become unavailable."
        ),
        event_type=EventType.ACCESS_SERVICE_CHANGED,
        payload={
            "entity_id": dependency,
            "entity_type": "service_booking",
            "change": "unavailable",
            "attributes": {"supports": requirement.requirement_id},
            "reason": "provider reported unavailable",
            "confidence": 1.0,
            "verification_state": "confirmed",
            "reported_by": "CREW-ACCESS",
            "affected": [dependency, requirement.requirement_id],
        },
        unavailable={dependency: "provider reported unavailable"},
        expected_constraints=_access_expected_constraints(dependency),
        expected_access_at_risk=(requirement.requirement_id,),
        expected_departments=("access_services", "production"),
        severity="high",
    )


def _continuity_template(rng: random.Random, index: int) -> Scenario:
    kind = rng.choice([
        "wardrobe_unavailable", "prop_unavailable", "story_day_conflict",
        "makeup_conflict", "weather_continuity_mismatch", "actor_state_mismatch",
    ])
    scene = rng.choice([a.scene_id for a in w.BASELINE_SCHEDULE])
    return Scenario(
        scenario_id=f"SC-CON-{index:04d}",
        family="continuity",
        title=kind.replace("_", " ").title(),
        description=f"{kind.replace('_', ' ')} reported on {scene}.",
        event_type=EventType.SOURCE_EVENT_RECEIVED,
        payload={
            "entity_id": scene,
            "kind": "continuity",
            "summary": f"{kind.replace('_', ' ')} on {scene}",
            "attributes": {"scene_id": scene, "issue": kind},
            "confidence": round(rng.uniform(0.8, 1.0), 2),
            "verification_state": "confirmed",
            "reported_by": "CREW-WARD",
        },
        disrupted_scenes=(scene,),
        # No constraint. Every kind in this family is a *report* about the
        # published day rather than a change to it: the baseline order is
        # continuity-valid, so preserving it breaches nothing, and the authored
        # production carries no wardrobe or prop entity that a
        # `wardrobe_unavailable` report could take away. `story_day_conflict`
        # previously declared C-CONT-001 here, which no injected change could
        # trip. What these scenarios test is that the system does not
        # manufacture a violation from an unactionable report — and it does not.
        # See docs/BENCHMARK.md §7 for the data gap behind it.
        expected_constraints=(),
        expected_departments=("wardrobe", "makeup", "props"),
        severity="medium",
    )


def _systems_template(rng: random.Random, index: int) -> Scenario:
    kind = rng.choice([
        "duplicate_event", "late_event", "out_of_order_event", "connector_failure",
        "command_rejection", "partial_update", "missing_acknowledgment",
        "schema_incompatibility",
    ])
    return Scenario(
        scenario_id=f"SC-SYS-{index:04d}",
        family="operational_systems",
        title=kind.replace("_", " ").title(),
        description=f"Operational fault injected: {kind.replace('_', ' ')}.",
        event_type=EventType.SOURCE_EVENT_RECEIVED,
        payload={
            "entity_id": None,
            "kind": "system_fault",
            "summary": kind.replace("_", " "),
            "attributes": {"fault": kind},
            "confidence": 1.0,
            "verification_state": "confirmed",
            "reported_by": "system",
        },
        # No department. A platform fault — a duplicate event, a stale one, a
        # rejected schema — leaves the shooting day untouched, and the correct
        # plan is to change nothing. These scenarios exist to check that the
        # fault is handled, not that anybody is dispatched about it. The earlier
        # version labelled `production` here, which was scored against a blast
        # radius that is necessarily empty: the payload carries no entity_id
        # because there is no entity in the production the fault happened to.
        expected_departments=(),
        severity="low",
    )


TEMPLATES: tuple[Template, ...] = (
    Template("weather", "weather", _weather_template),
    Template("cast_crew", "cast", _cast_template),
    Template("cast_crew", "crew", _crew_template),
    Template("location", "location", _location_template),
    Template("equipment", "equipment", _equipment_template),
    Template("access_communication", "access", _access_template),
    Template("continuity", "continuity", _continuity_template),
    Template("operational_systems", "systems", _systems_template),
)


def generate(count: int = 1000, seed: int = 20260314) -> list[Scenario]:
    """A reproducible corpus. Same seed, same corpus, on any machine."""
    rng = random.Random(seed)
    scenarios: list[Scenario] = [STORM_SCENARIO]
    index = 1
    while len(scenarios) < count:
        template = TEMPLATES[index % len(TEMPLATES)]
        scenarios.append(template.build(rng, index))
        index += 1
    return scenarios[:count]


def family_counts(scenarios: list[Scenario]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for scenario in scenarios:
        counts[scenario.family] = counts.get(scenario.family, 0) + 1
    return dict(sorted(counts.items()))


def scenario_problem(scenario: Scenario, twin: Any = None) -> SchedulingProblem:
    """The scheduling problem this scenario creates."""
    problem = build_problem(
        now=scenario.at,
        unavailable=dict(scenario.unavailable),
        weather=scenario.weather,
        disrupted_scene_ids=scenario.disrupted_scenes,
        state_hash=twin.state_hash(scenario.at) if twin is not None else "",
        state_sequence=twin.sequence if twin is not None else 0,
    )
    # The coordinator reads the twin off the problem for blast radius. Attaching
    # it here keeps `build_problem` free of a twin dependency it does not
    # otherwise need.
    problem.twin = twin  # type: ignore[attr-defined]
    return problem


def build_source_event(bus: LocalEventBus, scenario: Scenario) -> Event:
    """Publish the scenario's source event and return it."""
    disruption_id = "DISR-" + scenario.scenario_id.replace("SC-", "")
    event = bus.make_event(
        scenario.event_type,
        dict(scenario.payload),
        producer=_producer_for(scenario),
        actor=str(scenario.payload.get("reported_by") or "system"),
        authority=scenario.authority,
        disruption_id=disruption_id,
        correlation_id=disruption_id,
        effective_time=scenario.at,
        classification=Classification.PRODUCTION_INTERNAL,
        # Keyed by scenario, not by payload content. Two operational-fault
        # scenarios can legitimately carry identical payloads, and deduplicating
        # them by content would silently drop half the corpus.
        idempotency_key=f"{scenario.scenario_id}:{scenario.event_type.value}",
    )
    result = bus.publish(event)
    if not result.published or result.event is None:
        raise RuntimeError(
            f"scenario {scenario.scenario_id} produced an invalid source event: "
            f"{result.reason}"
        )
    return result.event


def _producer_for(scenario: Scenario) -> str:
    return {
        "weather": "weather_service",
        "cast_crew": "production_office",
        "location": "location_operations",
        "equipment": "equipment_inventory",
        "access_communication": "access_service_booking",
        "continuity": "continuity_department",
        "operational_systems": "system_monitor",
    }.get(scenario.family, "production_office")
