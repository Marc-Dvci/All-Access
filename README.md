# All-Access

**Every production disruption becomes a provably feasible, human-approved
recovery plan — and the system proves the plan actually happened everywhere it
was supposed to.**

Agentic Cinema · IBM track · Apache-2.0

---

A film set changes constantly. Weather closes an exterior, a performer is
delayed, a generator fails, a location withdraws access. Weather disruption alone
is estimated to cost a production **up to $500,000 a day**, and **85% of
productions hit scheduling problems** ([sources](docs/EVIDENCE.md)).

The tools productions run on are excellent at authoring and distributing a
schedule. They answer *"here is another location, and it is free."* They do not
calculate the cross-department consequence, they do not check that the
alternative preserves the access arrangements the production already approved,
and they do not verify that the revised decision actually reached every
downstream system. [`docs/COMPARISON.md`](docs/COMPARISON.md) sets this out
against Movie Magic, StudioBinder and current practice.

All-Access turns each change into a governed event, updates a temporal
production digital twin, runs specialist agents over it, generates recovery plans
with a deterministic solver that **publishes nothing it cannot prove feasible**,
routes the decision to the person with the authority to make it, executes through
typed commands, and then reconciles intended state against observed state before
anyone is allowed to call the day ready.

The inclusion argument is structural rather than decorative. Approved access
arrangements — a step-free route, interpretation covering every called minute,
refrigerated storage at base, a caregiving release time — are **hard constraints
with no soft weight**, so the objective function cannot trade one against a saved
hour. They are the constraints a rushed plan drops first. This one fails closed
instead.

---

## The numbers

1,000 disruptions. Full method in [`docs/BENCHMARK.md`](docs/BENCHMARK.md);
every figure recomputable from [`bench/results/`](bench/results/).

| | |
|---|---|
| Hard-constraint violations in 1,629 published plans | **0.000** |
| Access preservation across 3,630 approved arrangements | **1.000** |
| Rejected plans carrying a minimal conflict set | **1.000** |
| Fabricated constraints across 18,420 findings | **0.000** |
| Prohibited personal fields across 52,000+ events | **0** |
| Replay reproduces live state exactly · hash chain intact | **1.000** · **1.000** |
| **Incomplete executions caught before closure** | **75 of 75** |
| Disruptions ending in a named minimal conflict set | **0.395** |

**75 of 75 is the argument in one number.** The harness creates executions where
every command completes and a critical downstream step is still outstanding —
a department that never accepted, an update that reached only part of its
audience. Verification caught every one. A system that trusted command
acknowledgment would have declared all 75 days ready: **12.4% of the 605
executions in the corpus.**

**0.395 is the product working.** Those disruptions end with a named minimal
conflict set — the only alternative location has no step-free route, the
interpreter booking cannot be extended with the notice available. Failing closed
with a reason a location manager can act on is the point.

### What the pieces are worth

Same 200 scenarios, one capability removed at a time.

| Configuration | Hard violations per plan | Access preserved | False closure | Named conflict set |
|---|---|---|---|---|
| Full | 0.000 | 1.000 | 0.100 | 0.400 |
| **No independent validation** | **2.412** | **0.780** | **0.255** | **0.000** |

Remove the independent feasibility recheck — which is what a plan authored by a
language model or a spreadsheet actually is — and every published plan breaks
roughly two hard constraints, **22% of approved plans silently drop an approved
access arrangement**, and the named-conflict-set rate goes to **zero**. It never
fails closed, because it never checks.

---

## Run it

Nothing below needs a credential, a cloud project or a network.

```bash
git clone <repo> && cd All-Access
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"

python -m allaccess.cli hero        # the closed loop, 11 assertions
pytest -q                                 # 233 tests
python -m bench.run_benchmark --smoke     # 48 scenarios, ~20 s
python tools/a11y_audit.py                # 78 WCAG 2.2 AA checks

uvicorn allaccess.api:app --port 8765     # then open http://127.0.0.1:8765
```

**Watch it instead of reading about it:** <http://127.0.0.1:8765/?demo=1>

A 2:53 guided demonstration that plays itself — the storm arriving, the impact
traversal, the refusal with its named conflict set, the survey measurement
behind that refusal, the three plans, the human approval, and the verification
that will not call the day ready. It is not a recording: it drives this client
through this API over a workflow run that starts when you open the page, using
the same controls a person uses. Escape stops it. The narration is burned in as
captions, and [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) is its cue sheet,
generated from the beats themselves rather than transcribed from them.

