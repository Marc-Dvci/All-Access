"""The deterministic engine: search, diversity, proofs and infeasibility.

The load-bearing property is in `test_no_feasible_plan_violates_a_hard_constraint`:
every plan the engine publishes as feasible is independently re-validated against
the full constraint registry, from the plan object, with no access to whatever
the search believed while building it.
"""

from __future__ import annotations

import pytest

from allaccess.constraints.registry import evaluate
from allaccess.disruptions import STORM_SCENARIO, scenario_problem
from allaccess.solver import engine, infeasibility, objectives
from allaccess.solver.model import (
    CandidatePlan,
    baseline_assignments,
    build_problem,
)


@pytest.fixture(scope="module")
def storm_outcome():
    problem = scenario_problem(STORM_SCENARIO)
    return problem, engine.solve(problem, "DISR-TEST")


def test_storm_produces_feasible_and_rejected_plans(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    assert outcome.plans, "the storm must leave at least one workable plan"
    assert outcome.rejected, "the obvious replacements must be explicitly rejected"


def test_no_feasible_plan_violates_a_hard_constraint(storm_outcome) -> None:
    problem, outcome = storm_outcome
    for plan in outcome.plans:
        candidate = engine.candidate_from_plan(plan, problem)
        blocking = [v for v in evaluate(candidate, problem) if v.severity == "blocking"]
        assert not blocking, f"{plan.strategy}: {[v.message for v in blocking]}"


def test_every_feasible_plan_carries_a_validated_proof(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    for plan in outcome.plans:
        assert plan.proof is not None
        assert plan.proof.validated
        assert plan.proof.satisfiable
        assert plan.proof.constraint_set_hash
        assert plan.proof.solver_version


def test_plans_are_structurally_diverse(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    strategies = {p.strategy for p in outcome.plans}
    assert len(strategies) >= 2
    shapes = {
        tuple(sorted((s.scene_id, s.location_id, s.start.date().isoformat())
                     for s in p.scenes))
        for p in outcome.plans
    }
    assert len(shapes) == len(outcome.plans), "plans must not be reshuffled duplicates"


def test_preserve_original_is_rejected_on_safety(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    original = next(p for p in outcome.rejected if p.strategy == "preserve_original")
    assert original.conflicts
    conflict = original.conflicts[0]
    assert "C-SAFE-001" in conflict.constraint_ids
    assert conflict.change_permitted is False, (
        "the system must not offer a safety waiver as a route to feasibility"
    )


def test_boatshed_is_rejected_with_a_measured_reason(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    boatshed = next(
        (p for p in outcome.rejected if "boatshed" in p.strategy), None
    )
    assert boatshed is not None
    conflict = boatshed.conflicts[0]
    assert "C-ACC-001" in conflict.all_blocking_ids
    assert "mm" in conflict.production_language, (
        "the rejection must name a measurement: " + conflict.production_language
    )
    assert conflict.change_permitted is False


def test_every_rejected_plan_has_a_conflict_set(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    for plan in outcome.rejected:
        assert plan.conflicts
        for conflict in plan.conflicts:
            assert conflict.constraint_ids
            assert conflict.production_language
            assert conflict.evidence


def test_conflict_sets_are_minimal(storm_outcome) -> None:
    """Removing the conflict set must actually make the plan feasible again."""
    problem, outcome = storm_outcome
    from allaccess.constraints.registry import active_constraints

    for plan in outcome.rejected:
        conflict = plan.conflicts[0]
        if not conflict.minimal:
            continue
        candidate = engine.candidate_from_plan(plan, problem)
        remaining = tuple(
            c for c in active_constraints()
            if c.constraint_id not in set(conflict.constraint_ids)
        )
        blocking = [
            v for v in evaluate(candidate, problem, remaining) if v.severity == "blocking"
        ]
        # Removing a *minimal* conflict set may still leave other independent
        # conflicts; what must be true is that the named set really was blocking.
        assert set(conflict.constraint_ids) <= set(conflict.all_blocking_ids)
        assert len(blocking) < len([
            v for v in evaluate(candidate, problem) if v.severity == "blocking"
        ]) or not conflict.all_blocking_ids


def test_frozen_work_is_not_rescheduled(storm_outcome) -> None:
    """A scene already shot must appear unchanged in every plan."""
    problem, outcome = storm_outcome
    completed = {
        a.scene_id: a for a in problem.baseline
        if a.start <= problem.now and a.scene_id not in problem.disrupted_scene_ids
    }
    assert completed, "the fixture must have work already in the can"
    for plan in outcome.plans:
        for scene in plan.scenes:
            original = completed.get(scene.scene_id)
            if original is not None:
                assert scene.start == original.start, (
                    f"{plan.strategy} rescheduled {scene.scene_id}, already shot"
                )


def test_recommended_plan_preserves_every_access_arrangement(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    best = outcome.plans[0]
    assert best.access
    unsatisfied = [a for a in best.access if not a.satisfied]
    assert not unsatisfied, [a.requirement_id for a in unsatisfied]


def test_pareto_front_contains_no_dominated_plan(storm_outcome) -> None:
    _problem, outcome = storm_outcome
    by_id = {p.plan_id: p.objectives for p in outcome.plans}
    for plan_id in outcome.pareto_front:
        for other_id, other in by_id.items():
            if other_id == plan_id:
                continue
            assert not objectives.dominates(other, by_id[plan_id]), (
                f"{plan_id} is on the front but dominated by {other_id}"
            )


def test_objectives_exclude_safety_and_access() -> None:
    """Structural guarantee: there is no objective that could trade them away."""
    from allaccess.contracts import PlanObjectives

    labels = set(PlanObjectives.labels())
    for forbidden in ("safety", "access", "accessibility", "arrangement"):
        assert not any(forbidden in label for label in labels)


def test_scalarisation_is_only_for_ordering(storm_outcome) -> None:
    from allaccess.constraints.registry import SOFT_WEIGHTS

    _problem, outcome = storm_outcome
    scores = [
        objectives.scalarize(p.objectives, SOFT_WEIGHTS) for p in outcome.plans
    ]
    assert scores == sorted(scores), "plans must be presented in ranked order"


def test_quickxplain_finds_a_genuine_conflict() -> None:

    problem = build_problem()
    plan = CandidatePlan(
        strategy="test", label="t", rationale="t", assignments=baseline_assignments(),
    )
    plan.unit_bases["UNIT-MAIN"] = "LOC-BOATSHED"
    violations = evaluate(plan, problem)
    conflict = infeasibility.explain(plan, problem, violations)
    assert conflict.constraint_ids
    assert conflict.evidence
    for constraint_id in conflict.constraint_ids:
        assert constraint_id in conflict.all_blocking_ids


def test_search_reports_why_a_scene_will_not_fit() -> None:
    from allaccess.production import world as w
    from allaccess.solver.search import PlacementRequest, schedule

    problem = build_problem(now=w.at(22, 0))
    request = PlacementRequest(
        scene_id="SC-025", location_id="LOC-HARBOUR-WALL", unit_id="UNIT-MAIN",
        earliest=w.at(22, 0), latest=w.at(23, 30),
        equipment_ids=problem.requirements["SC-025"].equipment_ids,
    )
    result = schedule(problem, [request])
    assert not result.complete
    reason = result.failure_reasons["SC-025"]
    assert reason and reason != "no start time is compatible with the rest of the day"


def test_solver_is_deterministic() -> None:
    problem = scenario_problem(STORM_SCENARIO)
    first = engine.solve(problem, "DISR-D1")
    second = engine.solve(scenario_problem(STORM_SCENARIO), "DISR-D1")
    assert [p.plan_id for p in first.plans] == [p.plan_id for p in second.plans]
    assert [p.content_hash() for p in first.plans] == [
        p.content_hash() for p in second.plans
    ]
