"""Development-time MCP server over the committed test and benchmark artifacts.

    python -m tools.mcp_test_results

Registered in `.bob/mcp.json` as `test-results`. It exists for one reason: so
that IBM Bob, asked to write or review a claim about how well this system
performs, reads the number out of `bench/results/` instead of producing a
plausible one.

That failure mode is not hypothetical. The sibling project in this repository
hit it -- a generated dataset cited session counts its input did not contain,
which is to say it was teaching a model to invent numbers. The cheapest defence
is to make the real number easier to reach than the invented one.

Four tools, all read-only, all reading files that are committed:

* `latest_benchmark`   -- `bench/results/summary.json`, whole or by section
* `benchmark_scenarios`-- filtered rows from `bench/results/scenarios.jsonl`, so
                          any headline figure can be recomputed from the raw
                          measurements rather than trusted
* `latest_test_run`    -- runs pytest and reports what actually passed
* `coverage_summary`   -- what the artifacts do and do not cover

`latest_test_run` executes pytest, which is the one thing here that is not a
file read. It is deliberate: "the tests pass" is the claim most often made from
memory, and the suite is under six seconds. It runs with `--co -q` first for the
count, then the real run, and reports the exit status verbatim -- including a
failure. A tool that only reports green is worse than no tool.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.mcp_common import MCPServer  # noqa: E402

RESULTS = ROOT / "bench" / "results"
SUMMARY = RESULTS / "summary.json"
ABLATIONS = RESULTS / "ablations.json"
CALIBRATION = RESULTS / "calibration.json"
SCENARIOS = RESULTS / "scenarios.jsonl"
A11Y = ROOT / "docs" / "accessibility_audit.json"

server = MCPServer(
    name="productionpulse-test-results",
    instructions=(
        "The committed evidence for every quantitative claim about "
        "ProductionPulse. Read a number from here before writing it into a "
        "document. If a figure you want to state is not available from one of "
        "these tools, it has no artifact behind it: either generate the "
        "artifact or drop the claim."
    ),
)


def _load(path: Path) -> Any:
    if not path.exists():
        raise FileNotFoundError(
            f"{path.relative_to(ROOT)} does not exist. Generate it with "
            f"`python -m bench.run_benchmark --count 1000 --workers 6 --ablations`."
        )
    return json.loads(path.read_text(encoding="utf-8"))


@server.tool(
    "latest_benchmark",
    "The committed benchmark summary. Pass `section` for one part of it "
    "(impact_analysis, planning_quality, execution_quality, agent_quality, "
    "inclusion_and_privacy, platform_quality, robustness, latency, corpus, "
    "environment), or `ablations` / `calibration` for those artifacts.",
    {
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "artifact": {
                "type": "string",
                "enum": ["summary", "ablations", "calibration"],
                "description": "Which artifact to read. Defaults to summary.",
            },
        },
    },
)
def latest_benchmark(args: dict[str, Any]) -> Any:
    artifact = str(args.get("artifact") or "summary")
    path = {"summary": SUMMARY, "ablations": ABLATIONS, "calibration": CALIBRATION}[artifact]
    data = _load(path)
    section = args.get("section")
    if section:
        if section not in data:
            raise KeyError(f"no section {section!r}; available: {', '.join(sorted(data))}")
        return {"artifact": artifact, "section": section, "data": data[section]}
    return {"artifact": artifact, "generated_at": data.get("environment", {}), "data": data}


@server.tool(
    "benchmark_scenarios",
    "Raw per-scenario measurements, so a summary figure can be recomputed "
    "rather than taken on trust. One row per scenario per configuration.",
    {
        "type": "object",
        "properties": {
            "family": {
                "type": "string",
                "description": "weather | cast_crew | location | equipment | "
                               "access_communication | continuity | operational_systems",
            },
            "config": {
                "type": "string",
                "description": "full | no_twin | no_robustness | no_reconciliation | "
                               "no_validation. Defaults to full.",
            },
            "scenario_id": {"type": "string"},
            "fields": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Restrict the returned columns.",
            },
            "limit": {"type": "integer", "description": "Default 25, max 200."},
        },
    },
)
def benchmark_scenarios(args: dict[str, Any]) -> dict[str, Any]:
    if not SCENARIOS.exists():
        raise FileNotFoundError("bench/results/scenarios.jsonl does not exist")
    config = str(args.get("config") or "full")
    family = args.get("family")
    scenario_id = args.get("scenario_id")
    fields = args.get("fields")
    limit = max(1, min(int(args.get("limit") or 25), 200))

    rows: list[dict[str, Any]] = []
    matched = 0
    with SCENARIOS.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            if row.get("config") != config:
                continue
            if family and row.get("family") != family:
                continue
            if scenario_id and row.get("scenario_id") != scenario_id:
                continue
            matched += 1
            if len(rows) < limit:
                rows.append({k: row.get(k) for k in fields} if fields else row)
    return {
        "config": config,
        "matched": matched,
        "returned": len(rows),
        "truncated": matched > len(rows),
        "rows": rows,
    }


@server.tool(
    "latest_test_run",
    "Run the test suite now and report the result, including failures. This "
    "executes pytest; it does not read a cached report.",
    {
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "Optional pytest -k expression to narrow the run.",
            }
        },
    },
)
def latest_test_run(args: dict[str, Any]) -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-q", "--no-header"]
    expression = args.get("expression")
    if expression:
        command += ["-k", str(expression)]
    proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
        command, cwd=ROOT, capture_output=True, text=True, timeout=900
    )
    tail = [line for line in proc.stdout.strip().splitlines() if line.strip()][-25:]
    return {
        "command": " ".join(command[1:]),
        "exit_code": proc.returncode,
        "passed": proc.returncode == 0,
        "output_tail": tail,
        "stderr_tail": proc.stderr.strip().splitlines()[-10:],
    }


@server.tool(
    "coverage_summary",
    "What evidence exists, when it was generated, and what it does not cover. "
    "Read this before writing a claim, to find out whether it is supportable.",
)
def coverage_summary(_args: dict[str, Any]) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    for name, path in (
        ("benchmark_summary", SUMMARY),
        ("ablations", ABLATIONS),
        ("calibration", CALIBRATION),
        ("scenarios_jsonl", SCENARIOS),
        ("accessibility_audit", A11Y),
    ):
        artifacts[name] = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
        }
    environment: dict[str, Any] = {}
    if SUMMARY.exists():
        environment = json.loads(SUMMARY.read_text(encoding="utf-8")).get("environment", {})
    return {
        "artifacts": artifacts,
        "benchmark_environment": environment,
        "not_covered": [
            "No run against a hosted Confluent Cloud cluster. The benchmark uses "
            "the in-process bus, which performs the same validation and "
            "governance checks; the Confluent client path is exercised by "
            "tests/test_stream.py but not at benchmark scale.",
            "No run against Gemini on Vertex AI. Every committed figure is from "
            "the offline reasoning plane; `environment.reasoning_plane` in the "
            "summary states which was used.",
            "No browser-rendered accessibility testing. tools/a11y_audit.py is a "
            "static source audit; docs/ACCESSIBILITY.md lists what it cannot check.",
            "No IBM Bob session has been recorded on this repository. See "
            "bob-evidence/README.md for what is and is not established.",
        ],
    }


if __name__ == "__main__":
    server.run()
