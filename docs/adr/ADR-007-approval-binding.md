# ADR-007 — Approvals are signed, hash-bound, single-use and expiring

**Status:** Accepted

## Context

An approval authorises physical action: moving vehicles, recalling crew,
rebooking interpreters. There are four distinct ways one can be misused.

## Decision

Each closed by a specific property:

| Misuse | Property that closes it |
|---|---|
| Moved to a different plan | HMAC covers `plan_hash` |
| Replayed after the rules changed | HMAC covers `constraint_hash` |
| Replayed at all | `consume()` marks it spent |
| Used hours later | bounded TTL |

Authority is checked separately, in the policy path against `APPROVAL_MATRIX`.
Holding a valid signature does not make someone the right person to sign.

## Rejected

**Signing the plan id rather than its hash.** An id survives the plan changing
underneath it; a hash does not.

**Binding to the plan only.** An approval granted while a constraint was
temporarily inactive would then be replayable once it returned. The
constraint-set hash closes that.

## Consequences

- Approvals stop verifying across a restart unless `PP_APPROVAL_KEY` is supplied
  from Secret Manager. Terraform provisions the secret; it does not populate it.
  This is the finding UC-04 in `bob-evidence/USE_CASES.md` names as the one a
  security review ought to catch.
- **Inconvenient:** an approval cannot be reused after a legitimate minor plan
  edit. Re-approval is required, which is friction on a running day — and it is
  the right friction.
