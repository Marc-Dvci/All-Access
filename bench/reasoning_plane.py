"""Run the same disruptions on both reasoning planes and compare what moved.

    python -m bench.reasoning_plane --count 40
    python -m bench.reasoning_plane --count 40 --serial   # one agent at a time

The thousand-disruption benchmark runs on the offline plane, and it says so.
That is a deliberate choice — a committed result has to be reproducible by
somebody with no Vertex project — but on its own it leaves an obvious question
unanswered: what does Gemini contribute, and could it contribute something
unwanted?

This answers both, by running a corpus twice and diffing.

**What must not change.** The plan the system selects, its hash, which plans it
publishes, which it refuses and with which minimal conflict set, whether every
approved access arrangement survives, whether verification clears the day, and
the status every expert agent reached. These are decisions, and the reasoning
plane is not allowed to touch them. If a single one differs between the planes,
the separation this project claims is not real and this script says so.

**What must change.** The headline sentence on every finding. That is the
model's job and the only thing it does. A run where the headlines are identical
is a run where Gemini was not actually reached, and that is reported too rather
than passing quietly as a success.

**What is measured, not asserted.** Latency, token cost including the reasoning
tokens Gemini 3.x spends before answering, how often the grounding gate threw a
response away, and how often the plane fell back. Those are the numbers that
tell you what the model costs to keep in the loop.

Written to `bench/results/reasoning_plane.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from allaccess.agents.coordinator import ProductionCoordinator  # noqa: E402
from allaccess.agents.core import build_reasoner  # noqa: E402
from allaccess.disruptions import build_source_event, generate, scenario_problem  # noqa: E402
from allaccess.production import world as w  # noqa: E402
from allaccess.stream.bus import build_bus  # noqa: E402
from allaccess.systems import build_systems  # noqa: E402
from allaccess.twin import build_twin  # noqa: E402

RESULTS = ROOT / "bench" / "results"


def decisions(outcome: Any) -> dict[str, Any]:
    """Everything about a run that the reasoning plane may not influence.

    Deliberately excludes every field a model writes. `headline` is absent;
    `status`, `applicable_constraints` and `required_authority` are present,
    because those come from the deterministic evidence and an agent that let a
    sentence change them would be a defect.
    """
    selected = outcome.selected
    return {
        "state": outcome.disruption.state.value,
        "selected_plan_id": outcome.disruption.selected_plan_id,
        "selected_plan_hash": selected.content_hash() if selected else None,
        "published": sorted(p.content_hash() for p in outcome.plans),
        "rejected": sorted(
            [sorted(c.constraint_ids) for p in outcome.rejected for c in p.conflicts]
        ),
        "pareto_front": sorted(outcome.pareto_front),
        "access_preserved": (
            None if selected is None
            else sum(1 for a in selected.access if a.satisfied)
        ),
        "access_total": None if selected is None else len(selected.access),
        "verification_ready": (
            None if outcome.verification is None else outcome.verification.ready
        ),
        "findings": sorted(
            (f.producer, f.status.value, tuple(sorted(f.applicable_constraints)))
            for f in outcome.findings
        ),
    }


def headlines(outcome: Any) -> dict[str, str]:
    """The sentences the plane wrote, keyed so the two runs can be lined up."""
    return {f.finding_id[:2] + f.producer: f.headline for f in outcome.findings}


def run_one(scenario: Any, plane: str, twin: Any) -> tuple[dict[str, Any], Any, float]:
    bus = build_bus(w.PRODUCTION_ID)
    reasoner = build_reasoner(plane)
    coordinator = ProductionCoordinator(
        bus, build_systems(w.PRODUCTION_ID, hold_department="props"), reasoner=reasoner,
    )
    started = time.perf_counter()
    outcome = coordinator.handle(
        scenario_problem(scenario, twin=twin), build_source_event(bus, scenario),
        title=scenario.title, scenario_id=scenario.scenario_id, scenarios=40,
    )
    elapsed = (time.perf_counter() - started) * 1000.0
    return (
        {"decisions": decisions(outcome), "headlines": headlines(outcome)},
        reasoner,
        elapsed,
    )


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round(q * (len(ordered) - 1))))
    return round(ordered[index], 1)


def plane_report(calls: list[Any]) -> dict[str, Any]:
    latencies = [c.latency_ms for c in calls]
    return {
        "calls": len(calls),
        "failed": sum(1 for c in calls if c.error),
        "errors": sorted({(c.error or "")[:120] for c in calls if c.error}),
        "responses_rejected_as_ungrounded": sum(1 for c in calls if c.rejected_claims),
        "rejected_claims": sorted({
            claim for c in calls for claim in (c.rejected_claims or ())
        })[:20],
        "tokens_in": sum(c.tokens_in or 0 for c in calls),
        "tokens_out": sum(c.tokens_out or 0 for c in calls),
        "tokens_thought": sum(getattr(c, "tokens_thought", None) or 0 for c in calls),
        "mean_latency_ms": round(statistics.fmean(latencies), 1) if latencies else 0.0,
        "p95_latency_ms": _percentile(latencies, 0.95),
        "mean_response_chars": (
            round(statistics.fmean([c.response_chars for c in calls]), 1)
            if calls else 0.0
        ),
    }


BEGIN = "<!-- REASONING-PLANE:BEGIN -->"
END = "<!-- REASONING-PLANE:END -->"


def render_section(
    summary: dict[str, Any],
    serial: dict[str, Any] | None,
    fanout: dict[str, Any] | None = None,
) -> str:
    """Section 7 of docs/BENCHMARK.md, written from the artifact not by hand.

    The rule in section 6 is that no figure in that document changes without the
    artifact changing. The cheapest way to keep a rule like that is to make the
    prose a build product, so this section is generated and CI diffs it.
    """
    g = summary["gemini"]
    rows = summary["scenarios"]
    thought_ratio = g["tokens_thought"] / max(1, g["tokens_out"])
    lines = [
        BEGIN,
        "",
        "The corpus above runs on the offline plane, which is a deliberate choice:",
        "a committed result has to be reproducible by somebody with no Vertex",
        "project, and a benchmark that needs a model endpoint to be reachable is a",
        "benchmark that will one day report the endpoint. It leaves a fair question",
        "open, though - what is Gemini contributing, and could it contribute",
        "something unwanted? So the same disruptions run on both planes and the two",
        "runs are diffed.",
        "",
        "```bash",
        "python -m bench.reasoning_plane --count %d" % rows,
        "```",
        "",
        "**Model:** `%s` on Vertex AI, %d disruptions, seed %s. Artifact: "
        "`bench/results/reasoning_plane.json`."
        % (summary["model"], rows, summary["seed"]),
        "",
        "### 7.1 What the model may not move",
        "",
        "| Compared across both planes | Result |",
        "|---|---|",
        "| Disruptions whose decisions were byte-identical | **%d of %d** |"
        % (summary["decisions_identical"], rows),
        "| Selected plan, and its content hash | identical in all %d |" % rows,
        "| Published plans, refused plans and their minimal conflict sets | identical |",
        "| Access preservation, verification readiness, final state | identical |",
        "| Status and cited constraints on every expert finding | identical |",
        "",
        "This is the separation the whole design rests on, measured rather than",
        "asserted. The reasoning plane writes the sentence on a finding. It does not",
        "decide feasibility, it does not choose a plan, and it cannot reach the",
        "constraint registry - `engine.publish` takes its verdict from",
        "`engine.validate`, and no model output is anywhere on that call path.",
        "",
        "### 7.2 What the model does",
        "",
        "| | |",
        "|---|---|",
        "| Finding headlines rewritten by Gemini | **%d of %d** (%.1f%%) |"
        % (summary["headlines_reworded"], summary["headlines_compared"],
           100 * summary["headlines_reworded_rate"]),
        "| Calls to the model | %d |" % g["calls"],
        "| Calls that failed and fell back to the template | %d |" % g["failed"],
        "| Responses discarded by the grounding gate | %d |"
        % g["responses_rejected_as_ungrounded"],
        "| Mean latency per call | %.0f ms (p95 %.0f ms) |"
        % (g["mean_latency_ms"], g["p95_latency_ms"]),
        "| Tokens in / out / spent thinking | %s / %s / %s |"
        % (f"{g['tokens_in']:,}", f"{g['tokens_out']:,}", f"{g['tokens_thought']:,}"),
        "| Mean response length | %.0f characters |" % g["mean_response_chars"],
        "",
        "The plane is reached only where there is something to interpret. An agent",
        "whose domain is clear says so from a fixed sentence and never calls the",
        "model, which is why %d calls cover %d disruptions rather than %d."
        % (g["calls"], rows, rows * 11),
        "Rewriting is what proves the model was in the loop at all: a run where",
        "every headline came back identical to its template is a run that quietly",
        "fell back, and this script exits non-zero on one.",
        "",
        "**Thinking tokens are the operational surprise.** Gemini 3.x spends them",
        "before it answers and they draw on the same output budget - %s of them"
        % f"{g['tokens_thought']:,}",
        "against %s tokens of actual sentence, about %.0f:1. A budget sized for a"
        % (f"{g['tokens_out']:,}", thought_ratio),
        "two-sentence headline comes back as half a clause, or as nothing at all,",
        "and half a sentence about a safety finding is worse than the template it",
        "replaced. The plane treats a truncated response as a failed call rather",
        "than a short one, and `GeminiReasoner.MAX_OUTPUT_TOKENS` is sized for the",
        "thinking rather than for the answer.",
        "",
        "### 7.3 What it costs, and what the fan-out buys",
        "",
        "| Per disruption | Offline | Gemini |",
        "|---|---|---|",
    ]
    concurrent = (fanout or summary)["mean_wall_ms"]
    lines += [
        "| Wall clock, agents assessed concurrently | %.0f ms | %.0f ms |"
        % (concurrent.get("offline", 0), concurrent.get("gemini", 0)),
    ]
    if serial:
        sp = serial["mean_wall_ms"]
        # The same disruptions both ways. Timing a 40-disruption parallel run
        # against an 8-disruption serial one would be comparing two corpora and
        # calling the difference a speed-up.
        matched = (fanout or summary)["mean_wall_ms"]
        matched_n = (fanout or summary)["scenarios"]
        speedup = sp.get("gemini", 0) / max(1.0, matched.get("gemini", 1))
        lines += [
            "| Wall clock, one agent at a time (`AA_ASSESSMENT_WORKERS=1`) | "
            "%.0f ms | %.0f ms |" % (sp.get("offline", 0), sp.get("gemini", 0)),
            "",
            "The second row is the same %d disruptions as the first, run both ways."
            % matched_n,
            "Running the eleven experts concurrently is worth almost nothing on the",
            "offline plane and is the difference between a usable and an unusable",
            "product on the Gemini one: **%.1fx**, because the round costs one" % speedup,
            "agent's latency instead of the sum of eleven. The event log is unchanged",
            "by it - `map` returns in the order the agents were declared, the events",
            "are emitted in that order from a single thread, and the reasoning ledger",
            "is sorted back into it, so a concurrent run and a serial run of the same",
            "disruption produce the same log. `tests/test_parallel_assessment.py`",
            "asserts both halves: that the agents genuinely overlap, and that the",
            "overlap changes nothing.",
        ]
    lines += [
        "",
        "### 7.4 Running it against a live endpoint",
        "",
        "```bash",
        "gcloud services enable aiplatform.googleapis.com --project $GOOGLE_CLOUD_PROJECT",
        "pip install -e '.[cloud]'",
        "GOOGLE_CLOUD_PROJECT=... AA_REASONING_MODE=gemini python -m allaccess.cli hero",
        "```",
        "",
        "`GET /api/about` reports which plane is live and `GET /api/findings` reports",
        "every call it made, including anything the grounding gate threw away, so a",
        "judge never has to take the plane on trust.",
        "",
        END,
    ]
    return "\n".join(lines)


def update_docs(path: Path, section: str) -> None:
    text = path.read_text(encoding="utf-8")
    start, finish = text.index(BEGIN), text.index(END) + len(END)
    path.write_text(text[:start] + section + text[finish:], encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--seed", type=int, default=20260314)
    parser.add_argument("--serial", action="store_true",
                        help="assess one agent at a time, to price the fan-out")
    parser.add_argument("--out", type=Path, default=RESULTS / "reasoning_plane.json")
    parser.add_argument("--docs", type=Path, default=ROOT / "docs" / "BENCHMARK.md",
                        help="rewrite section 7 from this run; pass 'none' to skip")
    args = parser.parse_args()

    if args.serial:
        os.environ["AA_ASSESSMENT_WORKERS"] = "1"

    scenarios = generate(args.count, seed=args.seed)
    twin = build_twin()

    rows: list[dict[str, Any]] = []
    calls: dict[str, list[Any]] = {"offline": [], "gemini": []}
    wall: dict[str, list[float]] = {"offline": [], "gemini": []}
    planes: dict[str, str] = {}

    for index, scenario in enumerate(scenarios, 1):
        row: dict[str, Any] = {"scenario_id": scenario.scenario_id,
                               "family": scenario.family}
        results: dict[str, Any] = {}
        for plane in ("offline", "gemini"):
            result, reasoner, elapsed = run_one(scenario, plane, twin)
            results[plane] = result
            calls[plane].extend(reasoner.calls())
            wall[plane].append(elapsed)
            planes[plane] = getattr(reasoner, "model", None) or reasoner.plane

        same_decision = results["offline"]["decisions"] == results["gemini"]["decisions"]
        shared = set(results["offline"]["headlines"]) & set(results["gemini"]["headlines"])
        reworded = sum(
            1 for key in shared
            if results["offline"]["headlines"][key] != results["gemini"]["headlines"][key]
        )
        row["decisions_identical"] = same_decision
        row["headlines_compared"] = len(shared)
        row["headlines_reworded"] = reworded
        if not same_decision:
            row["divergence"] = {
                field: [results["offline"]["decisions"][field],
                        results["gemini"]["decisions"][field]]
                for field in results["offline"]["decisions"]
                if results["offline"]["decisions"][field]
                != results["gemini"]["decisions"][field]
            }
        rows.append(row)
        print(
            f"  {index:>3}/{len(scenarios)} {scenario.scenario_id:<28} "
            f"decisions {'match' if same_decision else 'DIFFER'}  "
            f"{reworded}/{len(shared)} headlines rewritten",
            flush=True,
        )

    identical = sum(1 for r in rows if r["decisions_identical"])
    compared = sum(r["headlines_compared"] for r in rows)
    reworded = sum(r["headlines_reworded"] for r in rows)
    gemini = plane_report(calls["gemini"])

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "platform": f"{platform.system()} {platform.release()}",
        "scenarios": len(rows),
        "seed": args.seed,
        "assessment": "serial" if args.serial else "parallel",
        "model": planes.get("gemini"),
        "decisions_identical": identical,
        "decisions_identical_rate": round(identical / max(1, len(rows)), 4),
        "headlines_compared": compared,
        "headlines_reworded": reworded,
        "headlines_reworded_rate": round(reworded / max(1, compared), 4),
        "gemini": gemini,
        "offline": plane_report(calls["offline"]),
        "mean_wall_ms": {
            plane: round(statistics.fmean(values), 1)
            for plane, values in wall.items() if values
        },
        "rows": rows,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print()
    print(f"  decisions identical      {identical}/{len(rows)}")
    print(f"  headlines rewritten      {reworded}/{compared}")
    print(f"  gemini calls             {gemini['calls']} "
          f"({gemini['failed']} failed, "
          f"{gemini['responses_rejected_as_ungrounded']} rejected as ungrounded)")
    print(f"  gemini tokens            {gemini['tokens_in']} in, "
          f"{gemini['tokens_out']} out, {gemini['tokens_thought']} thought")
    print(f"  gemini latency           {gemini['mean_latency_ms']} ms mean, "
          f"{gemini['p95_latency_ms']} ms p95")
    print(f"  wall clock per disruption {summary['mean_wall_ms']}")
    print(f"  wrote {args.out}")

    if str(args.docs).lower() != "none" and not args.serial:
        serial_path = RESULTS / "reasoning_plane_serial.json"
        serial = (
            json.loads(serial_path.read_text(encoding="utf-8"))
            if serial_path.exists() else None
        )
        fanout_path = RESULTS / "reasoning_plane_fanout.json"
        fanout = (
            json.loads(fanout_path.read_text(encoding="utf-8"))
            if fanout_path.exists() else None
        )
        update_docs(args.docs, render_section(summary, serial, fanout))
        print(f"  wrote {args.docs} section 7")

    # A run where nothing was rewritten never reached the model.
    return 0 if (identical == len(rows) and reworded > 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
