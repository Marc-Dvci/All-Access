# ADR-010 — Benchmark results are committed to the repository

**Status:** Accepted

## Context

`bench/results/scenarios.jsonl` is about 1.8 MB and roughly 5,000 rows. The
reflex is to gitignore it.

## Decision

It is committed, along with `summary.json`, `ablations.json` and
`calibration.json`. `.gitignore` names them explicitly as deliberately *not*
ignored, with the reason, so the next person to tidy the repository reads it
first.

Every quantitative claim in the README and `docs/` reads from these files. One
row per scenario per configuration means any headline figure can be
**recomputed** rather than trusted — and CI does exactly that on every push,
recomputing the zero-hard-violations claim from the raw rows and failing if it
disagrees with the summary that asserts it.

## Rejected

**Publishing the summary only.** A summary is a claim about data nobody can see.

**Regenerating in CI and publishing as a build artifact.** The 1,000-scenario run
takes about six minutes, which is affordable. But then the numbers in the
documentation move whenever CI runs, without anyone deciding they should, and a
headline figure that changes unattended is not evidence. Regeneration is a
deliberate act; CI runs a 48-scenario smoke test instead.

## Consequences

- A judge can verify any number without running anything.
- `tools/mcp_test_results.py` serves the same files to IBM Bob over MCP, so a
  session writing a performance claim reads the number rather than producing a
  plausible one.
- **Inconvenient:** the repository carries a couple of megabytes of results, and
  regenerating produces a large diff. That is the price of the numbers being
  checkable, and it is worth paying.
