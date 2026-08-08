# ProductionPulse Inclusive

**Every production disruption becomes a provably feasible, human-approved
recovery plan — and the system proves the plan actually happened everywhere it
was supposed to.**

Agentic Cinema · IBM track · Apache-2.0

---

A film set changes constantly. Weather closes an exterior, a performer is
delayed, a generator fails, a location withdraws access. Conventional tools
answer "here is another location, it is free" and stop there. They do not
calculate the cross-department consequence, they do not check that the
alternative preserves the access arrangements the production already approved,
and they do not verify that the revised decision actually reached every
downstream system.

ProductionPulse turns each change into a governed event, updates a temporal
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

1,000 disruptions, offline reasoning plane. Full detail and every caveat in
[`docs/BENCHMARK.md`](docs/BENCHMARK.md); artifacts in
[`bench/results/`](bench/results/).

| | |
|---|---|
| Hard-constraint violations in 1,629 published plans | **0.000** |
| Access preservation across 3,630 approved arrangements | **1.000** |
| Rejected plans carrying a minimal conflict set | **1.000** |
| Fabricated constraints across 18,420 findings | **0.000** |
| Replay reproduces live state exactly · hash chain intact | **1.000** · **1.000** |
| **False closure without verification** | **0.124** |
| **No feasible plan found** | **0.395** |
| **Affected-department precision** | **0.176** |

**0.124** is the argument in one number: 12.4% of executions would have been
declared complete by a system that trusted command acknowledgment, while a
critical downstream step was still outstanding.

**0.395** is correct behaviour, not failure. Those disruptions end with a named
minimal conflict set — the only alternative location has no step-free route, the
interpreter booking cannot be extended with the notice available. Failing closed
with a reason is the point.

**0.176** is the weakest number in the project and it is in this table on
purpose. `docs/BENCHMARK.md` §7.2 explains it.

### What the pieces are worth

Same 200 scenarios, one capability removed at a time.

| Configuration | Hard violations per plan | Access preserved | False closure | No feasible plan |
|---|---|---|---|---|
| Full | 0.000 | 1.000 | 0.100 | 0.400 |
| **No independent validation** | **2.412** | **0.780** | **0.255** | **0.000** |
| No digital twin | 0.000 | 1.000 | 0.100 | 0.400 |
| No robustness simulation | 0.000 | 1.000 | 0.100 | 0.400 |
| No reconciliation | 0.000 | 1.000 | 0.100 | 0.400 |

Remove the independent feasibility recheck — a plan that looks right and was
never checked — and every published plan breaks roughly two hard constraints,
22% of them silently drop an approved access arrangement, and **the
no-feasible-plan rate goes to zero**. It never fails closed, because it never
checks.

The twin ablation is a **null result on planning quality** and is reported as
one: it costs department recall and nothing else. The robustness ablation is a
null result on everything measured. Both are stated as such in
`docs/BENCHMARK.md` §5.3 rather than quietly omitted.

---

## Run it

Nothing below needs a credential, a cloud project or a network.

```bash
git clone <repo> && cd All-Access
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"

python -m productionpulse.cli hero        # the closed loop, 11 assertions
pytest -q                                 # 214 tests
python -m bench.run_benchmark --smoke     # 48 scenarios, ~20 s
python tools/a11y_audit.py                # 62 WCAG 2.2 AA checks

uvicorn productionpulse.api:app --port 8765     # then open http://127.0.0.1:8765
```

Or drive the interface without opening it yourself — thirteen views in a real
browser, failing on any console error, uncaught exception or failed request:

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
        │  blast radius scoped to the day           │
        └─────────────────────┬─────────────────────┘
                              │
        ┌─────────────────────▼─────────────────────┐
        │  Expert agents  ·  Gemini or offline      │
        │  typed findings with evidence.            │
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
| **Confluent** | `src/productionpulse/stream/` — `ConfluentEventBus` and `ConfluentSchemaRegistry` register 23 subjects, validate every payload before append, enforce BACKWARD compatibility, dead-letter failures | `PP_EVENT_BACKBONE=confluent`; `GET /api/streams`; `docs/CONFLUENT.md` |
| **Gemini / Vertex AI** | `agents/core.py::GeminiReasoner` — narration for 15 expert agents, with a system instruction that forbids feasibility judgements and an offline fallback that records the degradation rather than hiding it | `PP_REASONING_MODE=gemini`; `GET /api/about` reports the live plane |
| **Google ADK** | `agents/adk_tools.py` — seven read-only function tools over the product's own read model, and the `google.adk.agents.Agent` that holds them. The agent is built from that list and nowhere else, and `--dry-run` refuses to deploy if the implemented surface and the approved allowlist ever differ | `pip install -e ".[cloud]"; pytest -q tests/test_adk_tools.py` |
| **Google Cloud** | Cloud Run, Artifact Registry, Secret Manager, Vertex AI Agent Engine | `infra/terraform/`, `tools/deploy_agent_engine.py --dry-run` |
| **IBM Bob** | 7 custom modes with scoped file permissions, committed rules, 2 working MCP servers | `.bob/`, `tools/mcp_*.py`, `bob-evidence/` |

