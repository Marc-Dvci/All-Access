# Session record — UC-03, call-sheet connector modernization

**Brief:** `../briefs/uc-03-callsheet-modernization.md`
**Mode:** Connector Modernization
**Tool:** IBM Bob 2.0.3
**Recording:** `../Bob session.mp4` (5:26) — also uploaded (link in `../README.md`)
**Run by:** the human maintainer, in one session.
**Method:** (a) re-derivation — Bob was given only `callsheet_legacy.py` and the
brief, and told **not** to open the hand-written reference `callsheet_modern.py`.

---

## What Bob did

1. **Loaded the project.** IBM Bob opened this repository and read
   `.bob/custom_modes.yaml` — all seven project modes appeared in the mode picker
   (Production Architecture, Event Contract, Connector Modernization, Solver
   Engineering, Security Review, Test and Evaluation, Documentation and
   Submission). Connector Modernization mode was selected, which scopes writes to
   `src/allaccess/systems/` and `tests/test_callsheet_migration.py`.
2. **Read the inputs it was allowed to read.** The brief, `callsheet_legacy.py`,
   the existing `tests/test_callsheet_migration.py`, and `production/world.py`
   (to learn what the world module exposes). It did **not** open
   `callsheet_modern.py`. It then derived, from the legacy module and the test
   file's imports, a 16-point contract the connector must satisfy (constructor
   takes `production_id`, `apply(command) -> CommandResult`, `current_revision`,
   redacted `.log`, `.state()` shape, first publish is revision 2, idempotency by
   key and by content, schema validation, typed rejections, and so on).
3. **Wrote `src/allaccess/systems/callsheet_bob.py` from scratch** — a typed
   (Pydantic, `extra="forbid"`), idempotent, event-driven connector whose
   `apply()` replaces the legacy `poll_for_changes` busy-loop entirely.
4. **Wrote 16 `test_bob_*` tests** appended as a dedicated section of
   `tests/test_callsheet_migration.py`, one failing-first test per defect, each
   with a docstring stating why it fails without the fix.
5. **Summarized the work** as a design-decision table and an eight-defect table
   mapping each legacy defect to its fix and its failing-first test.

Session token use ≈ 92.6k / 270k.

---

## The eight defects, resolved

Each is documented in the `callsheet_bob.py` module docstring with the test that
covers it.

| # | Legacy defect | Fix in `callsheet_bob.py` | Failing-first test |
|---|---|---|---|
| D1 | No schema — any dict stored silently | `CallSheetEntry` Pydantic model, `extra="forbid"` | `test_bob_malformed_entry_is_rejected_not_stored` |
| D2 | Mutable module-level state shared between callers | all state instance-scoped in `__init__` | `test_bob_two_connectors_do_not_interfere` |
| D3 | `poll_for_changes` busy-loop | structural removal — synchronous `apply()` | (structural — no polling remains) |
| D4 | No idempotency | key-based `_seen` + content-hash `_content_seen` | `test_bob_duplicate_publish_changes_nothing` |
| D5 | Bare `except` returns `None` | `apply()` always returns a typed `CommandResult` | `test_bob_failures_are_typed_not_silent` |
| D6 | Cast call times written to the log | `_redacted_summary()` — scene and cast-call **counts** only, no ids, no names | `test_bob_log_line_carries_no_personal_data` |
| D7 | Off-by-one revision numbering (the genuine bug) | store baseline is revision 1; first publish is revision 2 | `test_bob_first_revision_is_two_and_supersedes_one` |
| D8 | No contract tests, no acknowledgment path | `CommandResult` with system version; 16 tests | `test_bob_result_carries_system_version` |

---

## Independent verification (human review, after the session)

Run against the committed result:

```
ruff check src/allaccess/systems/callsheet_bob.py   # clean
pytest -q tests/test_callsheet_migration.py          # 36 passed (16 new)
pytest -q                                            # 249 passed
```

**Re-derivation comparison.** `callsheet_bob.py` (311 lines) was written without
sight of the hand-written reference `callsheet_modern.py` (282 lines). On every
load-bearing design choice they agree: a Pydantic schema that forbids unknown
fields, per-instance state, content-hash idempotency, a redaction layer that logs
counts rather than identities, revision numbering that starts the first publish
at 2, and a typed `CommandResult` on every path. Reaching the reference's
architecture independently is the evidence the brief was built to produce.

---

## Accepted / rejected

This was a single-shot implementation task; the human accepted Bob's deliverable
after the verification above, having independently derived it and compared it to
the reference. **Suggestions accepted: 1 (the connector + its tests). Rejected:
0.** The independent check that a ledger of this kind needs is the re-derivation
comparison above, not an in-session disagreement.

## Out-of-scope discipline held

Bob touched only `src/allaccess/systems/callsheet_bob.py` and
`tests/test_callsheet_migration.py`. It did not modify the constraint registry,
the solver, the twin, the event contracts, or the reference connector — the
boundaries the Connector Modernization mode enforces.
