# Identity, authority and access

Three authority models sit in this system and they are not the same thing.

**Identity** decides who a request is. It is established in `identity.py`, from
one of three providers, and it is the first thing the approval endpoints read.

**Production authority** decides who may approve a change to a shooting day. It
is a property of a person's role on the production and it is enforced in
`constraints/registry.py`.

**Cloud IAM** decides which service account may call which API. It is enforced
in `infra/terraform/main.tf`.

Conflating them is a common and expensive mistake: a service account with
permission to write to a topic is not a first assistant director, and no cloud
role should ever be able to stand in for a production approval — and a request
that names a role is not a person who holds it, which is what §0 is about.

---

## 0. Identity

The version of this document that shipped first opened its "not done" list with
an admission: the web application had no identity provider, and a role arrived
as a request parameter rather than as a claim. That mattered more than its
position on the list suggested. Every control below the approval gate — the
matrix, the two hashes, the single-use ledger, the prohibited changes —
establishes that *this role* authorised *this plan*. None of them establishes
that the person at the keyboard holds the role. A signed approval proved the
application had recorded an approval. It did not prove a first AD was there.

### 0.1 The shape

```
request → provider → Principal(subject, roles) → approval
```

`POST /api/approval/sign` reads the role off the **principal** and the actor off
the principal's subject. `RoleSignature` has no `actor` field to send; the model
that used to carry one is now two fields, one of which is a comment. There is no
request shape that names its own signer.

### 0.2 Three providers, one principal

| Provider | Subject established by | Roles from | Where it runs |
|---|---|---|---|
| `directory` | a per-person access code | the production's crew directory | the public demonstration |
| `judge` | one bearer key, `AA_JUDGE_KEY` | every signing authority | evaluation, via `?judge=<key>` |
| `iap` | a verified Identity-Aware Proxy assertion | the production's crew directory | a real deployment |

Selected by `AA_AUTH_MODE` (`demo`, `closed`, `iap`). The three differ only in
where a subject comes from. The authority lookup and every check after it are
the same code, which is the property worth having: closing the gap for a real
deployment is a configuration change, not a second implementation.

**The demonstration publishes its access codes on the sign-in screen, on
purpose.** A public demonstration whose credentials are secret is a
demonstration nobody can run. What the codes exercise is real regardless: the
server decides which authority a session holds, and a session holding the
location manager cannot sign as the UPM whatever it sends. Set
`AA_AUTH_MODE=closed` and the same directory reads its codes from
`AA_ACCESS_CODES` and publishes none of them.

**The proxy path verifies rather than trusts.** In `iap` mode the assertion in
`X-Goog-IAP-JWT-Assertion` is verified against Google's published IAP keys with
`google-auth`, against the audience in `AA_IAP_AUDIENCE`. The plain
`X-Goog-Authenticated-User-Email` header is read only when a deployment sets
`AA_TRUST_IAP_HEADER=1`, which is only safe where ingress is restricted to the
load balancer IAP sits behind. Outside `iap` mode neither header is read at all:
a header is an authority claim only where a proxy is known to set it.

**Signing in is not the same as holding an authority.** An identity the proxy
authenticates but the directory does not know gets a principal with no roles.
They may read the product and they may decide nothing.

### 0.3 What a session is

An HMAC-signed, expiring bearer token — subject, roles, provider, channel, plane
entitlement — in an `HttpOnly`, `SameSite=Lax` cookie, `Secure` over TLS. The
same discipline as an approval and for the same reason: verification recomputes
the signature over the payload, so a client that edits its own roles invalidates
it. Twelve hours.

The key is `AA_AUTH_KEY`, and it is also what the access codes are derived from,
so rotating it rotates every code at once. **A multi-instance deployment must
supply one**: without it the key is per-process, and a session minted on one
instance does not verify on the next. `infra/terraform` provisions the secret;
it does not populate it.

### 0.4 Routing is not approving

`identity.ROUTING_AUTHORITIES` is the signing authorities plus the production
coordinator. A coordinator may take a plan to signature and may decline it, and
can never sign one — not by a special case, but because `may_sign` reads the
approval matrix and the coordinator does not appear in it. §1.1 has said that
since the first version of this document; it is now the code as well.

### 0.5 The evaluation identity, and what it costs

The judging link mints a principal holding every signing authority, because one
evaluator has to be able to take a two-signature plan through the gate alone.
That is a real weakening of separation of duty. It is therefore named rather
than hidden: its actor is `JUDGE/<role>`, its channel is `judge`, and the data
contract at the stream boundary **refuses** a `judge` approval whose actor does
not start with `JUDGE/` — the same rule, and the same reason, as the one that
stops the unattended approver wearing a crew member's identifier. Read the
ledger back and one evaluation identity signing for two authorities is visible
at a glance.

A judge session is also entitled to the Gemini reasoning plane: disruptions it
starts run the eleven specialist agents on Vertex AI, and everyone else's run
the deterministic plane every committed benchmark figure was measured on. The
entitlement is computed from what is actually installed and configured rather
than asserted, and `/api/identity` returns the reason, because a session that
claims Gemini and narrates from templates misreports itself.

Tests: `tests/test_identity.py`. Threats: `THREAT_MODEL.md` §3 T9.

---

## 1. Production authority

### 1.1 Roles

Defined in `contracts.Role`. Each maps to real responsibility on a production
rather than to a permission level.

