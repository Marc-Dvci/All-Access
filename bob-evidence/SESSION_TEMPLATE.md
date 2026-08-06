# Session record — <UC-ID> — <short title>

> Copy to `sessions/<uc-id>-<nnn>.md` and fill in. Record what happened,
> including the parts that went badly. A session where Bob proposed something
> wrong and a human caught it is better evidence of a working process than one
> where everything was accepted.

**Session id:**
**Use case:** `USE_CASES.md#uc-xx`
**Brief:** `briefs/<file>.md`
**Date:**
**Mode:**
**Operator:**

## 1. Context given

What was in scope, which files, which MCP servers were connected and what they
were asked for. Note anything `.bobignore` kept out that mattered.

## 2. Plan (workflow step 2)

Bob's technical plan, verbatim or linked.

**Human decision (step 3):** approved / amended / rejected.
**Amendments:** what was changed before approval, and why.

## 3. Implementation (step 4)

Files touched. Diff, or a reference to the commit.

Anything implemented that the plan did not describe — that is a scope escape and
worth recording even when the change was good.

## 4. Automated checks (step 5)

```
pytest -q            →
ruff check src tests →
```

Paste the real output. If something failed, say what and what was done about it.

## 5. Security review (step 6)

Findings to `security/`. Summarise here with severity, and note findings that
were already mitigated — those are still findings and should not be dropped.

## 6. Human review (step 7)

### Accepted

| # | Suggestion | What it changed |
|---|---|---|

### Rejected

| # | Suggestion | Why rejected |
|---|---|---|

**The rejected table is not optional.** If it is empty, either the session was
unusually good or the review was unusually shallow; say which.

## 7. What Bob caught that the brief did not anticipate

## 8. What Bob missed that the brief did anticipate

Both sections matter. Section 8 is the one that gets left out.

## 9. Measures

| Measure | Value | Source |
|---|---|---|
| Suggestions accepted / total | | this record |
| Tests added | | `tools/mcp_test_results.py` |
| Tests passing before / after | | `latest_test_run` |
| Benchmark deltas, if any | | `bench/results/summary.json` |

Do not record a time saving unless it was measured against something. An
estimate of how long it "would have taken" is not a measurement.

## 10. Contribution map row

Row added to `CONTRIBUTION_MAP.md`: yes / no.
