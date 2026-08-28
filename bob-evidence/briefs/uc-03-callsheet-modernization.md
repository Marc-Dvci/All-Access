# Task brief — UC-03, call-sheet connector modernization

**Mode:** Connector Modernization
**Written by:** the human maintainer, before any session
**Status:** approved as a brief; **no session run**
**Session record:** none yet. Add to `../sessions/` using `../SESSION_TEMPLATE.md`.

---

## 1. Requirement

`src/allaccess/systems/callsheet_legacy.py` is the integration that
publishes a revised call sheet to the production's call-sheet system. It is
representative of the integrations real productions actually run: written
quickly, kept alive because it works most of the time, and never given a
contract.

Replace it with a typed, idempotent, event-driven connector that participates in
the hero workflow, and prove the replacement is behaviour preserving except
where a defect was deliberately fixed.

## 2. Starting condition

Do not tidy `callsheet_legacy.py`. It is the before-state and the comparison is
worthless if it is cleaned up. Its docstring lists the eight defects; they are
all intentional except number 7, which is a genuine bug found while writing it
and deliberately left in.

## 3. Constraints on the work

- **Behaviour preservation is the hard requirement.** The modernized connector
  must produce the same intended call-sheet content for the same input. Where it
  differs, the difference must be one of the eight documented defects and must
  be named as such.
- **No change to the event contracts.** If the connector appears to need a
  contract change, stop and raise it — that is UC-01 and a different mode.
- **No personal data in any log line.** The legacy version logs a crew name;
  `redacted_summary()` is the pattern to follow. Verified by
  `privacy.check_no_prohibited_fields`.
- **The acknowledgment path is part of the deliverable.** A connector that
  publishes and does not confirm is the failure mode this whole system exists to
  catch.

## 4. Acceptance criteria

Each is mechanically checkable. A session is not complete until all pass.

| # | Criterion | How it is checked |
|---|---|---|
| 1 | All eight defects resolved | `reviews/uc-03-review.md` §2, defect by defect |
| 2 | Behaviour preserving | `test_modern_matches_legacy_semantics` passes |
| 3 | Idempotent | Publishing the same revision twice changes nothing and returns the original |
| 4 | Revision numbering correct | First publish is revision 2 *of* revision 1, asserted in tests |
| 5 | Typed failures | A rejected command returns a `CommandResult` with status and reason, never `None` |
| 6 | Stale plan versions rejected | Failure test |
| 7 | Participates in the hero workflow | `python -m allaccess.cli hero` → 11/11, connector publishes and acknowledges |
| 8 | No personal data in logs | `privacy.check_no_prohibited_fields` over the emitted lines |
| 9 | Clean | `pytest -q` and `ruff check src tests` |

## 5. Out of scope

The constraint registry, the solver, the twin, the approval path. If the work
appears to require any of them, it does not — raise it instead.

## 6. Reference target

`src/allaccess/systems/callsheet_modern.py` exists and meets all nine
criteria. It was **written by hand**, and its docstring says so.

Two ways to run this use case, and the ledger must record which:

- **(a) Re-derivation.** Move the reference implementation aside, give Bob only
  the legacy module and this brief, and compare what comes back. This is the
  stronger evidence — the reference is a fixed, independently-written answer to
  compare against, which is a rare luxury in evaluating an assistant.
- **(b) Review.** Give Bob the diff and ask Security Review and Test and
  Evaluation modes to find what is wrong with it. Weaker as a modernization
  demonstration, stronger as a review demonstration.

Do not do (a) and then present the existing reference as the session output.

## 7. Human approval

Brief approved as written. Approval of a *plan* is a separate step (workflow step
3) and has not happened, because no plan has been produced.