Or drive the interface without watching — thirteen views plus every
demonstration beat in a real browser, failing on any console error, uncaught
exception or failed request:

```bash
pip install -e ".[browser]" && playwright install chromium
python tools/ui_smoke.py                  # screenshots land in docs/screenshots/
```

`hero` runs a storm closing the night exterior, end to end, and asserts eleven
properties including that no published plan violates a hard constraint, that
verification blocked on a real missing department acceptance, that all six access
arrangements were preserved, and that a full replay reproduces live state.

**Ten minutes and you want the fastest accurate picture:** read
[`docs/JUDGE.md`](docs/JUDGE.md).

---

## Architecture

```
  weather · cast · crew · location · equipment · access · continuity · systems
                              │  source events
              ┌───────────────▼────────────────┐
              │  Confluent  ·  23 data contracts, 49 event types
              │  validation → hash chain → idempotency → dead letter
              └───────────────┬────────────────┘
                              │
        ┌─────────────────────▼─────────────────────┐
        │  Production digital twin                  │
        │  bitemporal · append-only · 208 entities  │
        │  blast radius scoped to the day, ranked   │
        └─────────────────────┬─────────────────────┘
                              │
        ┌─────────────────────▼─────────────────────┐
        │  Expert agents  ·  Gemini or offline      │
        │  typed findings with evidence.            │
        │  every claim checked against the facts.   │
        │  CANNOT decide feasibility.               │
        └─────────────────────┬─────────────────────┘
                              │
        ┌─────────────────────▼─────────────────────┐
        │  Deterministic engine                     │
        │  34 constraints · 28 predicates           │
        │  diverse plans · infeasibility explained  │
        │  robust simulation · independent validator│
        └─────────────────────┬─────────────────────┘
                              │  plan + feasibility proof
        ┌─────────────────────▼─────────────────────┐
        │  Human approval                           │
        │  signed · hash-bound · single-use · expiring
        └─────────────────────┬─────────────────────┘
                              │  typed commands, saga-coordinated
        ┌─────────────────────▼─────────────────────┐
        │  Downstream systems  →  acknowledgments   │
        └─────────────────────┬─────────────────────┘
                              │
        ┌─────────────────────▼─────────────────────┐
        │  Reconciliation and verification          │
        │  intended vs observed. No override.       │
        └───────────────────────────────────────────┘
```

**The load-bearing boundary is the fourth one.** The model plane produces typed
findings; the constraint registry decides feasibility. That is the call graph,
not a policy: `engine.publish` takes its verdict from `engine.validate`, which
runs `constraints.registry.evaluate`, which runs 28 predicates. No model output
reaches it. The ablation table above is what that boundary is worth.

---

## Runtime proof, not name-dropping

| Partner | Where it is called | How to see it |
|---|---|---|
| **Confluent** | `src/allaccess/stream/` — `ConfluentEventBus` and `ConfluentSchemaRegistry` register 23 subjects, validate every payload before append, enforce BACKWARD compatibility, dead-letter failures | `AA_EVENT_BACKBONE=confluent`; `GET /api/streams`; [`docs/CONFLUENT.md`](docs/CONFLUENT.md) |
| **Gemini / Vertex AI** | `agents/core.py::GeminiReasoner` — narration for 15 expert agents, with a system instruction that forbids feasibility judgements and a grounding gate that discards any response carrying an identifier or measurement the facts did not support | `AA_REASONING_MODE=gemini`; `GET /api/findings` reports the live plane and everything it rejected |
| **Google ADK** | `agents/adk_tools.py` — seven read-only function tools over the product's own read model, and the `google.adk.agents.Agent` that holds them. The agent is built from that list and nowhere else; the deployment refuses to run if the implemented surface and the approved allowlist differ | `pip install -e ".[cloud]"; pytest -q tests/test_adk_tools.py` |
| **Google Cloud** | Cloud Run, Artifact Registry, Secret Manager, Vertex AI Agent Engine | `infra/terraform/`, `tools/deploy_agent_engine.py --dry-run` |
| **IBM Bob** | 7 custom modes with scoped file permissions, committed rules, 2 working MCP servers | `.bob/`, `tools/mcp_*.py`, `bob-evidence/` |

`GET /api/about` reports which reasoning plane and which event backbone are live,
so a viewer never has to guess which one they are looking at.

### Letting a language model into a production decision system

