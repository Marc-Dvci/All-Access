# Model card — the All-Access reasoning plane

## What this card covers

The reasoning plane: the component that turns structured facts into language a
person reads. It is **not** the decision system. Two planes exist and confusing
them is the mistake this card exists to prevent.

| | Reasoning plane | Deterministic plane |
|---|---|---|
| Implementation | `agents/core.py` | `solver/`, `constraints/`, `execution/verification.py` |
| Decides feasibility | **No** | Yes |
| Decides authority | No | Yes (`APPROVAL_MATRIX`) |
| Decides readiness | No | Yes |
| Produces | narration attached to typed findings | plans, proofs, conflict sets, verdicts |
| Non-deterministic | when Gemini is selected | never |

## Two modes

### `offline` (default, and the basis of every published number)

Templated narration from structured facts. No model call, no network, fully
deterministic. Every figure in `BENCHMARK.md` was produced in this mode, and
`environment.reasoning_plane` in `bench/results/summary.json` records it.

### `gemini`

`AA_REASONING_MODE=gemini`, Gemini on Vertex AI, default `gemini-2.5-flash`,
temperature 0.2, 300 output tokens.

**System instruction, in full**, because it is the control and a control you
cannot read is not one:

> You are an expert assistant inside a film production decision system. You
> explain and summarise evidence that a deterministic constraint solver has
> already evaluated. You never decide whether a plan is feasible, never invent
> constraints, resources, people, times or costs, and never contradict the
> structured facts you are given. If the facts do not support a statement, say
> so. Write in plain production language, in at most three sentences. Do not
> include any personal information beyond what appears in the facts, and never
> speculate about why a person requires an access arrangement.

An instruction is not a control on its own, which is why the structural boundary
matters more: the call graph from `engine.publish` to `engine.validate` to
`constraints.registry.evaluate` never reads model output.

## Failure behaviour

On any error or empty response, `GeminiReasoner` falls back to the offline plane,
sets `degraded = True`, and records the failure in its call log with the error
attached.

It does **not** silently degrade while continuing to report "Gemini". A run that
claimed a model plane while quietly using templates would misrepresent what a
judge is looking at. `GET /api/about` reports the live plane and the Agent & MCP
observability view shows the per-call record.

## Inputs and outputs

**In:** agent name, purpose, a JSON object of structured facts the deterministic
layer has already computed, and the offline template as a fallback.

**Out:** one or two sentences of narration.

The facts are authoritative and the prompt says so. The narration is attached to
a `Finding` whose `applicable_constraints`, `evidence` and `status` fields were
set by the agent's own deterministic logic, not by the model.

## Measured behaviour

From the 1,000-scenario run, offline plane, 18,420 findings:

| | |
|---|---|
| Fabricated constraints — ids cited that are not in the registry | **0.000** |
| Blocking findings with no evidence | **0.000** |
| Missing required assessments | **0.000** |
| Abstention rate | 0.173 |

The abstention rate is a feature: an agent that cannot assess something says so
rather than guessing, and the abstention is recorded as a distinct status.

**These numbers are from the offline plane and therefore measure the harness, not
Gemini.** They establish that the finding structure is sound and that fabricated
constraint ids would be caught if they occurred. They do not establish anything
about Gemini's fabrication rate, because no benchmark run has used it.

## How the plane is controlled

Three controls, in increasing order of how much work they do.

1. **The system instruction** forbids feasibility judgements and invention. This
   is the weakest control and is listed first so it is not mistaken for the
   important one.
2. **The caller never asks a question whose answer would be a decision.**
   `narrate()` receives facts the deterministic layer has already established and
   asks only for their expression. No code path asks Gemini whether a plan is
   feasible; that question has one answer and `constraints.registry.evaluate`
   owns it.
3. **Every response is checked before it is used.**
   `agents/core.py::ungrounded_claims` reads the returned text for identifiers
   (`C-ACC-002`, `LOC-BOATSHED`) and quantities (`45 mm`, `18:30`, `68 kph`) that
   do not appear in the facts the model was given. A response carrying an
   invented constraint id or an invented threshold is **discarded** in favour of
   the deterministic template, and the rejection is recorded on the call and
   surfaced at `GET /api/findings`.

The third control is the one that matters: it does not ask the model to behave,
it checks whether it did. It cannot establish that the prose is *true* — no
regular expression can — but it establishes that every checkable token came from
the input, which is precisely the class of detail a fluent paragraph carries
convincingly and a reader cannot verify.

`tests/test_reasoning_plane.py` drives all of this against a stub client:
grounded text passes, an invented identifier is caught, an invented measurement
is caught, an invented time is caught, and each rejection falls back to the
deterministic template with the reason recorded.

**Determinism.** The offline plane renders the same narrative fields from
templates over the same evidence, which is what makes a thousand-scenario
benchmark comparable across runs. Every committed figure comes from it.

## Intended and unintended use

**Intended:** explaining a decision a deterministic system has already made, to a
production professional who can see the underlying evidence next to it.

**Not intended, and structurally prevented:** deciding whether a plan is
feasible, deciding who may approve a change, deciding whether a production is
ready, or inferring anything about why a person requires an access arrangement.
The last is in `PROHIBITED_CHANGES` as `infer_condition` and has no approving
role.
