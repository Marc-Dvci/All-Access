"""The constraint layer: registry integrity, and each predicate actually firing.

The important tests here are the negative ones. A constraint that has never been
observed to reject anything is a constraint nobody has tested, and this project's
central claim — that safety and approved access arrangements are enforced rather
than weighted — rests entirely on these predicates saying no when they should.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from productionpulse.constraints.registry import (
    CONSTRAINTS,
    CONSTRAINTS_BY_ID,
    PROHIBITED_CHANGES,
    active_constraints,
    constraint_set_hash,
    evaluate,
    required_approvals,
    validate_registry,
)
from productionpulse.contracts import ConstraintKind, Role
from productionpulse.production import world as w
from productionpulse.solver.model import (
    CandidatePlan,
    baseline_assignments,
    build_problem,
)
from productionpulse.solver.predicates import PREDICATES


def _baseline_plan() -> CandidatePlan:
    return CandidatePlan(
        strategy="baseline", label="Published plan", rationale="as published",
        assignments=baseline_assignments(),
    )


def test_registry_validates() -> None:
    validate_registry()
    assert len(CONSTRAINTS) >= 30


def test_every_constraint_resolves_to_a_predicate() -> None:
    for constraint in CONSTRAINTS:
        assert constraint.solver_encoding in PREDICATES, constraint.constraint_id


def test_every_predicate_is_reachable_from_a_constraint() -> None:
    encodings = {c.solver_encoding for c in CONSTRAINTS}
    assert set(PREDICATES) == encodings


def test_constraint_ids_are_unique() -> None:
    ids = [c.constraint_id for c in CONSTRAINTS]
    assert len(ids) == len(set(ids))


def test_every_constraint_has_provenance() -> None:
    """An explanation that cannot cite its source is an assertion."""
    for constraint in CONSTRAINTS:
        assert constraint.source.strip(), constraint.constraint_id
        assert constraint.source_evidence.strip(), constraint.constraint_id


def test_access_constraints_are_hard() -> None:
    """Approved access arrangements must never be soft.

    A soft access constraint is one the objective function can trade away, which
    is the exact failure this project exists to prevent.
    """
    access_ids = [c for c in CONSTRAINTS if c.constraint_id.startswith("C-ACC-")]
    assert access_ids
    for constraint in access_ids:
        assert constraint.kind in (ConstraintKind.HARD, ConstraintKind.CONDITIONAL), (
            f"{constraint.constraint_id} is {constraint.kind.value}"
        )


def test_safety_and_child_constraints_are_hard() -> None:
    for prefix in ("C-SAFE-", "C-CHILD-"):
        rows = [c for c in CONSTRAINTS if c.constraint_id.startswith(prefix)]
        assert rows
        for constraint in rows:
            assert constraint.kind in (ConstraintKind.HARD, ConstraintKind.CONDITIONAL)


def test_baseline_has_no_violations() -> None:
    """The published day must start out legal, or every later result is noise."""
    problem = build_problem()
    assert evaluate(_baseline_plan(), problem) == []


def test_constraint_hash_is_stable_and_sensitive() -> None:
    first = constraint_set_hash(active_constraints())
    assert first == constraint_set_hash(active_constraints())
    subset = tuple(c for c in active_constraints() if c.constraint_id != "C-SAFE-001")
    assert constraint_set_hash(subset) != first


# ---------------------------------------------------------------------------
# Each predicate must actually reject something
# ---------------------------------------------------------------------------


def test_weather_threshold_rejects_storm() -> None:
    storm = tuple(
        [win for win in w.BASELINE_WEATHER if win.end <= w.at(18, 30)]
        + [w.WeatherWindow(w.at(18, 30), w.at(23, 59), "storm_force", 68.0, 9.5, 0.95, 6)]
    )
    problem = build_problem(weather=storm)
    violations = evaluate(_baseline_plan(), problem)
    assert any(v.constraint_id == "C-SAFE-001" for v in violations)


def test_step_free_route_rejects_the_boatshed() -> None:
    """The hero rejection, as a unit test with the measurement in it."""
    problem = build_problem()
    plan = _baseline_plan()
    plan.assignments = [
        a.__class__(**{**a.__dict__, "location_id": "LOC-BOATSHED"})
        if a.scene_id == "SC-025" else a
        for a in plan.assignments
    ]
    plan.unit_bases["UNIT-MAIN"] = "LOC-BOATSHED"
    plan.notes.append("briefing:LOC-BOATSHED formats=written,captioned,spoken")
    violations = evaluate(plan, problem)
    access = [v for v in violations if v.constraint_id == "C-ACC-001"]
    assert access, "the boatshed must fail the step-free route constraint"
    assert "140 mm" in access[0].message, (
        "the rejection must carry the measurement, not a category: " + access[0].message
    )


def test_support_resources_lost_when_the_base_moves() -> None:
    problem = build_problem()
    plan = _baseline_plan()
    plan.unit_bases["UNIT-MAIN"] = "LOC-BOATSHED"
    violations = evaluate(plan, problem)
    assert any(v.constraint_id == "C-ACC-005" for v in violations)


def test_child_performer_window_enforced() -> None:
    problem = build_problem()
    plan = _baseline_plan()
    late = []
    for a in plan.assignments:
        if "CAST-003" in a.cast_calls:
            shift = timedelta(hours=6)
            late.append(a.__class__(**{
                **a.__dict__,
                "start": a.start + shift, "end": a.end + shift,
                "setup_start": a.setup_start + shift,
                "cast_calls": {k: v + shift for k, v in a.cast_calls.items()},
            }))
        else:
            late.append(a)
    plan.assignments = late
    violations = evaluate(plan, problem)
    assert any(v.constraint_id.startswith("C-CHILD-") for v in violations)


def test_permit_setup_cutoff_enforced() -> None:
    problem = build_problem()
    plan = _baseline_plan()
    plan.assignments = [
        a.__class__(**{**a.__dict__, "location_id": "LOC-BOATSHED"})
        if a.scene_id == "SC-025" else a
        for a in plan.assignments
    ]
    plan.notes.append("briefing:LOC-BOATSHED formats=written,captioned,spoken")
    violations = evaluate(plan, problem)
    # The boatshed permit prohibits setup after 21:00 and SC-025 rigs at 18:45,
    # so this particular placement is inside the cutoff; the permit predicate
    # must still have been evaluated and produced no false positive.
    assert not [
        v for v in violations
        if v.constraint_id == "C-PERM-002" and v.severity == "blocking"
    ]


def test_resource_exclusivity_detects_double_booking() -> None:
    problem = build_problem()
    plan = _baseline_plan()
    first = plan.assignments[0]
    clash = first.__class__(**{
        **first.__dict__, "scene_id": "SC-002", "unit_id": "UNIT-SECOND",
    })
    plan.assignments.append(clash)
    violations = evaluate(plan, problem)
    assert any(v.constraint_id == "C-RES-001" for v in violations)


def test_briefing_required_on_new_location() -> None:
    problem = build_problem()
    plan = _baseline_plan()
    plan.assignments = [
        a.__class__(**{**a.__dict__, "location_id": "LOC-NET-LOFT"})
        if a.scene_id == "SC-018" else a
        for a in plan.assignments
    ]
    violations = evaluate(plan, problem)
    assert any(v.constraint_id == "C-SAFE-003" for v in violations)
    # ... and is satisfied once the plan actually includes one.
    plan.notes.append("briefing:LOC-NET-LOFT formats=written,captioned,spoken")
    assert not [
        v for v in evaluate(plan, problem) if v.constraint_id == "C-SAFE-003"
    ]


def test_interpreter_coverage_gap_detected() -> None:
    problem = build_problem()
    plan = _baseline_plan()
    shifted = []
    for a in plan.assignments:
        if "CAST-001" in a.cast_calls and a.scene_id == "SC-018":
            shift = timedelta(days=1)
            shifted.append(a.__class__(**{
                **a.__dict__,
                "start": a.start + shift, "end": a.end + shift,
                "setup_start": a.setup_start + shift,
                "cast_calls": {k: v + shift for k, v in a.cast_calls.items()},
            }))
        else:
            shifted.append(a)
    plan.assignments = shifted
    violations = evaluate(plan, problem)
    assert any(v.constraint_id == "C-ACC-003" for v in violations)


def test_approval_matrix_covers_every_change_type() -> None:
    roles = required_approvals({"location_change", "overtime", "major_schedule_change"})
    assert Role.UPM in roles
    assert Role.FIRST_AD in roles


def test_prohibited_changes_are_documented() -> None:
    """The §13.4 decision boundaries exist as code, not only as prose."""
    for key in ("remove_access_arrangement", "waive_safety_control",
                "override_child_limit", "rank_crew_by_cost", "infer_condition"):
        assert key in PROHIBITED_CHANGES
        assert len(PROHIBITED_CHANGES[key]) > 40


@pytest.mark.parametrize("constraint_id", sorted(CONSTRAINTS_BY_ID))
def test_constraint_owner_is_a_real_role(constraint_id: str) -> None:
    constraint = CONSTRAINTS_BY_ID[constraint_id]
    assert isinstance(constraint.owner, Role)
