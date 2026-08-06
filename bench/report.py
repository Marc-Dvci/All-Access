"""Aggregate measurements into the metric families of the plan's §16.

The rules this module follows, because a benchmark report is only as good as
what it refuses to do:

* A rate whose denominator is zero is reported as `null`, never as 1.0 and never
  as 0.0. "No scenario exercised this" and "every scenario passed" are different
  facts and the report keeps them different.
* Micro-averaging over items, not macro-averaging over scenarios, wherever the
  underlying quantity is a set — otherwise a scenario with one expected
  constraint and a scenario with four weigh the same.
* Every metric names its denominator in the output, so a reader can tell a rate
  measured over 1,000 scenarios from one measured over 6.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable, Sequence

from .harness import INJECTABLE_FAULTS, Measurement


def _rate(numerator: int, denominator: int) -> float | None:
    """A proportion, or None when nothing was measured."""
    if denominator <= 0:
        return None
    return round(numerator / denominator, 4)


def _mean(values: Sequence[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def _quantile(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return round(ordered[index], 3)


def _set_scores(rows: Iterable[Measurement], expected_attr: str,
                detected_attr: str) -> dict[str, Any]:
    """Micro-averaged precision and recall over a set-valued prediction."""
    tp = fp = fn = 0
    scenarios_with_labels = 0
    for row in rows:
        expected = set(getattr(row, expected_attr))
        detected = set(getattr(row, detected_attr))
        if expected:
            scenarios_with_labels += 1
        tp += len(expected & detected)
        fp += len(detected - expected)
        fn += len(expected - detected)
    return {
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": _rate(tp, tp + fp),
        "recall": _rate(tp, tp + fn),
        "labelled_scenarios": scenarios_with_labels,
    }


def summarise(rows: list[Measurement]) -> dict[str, Any]:
    """Everything the report knows, grouped by the plan's metric families."""
    completed = [r for r in rows if r.error is None]
    errored = [r for r in rows if r.error is not None]
    planned = [r for r in completed if r.feasible_plans > 0]
    executed = [r for r in completed if r.commands > 0]
    verified = [r for r in completed if r.verification_ready is not None]

    return {
        "corpus": _corpus(rows, completed, errored),
        "impact_analysis": _impact(completed),
        "planning_quality": _planning(completed, planned),
        "robustness": _robustness(planned),
        "agent_quality": _agents(completed),
        "execution_quality": _execution(executed, verified),
        "inclusion_and_privacy": _privacy(completed, planned),
        "platform_quality": _platform(completed),
        "latency": _latency(completed),
    }


def _corpus(rows: list[Measurement], completed: list[Measurement],
            errored: list[Measurement]) -> dict[str, Any]:
    families: dict[str, int] = {}
    states: dict[str, int] = {}
    for row in rows:
        families[row.family] = families.get(row.family, 0) + 1
        if row.error is None:
            states[row.final_state or "unknown"] = states.get(row.final_state or "unknown", 0) + 1
    return {
        "scenarios": len(rows),
        "completed": len(completed),
        "errors": len(errored),
        "error_examples": sorted({r.error for r in errored if r.error})[:5],
        "families": dict(sorted(families.items())),
        "final_states": dict(sorted(states.items())),
        # A disruption for which no plan satisfies every hard constraint is
        # closed as such rather than resolved with a plan that breaks one. The
        # rate is reported because it is a property of the corpus and of the
        # constraint set, not a failure.
        "no_feasible_plan_rate": _rate(
            sum(1 for r in completed if r.feasible_plans == 0), len(completed)
        ),
    }


def _impact(rows: list[Measurement]) -> dict[str, Any]:
    return {
        "constraint_identification": _set_scores(
            rows, "expected_constraints", "detected_constraints"
        ),
        "affected_departments": _set_scores(
            rows, "expected_departments", "detected_departments"
        ),
        "disrupted_scenes": _set_scores(rows, "expected_scenes", "detected_scenes"),
        "access_requirements_reached": _set_scores(
            rows, "expected_access_at_risk", "detected_access_at_risk"
        ),
        "mean_blast_nodes": _mean([r.blast_nodes for r in rows if r.blast_nodes]),
        "max_blast_depth": max((r.blast_depth for r in rows), default=0),
    }


