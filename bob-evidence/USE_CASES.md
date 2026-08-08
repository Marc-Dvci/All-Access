# Use cases

Six subsystems where IBM Bob is the engineering partner, each scoped to one mode
from `.bob/custom_modes.yaml` and each with **acceptance criteria written before
the session runs**. That ordering is the point: a use case whose success
criterion is written afterwards is a use case that cannot fail.

| ID | Use case | Mode | Status |
|---|---|---|---|
| [UC-01](#uc-01) | Event contract evolution | Event Contract | prepared |
| [UC-02](#uc-02) | Solver predicate coverage | Solver Engineering | prepared |
| [UC-03](#uc-03) | Legacy call-sheet connector modernization | Connector Modernization | prepared, before-state preserved |
| [UC-04](#uc-04) | Security review of the approval path | Security Review | prepared |
| [UC-05](#uc-05) | Scenario and chaos coverage | Test and Evaluation | prepared |
| [UC-06](#uc-06) | Documentation synchronisation | Documentation and Submission | prepared |

---

## UC-01 {#uc-01}
### Event contract evolution

**Requirement.** Add a field to an existing event contract without breaking
consumers, and prove it.

**Why it is a good Bob task.** Compatibility is exactly the kind of rule that is
easy to state and easy to violate by accident, and the verdict is mechanical.
`tools/mcp_schema_registry.py` exposes `check_compatibility`, so the session can
consult the registered schema instead of reasoning about it from memory.

**Acceptance criteria.**
- `check_compatibility` returns compatible under BACKWARD for every changed subject.
- The new field is optional and the subject's `version` is incremented.
- A contract test covers a payload with and without the new field.
- `pytest -q` and `ruff check src tests` are clean.

**Scope.** `src/productionpulse/stream/schemas.py`, `tests/test_stream.py`. Not
the solver, not the registry of constraints.

---

## UC-02 {#uc-02}
### Solver predicate coverage

**Requirement.** For a named constraint record, write a property-based test that
generates plans and asserts the predicate's verdict against an independently
computed expectation.

**Why it is a good Bob task.** The predicates are the load-bearing part of the
system and their tests are the part most likely to be thin. Property tests are
mechanical to write and tedious to write well.

**Acceptance criteria.**
- The test fails if the predicate's threshold is changed by one unit in either
  direction. A test that passes against a deliberately broken predicate is not a
  test.
- No change to `constraints/registry.py`. Bob implements the approved formal
  model; it does not decide what the rules are.
- `pytest -q` clean.

**Scope.** `src/productionpulse/solver/predicates.py`, `tests/test_constraints.py`,
`tests/test_solver.py`.

---

## UC-03 {#uc-03}
### Legacy call-sheet connector modernization

**The primary use case.** A deliberately realistic legacy integration,
modernized into a typed, idempotent, event-driven connector that participates in
the hero workflow.

**Before state.** `src/productionpulse/systems/callsheet_legacy.py`, preserved
and excluded from lint (see the per-file ignore in `pyproject.toml`, which cites
this section). Eight documented defects:

1. No schema — takes a dict and pokes at whatever keys are there
2. Mutable module-level state shared between callers
3. Polling: `poll_for_changes` busy-checks a global
4. No idempotency — publishing the same revision twice publishes it twice
5. Errors swallowed by a bare `except` returning `None`, so failure looks like
   "no change"
6. Publishes personal data into the log line
7. Off-by-one revision numbering: the first publish is revision 2
8. No contract tests, no failure tests, no acknowledgment path

Defect 7 is a real bug, found while writing the before-state, and it is left in
because a modernization that does not have to find anything proves nothing.

**Reference target.** `src/productionpulse/systems/callsheet_modern.py`, written
by hand. It is the acceptance bar, not a Bob output — its docstring says so.

**Acceptance criteria.**
- Every one of the eight defects resolved, each traceable to a specific change.
- `test_modern_matches_legacy_semantics` passes: the modernized connector
  produces the same *intended* call-sheet content as the legacy one for the same
  input, so the change is provably behaviour preserving except where a defect
  was deliberately fixed.
- The connector publishes the revised call sheet and returns an acknowledgment
  event inside the hero workflow (`python -m productionpulse.cli hero`, 11/11).
- Failure tests: rejected command, duplicate command, stale plan version.
- No personal data in any log line, checked by
  `privacy.check_no_prohibited_fields`.

**Review record.** `reviews/uc-03-review.md` — the defect inventory and the
review criteria, written in advance. Populated with the session outcome when one
runs.

**Scope.** `src/productionpulse/systems/`, `tests/test_callsheet_migration.py`.

---

## UC-04 {#uc-04}
### Security review of the approval path

**Requirement.** Threat-model `execution/approvals.py` and the policy check that
guards it, and file findings.

**Acceptance criteria.**
- Every finding names the code path and a concrete exploitation sequence.
  "Consider validating input" is not a finding.
- Findings that are already mitigated are recorded as such, with the mitigation
  named, rather than dropped.
- No fix is applied in the same session as the review.

**Known ground truth for grading the session.** The approval is HMAC-signed over
the plan hash and the constraint-set hash, single-use, and expiring; authority is
checked separately in the policy path. A review that misses the per-process
signing-key default (`PP_APPROVAL_KEY` unset ⇒ approvals stop verifying across a
restart) has missed the real one. Recorded here so the session can be judged
rather than admired.

**Scope.** Read-only. Findings to `security/`.

---

## UC-05 {#uc-05}
### Scenario and chaos coverage

**Requirement.** Extend the operational-systems fault family. Three declared
faults are not injected by the harness — `command_rejection`,
`connector_failure`, `out_of_order_event` — and the benchmark reports them as
declared-but-not-injected rather than counting them as passes.

**Acceptance criteria.**
- Each new fault is injected by `bench/harness.py` and its handling measured.
- `declared_but_not_injected` in the summary shrinks accordingly.
- A fault that is not applicable to a scenario is recorded as `None`, never
  scored as a pass. The existing code does this; preserve it.

**Scope.** `bench/harness.py`, `src/productionpulse/disruptions.py`.

---

## UC-06 {#uc-06}
### Documentation synchronisation

**Requirement.** Check every quantitative claim in `README.md` and `docs/`
against `bench/results/`, and report drift.

**Why it is a good Bob task.** It is exactly the failure this project has already
hit once — a README carrying numbers from a smaller run than the committed
artifact — and `tools/mcp_test_results.py` exists to make the real number easier
to reach than the invented one.

**Acceptance criteria.**
- Every figure is either matched to an artifact or reported as unsupported.
- No number is *changed* in a document without the artifact being re-read.
- Claims with no artifact are listed for a human to either generate or remove.

**Scope.** `docs/`, `README.md`. Not `src/`.
