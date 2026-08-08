# Benchmark

**Corpus:** 1,000 disruptions, seed 20260314
**Configuration:** offline reasoning plane, in-process event bus
**Artifacts:** `bench/results/summary.json`, `scenarios.jsonl`, `ablations.json`, `calibration.json`
**Generated:** 6 August 2026, Python 3.12.10, Windows 11, 6 workers

```bash
python -m bench.run_benchmark --count 1000 --workers 6 --ablations --ablation-count 200
```

Roughly six minutes. `scenarios.jsonl` carries one row per scenario per
configuration, so every figure below can be recomputed rather than taken on
trust — and CI does exactly that, recomputing the headline claim from the raw
rows on every push.

**Read §7 before quoting anything from §3.** Two of these metrics are close to
tautological and one is a null result, and which is which matters more than the
values.

---

## 1. What is being measured against what

Ground truth lives on the `Scenario` objects in
`src/productionpulse/disruptions.py`. **Nothing in `src/productionpulse/` reads
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
| Prohibited personal fields anywhere | **0** | 51,924 events |
| Personal events to an unauthorised audience | **0** | |
| Replay reproduces live state exactly | **1.000** | |
| Hash chain intact | **1.000** | |
| Injected platform faults handled | **1.000** | 119 applicable |
| **False closure without verification** | **0.124** | 605 executions |
| **No feasible plan found** | **0.395** | 1,000 disruptions |
| **Affected-department precision** | **0.176** | |

The last three are in this table deliberately. They are the ones that say
something.

**0.124** is the product's argument in one number: **12.4% of executions would
have been declared complete by a system that trusted command acknowledgment**,
while a critical downstream step was still outstanding.

**0.395** is not a failure. 395 of 1,000 disruptions end with no feasible plan
and a named minimal conflict set — the only alternative location has no step-free
route, the interpreter booking cannot be extended with the notice available, the
permit prohibits setup after 21:00. Failing closed with a reason is the thesis.

**0.176** is the weakest number here and §7 explains it rather than burying it.

---

## 3. Impact analysis

| Measure | Precision | Recall | TP | FP | FN |
|---|---|---|---|---|---|
| Constraint identification | 1.000 | 1.000 | 542 | 0 | 0 |
| Affected departments | 0.176 | 1.000 | 2,001 | 9,344 | 0 |
| Disrupted scenes | 0.142 | 1.000 | 620 | 3,755 | 0 |
| Access requirements reached | 0.032 | 1.000 | 166 | 5,084 | 0 |

Mean blast radius: **117.8 nodes**, max depth 6, over a twin of 208 entities and
699 relationships.

**Do not read the first row as a difficulty result.** See §7.1.

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
| Events | 51,924 (mean 51.9 per disruption) |
| Dead letters | 28 — every one a deliberately malformed injection |
| Mean lineage size | 51.9 nodes |
| Mean end-to-end | 684 ms (p95 1,178 ms) |
| Mean solve | 441 ms (p95 732 ms) |

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
Two of its six metrics are degenerate as well — see §6.3.

---

## 6. Defects found, and what was changed

Every one of these was found by building the artifact that documents the claim.
The corpus repairs are listed separately in `dataset_card.md` with a
justification each, because "we fixed the ground truth and the score went up" has
to be auditable.

### 6.1 Product changes made this session

1. **Eight of fourteen departments had no propagating relationship.** The blast
   traversal reached six — the four that own equipment, plus transport and access
   services via a driver and an interpreter. Wardrobe, makeup, props, art,
   production, locations and safety existed as entities nothing could reach, so a
   scene move could not reach the costume department that has to re-dress it.
   Department recall was **0.333**. Added, each from a record that already
   existed: locations own their locations, the access coordinator's department
   owns each approved arrangement, the production office owns the call sheet, the
   safety lead owns the briefing, a scene requires the costume and makeup
   supervisors for the continuity state it carries, and a unit requires its
   critical crew (which is C-RES-007 drawn as an edge). Recall is now **1.000**.

2. **The prop breakdown was never registered.** `Scene.props` has carried 27
   props across 27 of the 32 scenes since the screenplay was written, and
   `build_twin` ignored it — so a continuity report naming a prop had nothing to
   point at. Props are now entities, with dressing owned by the art department and
   action props by the property master.

