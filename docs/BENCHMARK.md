# Benchmark

**Corpus:** 1,000 disruptions, seed 20260314
**Configuration:** offline reasoning plane, in-process event bus — and §7 measures
what changes when Gemini is the reasoning plane instead
**Artifacts:** `bench/results/summary.json`, `scenarios.jsonl`, `ablations.json`,
`calibration.json`, `reasoning_plane.json`
**Generated:** 8 August 2026, Windows 11, 6 workers

```bash
python -m bench.run_benchmark --count 1000 --workers 6 --ablations --ablation-count 200
```

Roughly two minutes. `scenarios.jsonl` carries one row per scenario per
configuration, so every figure below can be recomputed rather than taken on
trust — and CI does exactly that, recomputing the headline claim from the raw
rows on every push.

---

## 1. What is being measured against what

Ground truth lives on the `Scenario` objects in
`src/allaccess/disruptions.py`. **Nothing in `src/allaccess/` reads
those fields.** Two rules keep the harness honest:

1. **No metric is computed from a value the system reported about itself.** The
   constraint-identification score is not "did the agent say it found
   C-SAFE-001"; it is the constraint registry's own verdict on the *unchanged*
   day, compared against the label the scenario carries. That is a fact about the
   world, not about which plan the search happened to like, and it is the only
   version of the measurement that survives an ablation.
2. **A configuration flag never changes the scoring.** The ablations disable
   parts of the system. They do not relax what counts as correct.

---

## 2. Headline

| Metric | Result | n |
|---|---|---|
| Hard-constraint violations in published feasible plans | **0.000** | 1,629 plans |
| Rejected plans carrying a minimal conflict set | **1.000** | 2,612 plans |
| Non-minimal conflict sets | **0.000** | |
| Access preservation in approved plans | **1.000** | 3,630 arrangements |
| Fabricated constraints across all findings | **0.000** | 18,420 findings |
| Blocking findings with no evidence | **0.000** | |
| Prohibited personal fields anywhere | **0** | 52,000+ events |
| Personal events to an unauthorised audience | **0** | |
| Replay reproduces live state exactly | **1.000** | |
| Hash chain intact | **1.000** | |
| Injected platform faults handled | **1.000** | 119 applicable |
| **Incomplete executions caught before closure** | **75 of 75** | 605 executions |
| **Disruptions ending in a named conflict set** | **0.395** | 1,000 disruptions |

The last two are in this table deliberately. They are the ones that say
something.

**75 of 75 is a detection result, and the denominator matters.** The harness
creates executions in which every command completes while a critical downstream
step is still outstanding — a department that never accepted its task, an update
that reached only part of its audience. It created 75 such executions among the
605 in the corpus, and reconciliation caught every one. A system that closed the
day on command acknowledgment would have declared all 75 ready: **12.4% of
executions**. The rate follows from how often the corpus injects the condition;
the 75 of 75 is the property of the system.

**0.395 is the product working.** 395 of 1,000 disruptions end with no feasible
plan and a named minimal conflict set — the only alternative location has no
step-free route, the interpreter booking cannot be extended with the notice
available, the permit prohibits setup after 21:00. Failing closed with a reason
somebody can act on is the thesis.

---

## 3. Impact analysis: coverage first, then the lead band

Impact analysis has two jobs here and they pull in opposite directions. It has
to **reach everything**, because a department left off the list is a scene
nobody re-dressed. And it has to **hand somebody a short list**, because a first
AD at 18:40 will not read a hundred rows. The traversal does the first, the
ranking does the second, both are measured, and neither is allowed to stand in
for the other.

### 3.1 Coverage

| Axis | Recall | Reached | Labelled core |
|---|---|---|---|
| Constraint identification | **1.000** | 542 | 542 |
| Affected departments | **1.000** | 11,345 | 2,001 |
| Disrupted scenes | **1.000** | 4,375 | 620 |
| Access requirements | **1.000** | 5,250 | 166 |

Nothing labelled is missed, on any axis, in any of the 1,000 disruptions. Mean
traversal: **117.8 nodes**, max depth 6, over a twin of 208 entities and 699
relationships.