def _planning(rows: list[Measurement], planned: list[Measurement]) -> dict[str, Any]:
    published = sum(r.feasible_plans for r in rows)
    rejected = sum(r.rejected_plans for r in rows)
    return {
        "published_feasible_plans": published,
        "rejected_plans": rejected,
        # The headline safety property. Anything but zero invalidates the claim
        # that a published plan is a proved plan.
        "hard_constraint_violation_rate": _rate(
            sum(r.hard_violations_published for r in rows), published
        ),
        "unvalidated_proof_rate": _rate(
            sum(r.unvalidated_published for r in rows), published
        ),
        "rejected_without_conflict_set_rate": _rate(
            sum(r.rejected_without_conflict for r in rows), rejected
        ),
        "non_minimal_conflict_rate": _rate(
            sum(r.non_minimal_conflicts for r in rows), rejected
        ),
        "mean_options_offered": _mean([float(r.feasible_plans) for r in planned]),
        "mean_distinct_strategies": _mean([float(r.distinct_strategies) for r in planned]),
        "multiple_strategy_rate": _rate(
            sum(1 for r in planned if r.distinct_strategies >= 2), len(planned)
        ),
    }


def _robustness(planned: list[Measurement]) -> dict[str, Any]:
    on_time = [r.on_time_probability for r in planned if r.on_time_probability is not None]
    delay = [r.expected_delay_minutes for r in planned
             if r.expected_delay_minutes is not None]
    worst = [r.worst_credible_delay_minutes for r in planned
             if r.worst_credible_delay_minutes is not None]
    return {
        "plans_simulated": len(on_time),
        "mean_on_time_probability": _mean(on_time),
        "mean_expected_delay_minutes": _mean(delay),
        "p95_worst_credible_delay_minutes": _quantile(worst, 0.95),
    }


def _agents(rows: list[Measurement]) -> dict[str, Any]:
    findings = sum(r.findings for r in rows)
    assessed = [r for r in rows if r.findings]
    return {
        "findings": findings,
        "scenarios_assessed": len(assessed),
        # A required assessment that did not run is a workflow failure, not a
        # quality score. The coordinator raises rather than proceeding, so a
        # non-zero count here means something changed in the agent set.
        "missing_required_assessment_rate": _rate(
            sum(r.missing_required_assessments for r in assessed), len(assessed) * 6
        ),
        "abstention_rate": _rate(sum(r.abstentions for r in rows), findings),
        "fabricated_constraint_rate": _rate(
            sum(r.fabricated_constraints for r in rows), findings
        ),
        "blocking_finding_without_evidence_rate": _rate(
            sum(r.blocking_findings_without_evidence for r in rows), findings
        ),
    }


def _execution(executed: list[Measurement], verified: list[Measurement]) -> dict[str, Any]:
    commands = sum(r.commands for r in executed)
    acks_required = sum(r.acknowledgments_required for r in executed)
    naive = [r for r in verified if r.naive_ready]
    return {
        "commands_issued": commands,
        "command_completion_rate": _rate(
            sum(r.commands_completed for r in executed), commands
        ),
        "command_rejection_rate": _rate(
            sum(r.commands_rejected for r in executed), commands
        ),
        "acknowledgment_completeness": _rate(
            sum(r.acknowledgments_received for r in executed), acks_required
        ),
        "verification_ready_rate": _rate(
            sum(1 for r in verified if r.verification_ready), len(verified)
        ),
        "assertion_pass_rate": _rate(
            sum(r.assertions_passed for r in verified),
            sum(r.assertions_total for r in verified),
        ),
        # The number the reconciliation ablation exists to produce: how often a
        # system that trusted command acknowledgment alone would have declared a
        # disruption handled while a critical downstream step was outstanding.
        "false_closure_rate_without_verification": _rate(
            sum(1 for r in naive if r.false_closure), len(naive)
        ),
        "false_closure_denominator": len(naive),
    }