3. **Impact propagated backwards through documents and department labels.**
   `blast_radius` traversed every propagating edge in both directions, so
   thirty-two scenes documented in one call sheet made that call sheet a hub
   connecting the whole production to itself, and a camera fault "reached"
   wardrobe by way of the document that happens to list both. `documented_in` and
   `owned_by_department` are now forward-only: a scene change does invalidate the
   call sheet, but reissuing the call sheet does not disrupt the other
   thirty-one scenes.

4. **The blast radius was not scoped to the day being planned.** The twin holds
   the whole script; five of its thirty-two scenes are on shooting day 14. Every
   disruption returned all thirty-two. Scene precision was **0.022**. The
   traversal now takes the problem's scene scope and neither reports nor
   traverses through scenes outside it. Precision is now **0.142**, a 6.5×
   improvement, and the mean blast radius fell from 146 nodes to 118.

5. **A confirmed booking whose interpreter is unavailable counted as coverage.**
   `interpreter_coverage` checked `is_available(booking_id)` and not the people
   named on the booking. With the registered interpreter reported unavailable,
   the booking record still said 09:00–17:00 and the plan was published claiming
   interpretation nobody was going to provide. Now a booking with an unavailable
   interpreter provides no coverage.

### 6.2 Defects found in earlier sessions, recorded here because the findings still hold

6. **`privacy.PROHIBITED_FIELDS` contained the bare key `condition`.** Every
   weather event carries `condition: storm_force`, so the personal-data tripwire
   fired on all 125 weather scenarios. A tripwire that fires on every forecast
   gets switched off inside a week. It now names `medical_condition` and
   `health_condition` explicitly.

7. **The coordinator marked every message delivered without asking the
   notification system.** It appended straight to `notification.sent` and
   `notification.delivered`, bypassing the adapter that models delivery failure,
   then created an acknowledgment for a message that may never have arrived. It
   now issues a typed `notification.send` command and acknowledges only what the
   system reports as delivered. A person who never received an instruction can no
   longer be counted as having acknowledged it.

8. **Four real WCAG AA failures**, including a focus indicator at 1.47:1 against
   the selected tab's blue. See `ACCESSIBILITY.md` §4.

### 6.3 Two robustness metrics are degenerate, and one was the ranking key

`on_time_probability` is 0.00 for every plan — all uncertainty medians exceed
1.0, so P(zero overrun) ≈ 0 — and `overtime_risk` is 0.00 for every plan.
`robust.compare()` was sorting on `-on_time_probability`, which is to say
**ranking by a constant**. It now ranks on expected delay, then worst credible
delay, then recovery margin.

**The distributions were not touched.** They are a domain calibration decision,
not one to invent in a benchmark. `bench/calibration.py` emits a
`degenerate_metrics` block so the finding stays attached to the evidence, and
`calibration.json` confirms it at full size: `predicted_on_time` and
`predicted_overtime_risk`, over 189 plans from 120 scenarios.

**Calibration at n=120 scenarios / 189 plans / 200-sample ensemble:**

| | |
|---|---|
| Delay MAE | 1.63 min |
| Delay max error | 4.47 min |
| Worst-credible MAE | 4.64 min |
| On-time MAE | 0.0016 |

The reliability table has all 189 plans in the 0.00–0.25 bucket and the other
four empty, which is the same degeneracy seen from the other side. A calibration
curve with one populated bucket is not a calibration curve.

### 6.4 Three defects found by rendering the interface for the first time

None of these was reachable from the API tests, which passed throughout, and
none from the static accessibility audit, which reads markup. They were found by
`tools/ui_smoke.py` opening the pages in Chromium.

9. **The control board contradicted the Verification Agent.** Department
   readiness in the read model was derived by splitting a command result's
   human-readable detail string on `":"`, which produced a single row named
   `department_tasks` — the target system, not a department — with no counts. The
   API then re-derived readiness as `tasks_issued == tasks_accepted`, which is
   true at `0 == 0`, so the board showed a green "ready" chip in the same run
   where verification refused to close the day because props had not accepted.
   Readiness is now folded from `READINESS_CHANGED` events keyed by department,
   using the existing `production.state-change-value` contract — no new data
   contract — and the API takes the verdict from `DepartmentReadiness.ready`
   rather than re-deriving a second rule. Four tests cover it, including one that
   runs with `auto_resolve_blocking=False` so it exercises the state where the
   board and verification can actually disagree.

