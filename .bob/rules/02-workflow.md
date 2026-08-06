# Approved workflow

For every subsystem change:

1. A human writes the requirement and the acceptance criteria as a task brief in
   `bob-evidence/briefs/`.
2. Bob **Plan** mode produces a technical plan. It does not write code.
3. A human reviews and approves or amends the plan. The approval is recorded in
   the brief.
4. Bob **Agent** mode implements the scoped change, and only that change.
5. `pytest -q` and `ruff check src tests` run. Both must be clean.
6. Bob **Security Review** mode reviews the diff and files findings in
   `bob-evidence/security/`.
7. A human reviews the diff and records accepted and rejected suggestions in
   `bob-evidence/reviews/`.
8. The change is mapped to production code and test evidence in
   `bob-evidence/CONTRIBUTION_MAP.md`.

Rejected suggestions are recorded with the reason. A ledger that only records
what was accepted is a marketing document.
