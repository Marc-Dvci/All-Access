"""The constraint and policy registry.

Every constraint the system enforces is declared here once, with its owner, its
source document, its disclosure classification and the name of the predicate that
evaluates it. `validate_registry()` runs at import and raises if any constraint
names a predicate that does not exist — which is the mechanism that stops this
file from drifting into a list of good intentions.

The registry is also what the infeasibility explainer reads. When a plan is
rejected, the conflict set is a set of *these* records, so every explanation can
name the document the rule came from and the person who owns it. "Infeasible"
without provenance is not an explanation, it is an assertion.
"""

from __future__ import annotations

from datetime import datetime

from ..contracts import (
    Classification,
    ConstraintDomain,
    ConstraintKind,
    ConstraintRecord,
    ConstraintViolation,
    Role,
    stable_hash,
)
from ..solver.model import CandidatePlan, SchedulingProblem
from ..solver.predicates import PREDICATES

CONSTRAINTS: tuple[ConstraintRecord, ...] = (
    # -- safety ------------------------------------------------------------
    ConstraintRecord(
        constraint_id="C-SAFE-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.SAFETY,
        title="Prohibited weather conditions for exterior work",
        description=(
            "Exterior work is prohibited in storm, lightning or flood conditions, or above the "
            "configured wind threshold. The safety lead owns the threshold; the system enforces "
            "whatever is configured and never negotiates it."
        ),
        owner=Role.SAFETY_LEAD,
        source="Production safety plan, section 3",
        source_evidence="POLICIES['safety'].max_wind_speed_kph_exterior, prohibited_conditions",
        priority=1,
        solver_encoding="safety.weather_threshold",
        parameters={"max_wind_kph": 45, "prohibited": ["lightning", "storm_force", "flood"]},
    ),
    ConstraintRecord(
        constraint_id="C-SAFE-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.SAFETY,
        title="Marine safety supervision for on-water work",
        description="All on-water work requires the marine safety supervisor present.",
        owner=Role.SAFETY_LEAD,
        source="Marine operations permit PERM-MARINE-01",
        source_evidence="Permit condition: marine safety supervisor present for all on-water work",
        priority=1,
        solver_encoding="safety.marine_supervision",
    ),
    ConstraintRecord(
        constraint_id="C-SAFE-003",
        kind=ConstraintKind.CONDITIONAL,
        domain=ConstraintDomain.SAFETY,
        title="New location requires a revised safety briefing",
        description=(
            "If a plan introduces a location the issued briefing does not cover, a revised "
            "briefing must be published before work begins there."
        ),
        owner=Role.SAFETY_LEAD,
        source="Production safety plan, section 3",
        source_evidence="POLICIES['safety'].briefing_required_on_location_change",
        priority=2,
        solver_encoding="safety.briefing_current",
    ),
    ConstraintRecord(
        constraint_id="C-SAFE-004",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.EGRESS,
        title="Two independent emergency egress routes",
        description=(
            "Every working position requires two egress routes that do not share their first "
            "leg. Two exits down the same corridor are one route."
        ),
        owner=Role.SAFETY_LEAD,
        source="Production safety plan, section 5",
        source_evidence="Location access surveys; spatial twin egress analysis",
        priority=2,
        solver_encoding="safety.egress",
    ),
    # -- working hours -----------------------------------------------------
    ConstraintRecord(
        constraint_id="C-HOUR-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.WORKING_HOURS,
        title="Maximum crew working day",
        description=(
            "A unit's working day may not exceed the configured maximum. Between the standard "
            "and the with-approval maximum, UPM approval is required."
        ),
        owner=Role.UPM,
        source="Production working agreement, clause 4",
        source_evidence="POLICIES['working_hours'].max_crew_day_minutes",
        priority=3,
        solver_encoding="hours.crew_day_length",
        parameters={"standard_minutes": 720, "with_approval_minutes": 780},
    ),
    ConstraintRecord(
        constraint_id="C-HOUR-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.REST,
        title="Minimum turnaround between working days",
        description="Minimum rest between wrap and the following call.",
        owner=Role.UPM,
        source="Production working agreement, clause 4",
        source_evidence="POLICIES['working_hours'].minimum_turnaround_hours",
        priority=3,
        solver_encoding="hours.turnaround",
        parameters={"minimum_hours": 10.0},
    ),
    ConstraintRecord(
        constraint_id="C-CHILD-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.CHILD_PERFORMER,
        title="Child performer working window",
        description="A child performer may not be called before, or work beyond, the "
                    "configured daily window.",
        owner=Role.UPM,
        source="Production child performer policy, clause 2",
        source_evidence="POLICIES['child_performer'].earliest_call / latest_wrap",
        priority=1,
        solver_encoding="hours.child_performer",
        subject_ids=("CAST-003",),
        disclosure=Classification.PRODUCTION_INTERNAL,
    ),
    ConstraintRecord(
        constraint_id="C-CHILD-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.CHILD_PERFORMER,
        title="Child performer maximum time on set",
        description="Total time from first call to final wrap may not exceed the configured "
                    "maximum.",
        owner=Role.UPM,
        source="Production child performer policy, clause 2",
        source_evidence="POLICIES['child_performer'].max_on_set_minutes",
        priority=1,
        solver_encoding="hours.child_performer",
        subject_ids=("CAST-003",),
    ),
    ConstraintRecord(
        constraint_id="C-CHILD-003",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.CHILD_PERFORMER,
        title="Chaperone present whenever a child performer is called",
        description="A child performer may not be on set without the approved chaperone.",
        owner=Role.UPM,
        source="Production child performer policy, clause 2",
        source_evidence="POLICIES['child_performer'].chaperone_required",
        priority=1,
        solver_encoding="hours.child_performer",
        subject_ids=("CAST-003",),
    ),
    # -- resources ---------------------------------------------------------
    ConstraintRecord(
        constraint_id="C-RES-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.RESOURCE,
        title="Exclusive resource may not be double-assigned",
        description="An exclusive resource, including its prep time, may be assigned to one "
                    "scene at a time.",
        owner=Role.UPM,
        source="Equipment inventory and department assignments",
        source_evidence="EQUIPMENT records: exclusive, prep_minutes",
        priority=2,
        solver_encoding="resource.exclusivity",
    ),
    ConstraintRecord(
        constraint_id="C-RES-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.EQUIPMENT,
        title="Equipment must be available within its window",
        description="Equipment must exist, be serviceable, and be available for prep through wrap.",
        owner=Role.DEPARTMENT_HEAD,
        source="Equipment inventory",
        source_evidence="EQUIPMENT records: available_from, available_to, status",
        priority=2,
        solver_encoding="resource.availability",
    ),
    ConstraintRecord(
        constraint_id="C-RES-003",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.RESOURCE,
        title="Certified operator required for restricted equipment",
        description="Equipment requiring certification needs a certified, available operator.",
        owner=Role.SAFETY_LEAD,
        source="Production safety plan, section 4",
        source_evidence="EQUIPMENT.requires_certification; CREW.certifications",
        priority=1,
        solver_encoding="resource.certified_operator",
    ),
    ConstraintRecord(
        constraint_id="C-RES-004",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.AVAILABILITY,
        title="Performer availability",
        description="A performer must be available and have their prep allowance.",
        owner=Role.FIRST_AD,
        source="Cast availability records",
        source_evidence="PERFORMERS: available_from, available_to, prep_minutes",
        priority=2,
        solver_encoding="resource.performer_availability",
        disclosure=Classification.PERSONAL,
    ),
    ConstraintRecord(
        constraint_id="C-RES-005",
        kind=ConstraintKind.SOFT,
        domain=ConstraintDomain.AVAILABILITY,
        title="Performer prep allowance",
        description="A performer should have their full prep allowance before the first shot.",
        owner=Role.FIRST_AD,
        source="Cast agreements",
        source_evidence="PERFORMERS.prep_minutes",
        priority=40,
        solver_encoding="resource.performer_availability",
        disclosure=Classification.PERSONAL,
    ),
    ConstraintRecord(
        constraint_id="C-RES-006",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.AVAILABILITY,
        title="Performer exclusivity and travel",
        description="A performer cannot be in two scenes at once, or travel faster than the "
                    "travel matrix allows.",
        owner=Role.FIRST_AD,
        source="Schedule integrity",
        source_evidence="Travel matrix; scene assignments",
        priority=2,
        solver_encoding="resource.performer_exclusivity",
        disclosure=Classification.PERSONAL,
    ),
    ConstraintRecord(
        constraint_id="C-RES-007",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.AVAILABILITY,
        title="Critical crew availability",
        description="A unit may not work without its critical crew.",
        owner=Role.UPM,
        source="Crew list and department assignments",
        source_evidence="CREW.critical",
        priority=2,
        solver_encoding="resource.critical_crew",
    ),
    # -- locations and permits --------------------------------------------
    ConstraintRecord(
        constraint_id="C-LOC-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.LOCATION,
        title="Location availability",
        description="A location must be open and not closed by an active event.",
        owner=Role.LOCATION_MANAGER,
        source="Location agreements",
        source_evidence="LOCATIONS: available_from, available_to; live closure events",
        priority=2,
        solver_encoding="location.availability",
    ),
    ConstraintRecord(
        constraint_id="C-LOC-002",
        kind=ConstraintKind.SOFT,
        domain=ConstraintDomain.LOCATION,
        title="Noise curfew",
        description="Work should end before a location's noise curfew.",
        owner=Role.LOCATION_MANAGER,
        source="Location agreements and residential permits",
        source_evidence="LOCATIONS.noise_curfew",
        priority=30,
        solver_encoding="location.availability",
    ),
    ConstraintRecord(
        constraint_id="C-LOC-003",
        kind=ConstraintKind.SOFT,
        domain=ConstraintDomain.LOCATION,
        title="Location working party capacity",
        description="The working party a scene requires should fit the location.",
        owner=Role.LOCATION_MANAGER,
        source="Location surveys",
        source_evidence="LOCATIONS.capacity_crew",
        priority=35,
        solver_encoding="location.capacity",
    ),
    ConstraintRecord(
        constraint_id="C-PERM-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.PERMIT,
        title="Permit validity",
        description="Every permit a location requires must be valid and cover the working window.",
        owner=Role.LOCATION_MANAGER,
        source="Issued permits",
        source_evidence="PERMITS: valid_from, valid_to, status",
        priority=1,
        solver_encoding="permit.validity",
    ),
    ConstraintRecord(
        constraint_id="C-PERM-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.PERMIT,
        title="Permit setup cutoff",
        description="A permit condition prohibiting setup after a stated time is binding.",
        owner=Role.LOCATION_MANAGER,
        source="Boatshed occupancy permit PERM-BOATSHED-01",
        source_evidence="Permit condition: no new rigging or setup activity after 21:00",
        priority=1,
        solver_encoding="permit.validity",
    ),
    ConstraintRecord(
        constraint_id="C-PERM-003",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.PERMIT,
        title="Permit maximum persons",
        description="A permit's stated occupancy limit is binding.",
        owner=Role.LOCATION_MANAGER,
        source="Issued permits",
        source_evidence="PERMITS.max_crew",
        priority=2,
        solver_encoding="permit.validity",
    ),
    # -- approved access arrangements -------------------------------------
    ConstraintRecord(
        constraint_id="C-ACC-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.ACCESS,
        title="Step-free route to the working position",
        description=(
            "Where an approved step-free requirement applies, the location must offer a "
            "step-free route from arrival to working position, evidenced by the access survey "
            "and the spatial twin. This is a hard constraint and is never traded against cost "
            "or delay."
        ),
        owner=Role.ACCESS_COORDINATOR,
        source="Approved access arrangement ACC-001",
        source_evidence="Access survey; spatial twin STEP_FREE_LIMITS",
        priority=1,
        solver_encoding="access.step_free_route",
        subject_ids=("ACC-001",),
        disclosure=Classification.OPERATIONAL_REQUIREMENT,
        parameters={"max_gradient": "1:15", "min_clear_width_mm": 850, "max_threshold_mm": 20},
    ),
    ConstraintRecord(
        constraint_id="C-ACC-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.TRANSPORT,
        title="Accessible transport available and able to arrive",
        description=(
            "A step-free vehicle with an available driver must be able to reach the location "
            "before the call and return after wrap."
        ),
        owner=Role.ACCESS_COORDINATOR,
        source="Approved access arrangement ACC-001",
        source_evidence="VEHICLES.step_free; BOOK-TRANSPORT-1; travel matrix",
        priority=1,
        solver_encoding="access.accessible_transport",
        subject_ids=("ACC-001",),
        disclosure=Classification.OPERATIONAL_REQUIREMENT,
    ),
    ConstraintRecord(
        constraint_id="C-ACC-003",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.COMMUNICATION,
        title="Interpretation covers every called minute",
        description=(
            "Interpretation must cover the full period the person is called, by the union of "
            "confirmed bookings and any extension the plan includes with sufficient notice."
        ),
        owner=Role.ACCESS_COORDINATOR,
        source="Approved access arrangement ACC-002",
        source_evidence="BOOK-INTERP-1, BOOK-INTERP-2; extension notice periods",
        priority=1,
        solver_encoding="access.interpreter_coverage",
        subject_ids=("ACC-002",),
        disclosure=Classification.OPERATIONAL_REQUIREMENT,
    ),
    ConstraintRecord(
        constraint_id="C-ACC-004",
        kind=ConstraintKind.CONDITIONAL,
        domain=ConstraintDomain.COMMUNICATION,
        title="Revised briefing available in approved accessible formats",
        description=(
            "If a revised briefing is required and a person with an approved communication "
            "arrangement is working, the briefing must exist in written and captioned form "
            "before delivery."
        ),
        owner=Role.SAFETY_LEAD,
        source="Approved access arrangement ACC-003",
        source_evidence="POLICIES['communication'].accessible_formats_required",
        priority=1,
        solver_encoding="access.accessible_briefing",
        subject_ids=("ACC-003",),
        disclosure=Classification.OPERATIONAL_REQUIREMENT,
    ),
    ConstraintRecord(
        constraint_id="C-ACC-005",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.STORAGE,
        title="Support resources present where the work is",
        description=(
            "Refrigerated storage, quiet rest space and comparable approved arrangements must "
            "be available at the location where the person is working, either already present "
            "or explicitly relocated by the plan with setup time allowed."
        ),
        owner=Role.ACCESS_COORDINATOR,
        source="Approved access arrangements ACC-004, ACC-005",
        source_evidence="SUPPORT_RESOURCES; plan support_moves",
        priority=1,
        solver_encoding="access.support_resource",
        subject_ids=("ACC-004", "ACC-005"),
        disclosure=Classification.OPERATIONAL_REQUIREMENT,
    ),
    ConstraintRecord(
        constraint_id="C-ACC-006",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.ACCESS,
        title="Approved caregiving release time",
        description="An approved caregiving release time is binding on the schedule.",
        owner=Role.UPM,
        source="Approved caregiving arrangement ACC-006",
        source_evidence="ACCESS_REQUIREMENTS ACC-006 window",
        priority=1,
        solver_encoding="access.caregiving_window",
        subject_ids=("ACC-006",),
        disclosure=Classification.OPERATIONAL_REQUIREMENT,
    ),
    # -- continuity and time ----------------------------------------------
    ConstraintRecord(
        constraint_id="C-CONT-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.CONTINUITY,
        title="Continuity precedence",
        description="A scene carrying state forward must shoot after the scene establishing it.",
        owner=Role.DEPARTMENT_HEAD,
        source="Continuity breakdown",
        source_evidence="Scene continuity notes; twin follows_continuity edges",
        priority=4,
        solver_encoding="continuity.story_day_order",
    ),
    ConstraintRecord(
        constraint_id="C-CONT-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.CONTINUITY,
        title="Irreversible makeup and wardrobe state",
        description="Once a wet-down is played, dry material from the same story day cannot "
                    "follow it on the same day.",
        owner=Role.DEPARTMENT_HEAD,
        source="Continuity breakdown, SC-025 note",
        source_evidence="Scene SC-025 continuity_notes",
        priority=4,
        solver_encoding="continuity.wet_down",
    ),
    ConstraintRecord(
        constraint_id="C-TIME-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.DAYLIGHT,
        title="Daylight and darkness requirements",
        description="Day exteriors need daylight; night exteriors need darkness.",
        owner=Role.FIRST_AD,
        source="Script scene headings and almanac",
        source_evidence="Scene daylight_required / night_required; DAYLIGHT window",
        priority=3,
        solver_encoding="temporal.daylight",
    ),
    ConstraintRecord(
        constraint_id="C-TIME-002",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.LOCATION,
        title="Company move travel time",
        description="A unit must have time to reach its next location.",
        owner=Role.FIRST_AD,
        source="Travel time assumptions",
        source_evidence="TRAVEL_MINUTES matrix",
        priority=3,
        solver_encoding="temporal.travel",
    ),
    ConstraintRecord(
        constraint_id="C-TIME-003",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.RESOURCE,
        title="Setup and shooting durations respected",
        description="A plan must allow each scene its estimated setup and shooting time.",
        owner=Role.FIRST_AD,
        source="Scene estimates and duration model",
        source_evidence="Scene setup_minutes, shoot_minutes",
        priority=3,
        solver_encoding="temporal.setup_window",
    ),
    ConstraintRecord(
        constraint_id="C-SCOPE-001",
        kind=ConstraintKind.HARD,
        domain=ConstraintDomain.APPROVAL,
        title="Every published scene accounted for",
        description="A plan must schedule, defer or explicitly move every scene on the "
                    "published day.",
        owner=Role.COORDINATOR,
        source="Published call sheet",
        source_evidence="BASELINE_SCHEDULE",
        priority=5,
        solver_encoding="scope.mandatory_scenes",
    ),
)