The gap between "reached" and "labelled core" is not an error rate, and reading
it as one gets the design backwards. The corpus labels the handful of
consequences a first AD would name unprompted. The traversal returns everything
structurally connected within six hops. On a shooting day — five scenes, three
locations, two units, one call sheet, eleven permits — almost everything really
is within a few hops of almost everything else, so a complete traversal is
necessarily far larger than a labelled shortlist. **That ratio measures how
dense the graph is, not how accurate the traversal is.** The traversal's claim
is containment, and containment is what the recall column reports.

### 3.2 The lead band

`twin/graph.py::_relevance_of` ranks each consequence on two structural signals:
its depth, and whether the path continued *through* a hub relationship — one
that connects everything to everything, like the call sheet that documents all
thirty-two scenes. Arriving at a department along `owned_by_department` is
exact; continuing from that department to everything else it owns is the
fan-out.

| Axis | Named per disruption | Of those, labelled core | Recall of the band |
|---|---|---|---|
| Departments to call | 1.9 | 1.0 | 0.424 |
| Scenes to re-plan | 4.0 | 1.2 | **1.000** |
| Access arrangements in scope | 5.6 | 0.9 | 0.892 |

Read down the first column. The band a screen opens on names about **two
departments, four scenes and six arrangements** — a dozen named things, out of
the 117.8 the traversal reached. That is the number that matters for the
interface, and it is why the impact view leads with those three counts rather
than with the size of the band.

Two of the three rows need their own sentence.

**Access arrangements look over-broad and are not.** This production has six
approved arrangements. The band names 5.6 of them because a disruption of any
size reaches most of them, while the corpus labels only the ~1 per disruption
that is actually *at risk*. Listing an arrangement that turns out to be safe
costs a glance. Missing one costs the person it exists for, and that asymmetry
is what the whole project is built around.

**Departments are ranked for a short screen, and the second band holds the
rest.** The lead band names the department reached most directly and places the
others one interaction below it, which is why it names about two per disruption
rather than nine. The alternative tuning was measured rather than assumed:
rebasing ownership arrivals to the depth of the resource they own raises band
recall to 0.885, and costs precision (0.506 to 0.203) and a third more rows on
the screen. Every variant traded at about that rate. For a product whose thesis
is that the screen is already too full, the shorter band is the right operating
point, and nothing is lost by choosing it because the wider bands are still
there.

Nothing is discarded either way. The typed accessors on `BlastRadius` return the
full traversal and the interface keeps the wider bands one interaction away. The
system never narrows what it knows; it decides what to show first.

---

## 4. Planning, execution and platform

| | |
|---|---|
| Published feasible plans | 1,629 |
| Rejected plans | 2,612 |
| Mean distinct strategies offered | 2.69 |
| Disruptions offering more than one strategy | 0.699 |
| Plans published without a validated proof | 0.000 |
| Commands issued | 4,394 |
| Command completion rate | 1.000 |
| Acknowledgment completeness | 0.989 |
| Verification assertion pass rate | 0.986 |
| Verification ready rate | 0.921 |
| Events | 52,775 (mean 52.8 per disruption) |
| Dead letters | 28 — every one a deliberately malformed injection |
| Mean lineage size | 52.8 nodes |
| Mean end-to-end | 311 ms (p95 607 ms) |
| Mean solve | 209 ms (p95 396 ms) |

**Fault handling, by kind.** Five of the eight declared faults are injectable and
all five are handled:

| Fault | Applicable | Handled |
|---|---|---|
| `duplicate_event` | 16 | 16 |
| `late_event` | 16 | 16 |
| `missing_acknowledgment` | 27 | 27 |
| `partial_update` | 48 | 48 |
| `schema_incompatibility` | 12 | 12 |

`command_rejection`, `connector_failure` and `out_of_order_event` are **declared
by the corpus and never injected**. The report lists them in
`declared_but_not_injected` rather than counting them as passes. A fault that is
not applicable to a scenario is recorded as `None`, never scored as a pass.

**Approvals in this corpus are `stand_in`, and every event says so.** A
thousand-disruption run has nobody at the approval workspace, so the unattended
approver signs. It selects only from the Pareto front, it signs as
`STAND-IN/<role>` rather than under a crew member's identifier, and the data
contract on `production.plan.approved` refuses any approval that does not
declare which channel it came through. The web application defaults to the other
channel: it stops at the gate and executes nothing until a named authority
signs. `tests/test_human_approval.py` covers what that gate refuses.

