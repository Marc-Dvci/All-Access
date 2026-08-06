# Contribution map

Maps each IBM Bob contribution to the production code it changed and the tests
that cover it.

## Status

**Empty. No IBM Bob session has been run against this repository, so there are no
contributions to map.**

This file exists because `.bob/rules/02-workflow.md` step 8 requires it and
because its emptiness is itself the accurate record. It is not a placeholder for
rows that were deleted; it is a table that has never had a row.

| Use case | Session | Mode | Files changed | Tests | Accepted | Rejected |
|---|---|---|---|---|---|---|
| *(none)* | | | | | | |

---

## What goes in each column, when there is something to put there

- **Session** — the id in `sessions/`, one file per session.
- **Mode** — which of the seven modes in `.bob/custom_modes.yaml`. If a change
  crossed modes, that is two rows, because a change that needed permissions no
  single mode has is a finding about the mode scoping.
- **Files changed** — production paths only. A row that changes nothing under
  `src/`, `bench/` or `tools/` is documentation work; record it, but do not let
  it inflate the count.
- **Tests** — the specific tests that cover the change and did not exist, or did
  not pass, before it.
- **Accepted / Rejected** — counts of *suggestions*, not lines. Both columns are
  required. A ledger with an empty rejected column is not a ledger.

## Effectiveness measures

`.bob/rules/02-workflow.md` and the plan call for these to be published from this
project rather than asserted generally:

- time to implement a connector
- contract-test coverage before and after
- defects found before human review
- security findings and their remediations
- schema compatibility defects caught
- human rejection rate
- accepted-code survival after review
- benchmark regressions prevented

**None of these has a value yet.** They are not estimated here, and no
productivity claim appears anywhere in this repository. When sessions have run,
the numbers come from `tools/mcp_test_results.py` and from the session records,
and if they are unflattering they are published anyway.
