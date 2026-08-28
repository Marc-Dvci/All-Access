# ADR-004 — Three planes, deployed separately

**Status:** Accepted

## Context

Vertex AI Agent Engine is a managed runtime for agents, and it is tempting to
deploy the whole system into it.

## Decision

Three planes, three deployment mechanisms:

| Plane | Contents | Deployed by |
|---|---|---|
| Application | API, web client, solver, twin, verification | Terraform → Cloud Run |
| Reasoning | Gemini narration for the expert agents | `tools/deploy_agent_engine.py` → Agent Engine |
| Event backbone | Topics, Schema Registry, contracts | Confluent Cloud, outside this repository |

## Rejected

**Everything in Agent Engine.** It would make the feasibility proof depend on a
model runtime's availability and version. The proof names the constraint-set hash
and the twin state sequence it was computed against; that guarantee cannot
survive being computed inside a hosted agent.

**Everything in Cloud Run including the model calls.** Workable — it is what
`AA_REASONING_MODE=gemini` on Cloud Run actually does. The separate Agent Engine
deployment exists because the managed runtime provides sessions, tracing and
evaluation that are worth having for the narration plane specifically.

## Consequences

- The hosted agent gets seven read-only tools and no tool that can approve,
  execute or declare readiness. `validate()` in `tools/deploy_agent_engine.py`
  refuses to deploy otherwise, and CI runs it on every commit.
- With both cloud planes off, the container runs the full closed loop with no
  credentials at all — which is the configuration every benchmark figure was
  measured in.
- **Inconvenient:** three deployment paths to keep working, and none of them has
  ever been executed. See `infra/README.md` §"Verification status".
