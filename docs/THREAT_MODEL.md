# Threat model

Scope: the All-Access application plane, its agent plane, and the event
backbone between them. Out of scope: the security of Confluent Cloud, Google
Cloud, or the downstream production systems this integrates with.

The framing question throughout is not "can an attacker break in" but **"can a
consequential production action happen without an accountable human decision"**,
because that is the failure that hurts on a film set. A leaked call sheet is
embarrassing. A crew briefed onto a location nobody secured is a safety incident.

---

## 1. Assets, in the order they matter

| # | Asset | Why it matters |
|---|---|---|
| 1 | The authority to execute a plan | An executed plan moves people, vehicles and equipment in the physical world |
| 2 | Approved access arrangements | Removing one silently is the harm this whole product exists to prevent |
| 3 | Safety controls and permits | Working outside them is a legal and physical risk |
| 4 | Personal data on cast and crew | Names, rates, availability; and the *absence* of any reason for an arrangement |
| 5 | The event log's integrity | If the log can be edited, replay proves nothing and the audit trail is theatre |

---

## 2. Trust boundaries

```
   weather / location / vendor feeds        ← untrusted, authority-tagged
                 │
      ┌──────────▼───────────┐
      │  event backbone      │  contract validation, hash chain, idempotency
      └──────────┬───────────┘
                 │
      ┌──────────▼───────────┐
      │  agent plane         │  ← may READ and EXPLAIN. Cannot decide.
      │  (Gemini / offline)  │
      └──────────┬───────────┘
                 │  typed findings only
      ┌──────────▼───────────┐
      │  deterministic plane │  solver · registry · verification
      └──────────┬───────────┘
                 │  plan + proof
      ┌──────────▼───────────┐
      │  human approval      │  ← signed, hash-bound, single-use, expiring
      └──────────┬───────────┘
                 │  typed commands
      ┌──────────▼───────────┐
      │  downstream systems  │
      └──────────────────────┘
```

The boundary that carries the most weight is the third one. **The model plane
cannot declare feasibility.** It produces typed findings; the constraint registry
decides. That is not a policy statement, it is the call graph:
`engine.publish` takes its verdict from `engine.validate`, which runs
`constraints.registry.evaluate`, which runs 28 predicates over the plan. No
model output reaches it.

---

## 3. Threats and controls

### T1 — Prompt injection through a source event

A weather feed, vendor message or multimodal report contains text engineered to
make an agent recommend something.

**Controls.** The reasoning plane's system instruction forbids feasibility
judgements, inventing constraints, and contradicting the structured facts it is
given. But instructions are not a control, so: agent output is *narration
attached to a finding whose structure came from the deterministic layer*, and
the plan the finding relates to is validated independently. An injected
instruction can change the wording of an explanation. It cannot change whether a
plan is feasible, because nothing in that path reads the explanation.

**Measured.** `fabricated_constraint_rate` — constraint ids cited by an agent
that are not in the registry — is **0.000 across 18,420 findings**.
`blocking_finding_without_evidence_rate` is **0.000**.

**Residual.** A convincing injected narration could mislead a human approver who
reads the summary and not the conflict set. The UI puts the conflict set and the
evidence next to the narration for that reason, but the residual is real.

### T2 — Forged or replayed approval

**Controls.** An approval is HMAC-signed over both the plan hash and the
constraint-set hash, single-use, and expiring.

- Moving it to a different plan fails the plan hash.
- Replaying it after a constraint returns to force fails the constraint hash.
- Replaying it at all fails `consume()`, which marks it spent.
- Using it hours later fails the TTL.

Authority is checked separately in `policy.py` against `APPROVAL_MATRIX`.
Holding a valid signature does not make someone the right person to sign, and a
change type absent from the matrix cannot be executed at all — the policy agent
fails closed.

**Residual.** The signing key is per-process unless `AA_APPROVAL_KEY` is
supplied. A deployment must supply it from Secret Manager or approvals stop
verifying across a restart. `infra/terraform` provisions the secret; it does not
populate it.

### T3 — Command replay or reordering into a downstream system

**Controls.** Idempotency keys enforced at publish, inbox deduplication at the
target, and plan-version checks that reject a stale command rather than applying
it out of order. Saga dependencies mean a dependent command is not issued until
its predecessor completes.

