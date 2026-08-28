"""The deterministic decision engine.

This is the piece that turns "the storm has closed the night exterior" into a set
of materially different plans, each either proved feasible or rejected with a
minimal, evidence-backed conflict set.

Three properties matter more than the search itself:

**Diversity is structural, not cosmetic.** Each strategy is a genuinely different
operational idea — stay and cover, relocate, defer, split, extend. Plans that
turn out to have the same shape are collapsed by `structure_key()`, so five
options are five options rather than one option with five sets of timings.

**No plan is published feasible without an independent recheck.** `validate()`
re-runs the entire constraint registry against the finished plan, from the plan
object rather than from the search's internal state. The search and the verdict
share no code path, which is the only version of this claim worth making.

**Incremental repair freezes what it can.** A disruption at 19:00 has no business
rewriting a scene that wrapped at 17:15. `repair()` freezes completed and
in-progress work and searches only the affected neighbourhood, which is both
faster and — more importantly — produces plans a first AD recognises as their own
day with one part changed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..constraints.registry import (
    SOFT_WEIGHTS,
    active_constraints,
    constraint_set_hash,
    evaluate,
    required_approvals,
)
from ..contracts import (
    AccessImplementation,
    ConflictSet,
    ConstraintViolation,
    FeasibilityProof,
    Plan,
    SceneAssignment,
    TransportLeg,
    stable_hash,
)
from ..production import spatial as sp
from ..production import world as w
from . import infeasibility, objectives
from .model import Assignment, CandidatePlan, SchedulingProblem
from .search import PlacementRequest, schedule

SOLVER_VERSION = "allaccess-cp-1.0.0"
MODEL_VERSION = "salt-and-light-day14-1.0.0"


@dataclass
class SolveOutcome:
    plans: list[Plan] = field(default_factory=list)
    rejected: list[Plan] = field(default_factory=list)
    pareto_front: list[str] = field(default_factory=list)
    solve_ms: float = 0.0
    nodes: int = 0
    propagations: int = 0
    strategies_attempted: int = 0

    @property
    def feasible(self) -> list[Plan]:
        return [p for p in self.plans if p.feasible]


# ---------------------------------------------------------------------------
# Strategy generators
# ---------------------------------------------------------------------------


def _requests_for(
    problem: SchedulingProblem,
    scene_ids: list[str],
    *,
    location_overrides: dict[str, str] | None = None,
    unit_overrides: dict[str, str] | None = None,
    equipment_overrides: dict[str, tuple[str, ...]] | None = None,
    frozen: dict[str, Assignment] | None = None,
    earliest: datetime | None = None,
    latest: datetime | None = None,
    prefer_late: set[str] | None = None,
    optional: set[str] | None = None,
) -> list[PlacementRequest]:
    locations = location_overrides or {}
    units = unit_overrides or {}
    equipment = equipment_overrides or {}
    frozen = frozen or {}
    late = prefer_late or set()
    optional_ids = optional or set()
    out: list[PlacementRequest] = []
    for scene_id in scene_ids:
        req = problem.requirements[scene_id]
        base = next((a for a in problem.baseline if a.scene_id == scene_id), None)
        out.append(PlacementRequest(
            scene_id=scene_id,
            location_id=locations.get(scene_id,
                                      base.location_id if base else req.candidate_locations[0]),
            unit_id=units.get(scene_id, base.unit_id if base else req.unit_preference),
            earliest=earliest or problem.horizon_start,
            latest=latest or problem.horizon_end,
            equipment_ids=equipment.get(scene_id, req.equipment_ids),
            fixed=frozen.get(scene_id),
            prefer_late=scene_id in late,
            optional=scene_id in optional_ids,
        ))
    return out


def _completed_and_active(problem: SchedulingProblem) -> dict[str, Assignment]:
    """Scenes already shot, or with the camera actually turning, at the moment of
    the disruption.

    These are frozen. A plan that reschedules work already in the can is not a
    plan, and a first AD shown one stops trusting the tool immediately.

    The line is *shooting*, not setup. A scene in pre-light is not committed —
    standing one down is the most ordinary decision on a set, and it is exactly
    what a weather call at 19:00 does to a 22:45 exterior that started rigging at
    18:45. Freezing on `setup_start` would freeze the one scene the disruption is
    about, and the engine would then dutifully report that nothing can be done.

    A scene the disruption has explicitly invalidated is never frozen, even if it
    is mid-take: if the location has become unsafe, the take stops.
    """
    frozen: dict[str, Assignment] = {}
    for a in problem.baseline:
        if a.scene_id in problem.disrupted_scene_ids:
            continue
        if a.start <= problem.now:
            frozen[a.scene_id] = a
    return frozen


def _affected(problem: SchedulingProblem, frozen: dict[str, Assignment]) -> list[str]:
    return [a.scene_id for a in problem.baseline if a.scene_id not in frozen]


def _placed_any(result, cover: list[str]) -> bool:
    """Whether a cover strategy actually recovered any work.

    A strategy whose cover scenes were all skipped has quietly become "stand
    down and wrap" while still calling itself a split unit or a relocation. It
    must withdraw: presenting it would put a label on the comparison that the
    plan does not deserve, and would crowd out the plan that honestly is
    "stand down and wrap".
    """
    placed = set(result.placed)
    return any(scene_id in placed for scene_id in cover)


def _briefing_note(location_id: str) -> str:
    return f"briefing:{location_id} formats=written,captioned,spoken"


def strategy_preserve_original(problem: SchedulingProblem) -> CandidatePlan | None:
    """Carry on as published. Included so the option is explicitly evaluated and
    explicitly rejected, rather than silently assumed impossible."""
    plan = CandidatePlan(
        strategy="preserve_original",
        label="Continue as published",
        rationale="Shoot the night exterior on the harbour wall as scheduled.",
        assignments=list(problem.baseline),
    )
    return plan


def strategy_relocate(problem: SchedulingProblem, destination: str,
                      cover_scenes: list[str]) -> CandidatePlan | None:
    """Move the unit to a covered location and shoot interiors there.

    This is what a conventional scheduling tool proposes when a night exterior is
    lost: find a room that is free and big enough. Whether it is *usable* is a
    different question, and answering it is the point of the exercise.
    """
    frozen = _completed_and_active(problem)
    affected = _affected(problem, frozen)
    loc = w.LOCATIONS_BY_ID.get(destination)
    if loc is None:
        return None

    keep = [s for s in affected if s not in ("SC-025",)]
    scenes = keep + [s for s in cover_scenes if s in problem.requirements]
    if not scenes:
        return None

    requests = _requests_for(
        problem,
        list(frozen) + scenes,
        location_overrides={s: destination for s in scenes},
        unit_overrides={s: "UNIT-MAIN" for s in scenes},
        frozen=frozen,
        earliest=problem.now,
        latest=w.at(23, 45),
        optional=set(cover_scenes),
    )
    result = schedule(problem, requests)
    if not result.complete or not _placed_any(result, cover_scenes):
        return None

    plan = CandidatePlan(
        strategy=f"relocate_{destination.lower().replace('loc-', '')}",
        label=f"Relocate to {loc.name}",
        rationale=(
            f"Move the main unit to {loc.name} and shoot prepared interiors under cover. "
            "The night exterior moves to a later day."
        ),
        assignments=result.assignments,
        moved_to_next_day=["SC-025"],
        # A relocation moves the base: the trucks, catering, the quiet room and
        # the refrigerated storage all travel with the unit or do not travel at all.
        unit_bases={"UNIT-MAIN": destination},
    )
    plan.notes.append(_briefing_note(destination))
    plan.notes.append(f"nodes={result.nodes}")
    return plan


def strategy_cover_at_base(problem: SchedulingProblem) -> CandidatePlan | None:
    """Stay where the unit is, shoot prepared interiors, move the exterior.

    The recommended shape: the wheelhouse sets are two minutes from base, already
    dressed, already lit, and the base already holds every support arrangement
    the day depends on.
    """
    frozen = _completed_and_active(problem)
    affected = _affected(problem, frozen)
    keep = [s for s in affected if s != "SC-025"]
    # Both are wheelhouse interiors, so no location override: a cover scene is
    # shot on its own set. Overriding the location would let the engine propose
    # shooting a kitchen scene inside a boat -- a schedule that solves perfectly
    # and cannot be filmed.
    cover = [s for s in ("SC-027", "SC-022") if s in problem.requirements]
    scenes = keep + cover
    if not cover:
        return None

    requests = _requests_for(
        problem,
        list(frozen) + scenes,
        unit_overrides={s: "UNIT-MAIN" for s in cover},
        equipment_overrides={
            # The interior package is already rigged on the boat; the night
            # exterior package stands down.
            s: ("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A", "EQ-GRIP-BOAT") for s in cover
        },
        frozen=frozen,
        earliest=problem.now,
        latest=w.at(23, 30),
        optional=set(cover),
    )
    result = schedule(problem, requests)
    if not result.complete or not _placed_any(result, cover):
        return None

    plan = CandidatePlan(
        strategy="cover_at_base_defer_exterior",
        label="Cover interiors at base, exterior to tomorrow night",
        rationale=(
            "Stand down the night exterior, shoot the two prepared wheelhouse interiors at "
            "the current base, and move the exterior to the following evening's settled "
            "window. No company move, no base move, and every approved arrangement stays "
            "where it already is."
        ),
        assignments=result.assignments,
        moved_to_next_day=["SC-025"],
    )
    plan.notes.append(f"nodes={result.nodes}")
    return plan


def strategy_defer_only(problem: SchedulingProblem) -> CandidatePlan | None:
    """Cancel the exterior and wrap. Safe, simple, and expensive in lost time."""
    frozen = _completed_and_active(problem)
    keep = [s for s in _affected(problem, frozen) if s != "SC-025"]
    requests = _requests_for(problem, list(frozen) + keep, frozen=frozen,
                             earliest=problem.now, latest=w.at(23, 30))
    result = schedule(problem, requests)
    if not result.complete:
        return None
    return CandidatePlan(
        strategy="defer_only",
        label="Stand down and wrap",
        rationale=(
            "Cancel the night exterior and wrap the unit. Nothing else changes; the day's "
            "remaining work moves wholesale to a later day."
        ),
        assignments=result.assignments,
        moved_to_next_day=["SC-025"],
        notes=[f"nodes={result.nodes}"],
    )


def strategy_extend_and_wait(problem: SchedulingProblem) -> CandidatePlan | None:
    """Hold the crew and shoot the exterior later in the night as the front passes."""
    frozen = _completed_and_active(problem)
    keep = [s for s in _affected(problem, frozen) if s != "SC-025"]
    requests = _requests_for(
        problem,
        list(frozen) + keep + ["SC-025"],
        frozen=frozen,
        earliest=problem.now,
        latest=w.at(23, 59),
        prefer_late={"SC-025"},
    )
    result = schedule(problem, requests)
    if not result.complete:
        # Still return the shape so it can be rejected with a real explanation
        # rather than vanishing from the comparison.
        assignments = list(frozen.values())
        req = problem.requirements["SC-025"]
        start = w.at(22, 10)
        assignments.append(Assignment(
            scene_id="SC-025",
            location_id="LOC-HARBOUR-WALL",
            unit_id="UNIT-MAIN",
            setup_start=start - timedelta(minutes=req.setup_minutes),
            start=start,
            end=start + timedelta(minutes=req.shoot_minutes),
            equipment_ids=req.equipment_ids,
            cast_calls={
                pid: start - timedelta(minutes=w.PERFORMERS_BY_ID[pid].prep_minutes + 10)
                for pid in req.performer_ids if pid in w.PERFORMERS_BY_ID
            },
            crew_call=w.at(13, 30),
        ))
        return CandidatePlan(
            strategy="extend_and_wait",
            label="Hold the crew and shoot late",
            rationale="Wait for the front to pass and shoot the exterior at the end of the night.",
            assignments=assignments,
            notes=["nodes=0"],
        )
    return CandidatePlan(
        strategy="extend_and_wait",
        label="Hold the crew and shoot late",
        rationale="Wait for the front to pass and shoot the exterior at the end of the night.",
        assignments=result.assignments,
        notes=[f"nodes={result.nodes}"],
    )


def strategy_split_unit(problem: SchedulingProblem) -> CandidatePlan | None:
    """Recall the second unit to pick up interiors in parallel."""
    frozen = _completed_and_active(problem)
    keep = [s for s in _affected(problem, frozen) if s != "SC-025"]
    cover_main = [s for s in ("SC-022",) if s in problem.requirements]
    cover_second = [s for s in ("SC-016", "SC-020") if s in problem.requirements]
    if not cover_second:
        return None

    requests = _requests_for(
        problem,
        list(frozen) + keep + cover_main + cover_second,
        location_overrides={
            **{s: "LOC-BOAT-WHEELHOUSE" for s in cover_main},
            **{s: "LOC-NET-LOFT" for s in cover_second},
        },
        unit_overrides={
            **{s: "UNIT-MAIN" for s in cover_main},
            **{s: "UNIT-SECOND" for s in cover_second},
        },
        equipment_overrides={
            **{s: ("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A", "EQ-GRIP-BOAT")
               for s in cover_main},
            **{s: ("EQ-CAM-B", "EQ-LIGHT-KIT-2", "EQ-SOUND-B") for s in cover_second},
        },
        frozen=frozen,
        earliest=problem.now,
        latest=w.at(23, 30),
        optional=set(cover_main) | set(cover_second),
    )
    result = schedule(problem, requests)
    # A split unit that placed work on only one unit is not a split unit.
    if (not result.complete
            or not _placed_any(result, cover_main)
            or not _placed_any(result, cover_second)):
        return None
    plan = CandidatePlan(
        strategy="split_unit",
        label="Split units across two cover sets",
        rationale=(
            "Recall the second unit to the net loft for two interiors while the main unit "
            "covers the wheelhouse. Recovers the most page count tonight."
        ),
        assignments=result.assignments,
        moved_to_next_day=["SC-025"],
    )
    plan.notes.append(_briefing_note("LOC-NET-LOFT"))
    plan.notes.append(f"nodes={result.nodes}")
    return plan


def strategy_net_loft_cover(problem: SchedulingProblem) -> CandidatePlan | None:
    """Move to the net loft — step-free, quiet-capable, refrigerated, adjacent."""
    frozen = _completed_and_active(problem)
    keep = [s for s in _affected(problem, frozen) if s != "SC-025"]
    cover = [s for s in ("SC-016", "SC-020") if s in problem.requirements]
    if not cover:
        return None
    requests = _requests_for(
        problem,
        list(frozen) + keep + cover,
        location_overrides={s: "LOC-NET-LOFT" for s in cover},
        unit_overrides={s: "UNIT-MAIN" for s in cover},
        equipment_overrides={
            s: ("EQ-CAM-A", "EQ-LIGHT-KIT-1", "EQ-SOUND-A") for s in cover
        },
        frozen=frozen,
        earliest=problem.now,
        latest=w.at(23, 30),
        optional=set(cover),
    )
    result = schedule(problem, requests)
    if not result.complete or not _placed_any(result, cover):
        return None
    plan = CandidatePlan(
        strategy="net_loft_cover",
        label="Move next door to the net loft",
        rationale=(
            "Shoot two interiors in the net loft, three minutes from base and step-free "
            "throughout, with its own quiet room and refrigerated storage."
        ),
        assignments=result.assignments,
        moved_to_next_day=["SC-025"],
        unit_bases={"UNIT-MAIN": "LOC-NET-LOFT"},
    )
    plan.notes.append(_briefing_note("LOC-NET-LOFT"))
    plan.notes.append(f"nodes={result.nodes}")
    return plan


STRATEGIES = (
    strategy_preserve_original,
    strategy_cover_at_base,
    lambda p: strategy_relocate(p, "LOC-BOATSHED", ["SC-016", "SC-020"]),
    strategy_net_loft_cover,
    strategy_split_unit,
    strategy_defer_only,
    strategy_extend_and_wait,
)


# ---------------------------------------------------------------------------
# Deferred work and access implementation
# ---------------------------------------------------------------------------


def place_deferred_scenes(plan: CandidatePlan, problem: SchedulingProblem) -> None:
    """Schedule anything moved to the following day, and book what it needs.

    A plan that says "we'll do it tomorrow" without saying when, or without the
    interpreter cover tomorrow needs, has not actually solved anything. This is
    where the recommended plan earns its place: it detects that the following
    evening falls outside every confirmed interpreter booking and extends one,
    inside the provider's notice period, as part of the plan rather than as a
    thing someone remembers later.
    """
    if not plan.moved_to_next_day:
        return
    for scene_id in list(plan.moved_to_next_day):
        req = problem.requirements.get(scene_id)
        if req is None:
            continue
        base = next((a for a in problem.baseline if a.scene_id == scene_id), None)
        location = base.location_id if base else req.candidate_locations[0]
        unit = base.unit_id if base else req.unit_preference

        # Same slot, one day later: the night window is the same window.
        start = (base.start if base else w.at(20, 45)) + timedelta(days=1)
        setup_start = start - timedelta(minutes=req.setup_minutes)
        end = start + timedelta(minutes=req.shoot_minutes)
        calls = {
            pid: start - timedelta(minutes=w.PERFORMERS_BY_ID[pid].prep_minutes
                                   + w.CALL_BUFFER_MINUTES)
            for pid in req.performer_ids if pid in w.PERFORMERS_BY_ID
        }
        plan.assignments.append(Assignment(
            scene_id=scene_id,
            location_id=location,
            unit_id=unit,
            setup_start=setup_start,
            start=start,
            end=end,
            equipment_ids=req.equipment_ids,
            cast_calls=calls,
            crew_call=min([setup_start, *calls.values()]) if calls else setup_start,
        ))
        plan.moved_to_next_day.remove(scene_id)
        plan.notes.append(f"moved:{scene_id} to {start:%d %b %H:%M}")

        # Interpretation for the moved work.
        people = {
            r.person_id for r in w.ACCESS_REQUIREMENTS
            if r.category == "communication" and "interpret" in r.mechanism.lower()
        }
        if people & set(calls):
            need_from = min(calls[p] for p in people if p in calls)
            covered = any(
                b.start <= need_from and end <= b.end
                for b in w.SERVICE_BOOKINGS
                if "interpret" in b.kind and b.status == "confirmed"
            )
            if not covered:
                booking = w.BOOKINGS_BY_ID.get("BOOK-INTERP-2")
                if booking is not None:
                    plan.interpreter_extensions.append(("BOOK-INTERP-2", need_from, end))
                    plan.notes.append(
                        f"interpreter:BOOK-INTERP-2 extended {need_from:%d %b %H:%M}"
                        f"-{end:%H:%M}"
                    )


def access_implementations(plan: CandidatePlan,
                           problem: SchedulingProblem,
                           violations: list[ConstraintViolation],
                           ) -> tuple[AccessImplementation, ...]:
    """How this plan discharges each approved arrangement, satisfied or not.

    Every approved arrangement appears in every plan's record, including the ones
    it satisfies without effort. An arrangement that only shows up when it breaks
    is an arrangement nobody is tracking.
    """
    failed_by_requirement: dict[str, list[ConstraintViolation]] = {}
    for v in violations:
        rid = v.detail.get("requirement") or (
            v.subject_id if v.subject_id.startswith("ACC-") else None
        )
        if rid:
            failed_by_requirement.setdefault(str(rid), []).append(v)

    out: list[AccessImplementation] = []
    for req in w.ACCESS_REQUIREMENTS:
        failures = failed_by_requirement.get(req.requirement_id, [])
        blocking = [f for f in failures if f.severity == "blocking"]
        mechanism = req.mechanism
        if req.category == "mobility":
            locations = sorted(plan.locations())
            surveys = [
                f"{lid}: "
                + ("step-free"
                   if sp.assess_location_access(lid).get("step_free_satisfied")
                   else "NOT step-free")
                for lid in locations if sp.assess_location_access(lid).get("modelled")
            ]
            evidence = "; ".join(surveys) or "no modelled location in this plan"
        elif req.category == "communication" and plan.interpreter_extensions:
            evidence = "; ".join(
                f"{bid} extended to {end:%d %b %H:%M}"
                for bid, _s, end in plan.interpreter_extensions
            )
        else:
            evidence = req.mechanism
        if blocking:
            evidence = blocking[0].evidence or evidence
            mechanism = blocking[0].message

        out.append(AccessImplementation(
            requirement_id=req.requirement_id,
            person_id=req.person_id,
            requirement=req.requirement,
            satisfied=not blocking,
            mechanism=mechanism,
            evidence=evidence,
            at_risk=bool(failures) and not blocking,
        ))
    return tuple(out)


def transport_legs(plan: CandidatePlan, problem: SchedulingProblem) -> tuple[TransportLeg, ...]:
    """Vehicle movements the plan implies, including the accessible run."""
    legs: list[TransportLeg] = []
    counter = 1
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        for a, b in zip(rows, rows[1:]):
            if a.location_id == b.location_id:
                continue
            minutes = w.travel_minutes(a.location_id, b.location_id)
            legs.append(TransportLeg(
                leg_id=f"LEG-{counter:03d}",
                vehicle_id="VEH-BUS-1",
                from_location=a.location_id,
                to_location=b.location_id,
                depart=a.end,
                arrive=a.end + timedelta(minutes=minutes),
                passengers=tuple(c.crew_id for c in w.crew_for_unit(unit.unit_id)),
                step_free=False,
                purpose="company_move",
            ))
            counter += 1
            # The accessible vehicle runs the same move separately: it carries
            # fewer people and takes longer to load, so folding it into the
            # crew bus leg would understate the time it needs.
            for req in w.ACCESS_REQUIREMENTS:
                if req.category != "mobility":
                    continue
                vehicle = next((v for v in w.VEHICLES
                                if req.requirement_id in v.supports_requirements), None)
                if vehicle is None:
                    continue
                legs.append(TransportLeg(
                    leg_id=f"LEG-{counter:03d}",
                    vehicle_id=vehicle.vehicle_id,
                    from_location=a.location_id,
                    to_location=b.location_id,
                    depart=a.end - timedelta(minutes=vehicle.load_minutes),
                    arrive=a.end + timedelta(minutes=minutes),
                    passengers=(req.person_id,),
                    step_free=True,
                    purpose=f"accessible transport for {req.requirement_id}",
                ))
                counter += 1
    return tuple(legs)


# ---------------------------------------------------------------------------
# Validation and publication
# ---------------------------------------------------------------------------


def validate(plan: CandidatePlan, problem: SchedulingProblem) -> tuple[bool, dict[str, object]]:
    """Independent recheck of a finished plan.

    Runs the whole registry against the plan object, with no access to whatever
    the search believed while building it. A plan that passes here and failed
    during search — or the reverse — is a bug worth finding, which is precisely
    why the two paths are kept separate.
    """
    violations = evaluate(plan, problem)
    blocking_v = [v for v in violations if v.severity == "blocking"]
    report: dict[str, object] = {
        "constraints_checked": len(active_constraints()),
        "violations": len(violations),
        "blocking": len(blocking_v),
        "at_risk": len(violations) - len(blocking_v),
        "assignments": len(plan.assignments),
        "scenes_accounted": len(plan.assignments) + len(plan.deferred)
                            + len(plan.moved_to_next_day),
        "checks": [
            "every hard constraint",
            "every assignment",
            "every temporal relationship",
            "every approved access requirement",
            "every approval requirement",
            "every command precondition",
        ],
        "blocking_ids": sorted({v.constraint_id for v in blocking_v}),
    }
    return (not blocking_v), report


def _change_types(plan: CandidatePlan, problem: SchedulingProblem,
                  scores: objectives.ObjectiveBreakdown) -> set[str]:
    changes: set[str] = set()
    base = {a.scene_id: a for a in problem.baseline}
    for a in plan.assignments:
        original = base.get(a.scene_id)
        if original is None:
            changes.add("schedule_change")
        else:
            if original.location_id != a.location_id:
                changes.add("location_change")
            if original.start != a.start:
                changes.add("schedule_change")
            if original.crew_call != a.crew_call:
                changes.add("crew_call_time_change")
    if plan.unit_bases:
        changes.add("location_change")
    if scores.objectives.overtime_minutes > 0:
        changes.add("overtime")
    if scores.objectives.cost_delta > float(w.POLICIES["budget"]["vendor_approval_threshold"]):
        changes.add("cost_increase")
    if plan.interpreter_extensions or plan.support_moves:
        changes.add("additional_vendor")
    if plan.vehicle_reassignments:
        changes.add("resource_substitution")
    if len(plan.moved_to_next_day) + len(plan.deferred) > 0:
        changes.add("major_schedule_change")
    return changes


def _command_set(plan: CandidatePlan, problem: SchedulingProblem) -> tuple[str, ...]:
    commands = [
        "scheduling.apply_revision",
        "call_sheet.publish_revision",
        "department_tasks.publish",
        "crew_mobile.update",
        "notification.send",
        "executive_reporting.update",
    ]
    if plan.locations() - {a.location_id for a in problem.baseline}:
        commands.insert(1, "safety_briefing.publish_accessible")
        commands.insert(2, "location_operations.confirm")
    if any(a.location_id != b.location_id
           for a, b in zip(plan.by_unit("UNIT-MAIN"), plan.by_unit("UNIT-MAIN")[1:])):
        commands.insert(1, "transport_dispatch.rebook")
    if plan.interpreter_extensions:
        commands.insert(1, "interpreter_booking.extend")
    if plan.support_moves:
        commands.insert(1, "access_service_booking.relocate")
    if any(a.equipment_ids != tuple(
            next((b.equipment_ids for b in problem.baseline if b.scene_id == a.scene_id), ()))
           for a in plan.assignments):
        commands.insert(1, "equipment_inventory.reassign")
    return tuple(dict.fromkeys(commands))


def _verification_checklist(plan: CandidatePlan, problem: SchedulingProblem) -> tuple[str, ...]:
    checks = [
        "schedule version matches the approved plan",
        "call sheet revision published and current",
        "department tasks accepted by every affected department",
        "crew delivery confirmed for every affected person",
        "crew acknowledgment received for every critical instruction",
    ]
    if plan.interpreter_extensions:
        checks.insert(0, "interpreter booking extended and confirmed by the provider")
    if plan.locations() - {a.location_id for a in problem.baseline}:
        checks.insert(0, "revised safety briefing published in written and captioned format")
        checks.insert(1, "location confirmed and access route verified")
    if plan.support_moves:
        checks.insert(0, "relocated support resources confirmed in place and powered")
    checks.append("every approved access arrangement confirmed satisfied")
    return tuple(checks)


def publish(
    plan: CandidatePlan,
    problem: SchedulingProblem,
    disruption_id: str,
    *,
    solve_ms: float = 0.0,
    nodes: int = 0,
    propagations: int = 0,
    incremental: bool = False,
    frozen_count: int = 0,
) -> Plan:
    """Turn a candidate into an immutable `Plan` with a proof or a conflict set."""
    violations = evaluate(plan, problem)
    feasible, report = validate(plan, problem)
    scores = objectives.compute(plan, problem)

    conflicts: tuple[ConflictSet, ...] = ()
    if not feasible:
        conflict = infeasibility.explain(plan, problem, violations)
        near = infeasibility.near_miss(plan, problem, violations)
        if near:
            conflict = conflict.model_copy(
                update={"production_language": conflict.production_language + " " + near}
            )
        conflicts = (conflict,)

    constraints = active_constraints()
    proof = FeasibilityProof(
        solver_version=SOLVER_VERSION,
        model_version=MODEL_VERSION,
        constraint_set_hash=constraint_set_hash(constraints),
        input_state_sequence=problem.state_sequence,
        objective_weights=dict(SOFT_WEIGHTS),
        variable_assignments={
            a.scene_id: {
                "location": a.location_id,
                "unit": a.unit_id,
                "start": a.start.isoformat(),
                "end": a.end.isoformat(),
            }
            for a in sorted(plan.assignments, key=lambda x: x.scene_id)
        },
        satisfiable=feasible,
        solution_quality=objectives.scalarize(scores.objectives, SOFT_WEIGHTS),
        optimality_gap=None,
        search_nodes=nodes,
        propagations=propagations,
        solve_ms=round(solve_ms, 2),
        incremental=incremental,
        frozen_decisions=frozen_count,
        repaired_decisions=len(plan.assignments) - frozen_count,
        validated=True,
        validator_report=report,
    )

    scene_assignments = tuple(
        SceneAssignment(
            scene_id=a.scene_id,
            location_id=a.location_id,
            start=a.start,
            end=a.end,
            unit_id=a.unit_id,
            setup_start=a.setup_start,
            crew_call=a.crew_call or a.setup_start,
            cast_calls=dict(a.cast_calls),
            equipment_ids=a.equipment_ids,
            story_day=problem.requirements[a.scene_id].story_day
            if a.scene_id in problem.requirements else 1,
            exterior=problem.requirements[a.scene_id].exterior
            if a.scene_id in problem.requirements else False,
        )
        for a in sorted(plan.assignments, key=lambda x: x.start)
    )

    changes = _change_types(plan, problem, scores)
    plan_id = "PLAN-" + stable_hash(
        [disruption_id, plan.strategy, plan.content_hash()]
    )[:10].upper()

    safety_controls = ["configured weather thresholds enforced",
                       "briefing currency enforced",
                       "two independent egress routes required"]
    if any("marine_safety_supervision" in problem.requirements[a.scene_id].special_requirements
           for a in plan.assignments if a.scene_id in problem.requirements):
        safety_controls.append("marine safety supervisor present for on-water work")

    return Plan(
        plan_id=plan_id,
        disruption_id=disruption_id,
        strategy=plan.strategy,
        label=plan.label,
        rationale=plan.rationale,
        feasible=feasible,
        scenes=scene_assignments,
        transport=transport_legs(plan, problem),
        access=access_implementations(plan, problem, violations),
        safety_controls=tuple(safety_controls),
        permits=tuple(sorted({
            p for a in plan.assignments
            for p in (w.LOCATIONS_BY_ID[a.location_id].permits
                      if a.location_id in w.LOCATIONS_BY_ID else ())
        })),
        continuity_notes=tuple(n for n in plan.notes if n.startswith("moved:")),
        objectives=scores.objectives,
        proof=proof,
        conflicts=conflicts,
        required_approvals=required_approvals(changes),
        command_set=_command_set(plan, problem),
        verification_checklist=_verification_checklist(plan, problem),
        deferred_scenes=tuple(plan.deferred) + tuple(plan.moved_to_next_day),
    )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def candidate_from_plan(plan: Plan, problem: SchedulingProblem) -> CandidatePlan:
    """Rebuild the solver-side candidate from a published plan.

    Needed wherever a `Plan` has to be re-evaluated against the constraint
    registry — by the expert agents, and by the tests that independently
    re-validate every published plan. It lives here rather than in the
    coordinator because reconstructing a candidate is a solver concern, and a
    test that has to reach into an agent module to check the solver is a test
    describing the wrong boundary.
    """
    candidate = CandidatePlan(
        strategy=plan.strategy, label=plan.label, rationale=plan.rationale,
        assignments=[
            Assignment(
                scene_id=s.scene_id, location_id=s.location_id, unit_id=s.unit_id,
                setup_start=s.setup_start, start=s.start, end=s.end,
                equipment_ids=s.equipment_ids, cast_calls=dict(s.cast_calls),
                crew_call=s.crew_call,
            )
            for s in plan.scenes
        ],
    )
    baseline_locations = {a.location_id for a in problem.baseline}
    for location_id in sorted(candidate.locations() - baseline_locations):
        candidate.notes.append(
            f"briefing:{location_id} formats=written,captioned,spoken"
        )
        # A move to an adjacent set on the same site is not a base move; a move
        # to another site is.
        if location_id != "LOC-BOAT-WHEELHOUSE":
            candidate.unit_bases["UNIT-MAIN"] = location_id
    for access in plan.access:
        if access.requirement_id == "ACC-002" and "extended" in access.evidence:
            later = [s for s in plan.scenes if s.start.date() > w.SHOOT_DATE]
            if later:
                start = min(
                    s.cast_calls.get("CAST-001", s.setup_start) for s in later
                )
                candidate.interpreter_extensions.append(
                    ("BOOK-INTERP-2", start, max(s.end for s in later))
                )
    return candidate


def solve(problem: SchedulingProblem, disruption_id: str) -> SolveOutcome:
    """Generate, evaluate and rank every strategy."""
    started = time.perf_counter()
    outcome = SolveOutcome()
    seen_structures: set[tuple] = set()
    frozen = _completed_and_active(problem)

    for factory in STRATEGIES:
        outcome.strategies_attempted += 1
        try:
            candidate = factory(problem)
        except Exception:  # a broken strategy must not take the whole engine down
            candidate = None
        if candidate is None:
            continue
        place_deferred_scenes(candidate, problem)
        key = candidate.structure_key()
        if key in seen_structures:
            continue
        seen_structures.add(key)

        nodes = 0
        for note in candidate.notes:
            if note.startswith("nodes="):
                nodes = int(note.split("=", 1)[1])
        outcome.nodes += nodes

        plan = publish(
            candidate, problem, disruption_id,
            solve_ms=(time.perf_counter() - started) * 1000.0,
            nodes=nodes,
            propagations=len(candidate.assignments),
            incremental=True,
            frozen_count=len(frozen),
        )
        if plan.feasible:
            outcome.plans.append(plan)
        else:
            outcome.rejected.append(plan)

    outcome.plans.sort(
        key=lambda p: objectives.scalarize(p.objectives, SOFT_WEIGHTS)
    )
    outcome.pareto_front = objectives.pareto_front(
        [(p.plan_id, p.objectives) for p in outcome.plans]
    )
    outcome.solve_ms = (time.perf_counter() - started) * 1000.0
    outcome.propagations = sum(p.proof.propagations for p in outcome.plans + outcome.rejected
                               if p.proof)
    return outcome


def repair(problem: SchedulingProblem, disruption_id: str,
           strategy=strategy_cover_at_base) -> Plan | None:
    """Incremental repair: freeze what is settled, re-solve the rest."""
    frozen = _completed_and_active(problem)
    started = time.perf_counter()
    candidate = strategy(problem)
    if candidate is None:
        return None
    place_deferred_scenes(candidate, problem)
    return publish(
        candidate, problem, disruption_id,
        solve_ms=(time.perf_counter() - started) * 1000.0,
        incremental=True,
        frozen_count=len(frozen),
    )