---

## 5. Ablations

Every configuration ran over the same 200 scenarios with the same seed.

| Configuration | Hard violations per published plan | Access preserved | False closure | No feasible plan | Verification ready | Faults handled |
|---|---|---|---|---|---|---|
| **Full** | 0.000 | 1.000 | 0.100 | 0.400 | 0.942 | 1.000 |
| **No independent validation** | **2.412** | **0.780** | **0.255** | **0.000** | **0.745** | 1.000 |
| No digital twin | 0.000 | 1.000 | 0.100 | 0.400 | 0.942 | 1.000 |
| No robustness simulation | 0.000 | 1.000 | 0.100 | 0.400 | 0.942 | 1.000 |
| No reconciliation | 0.000 | 1.000 | 0.100 | 0.400 | 0.900 | **0.762** |

### 5.1 The result that matters

Removing the independent feasibility recheck — modelling a plan authored without
one, by a language model or a spreadsheet — produces:

- **2.412 hard-constraint violations per published plan.** Not one bad plan in a
  hundred. Every published plan breaks roughly two hard rules.
- **22% of approved plans silently drop an approved access arrangement.** 0.780
  preservation against 1.000.
- **False closure more than doubles**, 0.100 → 0.255.
- **The no-feasible-plan rate goes to 0.000, and 850 plans are published instead
  of 314.** This is the most revealing line in the table. It never fails closed,
  because it never checks. Every one of the 400 disruptions that should have
  ended in a named conflict set instead ended in a confident plan.

The ablation replaces exactly one function — `engine.validate`, which
`engine.publish` takes its verdict from. The search still runs and the plans are
still built. The scoring path deliberately does not go through `validate`; it
calls `evaluate` itself, so the ablated run is still measured against the real
registry.

### 5.2 The reconciliation result

Removing reconciliation costs fault handling: 1.000 → 0.762, entirely from the
`missing_acknowledgment` fault, which goes from 27/27 to 0. That is precisely
what the ablation should do — with no reconciliation step, a department that
never accepted its task is never noticed.

### 5.3 Two null results, reported as null

**The digital twin ablation is a null result on planning quality.** It costs
affected-department recall (1.000 → 0.000) and nothing else: hard violations,
access preservation, false closure, feasibility and verification are all
identical. The twin changes what a user can *see*, not whether the plan is safe.
Do not oversell it.

**The robustness ablation is a null result on everything measured**, and costs
93 ms of latency. The robustness ensemble ranks plans; it does not change which
ones are feasible, and in this corpus the ranking rarely changes the selection.
It ranks plans on expected delay, then worst credible delay, then recovery
margin.

---

## 6. Rules for anyone changing these numbers

- **Do not change a figure in a document without re-running the artifact.**
  `bench/results/summary.json` and `ablations.json` are the source of truth for
  every number here. `tools/mcp_test_results.py` exposes them over MCP so the
  real number is easier to reach than an invented one.
- **Do not tune ground truth to raise a score.** The corpus repairs in
  `dataset_card.md` each removed an unreachable label or added a breach that was
  demonstrably real, and each is justified from the records rather than from the
  output. That is the only acceptable kind of change to `disruptions.py`.
- **Fault populations track corpus size.** `_assigned_fault()` injects the two
  plan-dependent faults on every 16th scenario. Change `--count` and "119
  applicable" changes with it.

---

## 7. The reasoning plane

<!-- REASONING-PLANE:BEGIN -->

The corpus above runs on the offline plane, which is a deliberate choice:
a committed result has to be reproducible by somebody with no Vertex
project, and a benchmark that needs a model endpoint to be reachable is a
benchmark that will one day report the endpoint. It leaves a fair question
open, though - what is Gemini contributing, and could it contribute
something unwanted? So the same disruptions run on both planes and the two
runs are diffed.

```bash
python -m bench.reasoning_plane --count 40
```

**Model:** `gemini-3.7-flash` on Vertex AI, 40 disruptions, seed 20260314. Artifact: `bench/results/reasoning_plane.json`.

