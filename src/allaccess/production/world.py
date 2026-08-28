"""The production world: people, places, resources, policies and the shooting plan.

Everything here is fictional and original to this project — invented people,
invented harbour, invented vendors. No real person, company, location or union
agreement is represented. The working-hour numbers, turnaround rules and
child-performer limits are *configured policy values for this fictional
production*, not a claim about any real jurisdiction's law or any real
collective agreement. All-Access enforces whatever is configured; it does
not decide what the rules should be. See docs/PRIVACY.md §4 and §13.4 of the
plan.

Access requirements deserve a specific note, because they are the reason this
project exists. Every entry in `ACCESS_REQUIREMENTS` records a *practical
operational arrangement* and nothing else. There is no diagnosis field. There is
no medical history field. There is nowhere to put one. A location's step-free
route either exists or it does not; why a given person needs it is not the
production's information to hold, and the solver does not need it to compute the
right answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone

from ..contracts import Classification, Department, Role

PRODUCTION_ID = "PROD-SALT-AND-LIGHT"
PRODUCTION_TITLE = "Salt and Light"
SHOOT_DATE = date(2026, 3, 14)
TZ = timezone.utc


def at(hour: int, minute: int = 0, day_offset: int = 0) -> datetime:
    """A wall-clock time on the shooting day, as an aware UTC datetime.

    The whole system works in UTC internally and formats locally at the edge;
    mixing the two is how schedules quietly go wrong an hour at a time.
    """
    base = datetime.combine(SHOOT_DATE, time(0, 0), tzinfo=TZ)
    return base + timedelta(days=day_offset, hours=hour, minutes=minute)


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Unit:
    unit_id: str
    name: str
    first_ad: str
    base_location: str
    active: bool = True


UNITS: tuple[Unit, ...] = (
    Unit("UNIT-MAIN", "Main unit", "CREW-AD1", "LOC-HARBOUR-WALL"),
    # Both units base at the harbour wall. One base serving a two-unit day in a
    # single harbour is how this is actually run, and it is what keeps the quiet
    # room and the refrigerated storage within reach of both units.
    Unit("UNIT-SECOND", "Second unit", "CREW-AD2", "LOC-HARBOUR-WALL"),
)


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Performer:
    performer_id: str
    name: str
    character_id: str
    minor: bool
    available_from: datetime
    available_to: datetime
    daily_rate: float
    overtime_rate: float
    languages: tuple[str, ...] = ("en",)
    prep_minutes: int = 45
    turnaround_hours: float = 11.0
    notes: str = ""


PERFORMERS: tuple[Performer, ...] = (
    Performer(
        "CAST-001", "Reeve Alanko", "CHAR-MAREN", False,
        at(6, 0), at(23, 30), 1450.0, 320.0, ("en", "fse"), prep_minutes=55,
        notes="Deaf performer. Works with the production interpreter for briefings and blocking.",
    ),
    Performer(
        "CAST-002", "Halvard Ness", "CHAR-ARVO", False,
        at(6, 30), at(23, 0), 1800.0, 400.0, ("en",), prep_minutes=70,
    ),
    Performer(
        "CAST-003", "Juno Vekkeli", "CHAR-PIA", True,
        at(9, 0), at(17, 0), 620.0, 0.0, ("en",), prep_minutes=35,
        notes="Nine years old. Configured work limits apply; see POLICIES['child_performer'].",
    ),
    Performer(
        "CAST-004", "Emmerich Sole", "CHAR-TOIVO", False,
        at(7, 0), at(23, 30), 980.0, 210.0, ("en",),
    ),
    Performer(
        "CAST-005", "Bly Ortance", "CHAR-BUYER", False,
        at(11, 0), at(21, 0), 760.0, 165.0, ("en",),
    ),
    Performer(
        "CAST-006", "Ingrid Sarn", "CHAR-SIRI", False,
        at(7, 0), at(22, 30), 1100.0, 245.0, ("en", "fse"),
    ),
)

PERFORMERS_BY_ID: dict[str, Performer] = {p.performer_id: p for p in PERFORMERS}
PERFORMER_BY_CHARACTER: dict[str, Performer] = {p.character_id: p for p in PERFORMERS}


@dataclass(frozen=True)
class CrewMember:
    crew_id: str
    name: str
    role_title: str
    department: Department
    authority_role: Role
    call_time: datetime
    wrap_time: datetime
    hourly_rate: float
    overtime_multiplier: float = 1.5
    languages: tuple[str, ...] = ("en",)
    critical: bool = False
    units: tuple[str, ...] = ("UNIT-MAIN",)
    turnaround_hours: float = 10.0
    certifications: tuple[str, ...] = ()


# Day 14 is a night-exterior day: the main unit takes an afternoon call and
# wraps after midnight-adjacent work on the wall, while the second unit runs a
# morning half-day to keep the child performer inside her configured window.
#
# `call_time`/`wrap_time` on a crew record are the *availability envelope* the
# production has contracted for that person — the window inside which they can
# be called. Hours actually worked come from the schedule, and it is the
# schedule that the working-hour constraints are evaluated against. Confusing
# the two is how a roster ends up "proving" a legal day that nobody worked.
CREW: tuple[CrewMember, ...] = (
    CrewMember("CREW-UPM", "Sofie Rand", "Unit production manager", Department.PRODUCTION,
               Role.UPM, at(9, 0), at(23, 45), 78.0, critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND")),
    CrewMember("CREW-AD1", "Tomas Ekhild", "First assistant director", Department.PRODUCTION,
               Role.FIRST_AD, at(13, 0), at(23, 45), 82.0, critical=True),
    CrewMember("CREW-AD2", "Nour Belkacem", "Second unit first AD", Department.PRODUCTION,
               Role.FIRST_AD, at(8, 30), at(15, 30), 68.0, critical=True,
               units=("UNIT-SECOND",), languages=("en", "fr", "ar")),
    CrewMember("CREW-COORD", "Pell Iversen", "Production coordinator", Department.PRODUCTION,
               Role.COORDINATOR, at(8, 30), at(23, 45), 54.0, critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND")),
    CrewMember("CREW-SAFETY", "Marit Løvold", "Safety lead", Department.SAFETY,
               Role.SAFETY_LEAD, at(8, 30), at(23, 45), 96.0, critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND"),
               certifications=("marine_safety", "working_at_height", "confined_space")),
    CrewMember("CREW-ACCESS", "Dalia Weir", "Accessibility coordinator", Department.ACCESS,
               Role.ACCESS_COORDINATOR, at(8, 30), at(23, 45), 62.0, critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND")),
    CrewMember("CREW-LOC", "Ansel Praat", "Location manager", Department.LOCATIONS,
               Role.LOCATION_MANAGER, at(8, 0), at(23, 45), 66.0, critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND")),
    CrewMember("CREW-TRANS", "Yusra Idlib", "Transport coordinator", Department.TRANSPORT,
               Role.TRANSPORT_COORDINATOR, at(8, 0), at(23, 45), 58.0, critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND"), languages=("en", "ar")),
    CrewMember("CREW-DOP", "Ravel Nkomo", "Director of photography", Department.CAMERA,
               Role.DEPARTMENT_HEAD, at(13, 0), at(23, 45), 110.0, critical=True),
    CrewMember("CREW-AC1", "Ines Halla", "First assistant camera", Department.CAMERA,
               Role.CREW, at(13, 0), at(23, 45), 64.0),
    CrewMember("CREW-CAMB", "Osk Trellund", "B camera operator", Department.CAMERA,
               Role.CREW, at(8, 30), at(15, 30), 72.0, units=("UNIT-SECOND",)),
    CrewMember("CREW-GAFFER", "Petra Aalto", "Gaffer", Department.LIGHTING,
               Role.DEPARTMENT_HEAD, at(12, 0), at(23, 45), 86.0, critical=True,
               certifications=("high_voltage", "generator_operation")),
    CrewMember("CREW-SPARK", "Timo Reuss", "Best boy electric", Department.LIGHTING,
               Role.CREW, at(12, 0), at(23, 45), 58.0,
               certifications=("generator_operation",)),
    CrewMember("CREW-GRIP", "Bea Constant", "Key grip", Department.GRIP,
               Role.DEPARTMENT_HEAD, at(12, 30), at(23, 45), 74.0),
    CrewMember("CREW-SOUND", "Ilkka Vartia", "Production sound mixer", Department.SOUND,
               Role.DEPARTMENT_HEAD, at(13, 0), at(23, 45), 80.0),
    CrewMember("CREW-ART", "Mira Godel", "Production designer", Department.ART,
               Role.DEPARTMENT_HEAD, at(8, 30), at(22, 0), 84.0),
    CrewMember("CREW-WARD", "Kestrel Vaino", "Costume supervisor", Department.WARDROBE,
               Role.DEPARTMENT_HEAD, at(8, 0), at(23, 45), 61.0, critical=True),
    CrewMember("CREW-MAKEUP", "Saga Lindqvist", "Hair and makeup supervisor", Department.MAKEUP,
               Role.DEPARTMENT_HEAD, at(8, 0), at(23, 45), 63.0, critical=True),
    CrewMember("CREW-PROPS", "Otto Mensah", "Property master", Department.PROPS,
               Role.DEPARTMENT_HEAD, at(8, 30), at(23, 45), 66.0, critical=True),
    # Interpretation is covered by two registered interpreters rather than one.
    # A single person cannot cover 09:00-23:30, and pretending otherwise would
    # make the access constraint trivially satisfiable in a way real productions
    # never manage. The handover overlap at 16:00-17:00 is deliberate.
    CrewMember("CREW-INTERP", "Vera Solheim", "Production sign language interpreter",
               Department.ACCESS, Role.CREW, at(9, 0), at(17, 0), 92.0,
               languages=("en", "fse"), critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND"),
               certifications=("registered_interpreter",)),
    CrewMember("CREW-INTERP-2", "Anneli Rask", "Production sign language interpreter (night)",
               Department.ACCESS, Role.CREW, at(16, 0), at(23, 30), 98.0,
               languages=("en", "fse"), critical=True,
               units=("UNIT-MAIN",),
               certifications=("registered_interpreter",)),
    CrewMember("CREW-CHAP", "Hanne Ruus", "Child performer chaperone and tutor",
               Department.PRODUCTION, Role.CREW, at(8, 30), at(17, 30), 48.0, critical=True,
               units=("UNIT-SECOND",)),
    CrewMember("CREW-MEDIC", "Junius Baer", "Unit medic", Department.SAFETY,
               Role.CREW, at(8, 30), at(23, 45), 70.0, critical=True,
               units=("UNIT-MAIN", "UNIT-SECOND")),
    CrewMember("CREW-MARINE", "Solveig Aar", "Marine safety supervisor", Department.SAFETY,
               Role.CREW, at(12, 0), at(23, 45), 105.0, critical=True,
               certifications=("marine_safety", "coxswain")),
    CrewMember("CREW-DRIVER-A", "Ferran Oduya", "Driver, accessible vehicle", Department.TRANSPORT,
               Role.CREW, at(8, 0), at(23, 45), 44.0,
               units=("UNIT-MAIN", "UNIT-SECOND"),
               certifications=("passenger_lift", "accessible_transport")),
    CrewMember("CREW-DRIVER-B", "Lise Toft", "Driver, crew bus", Department.TRANSPORT,
               Role.CREW, at(8, 0), at(23, 45), 42.0, units=("UNIT-MAIN", "UNIT-SECOND")),
    CrewMember("CREW-CATER", "Odile Brisan", "Catering lead", Department.CATERING,
               Role.CREW, at(8, 0), at(22, 0), 46.0, units=("UNIT-MAIN", "UNIT-SECOND")),
)

CREW_BY_ID: dict[str, CrewMember] = {c.crew_id: c for c in CREW}


# ---------------------------------------------------------------------------
# Approved practical access and caregiving requirements
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccessRequirement:
    """One approved practical arrangement.

    Note what is *not* here: no diagnosis, no medical detail, no explanation.
    `requirement` is the operational fact a department needs in order to do its
    job, and `visible_to` is the smallest set of roles that need to see it.
    """

    requirement_id: str
    person_id: str
    requirement: str
    category: str
    approved_by: Role
    approved_at: datetime
    mechanism: str
    depends_on: tuple[str, ...] = ()
    window: tuple[datetime, datetime] | None = None
    classification: Classification = Classification.OPERATIONAL_REQUIREMENT
    visible_to: tuple[Role, ...] = (
        Role.ACCESS_COORDINATOR,
        Role.COORDINATOR,
        Role.UPM,
    )
    critical: bool = True


ACCESS_REQUIREMENTS: tuple[AccessRequirement, ...] = (
    AccessRequirement(
        "ACC-001", "CREW-AC1",
        "Step-free transport and a step-free route from vehicle to working position.",
        "mobility", Role.ACCESS_COORDINATOR, at(-72),
        mechanism="Accessible vehicle VEH-ACC-1 with powered lift; step-free route at location.",
        depends_on=("VEH-ACC-1",),
        visible_to=(Role.ACCESS_COORDINATOR, Role.COORDINATOR, Role.UPM,
                    Role.TRANSPORT_COORDINATOR, Role.LOCATION_MANAGER),
    ),
    AccessRequirement(
        "ACC-002", "CAST-001",
        "Sign language interpretation for all briefings, blocking and safety instruction.",
        "communication", Role.ACCESS_COORDINATOR, at(-72),
        mechanism="Registered interpreter present whenever this performer is called; "
                  "covered by bookings BOOK-INTERP-1 and BOOK-INTERP-2.",
        depends_on=("CREW-INTERP", "CREW-INTERP-2", "BOOK-INTERP-1", "BOOK-INTERP-2"),
        # The window is the span the performer can be called within. Coverage is
        # satisfied by the *union* of the bookings, which is why the access agent
        # checks union coverage rather than any single booking — see
        # agents/access.py.
        window=(at(9, 0), at(23, 30)),
        visible_to=(Role.ACCESS_COORDINATOR, Role.COORDINATOR, Role.UPM,
                    Role.FIRST_AD, Role.SAFETY_LEAD),
    ),
    AccessRequirement(
        "ACC-003", "CAST-001",
        "Safety briefings issued in written or captioned format in addition to spoken delivery.",
        "communication", Role.SAFETY_LEAD, at(-72),
        mechanism="Briefing service publishes captioned and written variants before delivery.",
        depends_on=("SVC-BRIEFING",),
        visible_to=(Role.ACCESS_COORDINATOR, Role.COORDINATOR, Role.UPM,
                    Role.SAFETY_LEAD, Role.FIRST_AD),
    ),
    AccessRequirement(
        "ACC-004", "CREW-SPARK",
        "Refrigerated storage available at unit base throughout the working day.",
        "storage", Role.ACCESS_COORDINATOR, at(-72),
        mechanism="Refrigerated unit at base; continuous power; access without asking.",
        depends_on=("RES-FRIDGE-1",),
        visible_to=(Role.ACCESS_COORDINATOR, Role.COORDINATOR, Role.UPM),
    ),
    AccessRequirement(
        "ACC-005", "CAST-003",
        "Quiet rest space available at base between setups.",
        "rest", Role.ACCESS_COORDINATOR, at(-72),
        mechanism="Dedicated quiet room at unit base, not shared with crew traffic.",
        depends_on=("RES-QUIET-1",),
        visible_to=(Role.ACCESS_COORDINATOR, Role.COORDINATOR, Role.UPM, Role.FIRST_AD),
    ),
    AccessRequirement(
        "ACC-006", "CREW-CHAP",
        "Caregiving cover: chaperone must be released by 17:30 for dependant collection.",
        "caregiving", Role.UPM, at(-72),
        mechanism="Hard release time; second chaperone required beyond 17:30.",
        window=(at(8, 30), at(17, 30)),
        visible_to=(Role.ACCESS_COORDINATOR, Role.COORDINATOR, Role.UPM),
    ),
)

ACCESS_BY_ID: dict[str, AccessRequirement] = {a.requirement_id: a for a in ACCESS_REQUIREMENTS}


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Location:
    location_id: str
    name: str
    address: str
    interior: bool
    step_free: bool
    step_free_notes: str
    permits: tuple[str, ...]
    travel_minutes_from_base: int
    capacity_crew: int
    power: str
    loading_zone: bool
    weather_exposed: bool
    quiet_space: bool
    refrigeration: bool
    egress_routes: int
    noise_curfew: datetime | None = None
    available_from: datetime | None = None
    available_to: datetime | None = None
    notes: str = ""


LOCATIONS: tuple[Location, ...] = (
    Location(
        "LOC-HARBOUR-WALL", "Harbour wall, east end", "East Wall, Ormsvik Harbour",
        interior=False, step_free=True,
        step_free_notes="Ramped approach from north car park, 1:18 gradient, 1.4 m clear width.",
        permits=("PERM-HARBOUR-01", "PERM-NIGHT-01"),
        travel_minutes_from_base=0, capacity_crew=45, power="generator",
        loading_zone=True, weather_exposed=True, quiet_space=True, refrigeration=True,
        egress_routes=2, noise_curfew=at(23, 0),
        available_from=at(4, 0), available_to=at(23, 30),
        notes="Unit base. Exposed to south-westerlies; the wall is the film's principal set.",
    ),
    Location(
        "LOC-QUAYSIDE", "Quayside, north", "North Quay, Ormsvik Harbour",
        interior=False, step_free=True,
        step_free_notes="Level throughout from north car park.",
        permits=("PERM-HARBOUR-01",),
        travel_minutes_from_base=6, capacity_crew=30, power="mains",
        loading_zone=True, weather_exposed=True, quiet_space=False, refrigeration=False,
        egress_routes=3, available_from=at(6, 0), available_to=at(20, 0),
    ),
    Location(
        "LOC-SLIPWAY", "Slipway", "Ormsvik Slipway",
        interior=False, step_free=False,
        step_free_notes="Slipway itself is 1:8 and wet. No step-free working position on the slip.",
        permits=("PERM-HARBOUR-01", "PERM-MARINE-01"),
        travel_minutes_from_base=9, capacity_crew=25, power="generator",
        loading_zone=False, weather_exposed=True, quiet_space=False, refrigeration=False,
        egress_routes=1,
        available_from=at(5, 0), available_to=at(19, 0),
        notes="Tide dependent. Working window tracks low water.",
    ),
    Location(
        "LOC-HARBOUR-OFFICE", "Harbour master's office", "Harbour Office, Ormsvik",
        interior=True, step_free=True,
        step_free_notes="Level threshold, 900 mm door, lift to first floor out of service.",
        permits=("PERM-INTERIOR-01",),
        travel_minutes_from_base=4, capacity_crew=14, power="mains",
        loading_zone=False, weather_exposed=False, quiet_space=True, refrigeration=False,
        egress_routes=2, available_from=at(6, 0), available_to=at(21, 0),
    ),
    Location(
        "LOC-BOAT-WHEELHOUSE", "Lightkeeper wheelhouse", "Berth 3, East Wall",
        interior=True, step_free=False,
        step_free_notes="Access by gangway and three steps. Not step-free. Alternate working "
                        "position on the wall is step-free.",
        permits=("PERM-HARBOUR-01", "PERM-MARINE-01"),
        travel_minutes_from_base=2, capacity_crew=10, power="generator",
        loading_zone=True, weather_exposed=False, quiet_space=False, refrigeration=False,
        egress_routes=2, available_from=at(5, 0), available_to=at(23, 30),
        notes="Practical boat set. Confined; crew capacity is the binding constraint. "
              "Secondary means of escape from the berth to the slip gate is surveyed.",
    ),
    Location(
        "LOC-BOAT-ENGINE", "Lightkeeper engine space", "Berth 3, East Wall",
        interior=True, step_free=False,
        step_free_notes="Vertical ladder access only. Confined space procedure applies.",
        permits=("PERM-HARBOUR-01", "PERM-MARINE-01", "PERM-CONFINED-01"),
        travel_minutes_from_base=2, capacity_crew=5, power="generator",
        loading_zone=False, weather_exposed=False, quiet_space=False, refrigeration=False,
        egress_routes=1, available_from=at(6, 0), available_to=at(21, 0),
    ),
    Location(
        "LOC-HOUSE-KITCHEN", "Ness house, kitchen", "14 Fisher Row, Ormsvik",
        interior=True, step_free=True,
        step_free_notes="Ramped front entrance installed by production; 1:15.",
        permits=("PERM-INTERIOR-02",),
        travel_minutes_from_base=12, capacity_crew=16, power="mains",
        loading_zone=True, weather_exposed=False, quiet_space=True, refrigeration=True,
        egress_routes=2, noise_curfew=at(22, 30),
        available_from=at(6, 0), available_to=at(22, 30),
    ),
    Location(
        "LOC-HOUSE-UPSTAIRS", "Ness house, first floor", "14 Fisher Row, Ormsvik",
        interior=True, step_free=False,
        step_free_notes="Staircase only. No step-free access to the first floor.",
        permits=("PERM-INTERIOR-02",),
        travel_minutes_from_base=12, capacity_crew=9, power="mains",
        loading_zone=False, weather_exposed=False, quiet_space=True, refrigeration=False,
        egress_routes=1, noise_curfew=at(22, 30),
        available_from=at(6, 0), available_to=at(22, 30),
    ),
    Location(
        "LOC-HOUSE-HALL", "Ness house, hall", "14 Fisher Row, Ormsvik",
        interior=True, step_free=True,
        step_free_notes="Ramped front entrance; hall level.",
        permits=("PERM-INTERIOR-02",),
        travel_minutes_from_base=12, capacity_crew=12, power="mains",
        loading_zone=True, weather_exposed=False, quiet_space=False, refrigeration=False,
        egress_routes=2, noise_curfew=at(22, 30),
        available_from=at(6, 0), available_to=at(22, 30),
    ),
    Location(
        "LOC-CHANDLERY", "Chandlery front", "Ormsvik Chandlery, Fore Street",
        interior=False, step_free=True,
        step_free_notes="Level pavement, dropped kerb at both ends.",
        permits=("PERM-STREET-01",),
        travel_minutes_from_base=15, capacity_crew=18, power="mains",
        loading_zone=True, weather_exposed=True, quiet_space=False, refrigeration=False,
        egress_routes=3, available_from=at(7, 0), available_to=at(19, 0),
    ),
    Location(
        "LOC-CHANDLERY-BACK", "Chandlery back room", "Ormsvik Chandlery, Fore Street",
        interior=True, step_free=False,
        step_free_notes="Two steps down from shop floor; no ramp fitted.",
        permits=("PERM-INTERIOR-03",),
        travel_minutes_from_base=15, capacity_crew=10, power="mains",
        loading_zone=False, weather_exposed=False, quiet_space=False, refrigeration=False,
        egress_routes=1, available_from=at(7, 0), available_to=at(19, 0),
    ),
    Location(
        "LOC-OPEN-WATER", "Open water, one mile out", "Ormsvik Bay",
        interior=False, step_free=False,
        step_free_notes="Vessel access only. Marine safety supervision mandatory.",
        permits=("PERM-MARINE-01", "PERM-MARINE-NIGHT-01"),
        travel_minutes_from_base=25, capacity_crew=7, power="vessel",
        loading_zone=False, weather_exposed=True, quiet_space=False, refrigeration=False,
        egress_routes=1, available_from=at(6, 0), available_to=at(23, 0),
    ),
    # Candidate replacement locations. These exist so a plan has somewhere to go
    # when the harbour wall becomes unsafe. LOC-BOATSHED is the one a
    # conventional scheduling tool would pick — it is available and it is the
    # right size — and it is also the one that fails on three separate approved
    # access arrangements. That is the hero scenario.
    Location(
        "LOC-BOATSHED", "Ormsvik boatshed", "Boatshed, West Wall",
        interior=True, step_free=False,
        step_free_notes="Threshold 140 mm, doorway 760 mm clear, internal ramp 1:7. Does not "
                        "satisfy a step-free route requirement.",
        permits=("PERM-BOATSHED-01",),
        travel_minutes_from_base=22, capacity_crew=40, power="mains",
        loading_zone=True, weather_exposed=False, quiet_space=False, refrigeration=False,
        egress_routes=2, noise_curfew=at(21, 0),
        available_from=at(8, 0), available_to=at(23, 0),
        notes="Superficially the obvious storm cover. Fails ACC-001 on route, ACC-004 on "
              "refrigeration and ACC-005 on quiet space; permit prohibits setup after 21:00.",
    ),
    Location(
        "LOC-NET-LOFT", "Net loft", "Net Loft, East Wall",
        interior=True, step_free=True,
        step_free_notes="Ground floor loft space, level access from the wall, 1.2 m doors.",
        permits=("PERM-HARBOUR-01", "PERM-INTERIOR-04"),
        travel_minutes_from_base=3, capacity_crew=22, power="mains",
        loading_zone=True, weather_exposed=False, quiet_space=True, refrigeration=True,
        egress_routes=2, available_from=at(6, 0), available_to=at(23, 0),
        notes="Adjacent to base. Smaller, but step-free, quiet-space capable and refrigerated.",
    ),
)

LOCATIONS_BY_ID: dict[str, Location] = {loc.location_id: loc for loc in LOCATIONS}


TRAVEL_MINUTES: dict[tuple[str, str], int] = {}


def _build_travel_matrix() -> None:
    """Travel times between every pair of locations.

    Derived from each location's distance from base rather than invented pairwise,
    so the matrix is symmetric and satisfies the triangle inequality. A travel
    matrix that violates the triangle inequality lets the solver "discover"
    impossible routes, which is a bug that looks like an optimisation.
    """
    for a in LOCATIONS:
        for b in LOCATIONS:
            if a.location_id == b.location_id:
                TRAVEL_MINUTES[(a.location_id, b.location_id)] = 0
                continue
            same_site = a.address.split(",")[-1].strip() == b.address.split(",")[-1].strip()
            direct = abs(a.travel_minutes_from_base - b.travel_minutes_from_base)
            via_base = a.travel_minutes_from_base + b.travel_minutes_from_base
            minutes = min(via_base, max(direct, 4 if not same_site else 2))
            if not same_site:
                minutes = max(minutes, 5)
            TRAVEL_MINUTES[(a.location_id, b.location_id)] = int(minutes)


_build_travel_matrix()


def travel_minutes(origin: str, dest: str) -> int:
    return TRAVEL_MINUTES.get((origin, dest), 30)


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Permit:
    permit_id: str
    name: str
    location_ids: tuple[str, ...]
    valid_from: datetime
    valid_to: datetime
    conditions: tuple[str, ...] = ()
    issuing_body: str = "Ormsvik Harbour Authority"
    status: str = "valid"
    prohibits_setup_after: datetime | None = None
    max_crew: int | None = None


PERMITS: tuple[Permit, ...] = (
    Permit("PERM-HARBOUR-01", "Harbour filming permit",
           ("LOC-HARBOUR-WALL", "LOC-QUAYSIDE", "LOC-SLIPWAY", "LOC-BOAT-WHEELHOUSE",
            "LOC-BOAT-ENGINE", "LOC-NET-LOFT"),
           at(4, 0), at(23, 30, day_offset=1), max_crew=50,
           conditions=("No obstruction of the lifeboat slip.", "Public access maintained on the "
                       "north quay.")),
    Permit("PERM-NIGHT-01", "Night filming and lighting permit",
           ("LOC-HARBOUR-WALL",), at(18, 0), at(23, 30),
           conditions=("Lighting must not be directed at the navigation channel.",
                       "Amplified sound prohibited after 23:00.")),
    Permit("PERM-MARINE-01", "Marine operations permit",
           ("LOC-SLIPWAY", "LOC-OPEN-WATER", "LOC-BOAT-WHEELHOUSE", "LOC-BOAT-ENGINE"),
           at(5, 0), at(23, 0),
           conditions=("Marine safety supervisor present for all on-water work.",
                       "Maximum sea state 3.")),
    Permit("PERM-MARINE-NIGHT-01", "Marine night operations permit",
           ("LOC-OPEN-WATER",), at(18, 0), at(23, 0),
           conditions=("Two-vessel minimum.", "Marine safety supervisor and coxswain present.")),
    Permit("PERM-CONFINED-01", "Confined space working permit",
           ("LOC-BOAT-ENGINE",), at(6, 0), at(21, 0),
           conditions=("Atmospheric test before each entry.", "Standby person at hatch.")),
    Permit("PERM-INTERIOR-01", "Harbour office interior permit",
           ("LOC-HARBOUR-OFFICE",), at(6, 0), at(21, 0)),
    Permit("PERM-INTERIOR-02", "Residential interior permit",
           ("LOC-HOUSE-KITCHEN", "LOC-HOUSE-UPSTAIRS", "LOC-HOUSE-HALL"),
           at(6, 0), at(22, 30),
           conditions=("Noise curfew 22:30.", "No vehicles on Fisher Row after 21:00.")),
    Permit("PERM-INTERIOR-03", "Chandlery interior permit",
           ("LOC-CHANDLERY-BACK",), at(7, 0), at(19, 0)),
    Permit("PERM-INTERIOR-04", "Net loft interior permit",
           ("LOC-NET-LOFT",), at(6, 0), at(23, 0)),
    Permit("PERM-STREET-01", "Street filming permit",
           ("LOC-CHANDLERY",), at(7, 0), at(19, 0),
           conditions=("Footway must remain passable.",)),
    Permit(
        "PERM-BOATSHED-01", "Boatshed occupancy permit",
        ("LOC-BOATSHED",), at(8, 0), at(23, 0),
        prohibits_setup_after=at(21, 0),
        conditions=(
            "No new rigging or setup activity after 21:00.",
            "Shared egress with the working yard; maximum 40 persons.",
        ),
    ),
)

PERMITS_BY_ID: dict[str, Permit] = {p.permit_id: p for p in PERMITS}


# ---------------------------------------------------------------------------
# Equipment, vehicles, vendors, resources
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Equipment:
    equipment_id: str
    name: str
    category: str
    department: Department
    exclusive: bool
    assigned_unit: str
    prep_minutes: int
    available_from: datetime
    available_to: datetime
    status: str = "available"
    requires_certification: tuple[str, ...] = ()
    substitutes: tuple[str, ...] = ()
    day_rate: float = 0.0


EQUIPMENT: tuple[Equipment, ...] = (
    Equipment("EQ-CAM-A", "A camera package", "camera", Department.CAMERA, True, "UNIT-MAIN",
              35, at(5, 0), at(23, 45), day_rate=780.0, substitutes=("EQ-CAM-C",)),
    Equipment("EQ-CAM-B", "B camera package", "camera", Department.CAMERA, True, "UNIT-SECOND",
              35, at(6, 0), at(23, 45), day_rate=640.0, substitutes=("EQ-CAM-C",)),
    Equipment("EQ-CAM-C", "Backup camera body", "camera", Department.CAMERA, True, "UNIT-MAIN",
              50, at(5, 0), at(23, 30), day_rate=310.0),
    Equipment("EQ-LIGHT-KIT-1", "Interior lighting package 1", "lighting", Department.LIGHTING,
              True, "UNIT-MAIN", 60, at(5, 0), at(23, 0), day_rate=520.0),
    Equipment("EQ-LIGHT-KIT-2", "Interior lighting package 2", "lighting", Department.LIGHTING,
              True, "UNIT-SECOND", 55, at(6, 0), at(21, 0), day_rate=430.0),
    Equipment(
        "EQ-LIGHT-KIT-3", "Night exterior lighting package", "lighting", Department.LIGHTING,
        True, "UNIT-SECOND", 110, at(5, 0), at(23, 45), day_rate=1450.0,
        requires_certification=("high_voltage",),
        # The single most contended resource in the production, and deliberately
        # assigned to the second unit. Any night exterior needs it.
    ),
    Equipment("EQ-LIGHT-BOUNCE", "Bounce and negative fill package", "lighting",
              Department.LIGHTING, False, "UNIT-MAIN", 20, at(5, 0), at(23, 30), day_rate=140.0),
    Equipment("EQ-SOUND-A", "Sound package A", "sound", Department.SOUND, True, "UNIT-MAIN",
              25, at(6, 0), at(23, 45), day_rate=380.0),
    Equipment("EQ-SOUND-B", "Sound package B", "sound", Department.SOUND, True, "UNIT-SECOND",
              25, at(7, 0), at(19, 30), day_rate=280.0),
    Equipment("EQ-GRIP-BOAT", "Marine grip and mounting package", "grip", Department.GRIP,
              True, "UNIT-MAIN", 75, at(5, 0), at(23, 45), day_rate=610.0,
              requires_certification=("marine_safety",)),
    Equipment("EQ-GENERATOR-A", "Silent generator 60 kVA", "power", Department.LIGHTING,
              True, "UNIT-MAIN", 45, at(5, 0), at(23, 45), day_rate=390.0,
              requires_certification=("generator_operation",)),
    Equipment("EQ-GENERATOR-B", "Silent generator 25 kVA", "power", Department.LIGHTING,
              True, "UNIT-SECOND", 35, at(6, 0), at(21, 0), day_rate=240.0,
              requires_certification=("generator_operation",)),
)

EQUIPMENT_BY_ID: dict[str, Equipment] = {e.equipment_id: e for e in EQUIPMENT}


@dataclass(frozen=True)
class Vehicle:
    vehicle_id: str
    name: str
    capacity: int
    step_free: bool
    lift_equipped: bool
    driver_id: str
    available_from: datetime
    available_to: datetime
    status: str = "available"
    load_minutes: int = 10
    hourly_rate: float = 0.0
    supports_requirements: tuple[str, ...] = ()


VEHICLES: tuple[Vehicle, ...] = (
    Vehicle("VEH-ACC-1", "Accessible minibus with powered lift", 8, True, True, "CREW-DRIVER-A",
            at(5, 0), at(23, 45), load_minutes=18, hourly_rate=62.0,
            supports_requirements=("ACC-001",)),
    Vehicle("VEH-BUS-1", "Crew bus", 16, False, False, "CREW-DRIVER-B",
            at(5, 0), at(23, 45), load_minutes=12, hourly_rate=48.0),
    Vehicle("VEH-VAN-1", "Camera and grip van", 3, False, False, "CREW-DRIVER-B",
            at(5, 0), at(22, 0), load_minutes=25, hourly_rate=40.0),
    Vehicle("VEH-VAN-2", "Lighting van", 3, False, False, "CREW-DRIVER-B",
            at(5, 0), at(22, 0), load_minutes=30, hourly_rate=42.0),
    Vehicle("VEH-BOAT-SAFETY", "Safety vessel", 6, False, False, "CREW-MARINE",
            at(6, 0), at(23, 0), load_minutes=20, hourly_rate=115.0),
)

VEHICLES_BY_ID: dict[str, Vehicle] = {v.vehicle_id: v for v in VEHICLES}


@dataclass(frozen=True)
class SupportResource:
    """Base facilities that approved access requirements depend on."""

    resource_id: str
    name: str
    kind: str
    location_id: str
    available_from: datetime
    available_to: datetime
    status: str = "available"
    portable: bool = False
    setup_minutes: int = 0


SUPPORT_RESOURCES: tuple[SupportResource, ...] = (
    SupportResource("RES-FRIDGE-1", "Refrigerated storage unit", "refrigeration",
                    "LOC-HARBOUR-WALL", at(4, 0), at(23, 30), portable=True, setup_minutes=25),
    SupportResource("RES-QUIET-1", "Quiet rest room", "quiet_space",
                    "LOC-HARBOUR-WALL", at(5, 0), at(23, 45)),
    SupportResource("RES-QUIET-2", "Quiet rest room (net loft)", "quiet_space",
                    "LOC-NET-LOFT", at(6, 0), at(23, 0)),
    SupportResource("RES-FRIDGE-2", "Refrigerated storage unit (net loft)", "refrigeration",
                    "LOC-NET-LOFT", at(6, 0), at(23, 0), portable=True, setup_minutes=25),
    SupportResource("RES-TUTOR-ROOM", "Tutoring room", "education",
                    "LOC-HARBOUR-WALL", at(8, 0), at(17, 30)),
)

SUPPORT_BY_ID: dict[str, SupportResource] = {r.resource_id: r for r in SUPPORT_RESOURCES}


@dataclass(frozen=True)
class ServiceBooking:
    booking_id: str
    kind: str
    provider: str
    person_ids: tuple[str, ...]
    start: datetime
    end: datetime
    status: str = "confirmed"
    extendable_to: datetime | None = None
    extension_notice_minutes: int = 120
    hourly_rate: float = 0.0
    supports_requirements: tuple[str, ...] = ()


SERVICE_BOOKINGS: tuple[ServiceBooking, ...] = (
    ServiceBooking(
        "BOOK-INTERP-1", "sign_language_interpretation", "Solheim Interpreting",
        ("CREW-INTERP",), at(9, 0), at(17, 0),
        extendable_to=at(19, 0), extension_notice_minutes=180, hourly_rate=92.0,
        supports_requirements=("ACC-002",),
    ),
    ServiceBooking(
        # Night cover. Booked to 23:30, which covers the *planned* day exactly
        # and nothing beyond it. Any plan that moves briefed work outside
        # 09:00-23:30 -- including the recommended plan, which moves the exterior
        # to the following morning -- needs a new or extended booking, and the
        # extension carries three hours' notice. This is the access conflict the
        # hero scenario turns on, and it is a scheduling fact rather than an
        # afterthought.
        "BOOK-INTERP-2", "sign_language_interpretation", "Rask Interpreting",
        ("CREW-INTERP-2",), at(16, 0), at(23, 30),
        extendable_to=at(23, 30, 1), extension_notice_minutes=180, hourly_rate=98.0,
        supports_requirements=("ACC-002",),
    ),
    ServiceBooking(
        "BOOK-TRANSPORT-1", "accessible_transport", "Ormsvik Accessible Transport",
        ("CREW-AC1",), at(8, 0), at(23, 45), hourly_rate=62.0,
        supports_requirements=("ACC-001",),
    ),
    ServiceBooking(
        "BOOK-CHAP-1", "chaperone", "In-house", ("CAST-003",), at(8, 30), at(17, 30),
        hourly_rate=48.0,
    ),
    ServiceBooking(
        "BOOK-MARINE-1", "marine_safety", "Aar Marine", ("CREW-MARINE",),
        at(12, 0), at(23, 45), hourly_rate=105.0,
    ),
)

BOOKINGS_BY_ID: dict[str, ServiceBooking] = {b.booking_id: b for b in SERVICE_BOOKINGS}


@dataclass(frozen=True)
class Vendor:
    vendor_id: str
    name: str
    supplies: tuple[str, ...]
    lead_time_minutes: int
    reachable_until: datetime
    call_out_fee: float = 0.0
    reliability: float = 0.95


VENDORS: tuple[Vendor, ...] = (
    Vendor("VEND-LIGHT", "Northern Grip and Electric", ("EQ-LIGHT-KIT-3", "EQ-GENERATOR-B"),
           180, at(19, 0), call_out_fee=850.0, reliability=0.88),
    Vendor("VEND-CAM", "Coastline Camera", ("EQ-CAM-C",), 150, at(18, 0),
           call_out_fee=420.0, reliability=0.93),
    Vendor("VEND-TRANS", "Ormsvik Accessible Transport", ("VEH-ACC-1",), 90, at(20, 0),
           call_out_fee=260.0, reliability=0.9),
    Vendor("VEND-FRIDGE", "Coldline Hire", ("RES-FRIDGE-1", "RES-FRIDGE-2"), 120, at(18, 0),
           call_out_fee=180.0, reliability=0.92),
)

VENDORS_BY_ID: dict[str, Vendor] = {v.vendor_id: v for v in VENDORS}


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

POLICIES: dict[str, dict[str, object]] = {
    "working_hours": {
        "max_crew_day_minutes": 720,
        "max_crew_day_with_approval_minutes": 780,
        "meal_break_after_minutes": 360,
        "meal_break_minutes": 45,
        "second_meal_after_minutes": 660,
        "minimum_turnaround_hours": 10.0,
        "owner": Role.UPM,
        "source": "Production working agreement, clause 4 (fictional)",
    },
    "child_performer": {
        "max_on_set_minutes": 420,
        "max_continuous_minutes": 150,
        "earliest_call": at(9, 0),
        "latest_wrap": at(17, 0),
        "tutoring_minutes_required": 60,
        "chaperone_required": True,
        "rest_break_minutes": 20,
        "rest_break_after_minutes": 120,
        "owner": Role.UPM,
        "source": "Production child performer policy, clause 2 (fictional)",
    },
    "safety": {
        "max_wind_speed_kph_exterior": 45,
        "max_wind_speed_kph_height": 30,
        "prohibited_conditions": ("lightning", "storm_force", "flood"),
        "max_sea_state": 3,
        "briefing_required_on_location_change": True,
        "briefing_valid_minutes": 720,
        "owner": Role.SAFETY_LEAD,
        "source": "Production safety plan, section 3 (fictional)",
    },
    "communication": {
        "call_time_change_reconfirm_threshold_minutes": 30,
        "accessible_formats_required": ("written", "captioned"),
        "max_messages_per_person_per_disruption": 3,
        "owner": Role.COORDINATOR,
        "source": "Production communication policy (fictional)",
    },
    "budget": {
        "contingency": 42000.0,
        "overtime_approval_threshold": 2500.0,
        "vendor_approval_threshold": 1500.0,
        "owner": Role.UPM,
        "source": "Approved production budget v4 (fictional)",
    },
}


# ---------------------------------------------------------------------------
# The baseline shooting plan for the demonstration day
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduledScene:
    scene_id: str
    unit_id: str
    location_id: str
    setup_start: datetime
    start: datetime
    end: datetime
    crew_call: datetime
    equipment_ids: tuple[str, ...]
    cast_calls: dict[str, datetime] = field(default_factory=dict)


#: Prep buffer added on top of each performer's `prep_minutes` when a call time
#: is derived. Ten minutes of slack is what a first AD actually leaves.
CALL_BUFFER_MINUTES = 10


def _calls(scene_start: datetime, performer_ids: tuple[str, ...]) -> dict[str, datetime]:
    """Derive cast call times from each performer's own prep requirement.

    Typing call times by hand is how a published schedule ends up with a
    performer called forty minutes before a scene that needs seventy — which is
    exactly what check B-005 flags, and exactly what it flagged when these were
    literals. Deriving them means the baseline cannot drift out of agreement
    with the prep allowances it is checked against.
    """
    out: dict[str, datetime] = {}
    for pid in performer_ids:
        performer = PERFORMERS_BY_ID[pid]
        out[pid] = scene_start - timedelta(minutes=performer.prep_minutes + CALL_BUFFER_MINUTES)
    return out


def _baseline() -> tuple[ScheduledScene, ...]:
    """The published day plan the production is working to when the storm hits.

    Main unit shoots the harbour-wall material and the boat interiors; second
    unit picks up the quayside and chandlery scenes with the child performer
    inside her configured window. The day ends on SC-025, the night exterior —
    which is exactly the scene the storm takes away.
    """
    rows: list[ScheduledScene] = [
        # Main unit: afternoon call, one boat interior, then the night exterior.
        # Only two scenes, because SC-025 is a 14/8 page night exterior needing
        # four hours of setup and shooting inside a permit window that closes at
        # 23:30. A day that also carried SC-022 would not be a legal day, and
        # the published plan is not permitted to start out illegal.
        ScheduledScene("SC-018", "UNIT-MAIN", "LOC-BOAT-WHEELHOUSE",
                       at(14, 0), at(15, 15), at(17, 15), at(13, 30),
                       ("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A", "EQ-GRIP-BOAT"),
                       _calls(at(15, 15), ("CAST-001", "CAST-002"))),
        # The hero scene. Night exterior, prohibitive weather sensitivity, and
        # it needs the night lighting package that lives with the second unit.
        ScheduledScene("SC-025", "UNIT-MAIN", "LOC-HARBOUR-WALL",
                       at(18, 45), at(20, 45), at(22, 45), at(13, 30),
                       ("EQ-CAM-A", "EQ-CAM-B", "EQ-LIGHT-KIT-3", "EQ-SOUND-A",
                        "EQ-GENERATOR-A", "EQ-GRIP-BOAT"),
                       _calls(at(20, 45), ("CAST-001", "CAST-002", "CAST-004"))),
        # Second unit: morning half-day, sized so the child performer wraps
        # comfortably inside her configured window.
        ScheduledScene("SC-003", "UNIT-SECOND", "LOC-QUAYSIDE",
                       at(9, 15), at(9, 55), at(10, 50), at(9, 0),
                       ("EQ-CAM-B", "EQ-SOUND-B"),
                       _calls(at(9, 55), ("CAST-003", "CAST-006"))),
        ScheduledScene("SC-010", "UNIT-SECOND", "LOC-CHANDLERY",
                       at(11, 0), at(11, 40), at(12, 30), at(9, 0),
                       ("EQ-CAM-B", "EQ-SOUND-B"),
                       _calls(at(11, 40), ("CAST-001", "CAST-003"))),
        ScheduledScene("SC-024", "UNIT-SECOND", "LOC-HOUSE-KITCHEN",
                       at(12, 40), at(13, 30), at(14, 30), at(9, 0),
                       ("EQ-CAM-B", "EQ-LIGHT-KIT-2", "EQ-SOUND-B"),
                       _calls(at(13, 30), ("CAST-003", "CAST-006"))),
    ]
    return tuple(rows)


BASELINE_SCHEDULE: tuple[ScheduledScene, ...] = _baseline()
SCHEDULED_BY_SCENE: dict[str, ScheduledScene] = {s.scene_id: s for s in BASELINE_SCHEDULE}

# Scenes prepared and available to move into the day if something is lost.
#
# SC-022 and SC-027 are the strong ones: both are wheelhouse interiors two
# minutes from base, both are already dressed, and both need only the interior
# lighting package that is already rigged. That is what makes the recommended
# hero plan operationally better than a company move, not just safer.
COVER_SET_SCENES: tuple[str, ...] = ("SC-022", "SC-027", "SC-016", "SC-020", "SC-007")


@dataclass(frozen=True)
class WeatherWindow:
    start: datetime
    end: datetime
    condition: str
    wind_kph: float
    precipitation_mm: float
    precipitation_probability: float
    sea_state: int
    lightning_risk: float = 0.0


BASELINE_WEATHER: tuple[WeatherWindow, ...] = (
    WeatherWindow(at(4, 0), at(10, 0), "overcast", 14.0, 0.0, 0.10, 2),
    WeatherWindow(at(10, 0), at(15, 0), "cloud", 18.0, 0.2, 0.20, 2),
    WeatherWindow(at(15, 0), at(19, 0), "cloud", 24.0, 0.6, 0.35, 2),
    WeatherWindow(at(19, 0), at(23, 30), "rain", 31.0, 2.4, 0.55, 3),
    # The following day. The forecast is settled, which is what makes deferring
    # the night exterior by twenty-four hours a genuinely better plan rather
    # than simply a later one.
    WeatherWindow(at(6, 0, 1), at(12, 0, 1), "clear", 12.0, 0.0, 0.10, 1),
    WeatherWindow(at(12, 0, 1), at(18, 0, 1), "cloud", 15.0, 0.1, 0.15, 1),
    WeatherWindow(at(18, 0, 1), at(23, 59, 1), "clear", 11.0, 0.0, 0.08, 1),
)

DAYLIGHT_SUNRISE = at(6, 42)
DAYLIGHT_SUNSET = at(18, 6)
CIVIL_DAWN = at(6, 8)
CIVIL_DUSK = at(18, 40)


def is_daylight(when: datetime) -> bool:
    return DAYLIGHT_SUNRISE <= when <= DAYLIGHT_SUNSET


def is_night(when: datetime) -> bool:
    return when >= CIVIL_DUSK or when <= CIVIL_DAWN


RATE_CARD: dict[str, float] = {
    "crew_overtime_multiplier": 1.5,
    "cast_overtime_multiplier": 1.75,
    "night_premium_multiplier": 1.25,
    "vehicle_idle_hourly": 22.0,
    "company_move_fixed": 640.0,
    "location_cancellation_fee": 1200.0,
    "vendor_call_out_night": 1.4,
    "catering_late_meal_per_head": 18.0,
    "interpreter_extension_hourly": 92.0 * 1.5,
}


def crew_for_unit(unit_id: str) -> tuple[CrewMember, ...]:
    return tuple(c for c in CREW if unit_id in c.units)


def head_count(unit_id: str) -> int:
    return len(crew_for_unit(unit_id))


def access_requirements_for(person_id: str) -> tuple[AccessRequirement, ...]:
    return tuple(a for a in ACCESS_REQUIREMENTS if a.person_id == person_id)


def permits_for_location(location_id: str) -> tuple[Permit, ...]:
    return tuple(p for p in PERMITS if location_id in p.location_ids)


def weather_at(when: datetime,
               windows: tuple[WeatherWindow, ...] = BASELINE_WEATHER) -> WeatherWindow | None:
    for w in windows:
        if w.start <= when < w.end:
            return w
    return None
