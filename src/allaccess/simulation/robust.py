"""Discrete-event simulation of a production day, and robustness under uncertainty.

A plan that is feasible under one exact set of estimates can be operationally
weak. This module runs the revised day many times with the durations drawn from
calibrated distributions and reports what actually happens: how often it finishes
on time, how much delay to expect, the worst credible case, and which assumption
the answer is most sensitive to.

Two design decisions worth stating.

**The distributions are asymmetric.** Setup and travel overrun far more often
than they underrun, so the sampler uses a lognormal shape with a floor rather
than a normal. Modelling production durations as symmetric is the single fastest
way to build a schedule that is optimistic in exactly the way real schedules are.

**Sensitivity is measured, not asserted.** `sensitivity` re-runs the ensemble
with each uncertainty source pinned to its median in turn; the drop in expected
delay is that source's contribution. A "sensitive assumption" is one that
measurably moves the answer, not one somebody guessed was important.

Seeded throughout, so the same plan gives the same numbers on every machine.

**Two of the six reported quantities do not discriminate, and are not used to
rank plans.** Because every uncertainty median is above 1.0, P(zero overrun) is
approximately zero for every plan, so `on_time_probability` reads 0.00
throughout; and because the overrun on this production does not push the crew
day past the configured 720 minutes, `overtime_risk` reads 0.00 throughout.
`bench/calibration.py` measures both. They are still reported, because
suppressing a measurement because it came out flat is how a flat measurement
becomes a surprise later — but `compare()` ranks on expected delay, worst
credible delay and recovery margin, and `docs/BENCHMARK.md` §7 states the
limitation. Do not put on-time probability in front of a first AD as a
comparison column.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from ..contracts import RobustnessReport
from ..production import world as w
from ..solver.model import CandidatePlan, SchedulingProblem

#: Multiplicative uncertainty per source: (median, sigma of the log, floor).
#: Calibrated in `bench/calibration.py` against the simulator's own observed
#: outcomes; see docs/BENCHMARK.md §5.
UNCERTAINTY: dict[str, tuple[float, float, float]] = {
    "setup_duration": (1.03, 0.18, 0.75),
    "scene_duration": (1.05, 0.22, 0.70),
    "travel_time": (1.08, 0.25, 0.80),
    "transport_loading": (1.10, 0.30, 0.80),
    "performer_arrival": (1.02, 0.15, 0.85),
    "equipment_preparation": (1.06, 0.20, 0.80),
    "location_readiness": (1.04, 0.17, 0.85),
    "department_handoff": (1.07, 0.24, 0.80),
    "communication_latency": (1.00, 0.12, 0.90),
}


def _draw(rng: random.Random, source: str, pinned: set[str]) -> float:
    median, sigma, floor = UNCERTAINTY[source]
    if source in pinned:
        return median
    value = median * math.exp(rng.gauss(0.0, sigma))
    return max(floor, value)


@dataclass
class RunOutcome:
    delay_minutes: float
    overtime_minutes: float
    violated: bool
    finish: float


@dataclass
class Ensemble:
    runs: list[RunOutcome] = field(default_factory=list)

    def quantile(self, q: float) -> float:
        if not self.runs:
            return 0.0
        ordered = sorted(r.delay_minutes for r in self.runs)
        index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
        return ordered[index]

    @property
    def expected_delay(self) -> float:
        return sum(r.delay_minutes for r in self.runs) / len(self.runs) if self.runs else 0.0

    @property
    def on_time(self) -> float:
        if not self.runs:
            return 1.0
        return sum(1 for r in self.runs if r.delay_minutes <= 0.0) / len(self.runs)

    @property
    def overtime_risk(self) -> float:
        if not self.runs:
            return 0.0
        return sum(1 for r in self.runs if r.overtime_minutes > 0) / len(self.runs)

    @property
    def violation_risk(self) -> float:
        if not self.runs:
            return 0.0
        return sum(1 for r in self.runs if r.violated) / len(self.runs)


def _simulate_once(
    plan: CandidatePlan,
    problem: SchedulingProblem,
    rng: random.Random,
    pinned: set[str],
) -> RunOutcome:
    """One run of the revised day, department by department, move by move."""
    worst_overrun = 0.0
    total_overtime = 0.0
    violated = False

    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        if not rows:
            continue
        by_day: dict[Any, list] = {}
        for a in rows:
            by_day.setdefault(a.start.date(), []).append(a)

        for day_rows in by_day.values():
            day_rows.sort(key=lambda a: a.start)
            # The whole simulation runs in minutes from the day's first planned
            # setup. Working in elapsed minutes rather than wall-clock datetimes
            # keeps the arithmetic in one unit; mixing the two is how a simulator
            # quietly starts adding a duration to a timestamp.
            origin = min(a.setup_start for a in day_rows)
            planned_wrap = max(a.end for a in day_rows)
            call = min((a.crew_call or a.setup_start) for a in day_rows)
            clock = 0.0
            previous_location: str | None = None

            for a in day_rows:
                requirement = problem.requirements.get(a.scene_id)
                if requirement is None:
                    continue
                if previous_location and previous_location != a.location_id:
                    travel = w.travel_minutes(previous_location, a.location_id)
                    clock += travel * _draw(rng, "travel_time", pinned)
                    clock += 6.0 * _draw(rng, "transport_loading", pinned)

                # Work cannot start before its planned setup: a crew does not
                # turn up early because the previous scene ran short.
                planned_setup_offset = (a.setup_start - origin).total_seconds() / 60.0
                clock = max(clock, planned_setup_offset)

                setup = requirement.setup_minutes * _draw(rng, "setup_duration", pinned)
                setup *= _draw(rng, "equipment_preparation", pinned) ** 0.5
                setup *= _draw(rng, "location_readiness", pinned) ** 0.5
                clock += setup

                if a.cast_calls:
                    # Performer readiness shifts the turnover by a few minutes
                    # either side of the estimate.
                    clock += 40.0 * (_draw(rng, "performer_arrival", pinned) - 1.0)

                shoot = requirement.shoot_minutes * _draw(rng, "scene_duration", pinned)
                clock += shoot
                clock += 5.0 * _draw(rng, "department_handoff", pinned)
                previous_location = a.location_id

            planned = (planned_wrap - origin).total_seconds() / 60.0
            overrun = max(0.0, clock - planned)
            worst_overrun = max(worst_overrun, overrun)

            # Overtime is measured against the configured day, from the call.
            call_to_planned_wrap = (planned_wrap - call).total_seconds() / 60.0
            actual_span = call_to_planned_wrap + overrun
            standard = float(w.POLICIES["working_hours"]["max_crew_day_minutes"])  # type: ignore[arg-type]
            hard = float(w.POLICIES["working_hours"]["max_crew_day_with_approval_minutes"])  # type: ignore[arg-type]
            if actual_span > standard:
                total_overtime += actual_span - standard
            if actual_span > hard:
                violated = True

            # A curfew breached by the overrun is a real violation, not just a
            # late finish. Compared against that day's curfew, shifted by the
            # number of days the assignment sits after the shooting day.
            last = max(day_rows, key=lambda a: a.end)
            location = w.LOCATIONS_BY_ID.get(last.location_id)
            if location and location.noise_curfew:
                offset = timedelta(days=(last.end.date() - w.SHOOT_DATE).days)
                curfew = location.noise_curfew + offset
                actual_end = last.end + timedelta(minutes=overrun)
                if actual_end > curfew:
                    violated = True

    return RunOutcome(
        delay_minutes=round(worst_overrun, 2),
        overtime_minutes=round(total_overtime, 2),
        violated=violated,
        finish=round(worst_overrun, 2),
    )


def run_ensemble(
    plan: CandidatePlan,
    problem: SchedulingProblem,
    *,
    scenarios: int = 200,
    seed: int = 20260314,
    pinned: set[str] | None = None,
) -> Ensemble:
    rng = random.Random(seed)
    ensemble = Ensemble()
    for _ in range(scenarios):
        ensemble.runs.append(_simulate_once(plan, problem, rng, pinned or set()))
    return ensemble


def assess(
    plan: CandidatePlan,
    problem: SchedulingProblem,
    *,
    scenarios: int = 200,
    seed: int = 20260314,
    measure_sensitivity: bool = True,
) -> RobustnessReport:
    """Robustness of one plan, with measured sensitivity to each assumption."""
    base = run_ensemble(plan, problem, scenarios=scenarios, seed=seed)
    sensitivity: dict[str, float] = {}
    if measure_sensitivity:
        baseline_delay = base.expected_delay
        # A smaller ensemble per source: this is a ranking, not a headline number,
        # and eight full ensembles would dominate the solve time for no gain.
        per_source = max(40, scenarios // 4)
        for source in UNCERTAINTY:
            pinned_run = run_ensemble(
                plan, problem, scenarios=per_source, seed=seed + 1, pinned={source}
            )
            sensitivity[source] = round(baseline_delay - pinned_run.expected_delay, 2)

    ranked = sorted(sensitivity.items(), key=lambda kv: -abs(kv[1]))
    sensitive = tuple(
        f"{name.replace('_', ' ')} contributes {value:.1f} min of expected delay"
        for name, value in ranked[:3] if abs(value) >= 0.5
    )

    # Recovery margin: how much slack the plan has before it breaches the
    # configured day, at the median outcome.
    standard = float(w.POLICIES["working_hours"]["max_crew_day_minutes"])  # type: ignore[arg-type]
    spans: list[float] = []
    for unit in w.UNITS:
        rows = plan.by_unit(unit.unit_id)
        if not rows:
            continue
        by_day: dict[Any, list] = {}
        for a in rows:
            by_day.setdefault(a.start.date(), []).append(a)
        for day_rows in by_day.values():
            call = min((a.crew_call or a.setup_start) for a in day_rows)
            wrap = max(a.end for a in day_rows)
            spans.append((wrap - call).total_seconds() / 60.0)
    headroom = standard - max(spans) if spans else standard
    margin = max(0.0, headroom - base.quantile(0.5))

    return RobustnessReport(
        scenarios=scenarios,
        on_time_probability=round(base.on_time, 4),
        expected_delay_minutes=round(base.expected_delay, 2),
        worst_credible_delay_minutes=round(base.quantile(0.95), 2),
        overtime_risk=round(base.overtime_risk, 4),
        constraint_violation_risk=round(base.violation_risk, 4),
        recovery_margin_minutes=round(margin, 2),
        sensitive_assumptions=sensitive,
        sensitivity=sensitivity,
    )


def compare(reports: dict[str, RobustnessReport]) -> list[dict[str, Any]]:
    """Rank plans by robustness, for the plan comparison view.

    The ranking key is expected delay, then the worst credible case, then how
    much recovery margin is left — deliberately *not* `on_time_probability`.

    Under the configured uncertainty every source has a median above 1.0, which
    is the modelling position that scheduled durations are optimistic. The
    consequence is that P(zero overrun) is approximately zero for every plan, so
    on-time probability does not discriminate between plans and ranking by it is
    ranking by a constant. `bench/calibration.py` measures this — it read 0.00
    for all 34 plans in its first run — and `docs/BENCHMARK.md` §7 reports it as
    a limitation rather than presenting the number as a result.
    """
    rows = [
        {
            "plan_id": plan_id,
            "on_time_probability": report.on_time_probability,
            "expected_delay_minutes": report.expected_delay_minutes,
            "worst_credible_delay_minutes": report.worst_credible_delay_minutes,
            "overtime_risk": report.overtime_risk,
            "constraint_violation_risk": report.constraint_violation_risk,
            "recovery_margin_minutes": report.recovery_margin_minutes,
            "scenarios": report.scenarios,
        }
        for plan_id, report in reports.items()
    ]
    return sorted(
        rows,
        key=lambda r: (
            r["expected_delay_minutes"],
            r["worst_credible_delay_minutes"],
            -r["recovery_margin_minutes"],
        ),
    )
