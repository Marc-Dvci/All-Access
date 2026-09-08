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
| Taken by nobody, and read later as if by somebody | `approval_channel` on the event |

Authority is checked separately, in the policy path against `APPROVAL_MATRIX`.
Holding a valid signature does not make someone the right person to sign.

The fifth row is the one that took a second pass. The first four are properties
of the signature and can be checked from it. Whether a *person* produced it
cannot: an HMAC computed by a workflow with nobody watching verifies exactly as
well as one computed when somebody pressed a button. So the workflow stopped
implying an answer and started recording one.

`ApprovalGateway` has two implementations and each declares a `channel`.
`HumanApprovalGateway` blocks the workflow until somebody chooses a plan and
signs for every required authority at `/api/approval/*`; nothing supplies a
default and a wait that runs out abandons the disruption. `StandInApprover` is
the unattended path that the benchmark, the tests and any CLI run use — it picks
off the Pareto front and signs as `STAND-IN/<role>`, an identifier belonging to
no one on the production. The channel is written onto the approval-requested and
approval-granted events, and the data contract for `production.plan.approved`
**requires** it and refuses a `stand_in` approval that carries a crew member's
identifier. The web application defaults to `human`.

## Rejected

**Signing the plan id rather than its hash.** An id survives the plan changing
underneath it; a hash does not.

**Binding to the plan only.** An approval granted while a constraint was
temporarily inactive would then be replayable once it returned. The
constraint-set hash closes that.

## Consequences

- Approvals stop verifying across a restart unless `AA_APPROVAL_KEY` is supplied
  from Secret Manager. Terraform provisions the secret; it does not populate it.
  This is the finding UC-04 in `bob-evidence/USE_CASES.md` names as the one a
  security review ought to catch.
- **Inconvenient:** an approval cannot be reused after a legitimate minor plan
  edit. Re-approval is required, which is friction on a running day — and it is
  the right friction.
- **The product does not finish by itself.** Opening the web application gets a
  scoped, planned, assessed disruption and a stop. Somebody has to decide. That
  is the intended behaviour and it is what the headline claim means, but it does
  mean an unattended deployment shows a half-finished day until a person arrives
  — which is the honest depiction of a system that will not act without one.