| Role | Approves | Sees at most |
|---|---|---|
| UPM | major schedule change, location change, cost increase, overtime, additional vendor, resource substitution, access arrangement change, public communication | `PERSONAL` |
| First AD | schedule change, major schedule change, crew call time change | `OPERATIONAL_REQUIREMENT` |
| Production coordinator | — (routes and communicates) | `PERSONAL` |
| Safety lead | safety exception, emergency action | `OPERATIONAL_REQUIREMENT` |
| Accessibility coordinator | access arrangement change | `OPERATIONAL_REQUIREMENT` |
| Location manager | location change | `OPERATIONAL_REQUIREMENT` |
| Transport coordinator | — | `OPERATIONAL_REQUIREMENT` |
| Department head | — | `OPERATIONAL_REQUIREMENT` |
| Executive | — | `PRODUCTION_INTERNAL` |
| Crew | — | `OPERATIONAL_REQUIREMENT` |

Clearance is `privacy.ROLE_CLEARANCE`; see `PRIVACY.md` §2.1.

### 1.2 The approval matrix

`APPROVAL_MATRIX` maps a change type to the roles that must approve it. Some
require two.

| Change type | Required |
|---|---|
| `schedule_change` | First AD |
| `major_schedule_change` | First AD **and** UPM |
| `location_change` | UPM **and** location manager |
| `safety_exception` | Safety lead |
| `cost_increase`, `overtime`, `additional_vendor`, `resource_substitution` | UPM |
| `access_arrangement_change` | Accessibility coordinator **and** UPM |
| `crew_call_time_change` | First AD |
| `public_communication` | UPM |
| `emergency_action` | Safety lead |

**A change type absent from this table cannot be executed at all.** The policy
agent fails closed rather than defaulting to the UPM, because a default approver
for an unrecognised change is how an unrecognised change gets approved.

### 1.3 What an approval is

Signed, single-use, expiring, and bound to two hashes:

- `plan_hash` — the approval cannot be moved to a different plan
- `constraint_hash` — the approval cannot be replayed once the active constraint
  set has changed

`consume()` marks it spent. Authority is checked separately from signature
validity: a valid signature from the wrong role is refused.

Implementation: `execution/approvals.py`. Threats and residual risk:
`THREAT_MODEL.md` §3 T2.

### 1.4 What nobody can approve

`PROHIBITED_CHANGES` — five changes with no approving role at any level. Listed
in `THREAT_MODEL.md` §4.

---

## 2. Cloud IAM

### 2.1 The application plane

One dedicated service account, `allaccess-app`, created by Terraform. It
holds:

| Grant | When | Why |
|---|---|---|
| `roles/secretmanager.secretAccessor` **on each named secret** | when `enable_confluent` | per-secret, not project-wide, so it cannot read a secret added later for something else |
| `roles/aiplatform.user` | when `enable_gemini` | the narrowest role permitting `generateContent`. The service never trains, tunes or deploys a model |

It holds nothing else. No storage, no logging writer beyond the Cloud Run
default, no project-level secret access, no `run.admin`.

With both flags off — the default — the service account holds **no roles at
all**, and the deployment runs the in-process bus and the offline reasoning
plane. That configuration is the one every benchmark figure was measured in.

### 2.2 Credentials are never Terraform variables

Terraform creates the secret *containers* and never the versions. A credential
passed as a variable is written into the state file and printed in the plan
output, and both get shared.

```bash
printf %s "$CONFLUENT_API_KEY" | \
  gcloud secrets versions add allaccess-confluent-api-key --data-file=-
```

### 2.3 The reasoning plane

The Agent Engine deployment runs under its own Vertex-managed identity. The
manifest in `tools/deploy_agent_engine.py` gives it seven read-only tools and
`validate()` refuses to deploy anything carrying a state-changing tool. It is
given no Confluent credentials: the hosted plane narrates, and publishing is done
by the application plane.

### 2.4 Confluent

Least privilege at the cluster is configured in Confluent Cloud, not here. The
principle applied: the application plane holds a key that may produce to the
topics it owns and consume from the topics it subscribes to, and the
development Schema Registry key given to IBB Bob's MCP server (`.bob/mcp.json`)
is read-and-compatibility-check only, pointed at a **development** registry.

A tool that can read production subjects during an agent session is a tool that
will eventually paste one into a diff.

---

## 3. Separation summary

| Question | Answered by | Enforced in |
|---|---|---|
| Who is this request? | identity provider | `identity.py`, `api.py::_signed_in` |
| May this person approve this change? | production authority | `constraints/registry.py`, `execution/policy` path |
| Is this approval genuine and current? | signature + two hashes + TTL | `execution/approvals.py` |
| May this recipient see this field? | classification and visibility | `execution/privacy.py` |
| May this process call this API? | cloud IAM | `infra/terraform/main.tf` |
| May this agent use this tool? | tool allowlist | `tools/deploy_agent_engine.py` |

No row can substitute for another. That is the design.

---

## 4. Not done

- **No account lifecycle.** There is no registration, no password, no reset and
  no self-service role change. Roles are read from the production's directory on
  every sign-in, which is the right shape for a system whose authorities are
  people on a call sheet rather than users of a SaaS — and it means an
  integration with a real production's HR or scheduling system is where the
  directory should come from, and does not yet.
- **The demonstration deployment publishes its access codes.** Deliberately, and
  §0.2 says why, but it means the public deployment authenticates *which
  authority you are acting as* rather than *that you are that person*. The `iap`
  mode that closes it is implemented and unit-tested against a stubbed
  assertion; it is not what the hosted URL runs, because a hosted URL behind IAP
  is one no judge can open.
- **The evaluation identity holds every authority.** §0.5. Named in the ledger,
  refused a crew identifier by the data contract, and still a weakening.
- **No rate limiting on sign-in.** A six-character code has 32^6 values and
  nothing here slows a guess. On a closed deployment that is a real gap; on the
  demonstration the codes are printed on the screen, so it is not the weak part.
- No audit of who *viewed* what. The system audits redactions and decisions, not
  reads.
- Confluent ACLs are described here as intent; they are not provisioned by any
  code in this repository.
