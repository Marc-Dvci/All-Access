# Model card — the ProductionPulse reasoning plane

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

`PP_REASONING_MODE=gemini`, Gemini on Vertex AI, default `gemini-2.5-flash`,
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

## Limitations

- **Never evaluated against Gemini.** Not one committed figure comes from a model
  run. The Gemini path is exercised by hand and is not in CI, because CI has no
  credentials.
- **No adversarial testing.** The prompt-injection argument in
  `THREAT_MODEL.md` §3 T1 is structural — narration cannot reach the feasibility
  path — and has not been tested against an injected-payload corpus.
- **No evaluation of narration quality.** Nothing measures whether the sentences
  are useful, accurate in emphasis, or usable by a first AD under time pressure.
  There is no human evaluation and no LLM-judge scoring.
- **Offline narration is templated**, so it reads as templated. That is a
  deliberate trade — determinism for the benchmark — and it means the offline
  demo understates the language quality the Gemini plane would give.
- **Model choice is not justified by evidence.** `gemini-2.5-flash` is the
  default because it is fast and cheap for short narration. No comparison against
  other models was run.

## Intended and unintended use

**Intended:** explaining a decision a deterministic system has already made, to a
production professional who can see the underlying evidence next to it.

**Not intended, and structurally prevented:** deciding whether a plan is
feasible, deciding who may approve a change, deciding whether a production is
ready, or inferring anything about why a person requires an access arrangement.
The last is in `PROHIBITED_CHANGES` as `infer_condition` and has no approving
role.
