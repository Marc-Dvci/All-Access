# Identity, authority and access

Two authority models sit in this system and they are not the same thing.

**Production authority** decides who may approve a change to a shooting day. It
is a property of a person's role on the production and it is enforced in
`constraints/registry.py`.

**Cloud IAM** decides which service account may call which API. It is enforced
in `infra/terraform/main.tf`.

Conflating them is a common and expensive mistake: a service account with
permission to write to a topic is not a first assistant director, and no cloud
role should ever be able to stand in for a production approval.

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

One dedicated service account, `productionpulse-app`, created by Terraform. It
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
  gcloud secrets versions add productionpulse-confluent-api-key --data-file=-
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
| May this person approve this change? | production authority | `constraints/registry.py`, `execution/policy` path |
| Is this approval genuine and current? | signature + two hashes + TTL | `execution/approvals.py` |
| May this recipient see this field? | classification and visibility | `execution/privacy.py` |
| May this process call this API? | cloud IAM | `infra/terraform/main.tf` |
| May this agent use this tool? | tool allowlist | `tools/deploy_agent_engine.py` |

No row can substitute for another. That is the design.

---

## 4. Not done

- No identity provider integration. The web application has no authentication;
  role is a parameter, not a claim. For a real deployment this is the first gap
  to close — behind IAP, with roles from the production's own directory.
- No audit of who *viewed* what. The system audits redactions and decisions, not
  reads.
- Confluent ACLs are described here as intent; they are not provisioned by any
  code in this repository.