The model plane is allowed to write, and then its writing is checked by
deterministic code. `agents/core.py::ungrounded_claims` reads every response for
identifiers (`C-ACC-002`, `LOC-BOATSHED`) and measurements (`45 mm`, `18:30`,
`68 kph`) that do not appear in the facts the model was given. A response
carrying an invented constraint id or an invented threshold is **discarded** in
favour of the deterministic text, and the rejection is recorded and shown in the
product.

It does not check that the prose is true — no regular expression can. It checks
that every checkable token came from the input, which is exactly the class of
detail a fluent paragraph carries convincingly and a reader cannot verify.

---

## Documentation

| | |
|---|---|
| [`docs/JUDGE.md`](docs/JUDGE.md) | Ten-minute offline evaluation path. Start here |
| [`docs/EVIDENCE.md`](docs/EVIDENCE.md) | The problem in the industry's own words, with sources |
| [`docs/COMPARISON.md`](docs/COMPARISON.md) | Against Movie Magic, StudioBinder and current practice |
| [`docs/DEVPOST.md`](docs/DEVPOST.md) | The submission narrative |
| [`docs/BENCHMARK.md`](docs/BENCHMARK.md) | Method, results and ablations |
| [`docs/screenshots/`](docs/screenshots/) | Every view, produced by `tools/ui_smoke.py` |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | The guided demonstration and its cue sheet, generated from the beats |
| [`docs/CONFLUENT.md`](docs/CONFLUENT.md) | Contracts, governance, lineage, replay |
| [`docs/PRIVACY.md`](docs/PRIVACY.md) | Minimum-necessary disclosure |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Assets, boundaries, eight threats |
| [`docs/IAM.md`](docs/IAM.md) | Production authority and cloud IAM, kept separate |
| [`docs/ACCESSIBILITY.md`](docs/ACCESSIBILITY.md) | WCAG 2.2 AA, 78 checks, behaviour verified in a browser |
| [`docs/MEDIA_RIGHTS.md`](docs/MEDIA_RIGHTS.md) | Provenance of every creative asset |
| [`docs/model_card.md`](docs/model_card.md), [`docs/dataset_card.md`](docs/dataset_card.md) | Reasoning plane and corpus |
| [`docs/adr/`](docs/adr/) | Architecture decision records |
| [`infra/README.md`](infra/README.md) | Deployment |

---

## The product

Thirteen views in five groups, following the decision rather than an alphabet:
**the day** (control board, intake), **the decision** (impact map, plan
comparison, infeasible plans, spatial survey), **the action** (approval,
execution, departments), **who it reaches** (crew view, executive), and **the
evidence** (decision replay, streams).

Every view opens on the sentence it concluded, then the evidence for it. A
screen that makes a first AD derive the verdict from a table has not finished
the job the table started.

**The infeasible-plan explorer** is the one worth looking at first. It is the
view most systems do not have — 395 of 1,000 disruptions end there, each with the
minimal set of constraints that cannot be satisfied together, each naming the
document the rule came from and the person who owns it. "Infeasible" without
provenance is an assertion, not an explanation.

**The impact map** is ranked, not just listed, and drawn as what it is. A
shooting day is a dense graph: five scenes, three locations, two units and one
call sheet put almost everything within a few hops of everything else. The
traversal finds every labelled consequence in the corpus — recall 1.000 on
departments, scenes and access arrangements — and then ranks what it found by
how directly the disruption reaches it. The screen leads with **31 of 118**
consequences on average, and that band contains **every disrupted scene** at 2.2×
the precision of the full traversal. Nothing is discarded; the wider bands are
one click away.

The diagram places each entity by traversal depth and clusters it by kind, so
the shape of the problem — access arrangements at depth two, crew at depth three
— is visible before a word is read. Layout is a pure function of the payload:
types ordered by size then name, members by depth then id. Two runs of the same
disruption draw the same picture, pixel for pixel, and no number appears only in
a drawing — the table under each one carries the data.

**The executive view** is the shift, not the incident: cumulative delay, cost and
overtime, access preservation across every disruption handled, and a
**constraint-pressure table** ranking the rules that removed the most options —
with the owner and the source document for each. That converts "the day was hard"
into a list of things somebody can buy, hire or renegotiate. A second
interpreter, a ramp at the boatshed, a later curfew.

---

## Licence

Apache-2.0. See [`LICENSE`](LICENSE). *Salt and Light*, the production world, the
access surveys and the disruption corpus were all authored for this project;
there is no third-party creative material anywhere in it. See
[`docs/MEDIA_RIGHTS.md`](docs/MEDIA_RIGHTS.md).