def _privacy(rows: list[Measurement], planned: list[Measurement]) -> dict[str, Any]:
    with_access = [r for r in planned if r.access_preserved is not None]
    return {
        "approved_arrangements_in_selected_plans": sum(
            r.access_arrangements for r in with_access
        ),
        "access_preservation_rate": _rate(
            sum(1 for r in with_access if r.access_preserved), len(with_access)
        ),
        # Both of the following must be zero. They are tripwires, not scores:
        # the design has no code path that would populate them.
        "prohibited_field_occurrences": sum(r.prohibited_field_hits for r in rows),
        "personal_events_to_unauthorised_audience": sum(
            r.personal_events_to_unauthorised_audience for r in rows
        ),
    }


def _platform(rows: list[Measurement]) -> dict[str, Any]:
    faulted = [r for r in rows if r.fault]
    injected = [r for r in faulted if r.fault_injected]
    # A fault injected into a run where it could not apply — a withheld
    # department acceptance on a plan that issued that department no task — is
    # excluded from the denominator rather than scored as a pass.
    applicable = [r for r in injected if r.fault_handled is not None]
    handled = [r for r in applicable if r.fault_handled is True]
    by_fault: dict[str, dict[str, int]] = {}
    for row in applicable:
        entry = by_fault.setdefault(str(row.fault), {"applicable": 0, "handled": 0})
        entry["applicable"] += 1
        entry["handled"] += int(bool(row.fault_handled))
    return {
        "events": sum(r.events for r in rows),
        "mean_events_per_disruption": _mean([float(r.events) for r in rows if r.events]),
        "hash_chain_intact_rate": _rate(
            sum(1 for r in rows if r.chain_intact), len(rows)
        ),
        "replay_identical_rate": _rate(
            sum(1 for r in rows if r.replay_identical), len(rows)
        ),
        "mean_lineage_nodes": _mean([float(r.lineage_nodes) for r in rows if r.lineage_nodes]),
        "duplicates_suppressed": sum(r.duplicates_suppressed for r in rows),
        "inbox_duplicates_suppressed": sum(r.inbox_suppressed for r in rows),
        "dead_letters": sum(r.dead_letters for r in rows),
        "fault_scenarios": len(faulted),
        "faults_injected": len(injected),
        "faults_applicable": len(applicable),
        "fault_handling_rate": _rate(len(handled), len(applicable)),
        "fault_handling_by_kind": dict(sorted(by_fault.items())),
        "injectable_faults": sorted(INJECTABLE_FAULTS),
        "declared_but_not_injected": sorted({
            r.fault for r in faulted if r.fault and not r.fault_injected
        }),
    }


def _latency(rows: list[Measurement]) -> dict[str, Any]:
    total = [r.total_ms for r in rows if r.total_ms]
    solve = [r.solve_ms for r in rows if r.solve_ms]
    return {
        "mean_end_to_end_ms": _mean(total),
        "p95_end_to_end_ms": _quantile(total, 0.95),
        "mean_solve_ms": _mean(solve),
        "p95_solve_ms": _quantile(solve, 0.95),
    }


def compare_ablations(baseline: dict[str, Any],
                      ablations: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """The ablation table: what each removed capability costs.

    Only metrics the ablation can actually move are compared. Removing the
    robustness ensemble cannot change the constraint-violation rate, and a table
    that showed a 0.000 delta there would invite the reader to conclude the
    ablation did nothing.
    """
    tracked = [
        ("hard_constraint_violation_rate", "planning_quality"),
        ("unvalidated_proof_rate", "planning_quality"),
        ("mean_options_offered", "planning_quality"),
        ("false_closure_rate_without_verification", "execution_quality"),
        ("verification_ready_rate", "execution_quality"),
        ("access_preservation_rate", "inclusion_and_privacy"),
        ("mean_end_to_end_ms", "latency"),
    ]
    rows: list[dict[str, Any]] = []
    for name, summary in ablations.items():
        entry: dict[str, Any] = {"configuration": name}
        for metric, family in tracked:
            base_value = baseline[family].get(metric)
            value = summary[family].get(metric)
            entry[metric] = value
            if isinstance(base_value, (int, float)) and isinstance(value, (int, float)):
                entry[f"{metric}_delta"] = round(value - base_value, 4)
        # Impact analysis is only comparable where the ablation touches it.
        entry["constraint_recall"] = summary["impact_analysis"][
            "constraint_identification"]["recall"]
        entry["department_recall"] = summary["impact_analysis"][
            "affected_departments"]["recall"]
        rows.append(entry)
    return rows