CONSTRAINTS_BY_ID: dict[str, ConstraintRecord] = {c.constraint_id: c for c in CONSTRAINTS}

#: Soft-constraint objective weights. Used to rank feasible plans only — a hard
#: constraint has no weight because it cannot be traded.
SOFT_WEIGHTS: dict[str, float] = {
    "delay_minutes": 1.0,
    "cost_delta": 0.02,
    "overtime_minutes": 1.4,
    "idle_crew_minutes": 0.3,
    "travel_minutes": 0.25,
    "setup_complexity": 0.6,
    "weather_exposure": 1.1,
    "continuity_risk": 1.6,
    "operational_risk": 1.3,
    "communication_burden": 0.5,
    "changed_assignments": 2.0,
}


class RegistryError(RuntimeError):
    pass


def validate_registry() -> None:
    """Every constraint must name a predicate that exists. Raises if not."""
    missing = sorted(
        {c.solver_encoding for c in CONSTRAINTS if c.solver_encoding not in PREDICATES}
    )
    if missing:
        raise RegistryError(
            "constraints reference predicates that do not exist: " + ", ".join(missing)
        )
    duplicates = [
        cid for cid in {c.constraint_id for c in CONSTRAINTS}
        if sum(1 for c in CONSTRAINTS if c.constraint_id == cid) > 1
    ]
    if duplicates:
        raise RegistryError(f"duplicate constraint ids: {sorted(set(duplicates))}")
    # Every predicate should be reachable from at least one constraint, or it is
    # dead code that will rot.
    unused = sorted(set(PREDICATES) - {c.solver_encoding for c in CONSTRAINTS})
    if unused:
        raise RegistryError(f"predicates with no constraint record: {unused}")


