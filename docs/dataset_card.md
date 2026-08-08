# Dataset card — the ProductionPulse disruption corpus

## Summary

| | |
|---|---|
| **Name** | ProductionPulse disruption corpus |
| **Location** | `src/productionpulse/disruptions.py` |
| **Size** | 1,000 scenarios at the committed seed; `generate(n)` produces any size |
| **Seed** | 20260314. Same seed, same corpus, on any machine |
| **Families** | 7 (weather, cast and crew, location, equipment, access and communication, continuity, operational systems) |
| **Templates** | 8 (cast and crew has two) |
| **Licence** | Apache-2.0, authored for this project |
| **Personal data** | None. Every person is invented |

## What a scenario is

A change to the world, plus **ground truth the system cannot see**:

```python
Scenario(
    scenario_id, family, title, description,
    event_type, payload,              # what the system receives
    unavailable, weather,             # what actually changes in the world
    disrupted_scenes,
    expected_constraints,             # ground truth ↓
    expected_access_at_risk,
    expected_departments,
    expected_feasible, severity,
)
```

Nothing in `src/productionpulse/` reads the `expected_*` fields. They exist so
`bench/harness.py` can score against them, which is the only reason the recall
and precision numbers in `BENCHMARK.md` mean anything.

## How ground truth is established

By reasoning from the constraint definitions and the production records — never
by running the system and recording what it said.

Two rules in the harness keep this honest, and both are easy to break later:

1. **No metric is computed from a value the system reported about itself.**
   "Which constraints does this disruption trip" is answered by running the
   constraint registry against the *unchanged* day, which is a fact about the
   world rather than about which plan the search happened to like.
2. **A configuration flag never changes the scoring.** The ablations disable
   parts of the system. They do not relax what counts as correct.

## Family distribution at n=1,000

| Family | Scenarios |
|---|---|
| cast and crew | 250 |
| weather | 125 |
| location | 125 |
| equipment | 125 |
| access and communication | 125 |
| continuity | 125 |
| operational systems | 125 |

## Corpus repairs, and why they are disclosed

The corpus was repaired in August 2026 after the first full benchmark run showed
a constraint-identification recall of 0.693. **Every miss traced to a defect in
the corpus, not in the detector**: labels declaring a constraint that the
injected change could not possibly trip, and labels omitting constraints it
plainly did.

Each repair is listed with its justification, because "we fixed the ground truth
and the score went up" is a claim that has to be auditable.

| # | Repair | Justification |
|---|---|---|
| 1 | Equipment faults other than `failure` now inject a real world change | Three of the four kinds set no `unavailable` entry, so nothing changed and no predicate could fire — while still declaring `C-RES-001` |
| 2 | `C-RES-002` expected only when the package is on the call sheet | Three of twelve packages are spares no scheduled scene calls for. Losing a spare breaches nothing; these scenarios are the family's negative control |
| 3 | Cast scenarios draw only from performers called that day | One of six performers is not called. Reporting them unavailable changes nothing, but `C-RES-004` was declared |
| 4 | Access scenarios derive the expected constraint from the *dependency*, not the category | ACC-002 and ACC-003 are both `communication` but depend on interpreters and on the briefing service respectively, and those fail into different constraints |
| 5 | ACC-006 removed from the access-failure template | Its mechanism is a hard release time, not a bookable service. The template had been falling back to `SVC-BRIEFING`, publishing an event asserting the briefing service supports the caregiving arrangement. It does not |
| 6 | Critical-crew scenarios declare `C-ACC-003`, `C-RES-003` and `C-SAFE-002` where applicable | An interpreter takes their booking's coverage with them; the sole holder of a certification leaves that equipment with no operator; the marine supervisor is named on the permit. All were real breaches the labels omitted |
| 7 | Continuity scenarios declare no constraint | Every kind in the family is a *report* about the published day, not a change to it. The baseline order is continuity-valid, so preserving it breaches nothing |
| 8 | Operational-system scenarios declare no affected department | A platform fault leaves the shooting day untouched, and the payload carries no `entity_id` because there is no entity in the production it happened to |

**What this measures.** Constraint identification reads 1.000 precision and
1.000 recall. The labels enumerate the constraints an injected change breaches;
the detector is the registry evaluating that change against the unchanged day.
Both are derived from the same production records by different routes, so
agreement demonstrates that **the registry is correctly wired to the world
model** — which is what this metric is for, and why it sits alongside the
planning, execution and inclusion measures rather than standing in for them.

**No label was changed to match an output.** Repairs 1–3 and 7–8 *remove*
unreachable labels; repairs 4–6 *add* breaches that were being scored as false
positives against a correct detector. Two product changes were made in the same
pass — a booking whose interpreter is unavailable no longer counts as coverage,
and eight departments gained the propagating relationships they lacked.

## Scope of the corpus

- **One production, one shooting day.** *Salt and Light*, 32 scenes of which 5
  are scheduled on day 14. The corpus varies the disruption against a fixed
  world, which is what makes a thousand runs comparable to each other.
- **Eight scenario families**, parameterised: weather, cast and crew, location,
  equipment, access and communication, continuity, operational systems.
- **Fault population scales with the corpus.** `_assigned_fault()` injects the
  two plan-dependent faults on every 16th scenario, so denominators in the report
  track `--count`. A figure quoted as "119 applicable" belongs to a
  1,000-scenario run.
- **Five of eight declared faults are injected**, and all five are handled. The
  other three are reported in `declared_but_not_injected` rather than counted as
  passes; UC-05 in `bob-evidence/USE_CASES.md` extends them.

## Reproduction

```bash
python -m bench.run_benchmark --count 1000 --workers 6 --ablations --ablation-count 200
```

Roughly two minutes on six workers. Writes `bench/results/summary.json`,
`scenarios.jsonl` (one row per scenario per configuration) and `ablations.json`,
all committed.