10. **The decision replay's effective-time column was empty for 62 of 63
    events.** `effective_time` is set only where it differs from emission — which
    is the point of storing both — and the view rendered it alone. The endpoint
    now returns `event_time` as well and the view shows both clocks, so the
    bitemporal claim is visible instead of being a column of em-dashes.

11. **Scene end times rendered as "50 AM".** The scene table built its shoot
    window as `clock(start) + " – " + clock(end).slice(-5)`. Under a 12-hour
    locale the last five characters of `"Mar 14, 11:50 AM"` are `"50 AM"` — a
    valid substring and never a time.

---

## 7. Where this is weak

### 7.1 Constraint identification at 1.000/1.000 is close to a tautology

The labels enumerate the constraints the injected change breaches; the detector
is the constraint registry evaluating the same change against the unchanged day.
Both are derived from the same production records by different routes, so
agreement demonstrates that **the registry is correctly wired to the world
model** — which is worth knowing and is not nothing — but it does not
demonstrate that detection is hard.

It read 0.693 recall before the corpus repairs in `dataset_card.md`, and every
one of those misses was a label that no injected change could reach. Fixing them
was right and the resulting number is less interesting than the one it replaced.
**Quote it with this paragraph attached or not at all.**

### 7.2 Precision on breadth metrics is low, and it is structural

Departments 0.176, scenes 0.142, access requirements 0.032, all at recall 1.000.

The reason is the shape of a shooting day. Five scheduled scenes across three
locations, two units, three story days, one call sheet, one briefing, and eleven
permits several of which cover more than one location. Everything genuinely is
connected to everything within three to five hops, and the corpus labels only the
*core* consequences — the departments a first AD would name, not every department
with a real dependency. So precision against those labels measures **breadth,
not error**.

That is an explanation and not an excuse: **118 unranked consequences is not a
usable screen.** The mitigations are real but partial — the map ranks by depth
and says so, the day scoping in §6.1.4 cut the mean from 146 to 118, and the
correct department is at depth 1 or 2 while the rest sit at 3 to 5. The
honest summary is "a recall instrument, ranked for use", and the next real
improvement is a relevance cut rather than more edges.

### 7.3 One department is still unreachable

`DEPT-catering` has no propagating relationship. Catering is on the crew list and
in the working-hours meal-break policy, but the production records carry no
catering plan — no meal service, no location, no covers — so there is nothing to
hang an edge on. Nothing in the corpus labels catering, so this shows up nowhere
in the metrics, which is exactly why it is written down here. It is a gap in the
authored world.

### 7.4 The corpus is one production and one day

One authored production, one shooting day, eight scenario templates. Parameter
variation within eight shapes is not the diversity of real production days, and
nothing here demonstrates generalisation.

### 7.5 Three declared faults are never injected

`command_rejection`, `connector_failure`, `out_of_order_event`. Reported as
`declared_but_not_injected`. The fault-handling rate of 1.000 is over the 119
applicable injections of the five that are.

### 7.6 No hosted-platform run

Every figure is from the in-process event bus and the offline reasoning plane.
No run against Confluent Cloud, no run against Gemini on Vertex AI. The local bus
performs the same validation, governance, chaining and idempotency — that is why
the measurement is honest — but broker failure, partition rebalancing and
network partition are properties of a cluster and are not measured here.
`environment.reasoning_plane` in the summary records which plane produced these
numbers.

### 7.7 The interface is rendered and checked, but not by a human

`tools/ui_smoke.py` drives all thirteen views in Chromium on every CI run and
fails on any console error, uncaught exception or failed request. That closed a
real gap — see §6.4 — but it is a machine reading the DOM, not a person using
the product. It cannot tell you that a table is unreadable at 200% zoom, that a
colour pairing is uncomfortable, or that the impact map's 118 rows are more than
anyone wants to scroll. `ACCESSIBILITY.md` §3 lists what a static audit and an
automated render both miss. **No screen-reader user has tested this.**

---

## 8. Rules for anyone changing these numbers

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