validate_registry()


def active_constraints(
    when: datetime | None = None,
    *,
    kinds: tuple[ConstraintKind, ...] | None = None,
) -> tuple[ConstraintRecord, ...]:
    """Constraints in force at a moment."""
    out = []
    for c in CONSTRAINTS:
        if kinds is not None and c.kind not in kinds:
            continue
        if when is not None:
            if c.effective_from and when < c.effective_from:
                continue
            if c.effective_to and when > c.effective_to:
                continue
        out.append(c)
    return tuple(out)


def constraint_set_hash(constraints: tuple[ConstraintRecord, ...] | None = None) -> str:
    """Identity of the active constraint set.

    Approvals are bound to this. An approval granted while a constraint was
    inactive cannot be replayed once it returns, because the hash will not match.
    """
    records = constraints if constraints is not None else CONSTRAINTS
    return stable_hash(sorted(
        (c.constraint_id, c.kind.value, c.solver_encoding, sorted(c.parameters.items()))
        for c in records
    ))


def evaluate(
    plan: CandidatePlan,
    problem: SchedulingProblem,
    constraints: tuple[ConstraintRecord, ...] | None = None,
) -> list[ConstraintViolation]:
    """Run every active constraint's predicate against a plan.

    Predicates are run once per *distinct predicate*, not once per constraint,
    because several constraint records share an implementation (the three
    child-performer rules are one function). Violations carry their own
    constraint id, so the mapping back is exact.
    """
    records = constraints if constraints is not None else active_constraints()
    wanted = {c.solver_encoding for c in records}
    known_ids = {c.constraint_id for c in records}
    violations: list[ConstraintViolation] = []
    for name in sorted(wanted):
        fn = PREDICATES[name]
        for violation in fn(plan, problem):  # type: ignore[operator]
            if violation.constraint_id in known_ids:
                violations.append(violation)
    return violations