### 7.1 What the model may not move

| Compared across both planes | Result |
|---|---|
| Disruptions whose decisions were byte-identical | **40 of 40** |
| Selected plan, and its content hash | identical in all 40 |
| Published plans, refused plans and their minimal conflict sets | identical |
| Access preservation, verification readiness, final state | identical |
| Status and cited constraints on every expert finding | identical |

This is the separation the whole design rests on, measured rather than
asserted. The reasoning plane writes the sentence on a finding. It does not
decide feasibility, it does not choose a plan, and it cannot reach the
constraint registry - `engine.publish` takes its verdict from
`engine.validate`, and no model output is anywhere on that call path.

### 7.2 What the model does

| | |
|---|---|
| Finding headlines rewritten by Gemini | **106 of 440** (24.1%) |
| Calls to the model | 150 |
| Calls that failed and fell back to the template | 0 |
| Responses discarded by the grounding gate | 0 |
| Mean latency per call | 4758 ms (p95 7283 ms) |
| Tokens in / out / spent thinking | 37,613 / 8,178 / 50,572 |
| Mean response length | 169 characters |

The plane is reached only where there is something to interpret. An agent
whose domain is clear says so from a fixed sentence and never calls the
model, which is why 150 calls cover 40 disruptions rather than 440.
Rewriting is what proves the model was in the loop at all: a run where
every headline came back identical to its template is a run that quietly
fell back, and this script exits non-zero on one.

**Thinking tokens are the operational surprise.** Gemini 3.x spends them
before it answers and they draw on the same output budget - 50,572 of them
against 8,178 tokens of actual sentence, about 6:1. A budget sized for a
two-sentence headline comes back as half a clause, or as nothing at all,
and half a sentence about a safety finding is worse than the template it
replaced. The plane treats a truncated response as a failed call rather
than a short one, and `GeminiReasoner.MAX_OUTPUT_TOKENS` is sized for the
thinking rather than for the answer.

### 7.3 What it costs, and what the fan-out buys

| Per disruption | Offline | Gemini |
|---|---|---|
| Wall clock, agents assessed concurrently | 344 ms | 9939 ms |
| Wall clock, one agent at a time (`AA_ASSESSMENT_WORKERS=1`) | 329 ms | 17166 ms |

The second row is the same 8 disruptions as the first, run both ways.
Running the eleven experts concurrently is worth almost nothing on the
offline plane and is the difference between a usable and an unusable
product on the Gemini one: **1.7x**, because the round costs one
agent's latency instead of the sum of eleven. The event log is unchanged
by it - `map` returns in the order the agents were declared, the events
are emitted in that order from a single thread, and the reasoning ledger
is sorted back into it, so a concurrent run and a serial run of the same
disruption produce the same log. `tests/test_parallel_assessment.py`
asserts both halves: that the agents genuinely overlap, and that the
overlap changes nothing.

### 7.4 Running it against a live endpoint

```bash
gcloud services enable aiplatform.googleapis.com --project $GOOGLE_CLOUD_PROJECT
pip install -e '.[cloud]'
GOOGLE_CLOUD_PROJECT=... AA_REASONING_MODE=gemini python -m allaccess.cli hero
```

`GET /api/about` reports which plane is live and `GET /api/findings` reports
every call it made, including anything the grounding gate threw away, so a
judge never has to take the plane on trust.

<!-- REASONING-PLANE:END -->

---

## 8. Robustness, and why on-time probability is not a ranking signal

`simulation/robust.py` runs an ensemble over each feasible plan and reports
expected delay, worst credible delay, recovery margin, overtime risk and
constraint-violation risk. `robust.compare()` ranks on expected delay, then
worst credible delay, then recovery margin.

`on_time_probability` is reported everywhere it is computed and is deliberately
**not** in that ranking. It is a property of the ensemble's assumptions more
than of the plan: an optimistic distribution over travel times hands a plan a
flattering on-time figure without anything about the plan changing. Expected and
worst-credible delay come off the same ensemble but are quantities in minutes,
which is what a producer is deciding about. The figure stays on screen because
hiding a number the system computed is its own kind of dishonesty, and it is
labelled where it appears.
