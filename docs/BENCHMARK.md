# Benchmark

**Corpus:** 1,000 disruptions, seed 20260314
**Configuration:** offline reasoning plane, in-process event bus
**Artifacts:** `bench/results/summary.json`, `scenarios.jsonl`, `ablations.json`, `calibration.json`
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

## 3. Impact analysis

The traversal finds everything, then ranks it. Both are measured: recall over the
full traversal, and precision over the band the interface leads with.

| Measure | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|
| Constraint identification | 1.000 | 1.000 | 542 | 0 | 0 |
| Affected departments — all reached | 0.176 | **1.000** | 2,001 | 9,344 | 0 |
| Disrupted scenes — all reached | 0.142 | **1.000** | 620 | 3,755 | 0 |
| Access requirements — all reached | 0.032 | **1.000** | 166 | 5,084 | 0 |

Mean blast radius: **117.8 nodes**, max depth 6, over a twin of 208 entities and
699 relationships.

### 3.1 The ranked band

A shooting day is a dense graph. Five scheduled scenes across three locations,
two units, one call sheet and eleven permits mean almost everything is genuinely
within three to five hops of almost everything else, and the corpus labels the
*core* consequences — the departments a first AD would name. Complete recall over
that graph is the property worth having and it is not, by itself, a usable
screen.

`twin/graph.py::_relevance_of` ranks each consequence on two structural signals:
its depth, and whether the path continued *through* a hub relationship — one that
connects everything to everything, like the call sheet that documents all
thirty-two scenes. Arriving at a department along `owned_by_department` is exact;
continuing from that department to everything else it owns is the fan-out.

| Measure | Precision | Recall | vs. full traversal |
|---|---|---|---|
| Disrupted scenes — primary band | **0.307** | **1.000** | 2.2× precision, no recall cost |
| Affected departments — primary band | **0.504** | 0.424 | 2.9× precision |
| Access requirements — primary band | **0.163** | 0.892 | 5.1× precision |

The primary band averages **31.3 of 117.8** consequences — a quarter of the
traversal — and contains **every disrupted scene**.

Nothing is discarded. The typed accessors on `BlastRadius` return the full
traversal and the interface keeps the wider bands one interaction away, because
the operational asymmetry runs the other way from the usual one: a department
missing from the list is a scene nobody re-dressed, and a department listed
unnecessarily is one wasted phone call. The system never narrows what it knows;
it decides what to show first.

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