**Measured.** `duplicate_event` fault: 16/16 suppressed. `late_event` fault:
16/16 — the coordinator refuses to act on a stale report *and* the view counts it
as late rather than silently reordering it.

### T4 — An approved access arrangement removed to save time or money

The threat this product is named for, and it is modelled as a *systems* threat
rather than a malicious one: the usual cause is a plan generated under pressure
that nobody rechecked.

**Controls.** `remove_access_arrangement` is in `PROHIBITED_CHANGES` — nobody can
approve it, at any role. Access constraints are `HARD` and carry no soft weight,
so they cannot be traded against delay or cost by the objective function. The
independent revalidation before publication re-reads the registry.

**Measured, and this is the strongest evidence in the project.** With
validation on, access preservation is **1.000**. With the independent recheck
removed — a plan that looks right and was never checked — it falls to **0.780**.
See `BENCHMARK.md` §5.

### T5 — Tampering with the audit record

**Controls.** Hash chain per partition; altering a historical event invalidates
every event after it. `verify_chain()` is asserted in the hero loop and measured
across the corpus at **1.000**.

**Residual.** The chain proves internal consistency, not external truth. Someone
with write access to the whole log could rebuild a consistent chain. Confluent
Cloud's own retention and ACLs are the control there, and are out of scope here.

### T6 — Over-disclosure of personal data

See `PRIVACY.md`. Clearance by role, per-requirement visibility, prohibited-field
tripwire. `prohibited_field_occurrences` = **0** across 52,775 events;
`personal_events_to_unauthorised_audience` = **0**.

### T7 — A model plane given a tool that changes state

**Controls.** `tools/deploy_agent_engine.py` carries an allowlist of seven
read-only tools and a denylist naming `approve_plan`, `issue_command`,
`execute_plan`, `declare_ready`, `override_constraint` and
`remove_access_arrangement`. `validate()` refuses to deploy a manifest that
breaches either, and CI runs it on every commit.

### T8 — Silent false completion

Not an attacker; the ordinary failure of trusting an acknowledgment. A system
that marks a disruption closed when every command returned OK will close over an
outstanding critical step.

**Controls.** Verification compares intended against observed state in each
downstream system and refuses `ready` while any critical assertion fails. There
is no override.

**Measured.** `false_closure_rate_without_verification` — how often a
command-acknowledgment-only system would have declared completion while a
critical step was outstanding — is **0.124**. That is the number the reconciliation
step exists to prevent.

---

## 4. Explicit decision boundaries

`PROHIBITED_CHANGES` in `constraints/registry.py`. These are not configurable and
have no approving role:

| Change | Reason |
|---|---|
| `remove_access_arrangement` | Not a scheduling action. Changing the arrangement is a separate decision owned by the accessibility coordinator and the person concerned |
| `waive_safety_control` | The system does not approve safety exceptions. The safety lead does, outside it |
| `override_child_limit` | Configured child performer limits are not waivable within the system |
| `rank_crew_by_cost` | The system does not rank workers by cost or inconvenience |
| `infer_condition` | The system does not infer or record a reason for an access requirement |

---

## 5. Residual risk and deployment posture

- **The demonstration deployment is deliberately open.** It serves a read-mostly
  UI over authored fictional data, so `allow_unauthenticated` in
  `infra/terraform` is `true`. Pointing this at a real production means setting
  it to `false` and putting IAP or an equivalent in front — the variable exists
  precisely so that is a one-line change rather than an architecture change.
- **`POST /api/disruptions` runs a solve**, so a production deployment puts rate
  limiting in front of it. Every other endpoint is a read over a completed
  decision.
- **`sbom.json` records the full dependency surface** in CycloneDX, which is what
  an advisory scanner consumes; CI verifies it covers every declared runtime
  dependency on each push.
- **The prompt-injection control is structural.** Narration cannot reach the
  feasibility path — `engine.publish` takes its verdict from
  `constraints.registry.evaluate`, and no model output is an input to it — and
  every model response is additionally filtered by
  `agents/core.py::ungrounded_claims`, which discards any identifier or
  measurement absent from the facts the model was given.
