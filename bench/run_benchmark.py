"""Run the benchmark and write the artifacts the documentation cites.

    python -m bench.run_benchmark --count 1000 --workers 7
    python -m bench.run_benchmark --count 200 --ablations
    python -m bench.run_benchmark --smoke                 # 48 scenarios, ~25 s

Writes `bench/results/summary.json` (aggregate), `bench/results/scenarios.jsonl`
(one row per scenario, so any number in the summary can be recomputed) and, with
`--ablations`, `bench/results/ablations.json`.

The corpus is a pure function of `--count` and `--seed`. Same arguments, same
scenarios, on any machine — which is the only reason a committed result is worth
committing.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bench.harness import Measurement, RunConfig, run_scenario  # noqa: E402
from bench.report import compare_ablations, summarise  # noqa: E402

RESULTS = ROOT / "bench" / "results"

#: The ablations. Each removes exactly one capability, so the delta is
#: attributable. `no_validation` also stands in for a plan authored without a
#: solver at all — see `docs/BENCHMARK.md` §6 for what that surrogate does and
#: does not establish.
ABLATIONS: dict[str, dict[str, bool]] = {
    "no_twin": {"twin": False},
    "no_robustness": {"robustness": False},
    "no_reconciliation": {"reconciliation": False},
    "no_validation": {"validation": False},
}

#: Faults that need a disruption which actually produces a plan and issues
#: commands. The operational-systems family cannot exercise them — a platform
#: fault leaves the shooting day unchanged, so the correct plan is "change
#: nothing" and there is no department task to withhold. They are assigned to
#: every `_FAULT_STRIDE`-th scenario of the whole corpus instead, deterministically.
_PLAN_DEPENDENT_FAULTS: tuple[str, ...] = ("missing_acknowledgment", "partial_update")
_FAULT_STRIDE = 16


def _assigned_fault(index: int) -> str | None:
    if index == 0 or index % _FAULT_STRIDE:
        return None
    return _PLAN_DEPENDENT_FAULTS[(index // _FAULT_STRIDE - 1) % len(_PLAN_DEPENDENT_FAULTS)]


def _worker(args: tuple[dict, int, int, list[int]]) -> list[dict]:
    """Regenerate the corpus in the child and run the assigned indices.

    Scenarios are regenerated rather than pickled: the corpus is deterministic,
    and sending a thousand frozen dataclasses across a process boundary on
    Windows spawn is slower than rebuilding them.
    """
    config_kwargs, count, seed, indices = args
    from productionpulse.disruptions import generate
    from productionpulse.twin import build_twin

    config = RunConfig(**config_kwargs)
    scenarios = generate(count, seed=seed)
    twin = build_twin() if config.twin else None
    rows: list[dict] = []
    for index in indices:
        measurement = run_scenario(
            scenarios[index], config, twin=twin, injected_fault=_assigned_fault(index)
        )
        rows.append(measurement.as_dict())
    return rows


def _chunks(total: int, workers: int) -> list[list[int]]:
    buckets: list[list[int]] = [[] for _ in range(workers)]
    for index in range(total):
        buckets[index % workers].append(index)
    return [b for b in buckets if b]


def run_corpus(config: RunConfig, count: int, seed: int, workers: int) -> list[Measurement]:
    started = time.perf_counter()
    payloads = [
        (config.__dict__.copy(), count, seed, indices)
        for indices in _chunks(count, max(1, workers))
    ]
    rows: list[dict] = []
    if workers <= 1:
        for payload in payloads:
            rows.extend(_worker(payload))
    else:
        with mp.Pool(processes=workers) as pool:
            for result in pool.imap_unordered(_worker, payloads):
                rows.extend(result)
                print(f"  {config.name}: {len(rows)}/{count}", flush=True)
    elapsed = time.perf_counter() - started
    print(f"  {config.name}: {count} scenarios in {elapsed:.1f} s", flush=True)
    return [Measurement(**row) for row in rows]


def _environment(count: int, seed: int, workers: int) -> dict:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scenarios": count,
        "seed": seed,
        "workers": workers,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "reasoning_plane": "offline",
        "command": (
            f"python -m bench.run_benchmark --count {count} --seed {seed} "
            f"--workers {workers}"
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ProductionPulse benchmark")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20260314)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--scenarios", type=int, default=60,
                        help="robustness ensemble size per plan")
    parser.add_argument("--ablations", action="store_true",
                        help="also run every ablation over the same corpus")
    parser.add_argument("--ablations-only", action="store_true")
    parser.add_argument("--ablation-count", type=int, default=200,
                        help="corpus size for the ablation runs")
    parser.add_argument("--smoke", action="store_true",
                        help="48 scenarios, no ablations; for CI")
    parser.add_argument("--out", type=Path, default=RESULTS)
    args = parser.parse_args(argv)

    count = 48 if args.smoke else args.count
    args.out.mkdir(parents=True, exist_ok=True)

    baseline_summary: dict | None = None
    if not args.ablations_only:
        print(f"Baseline: {count} scenarios on {args.workers} worker(s)")
        config = RunConfig(name="full", scenarios=args.scenarios)
        rows = run_corpus(config, count, args.seed, args.workers)
        baseline_summary = summarise(rows)
        baseline_summary["environment"] = _environment(count, args.seed, args.workers)

        (args.out / "scenarios.jsonl").write_text(
            "\n".join(json.dumps(r.as_dict(), sort_keys=True) for r in rows) + "\n",
            encoding="utf-8",
        )
        (args.out / "summary.json").write_text(
            json.dumps(baseline_summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Wrote {args.out / 'summary.json'}")

    if args.ablations or args.ablations_only:
        ablation_count = min(args.ablation_count, count) if not args.smoke else 48
        # Like for like: the baseline in the ablation table is re-run over the
        # same, smaller corpus. Comparing a 200-scenario ablation against a
        # 1,000-scenario baseline is not a comparison.
        print(f"Ablations: {ablation_count} scenarios each")
        base_config = RunConfig(name="full", scenarios=args.scenarios)
        base_rows = run_corpus(base_config, ablation_count, args.seed, args.workers)
        base = summarise(base_rows)

        summaries: dict[str, dict] = {}
        for name, overrides in ABLATIONS.items():
            config = RunConfig(name=name, scenarios=args.scenarios, **overrides)
            rows = run_corpus(config, ablation_count, args.seed, args.workers)
            summaries[name] = summarise(rows)

        payload = {
            "environment": _environment(ablation_count, args.seed, args.workers),
            "note": (
                "Every configuration ran over the same corpus of "
                f"{ablation_count} scenarios with the same seed."
            ),
            "baseline": base,
            "ablations": summaries,
            "table": compare_ablations(base, summaries),
        }
        (args.out / "ablations.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Wrote {args.out / 'ablations.json'}")

    if baseline_summary is not None:
        _print_headline(baseline_summary)
    return 0


def _print_headline(summary: dict) -> None:
    planning = summary["planning_quality"]
    impact = summary["impact_analysis"]
    execution = summary["execution_quality"]
    privacy = summary["inclusion_and_privacy"]
    platform_ = summary["platform_quality"]
    print("\nHeadline")
    for label, value in [
        ("hard-constraint violation rate (published plans)",
         planning["hard_constraint_violation_rate"]),
        ("constraint identification precision",
         impact["constraint_identification"]["precision"]),
        ("constraint identification recall",
         impact["constraint_identification"]["recall"]),
        ("access preservation rate", privacy["access_preservation_rate"]),
        ("false closure rate without verification",
         execution["false_closure_rate_without_verification"]),
        ("replay identical rate", platform_["replay_identical_rate"]),
        ("prohibited field occurrences", privacy["prohibited_field_occurrences"]),
    ]:
        print(f"  {label:52s} {value}")


if __name__ == "__main__":
    if os.name == "nt":
        mp.freeze_support()
    raise SystemExit(main())
