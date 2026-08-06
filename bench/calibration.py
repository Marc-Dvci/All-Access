"""Is the robustness ensemble telling the truth?

`simulation/robust.py` reports an on-time probability and an expected delay for
each plan. Those numbers appear on the plan comparison view and a first AD is
being asked to choose between plans on the strength of them, so "is 0.72 really
0.72" is not an academic question.

The check here is a held-out one. The ensemble the plan is scored with uses seed
S. This module re-runs each plan against a *different* seed, treats those runs
as the world actually happening, and asks two things:

* **Calibration.** Bucket plans by predicted on-time probability. In each
  bucket, what fraction of held-out runs actually finished on time? A well
  calibrated ensemble puts the observed frequency inside the bucket.
* **Delay error.** Mean absolute error between predicted expected delay and the
  held-out mean delay, in minutes.

What this does *not* establish: that the simulator matches a real shooting day.
It matches itself under a different draw. The uncertainty model in `UNCERTAINTY`
is configured from production norms, not fitted to observed data, and
`docs/BENCHMARK.md` §7 says so. This measures ensemble stability and
self-consistency, which is the strongest claim the available evidence supports.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from productionpulse.disruptions import generate, scenario_problem  # noqa: E402
from productionpulse.simulation import robust  # noqa: E402
from productionpulse.solver import engine  # noqa: E402
from productionpulse.twin import build_twin  # noqa: E402

#: Buckets for the reliability diagram. Coarse on purpose: a bucket with four
#: plans in it tells you nothing, and ten buckets over a few hundred plans is
#: four plans a bucket.
BUCKETS: tuple[tuple[float, float], ...] = (
    (0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 0.95), (0.95, 1.0001),
)

PREDICTION_SEED = 20260314
HELDOUT_SEED = 77712043


def calibrate(count: int = 120, scenarios: int = 200) -> dict[str, Any]:
    twin = build_twin()
    rows: list[dict[str, Any]] = []

    for scenario in generate(count):
        problem = scenario_problem(scenario, twin=twin)
        outcome = engine.solve(problem, f"CAL-{scenario.scenario_id}")
        for plan in outcome.plans:
            candidate = engine.candidate_from_plan(plan, problem)
            predicted = robust.assess(
                candidate, problem, scenarios=scenarios, seed=PREDICTION_SEED,
                measure_sensitivity=False,
            )
            held_out = robust.run_ensemble(
                candidate, problem, scenarios=scenarios, seed=HELDOUT_SEED,
            )
            rows.append({
                "scenario_id": scenario.scenario_id,
                "plan_id": plan.plan_id,
                "strategy": plan.strategy,
                "predicted_on_time": predicted.on_time_probability,
                "observed_on_time": round(held_out.on_time, 4),
                "predicted_delay": predicted.expected_delay_minutes,
                "observed_delay": round(held_out.expected_delay, 2),
                "predicted_worst": predicted.worst_credible_delay_minutes,
                "observed_worst": round(held_out.quantile(0.95), 2),
                "predicted_overtime_risk": predicted.overtime_risk,
                "predicted_violation_risk": predicted.constraint_violation_risk,
            })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios": count,
        "plans": len(rows),
        "ensemble_size": scenarios,
        "prediction_seed": PREDICTION_SEED,
        "heldout_seed": HELDOUT_SEED,
        "reliability": _reliability(rows),
        "on_time_mae": _mae([(r["predicted_on_time"], r["observed_on_time"]) for r in rows]),
        "delay_mae_minutes": _mae([(r["predicted_delay"], r["observed_delay"]) for r in rows]),
        "delay_max_error_minutes": _max_error(
            [(r["predicted_delay"], r["observed_delay"]) for r in rows]
        ),
        "worst_credible_mae_minutes": _mae(
            [(r["predicted_worst"], r["observed_worst"]) for r in rows]
        ),
        "degenerate_metrics": _degenerate(rows),
        "rows": rows,
    }


def _degenerate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Reported quantities that take one value across the whole corpus.

    A metric with a single distinct value cannot rank anything. Naming them in
    the artifact keeps the limitation attached to the evidence rather than only
    to the prose that cites it.
    """
    tracked = [
        "predicted_on_time", "predicted_delay", "predicted_worst",
        "predicted_overtime_risk", "predicted_violation_risk",
    ]
    out: dict[str, Any] = {}
    for key in tracked:
        values = {r[key] for r in rows}
        out[key] = {
            "distinct_values": len(values),
            "degenerate": len(values) <= 1,
            "value": next(iter(values)) if len(values) == 1 else None,
        }
    return out


def _reliability(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for low, high in BUCKETS:
        members = [r for r in rows if low <= r["predicted_on_time"] < high]
        if not members:
            out.append({
                "bucket": f"{low:.2f}-{min(high, 1.0):.2f}", "plans": 0,
                "mean_predicted": None, "mean_observed": None, "gap": None,
            })
            continue
        predicted = statistics.fmean(r["predicted_on_time"] for r in members)
        observed = statistics.fmean(r["observed_on_time"] for r in members)
        out.append({
            "bucket": f"{low:.2f}-{min(high, 1.0):.2f}",
            "plans": len(members),
            "mean_predicted": round(predicted, 4),
            "mean_observed": round(observed, 4),
            "gap": round(observed - predicted, 4),
        })
    return out


def _mae(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    return round(statistics.fmean(abs(a - b) for a, b in pairs), 4)


def _max_error(pairs: list[tuple[float, float]]) -> float | None:
    if not pairs:
        return None
    return round(max(abs(a - b) for a, b in pairs), 4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Robustness calibration check")
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--scenarios", type=int, default=200)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "bench" / "results" / "calibration.json")
    args = parser.parse_args(argv)

    result = calibrate(args.count, args.scenarios)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    print(f"{result['plans']} plans from {result['scenarios']} scenarios")
    print(f"on-time MAE        {result['on_time_mae']}")
    print(f"delay MAE (min)    {result['delay_mae_minutes']}")
    print(f"delay max error    {result['delay_max_error_minutes']}")
    print(f"worst-case MAE     {result['worst_credible_mae_minutes']}")
    degenerate = [k for k, v in result["degenerate_metrics"].items() if v["degenerate"]]
    print(f"degenerate metrics {', '.join(degenerate) if degenerate else 'none'}")
    print("\nreliability")
    for row in result["reliability"]:
        print(f"  {row['bucket']:>11s}  n={row['plans']:<4d} "
              f"predicted={row['mean_predicted']} observed={row['mean_observed']} "
              f"gap={row['gap']}")
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
