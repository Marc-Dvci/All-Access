# ADR-011 — IBM Bob implements the approved formal model; it does not choose it

**Status:** Accepted

## Context

`.bob/custom_modes.yaml` defines seven modes with file permissions. The question
is where the boundaries go, and the tempting answer is "wherever Bob is
competent", which is broad.

## Decision

Competence is not the criterion. **Ownership of the decision** is.

Solver Engineering mode may write predicates and property tests. It may **not**
edit `constraints/registry.py`. Deciding what counts as a hard safety threshold,
which access arrangements are binding, or who must approve an overtime call is a
production policy decision owned by the safety lead, the UPM and the
accessibility coordinator. It is not an engineering decision, so it is not
delegable to an engineering assistant however good that assistant is.

The same line runs through every mode:

| Mode | May edit | May not |
|---|---|---|
| Production Architecture | `docs/`, `README.md`, `.bob/` | `src/` |
| Event Contract | schema and contract directories | solver, registry |
| Connector Modernization | `systems/` and its tests | contracts, registry |
| Solver Engineering | predicates, solver, tests | **the constraint registry** |
| Security Review | nothing — findings only | everything |
| Test and Evaluation | tests, fixtures, harness | product code under `src/` |
| Documentation and Submission | `docs/`, `README.md` | `src/` |

Permissions are `fileRegex` scopes, so the boundary is enforced rather than
advisory.

## Rejected

**One general mode with full access.** It works, and it makes the ledger
meaningless: every contribution would be "Bob changed something", with no
statement about what kind of decision was delegated.

**Read-only everywhere, with a human applying every diff.** Too conservative to
demonstrate anything, and it makes the workflow's review step redundant rather
than load-bearing.

## Consequences

- A change needing permissions no single mode has is either two sessions or a
  signal that the scoping is wrong. It is recorded as two rows in
  `bob-evidence/CONTRIBUTION_MAP.md` so the signal stays visible.
- Security Review mode files findings and applies no fixes. Review and
  remediation are workflow steps 6 and 7, in that order.
- **Inconvenient:** the scoping is slower than letting one mode do everything,
  and it is entirely untested — **no Bob session has been run against this
  repository.** See `bob-evidence/README.md`. The first real session may show
  these boundaries are drawn in the wrong places, and that would itself be a
  useful finding.