`GET /api/about` reports which reasoning plane and which event backbone are live,
so a viewer never has to guess which one they are looking at.

### On the IBM Bob evidence — read this before the ledger

**No IBM Bob session has been run against this repository.**
[`bob-evidence/`](bob-evidence/) contains committed configuration, two working
MCP servers, six use cases with acceptance criteria, and a preserved
before-state for the connector modernization. It contains **no session
summaries, no generated diffs, no "findings Bob caught" and no productivity
claims**, because none of those exist yet. `bob-evidence/CONTRIBUTION_MAP.md` is
an empty table and says so.

The two MCP servers are the part that is more than intent. `mcp_test_results`
exists specifically so a session asked to write a claim about this system's
performance reads the number out of `bench/results/` rather than producing a
plausible one.

---

## Documentation

| | |
|---|---|
| [`docs/JUDGE.md`](docs/JUDGE.md) | Ten-minute offline evaluation path. Start here |
| [`docs/DEVPOST.md`](docs/DEVPOST.md) | The submission narrative: gap, inclusion argument, numbers, learnings |
| [`docs/screenshots/`](docs/screenshots/) | Every view, produced by `tools/ui_smoke.py` |
| [`docs/BENCHMARK.md`](docs/BENCHMARK.md) | Method, results, ablations, and §7 "where this is weak" |
| [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) | Three-minute shot list |
| [`docs/CONFLUENT.md`](docs/CONFLUENT.md) | Contracts, governance, lineage, replay |
| [`docs/PRIVACY.md`](docs/PRIVACY.md) | Minimum-necessary disclosure, and what is not measured |
| [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) | Assets, boundaries, eight threats, residual risk |
| [`docs/IAM.md`](docs/IAM.md) | Production authority and cloud IAM, kept separate |
| [`docs/ACCESSIBILITY.md`](docs/ACCESSIBILITY.md) | WCAG 2.2 AA, 62 checks, and what a static audit cannot see |
| [`docs/MEDIA_RIGHTS.md`](docs/MEDIA_RIGHTS.md) | Provenance of every creative asset |
| [`docs/model_card.md`](docs/model_card.md), [`docs/dataset_card.md`](docs/dataset_card.md) | Reasoning plane and corpus, with limitations |
| [`docs/adr/`](docs/adr/) | Architecture decision records |
| [`infra/README.md`](infra/README.md) | Deployment, and what has not been deployed |

---

## The product

Thirteen views: control board, disruption intake, impact map, plan comparison,
infeasible-plan explorer, spatial location view, approval workspace, execution
board, department queues, crew view, executive analytics, decision replay, stream
governance.

The infeasible-plan explorer is the one worth looking at first. It is the view
most systems do not have — 395 of 1,000 disruptions end there, each with the
minimal set of constraints that cannot be satisfied together, each naming the
document the rule came from and the person who owns it. "Infeasible" without
provenance is an assertion, not an explanation.

Screenshots of every view are in [`docs/screenshots/`](docs/screenshots/),
produced by `tools/ui_smoke.py` rather than cropped by hand.

### What rendering it actually found

For most of this project's life all 15 endpoints returned 200 with substantive
payloads, the client passed 62 static accessibility checks, and **no browser had
drawn a single pixel.** Three defects were sitting in the two views a judge opens
first, and no test in the suite could have seen any of them:

- **The control board declared every department ready while verification was
  blocking the day on props.** The read model folded one row keyed on the *target
  system* name with zero counts, and the board re-derived readiness as
  `issued == accepted`, which is true at `0 == 0`. A board contradicting the
  system's own verification step is worse than a board with no readiness column.
- **Every event in the decision replay showed an em-dash for its effective
  time**, because `effective_time` is set only where it differs from emission and
  the view never asked for `event_time`. The bitemporal claim was rendering as a
  column of nothing.
- **Scene end times read "50 AM"** — the last five characters of a formatted
  datetime, which is a valid substring and never a time.

Each is now fixed, covered by a test that fails without the fix, and `ui_smoke.py`
runs in CI so the interface cannot silently stop rendering again.

---

## Honest status

Stated here rather than left to be discovered.

- **No IBM Bob session has been run.** See above. This is the one open item that
  is not a limitation but an unmet requirement, and it is stated first for that
  reason.
- **No run against Confluent Cloud or Vertex AI.** Every committed figure is from
  the in-process bus and the offline reasoning plane, and
  `bench/results/summary.json` records that.
- **The Terraform has never been applied and the container image has not been
  built successfully on this machine** (no Docker daemon available). Both are
  validated in CI; neither has been deployed.
- **The corpus is one authored production and one shooting day.** Nothing here
  demonstrates generalisation.
- **Constraint identification reads 1.000/1.000 and that is close to a
  tautology.** `docs/BENCHMARK.md` §7.1 explains why, and asks you not to quote
  it without the explanation.

---

## Licence

Apache-2.0. See [`LICENSE`](LICENSE). *Salt and Light*, the production world, the
access surveys and the disruption corpus were all authored for this project;
there is no third-party creative material anywhere in it. See
[`docs/MEDIA_RIGHTS.md`](docs/MEDIA_RIGHTS.md).
