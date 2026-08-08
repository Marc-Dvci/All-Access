# Judge mode — ten minutes, offline, no credentials

Everything here runs with no network, no cloud project and no API key. If any of
it fails, that is a real result and worth telling us about.

```bash
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Minute 1–2 — the closed loop

```bash
python -m productionpulse.cli hero
```

A storm reaches the harbour at 18:30, an hour before the night exterior on the
wall turns over. 68 kph winds and sea state six put the scene outside every
configured safety threshold.

Watch for eleven assertions. The three that matter:

- **"no published feasible plan violates a hard constraint — independently
  revalidated."** The plan is re-checked against the constraint registry from the
  plan object, not from the search's own state.
- **"verification blocked on a real missing acceptance — props had not
  accepted."** The system refused to call the day ready. Every command had
  completed successfully.
- **"every approved access arrangement preserved — 6/6."**

Expect `11/11 assertions passed | 122 events` in under a second.

## Minute 3 — the tests

```bash
pytest -q                        # 214 passed
ruff check src bench tools tests # clean
python tools/a11y_audit.py       # 62/62
```

## Minute 4–6 — the product

```bash
uvicorn productionpulse.api:app --port 8765
```

Open <http://127.0.0.1:8765>. Thirteen views. In priority order:

1. **Impact map.** ~118 nodes from one storm. Ranked by depth: depth 1 is what
   the disruption touched directly, depth 5 is what it reaches through four
   intermediaries. Expand a node to see the path that reached it — an impact
   analysis you cannot interrogate is an assertion.
2. **Infeasible plan explorer.** The view most systems do not have. Each rejected
   plan carries a *minimal* conflict set, and each constraint names the document
   it came from and the person who owns it.
3. **Plan comparison.** Two to three structurally different plans, with delay,
   cost, continuity risk, access impact, robustness and required approvals side
   by side. Note what is *not* a comparison column: on-time probability, which is
   degenerate in this corpus and was removed rather than displayed. See
   `BENCHMARK.md` §6.3.
4. **Approval workspace.** The conflict set sits above the approve control on
   purpose.
5. **Decision replay.** Rebuilds state at any sequence number and asserts it
   matches live.

If you would rather not open thirteen tabs by hand, this drives all of them in
Chromium, fails on any console error or failed request, and leaves a screenshot
of each in `docs/screenshots/`:

```bash
pip install -e ".[browser]" && playwright install chromium
python tools/ui_smoke.py
```

**Please note:** the first time this interface was rendered it had three defects
in these very views, including a control board that declared every department
ready while verification was blocking the day. All fifteen endpoints were
returning 200 the whole time. They are fixed, tested and described in
`BENCHMARK.md` §6.4 — and they are the reason `ui_smoke.py` now runs in CI. No
screen-reader user has tested this.

## Minute 7 — the benchmark

```bash
python -m bench.run_benchmark --smoke        # 48 scenarios, ~20 s
```

Then read the committed 1,000-scenario evidence:

```bash
python -c "import json;print(json.dumps(json.load(open('bench/results/summary.json')),indent=1))"
```

Or recompute the headline claim from the raw rows rather than trusting the
summary that asserts it — this is what CI does:

```bash
python -c "
import json
rows=[json.loads(l) for l in open('bench/results/scenarios.jsonl') if l.strip()]
full=[r for r in rows if r['config']=='full']
print(len(full),'scenarios;',sum(r['hard_violations_published'] for r in full),'hard violations')"
```

## Minute 8 — where it is weak

`docs/BENCHMARK.md` §7. Six numbered weaknesses, including the one where a
headline metric is close to a tautology and we ask you not to quote it without
the explanation.

That section is the fastest way to judge whether the rest of the evidence is
trustworthy.

## Minute 9 — the two things that are not done

`bob-evidence/README.md` — **no IBM Bob session has been run.** The directory
holds configuration, two working MCP servers, and six use cases with acceptance
criteria. It holds no invented session records.

`infra/README.md` §"Verification status" — the Terraform validates in CI and has
never been applied.

## Minute 10 — one thing to try yourself

```bash
curl -s localhost:8765/api/about
curl -s -X POST localhost:8765/api/disruptions \
  -H 'Content-Type: application/json' -d '{"scenario_id":"SC-STORM-001"}'
```

Or break something and watch it fail closed. Take the hero storm and also remove
the only step-free vehicle:

```python
from productionpulse.agents.coordinator import ProductionCoordinator
from productionpulse.agents.core import build_reasoner
from productionpulse.disruptions import STORM_SCENARIO, build_source_event, scenario_problem
from productionpulse.production import world as w
from productionpulse.stream.bus import build_bus
from productionpulse.systems import build_systems
from productionpulse.twin import build_twin

problem = scenario_problem(STORM_SCENARIO, twin=build_twin())
problem.unavailable["VEH-ACC-1"] = "powered lift failure"   # the only step-free vehicle

bus = build_bus(w.PRODUCTION_ID)
out = ProductionCoordinator(
    bus, build_systems(w.PRODUCTION_ID), reasoner=build_reasoner("offline")
).handle(problem, build_source_event(bus, STORM_SCENARIO), title=STORM_SCENARIO.title)

print(f"{len(out.plans)} feasible, {len(out.rejected)} rejected")
for plan in out.rejected:
    for conflict in plan.conflicts:
        print(" ", sorted(conflict.constraint_ids), "|", conflict.production_language)
```

Expected: **0 feasible, 5 rejected**, four naming `C-ACC-002` ("no step-free
vehicle is available to satisfy ACC-001") and one naming `C-ACC-001` ("Ormsvik
boatshed has no step-free route from arrival to the working position and no
surveyed step-free alternate position").

That last one is the interesting rejection. The boatshed is the obvious
replacement location, it is free, and a conventional scheduler would offer it.
This one refuses, and says why, in a sentence a location manager can act on.

If it silently produces a feasible plan instead, that is the exact failure this
project is built to prevent, and we would want to know.

---

## Reset

Delete `var/`. It holds runtime SQLite stores, the generated approval signing key
and benchmark worker databases, and it is gitignored. Nothing else is stateful.

`bench/results/` is **committed on purpose** — it is the evidence for the
documented numbers, not a build artifact.
