# IBM Bob evidence ledger

## Status, stated first because it is the only thing that matters here

**No IBM Bob session has been run against this repository.**

Everything in this directory is either (a) committed Bob *configuration*, which
proves intent and not use, or (b) *inputs prepared for sessions that have not
happened yet* — task briefs, acceptance criteria, a preserved before-state, and
the templates the sessions will be recorded into.

There are no session summaries here, no generated diffs, no "findings Bob
caught", no acceptance rates and no productivity claims, because none of those
things exist yet. A ledger that invented them would be a fabricated record, and
it is the one part of this submission where that would be both dishonest and
trivially checkable.

When sessions are run, `SESSION_TEMPLATE.md` is the shape each one is recorded
in, `CONTRIBUTION_MAP.md` gains rows mapping contributions to production code
and tests, and this section is rewritten to say what actually happened.

---

## What *is* established

| Artifact | What it proves |
|---|---|
| `.bob/custom_modes.yaml` | Seven project-specific modes with scoped file permissions |
| `.bob/rules/`, `.bob/rules-*/` | Engineering standards and the approved workflow, committed |
| `.bob/mcp.json` | Two development MCP servers, both implemented and both answering the protocol |
| `.bobignore` | Context scoping |
| `tools/mcp_schema_registry.py` | Read-only access to the 23 data contracts, with a real compatibility check |
| `tools/mcp_test_results.py` | Read-only access to the committed benchmark artifacts and a live pytest run |
| `src/productionpulse/systems/callsheet_legacy.py` | The preserved before-state for UC-03, with eight documented defects |
| `USE_CASES.md`, `briefs/` | Six use cases with requirements and acceptance criteria |

The two MCP servers are the part of this that is more than configuration. They
are exercised in CI (`.github/workflows/ci.yml`, job `deployment`), and
`mcp_test_results` exists for a specific reason: so that a session asked to write
a claim about how well this system performs reads the number out of
`bench/results/` instead of producing a plausible one.

---

## The scoping decision worth reading

`.bob/custom_modes.yaml` gives Solver Engineering mode permission to write
predicates and tests, and **no permission to edit the constraint registry**.

That is not a safety theatre restriction. Deciding *what the rules are* — what
counts as a hard safety threshold, which access arrangements are binding, who
must approve an overtime call — is a production policy decision owned by the
safety lead, the UPM and the accessibility coordinator. Bob implements the
approved formal model. It does not choose it. The same reasoning runs through
every mode: Production Architecture can write ADRs but not source; Event
Contract can write schemas but not solver code; Documentation and Submission can
write docs but cannot touch `src/`.

See `docs/adr/ADR-011-bob-scope.md`.

---

## The workflow each session must follow

From `.bob/rules/02-workflow.md`, unchanged:

1. A human writes the requirement and acceptance criteria as a brief in `briefs/`.
2. Bob **Plan** mode produces a technical plan. It does not write code.
3. A human approves or amends the plan; the approval is recorded in the brief.
4. Bob **Agent** mode implements the scoped change, and only that change.
5. `pytest -q` and `ruff check src tests` run. Both must be clean.
6. Bob **Security Review** mode reviews the diff; findings go in `security/`.
7. A human reviews the diff and records accepted **and rejected** suggestions in
   `reviews/`.
8. The change is mapped to code and tests in `CONTRIBUTION_MAP.md`.

Step 7 is the one that makes this a ledger rather than a marketing document.
Rejected suggestions are recorded with the reason.

---

## For whoever runs the first session

Start with `briefs/uc-03-callsheet-modernization.md`. It is the strongest use
case: a deliberately realistic legacy adapter with eight documented defects, a
preserved before-state, fixed acceptance criteria, and a parity test that makes
"behaviour preserving except where a defect was fixed" checkable rather than
asserted.

Record the session in `sessions/` using `SESSION_TEMPLATE.md`. Record what
happened, including the parts that went badly. A session where Bob proposed
something wrong and a human caught it is better evidence of a working process
than one where everything was accepted.
