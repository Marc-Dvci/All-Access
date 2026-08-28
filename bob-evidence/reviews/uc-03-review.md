# Review record — UC-03, call-sheet connector modernization

**Status: no session has been run. This file is the review *instrument*, written
in advance. Sections 3 and 4 are empty and stay empty until there is something
true to put in them.**

Cited from `src/allaccess/systems/callsheet_legacy.py`,
`callsheet_modern.py` and `pyproject.toml`.

---

## 1. Why the instrument is written first

A review checklist written after seeing the output measures the output. Written
before, it measures the work. The eight defects below were catalogued while
authoring the before-state, so the bar is fixed and a session can be judged
against it rather than admired.

---

## 2. Defect inventory and the bar for each

| # | Defect in `callsheet_legacy.py` | What a resolution must do | Check |
|---|---|---|---|
| 1 | No schema; takes a dict and pokes at whatever keys exist | Validate at the boundary and reject bad input with a reason | Contract test with a malformed payload |
| 2 | Mutable module-level state shared by every caller | Instance-scoped state; two connectors cannot interfere | Two instances, interleaved publishes |
| 3 | `poll_for_changes` busy-checks a global | Event-driven: consume commands, emit results | No polling loop remains |
| 4 | No idempotency; the same revision publishes twice | Idempotency key per revision; a repeat returns the original and changes nothing | Duplicate-publish test |
| 5 | Bare `except` returning `None`, so failure looks like "no change" | Typed `CommandResult` with status and reason | Failure test asserts status, not falsiness |
| 6 | Personal data in the log line | Log counts, never names or call times | `privacy.check_no_prohibited_fields` over emitted lines |
| 7 | Off-by-one: the first publish is revision 2 | First publish is revision 2 *of* revision 1 — i.e. the numbering is right, not merely different | Assertion on the sequence, not on one value |
| 8 | No contract tests, failure tests or acknowledgment path | All three | `tests/test_callsheet_migration.py` |

**Defect 7 is the interesting one.** It is a real bug rather than a staged one,
and "fix the off-by-one" is ambiguous: a session could satisfy a naive test by
starting at 1 and be just as wrong. The check is on the whole sequence.

## 2.1 The parity requirement

`test_modern_matches_legacy_semantics` asserts the modernized connector produces
the same *intended* call-sheet content as the legacy one for identical input.
This is what makes "behaviour preserving except where a defect was deliberately
fixed" a checkable claim rather than a reassuring sentence. Any divergence must
be traceable to a numbered defect above.

---

## 3. Session outcome

*Empty. No session has been run.*

To be recorded when one is:

- Which mode, which model, what was in context
- The plan Bob produced, and what the human amended before approving it
- The diff, and which parts survived review
- **Accepted suggestions**, with what each one changed
- **Rejected suggestions**, with the reason each was rejected
- Defects Bob found that this inventory did not anticipate
- Defects in this inventory that Bob missed
- Test results before and after, from `tools/mcp_test_results.py`

---

## 4. Human review

*Empty. Nothing has been reviewed, because nothing has been produced.*

---

## 5. Note on the current state of the code

`callsheet_modern.py` exists in the tree and meets all nine acceptance criteria
in the brief. **It was written by hand.** It is the reference target, not a
session output, and its docstring says so. Nothing in this repository attributes
it to IBM Bob.

If UC-03 is run as a re-derivation (brief §6a), the reference must be moved aside
first, and what Bob returns must be compared against it and recorded here —
including the ways it is worse.