def blocking(violations: list[ConstraintViolation]) -> list[ConstraintViolation]:
    return [v for v in violations if v.severity == "blocking"]


def at_risk(violations: list[ConstraintViolation]) -> list[ConstraintViolation]:
    return [v for v in violations if v.severity == "at_risk"]


# ---------------------------------------------------------------------------
# Approval authority matrix
# ---------------------------------------------------------------------------

#: Which role must approve which kind of change. A change type absent from this
#: table cannot be executed at all — the policy agent fails closed.
APPROVAL_MATRIX: dict[str, tuple[Role, ...]] = {
    "schedule_change": (Role.FIRST_AD,),
    "major_schedule_change": (Role.FIRST_AD, Role.UPM),
    "location_change": (Role.UPM, Role.LOCATION_MANAGER),
    "safety_exception": (Role.SAFETY_LEAD,),
    "cost_increase": (Role.UPM,),
    "overtime": (Role.UPM,),
    "additional_vendor": (Role.UPM,),
    "resource_substitution": (Role.UPM,),
    "access_arrangement_change": (Role.ACCESS_COORDINATOR, Role.UPM),
    "crew_call_time_change": (Role.FIRST_AD,),
    "public_communication": (Role.UPM,),
    "emergency_action": (Role.SAFETY_LEAD,),
}

#: Changes nobody may approve. These are the §13.4 decision boundaries expressed
#: as code rather than as a paragraph in a policy document.
PROHIBITED_CHANGES: dict[str, str] = {
    "remove_access_arrangement": (
        "An approved access arrangement cannot be removed to improve cost or schedule. "
        "Changing the arrangement itself is a separate decision owned by the accessibility "
        "coordinator and the person concerned, not a scheduling action."
    ),
    "waive_safety_control": (
        "The system does not approve safety exceptions. The safety lead does, outside it."
    ),
    "override_child_limit": (
        "Configured child performer limits are not waivable within the system."
    ),
    "rank_crew_by_cost": (
        "The system does not rank workers by cost or inconvenience."
    ),
    "infer_condition": (
        "The system does not infer or record a reason for an access requirement."
    ),
}


def required_approvals(change_types: set[str]) -> tuple[Role, ...]:
    roles: list[Role] = []
    for change in sorted(change_types):
        for role in APPROVAL_MATRIX.get(change, ()):
            if role not in roles:
                roles.append(role)
    return tuple(roles)
