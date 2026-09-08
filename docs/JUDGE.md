# Judge mode — ten minutes, offline, no credentials

Everything below runs with no network, no cloud project and no API key. If any of
it fails, that is a real result and worth telling us about.

---

## The judging link, first

The hosted product has two modes, and what separates them is a session rather
than a build.

**Anyone** can open <https://all-access-1022938933263.europe-west1.run.app>, read
all thirteen views, run any disruption in the library, and sign in as a named
authority on this production to take a plan through the approval gate. Those runs
use the deterministic reasoning plane — the one every committed benchmark figure
was measured on, which costs nothing and cannot be exhausted by a public URL.

**The judging link is the same product with an evaluation identity.** It is the
URL on the submission form, and opening it does three things:

1. Exchanges the key in it for a session, then strips the key from the address
   bar — a bearer credential in a URL is a bearer credential in a screenshot.
2. Grants that session **every approving authority**, so one person can take a
   two-signature plan through the gate alone. Recorded as `JUDGE/<role>` on the
   `judge` channel, never under a crew member's name; the data contract refuses
   it at the stream boundary if it tries.
3. Entitles it to **Gemini on Vertex AI**. Every disruption started from that
   session runs the eleven specialist agents on `gemini-3.7-flash` rather than
   the offline plane. Press **Run disruption** and read the footer: the plane it
   reports is read off the run that just happened, not off a badge.

The two planes produce identical decisions and different language — that is what
`bench/reasoning_plane.py` exists to check — so what the judging link changes is
what a human is given to read and what a run costs. Nothing about what the
constraint engine is permitted to publish.

If the link has expired or its key has been rotated, everything below still runs,
and so does every view on the public URL.

## Where the identity is

`docs/IAM.md` §0. The short version: `POST /api/approval/sign` reads the role off
the session and the actor off the session's subject, and there is no field in the
request that names either. `tests/test_identity.py` is seventeen tests written
against the failure rather than the feature — the anonymous caller at all three
write endpoints, the session that tries to widen itself, the edited token, the
expired session, the client that names its own actor, the coordinator who may
route and may never sign.

Two checks, a minute each, against a local server:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8765/api/approval/sign \
  -H 'Content-Type: application/json' -d '{"role":"unit_production_manager"}'
# 401 — nobody is signed in, and the gate is still shut

curl -s localhost:8765/api/identity | python -m json.tool | head -40
# the production directory, and this deployment's published demonstration codes
```

Then sign in as the location manager in the browser and try the UPM's signature:
`403`, and the reason names the session rather than the plan.

---

```bash
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Minute 1–2 — the closed loop

```bash
python -m allaccess.cli hero
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

Expect `11/11 assertions passed | 131 events` in under a second.

## Minute 3 — the tests

```bash
pytest -q                        # 265 passed
ruff check src bench tools tests # clean
python tools/a11y_audit.py       # 78/78
```

## Minute 4–6 — the product

```bash
uvicorn allaccess.api:app --port 8765
```

**The fastest honest tour is <http://127.0.0.1:8765/?demo=1>.** It plays a
2 minute 53 second guided walk through the whole workflow, by itself, driving
this client through this API over a run that starts when you open it — the same
buttons you would press, in the same order, with the argument narrated in
captions. Escape stops it and hands the product back. It is the same thing the
demonstration video records, and `docs/DEMO_SCRIPT.md` is its cue sheet,
generated from the beats themselves.

Then open <http://127.0.0.1:8765> and drive it yourself. Thirteen views, in
priority order:

1. **Impact map.** 119 entities from one storm, drawn as a blast radius:
   distance from the centre is how many relationships the disruption had to
   traverse, each wedge is one kind of thing, and the purple marks are approved
   access arrangements. Expand a band to see the path that reached each one — an
   impact analysis you cannot interrogate is an assertion.
2. **Infeasible plan explorer.** The view most systems do not have. Each rejected
   plan carries a *minimal* conflict set, and each constraint names the document
   it came from and the person who owns it.
3. **Plan comparison.** Two to three structurally different plans, with delay,
   cost, continuity risk, access impact, robustness and required approvals side
   by side. Plans are ranked on expected delay, then worst credible delay, then
   recovery margin.
4. **Approval workspace — and this is where the product stops.** Nothing has
   been executed when you arrive. The workflow scoped the disruption, built the
   plans, proved each feasible and had eleven experts assess the strongest, and
   then it stopped inside the coordinator and is waiting for you. It is waiting
   for a *person*: the first panel is a sign-in, and until you take an identity
   there is no button on the screen that routes a plan. Sign in as one of the
   named authorities, choose a plan, then sign for each authority the plan
   requires; the banner across the top tracks what is outstanding. A plan
   needing two signatures will ask you to sign in as the second person, because
   a session holds exactly the authority its holder holds and there is no
   request that widens it. Decline instead and the disruption is abandoned with
   nothing issued. Every approval records the channel it came through, so a run
   signed here, a run signed on the judging link and a run signed by the
   unattended approver are told apart in the log rather than by inference.
5. **Decision replay.** Rebuilds state at any sequence number and asserts it
   matches live.

If you would rather not open thirteen tabs by hand, this drives all of them in
Chromium — plus the whole guided demonstration at speed — fails on any console
error or failed request, and leaves a screenshot of each in `docs/screenshots/`:

```bash
pip install -e ".[browser]" && playwright install chromium
python tools/ui_smoke.py
```

Every view and every demonstration beat is driven in Chromium on each CI run and
every render is asserted, so what you open is what the pipeline last proved
renders.

## Minute 6–7 — check that the gate is real

The claim is that nothing executes without a signature. It is worth a minute
because it is the one claim a reader is entitled to disbelieve.

```bash
curl -s localhost:8765/api/execution | python -c "import json,sys;print(json.load(sys.stdin)['commands'])"
# []  — no command has been issued
curl -s localhost:8765/api/approval | python -c "import json,sys;d=json.load(sys.stdin);print(d['channel'], d['pending']['waiting_on'])"
# human selection
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:8765/api/approval/select \
  -H 'Content-Type: application/json' -d '{"plan_id":"anything"}'
# 401 — and it is 401 rather than 409, because the caller is nobody
```

Sign it off in the browser, then run all three again: the commands appear and the
approvals name the people who signed. Or take the other channel and watch the
difference show up in the data rather than in a sentence:

```bash
AA_APPROVAL_MODE=stand_in uvicorn allaccess.api:app --port 8766
curl -s localhost:8766/api/approval | python -c "import json,sys;d=json.load(sys.stdin);print([(a['role'],a['actor']) for a in d['approvals']])"
# [('unit_production_manager', 'STAND-IN/unit_production_manager'), ...]
```

`pytest -q tests/test_human_approval.py tests/test_identity.py` covers what the
gate refuses: a plan that was never offered, an infeasible plan, an authority the
plan does not require, signing before a plan is chosen, a caller with no session
at all, a session signing for an authority it does not hold, an edited session
token, and a stand-in or evaluation approval wearing a crew member's identifier —
those last two are refused by the data contract, at the stream boundary, not by
the caller.

## Minute 8 — the benchmark

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

## Minute 9 — the ablation

The single strongest claim in the project, and the fastest one to check:

```bash
python -c "
import json
a=json.load(open('bench/results/ablations.json'))
for row in a['table']:
    print(f\"{row['configuration']:20} violations/plan {row['hard_constraint_violation_rate']:.3f}  access {row['access_preservation_rate']:.3f}\")"
```

`no_validation` replaces exactly one function — `engine.validate`, which
`engine.publish` takes its verdict from. Search still runs, plans are still
built, and every published plan then breaks roughly **two hard constraints**,
**22% of approved plans silently drop an approved access arrangement**, and the
named-conflict-set rate goes to **zero**: it never fails closed because it never
checks.

The scoring path deliberately does not go through `validate`; it calls `evaluate`
itself, so the ablated run is still measured against the real registry.

## Minute 9 — the two things worth reading

`docs/EVIDENCE.md` — the problem in the industry's own words. Weather disruption
at up to $500,000 a day; the production accessibility coordinator whose published
duties include adapting access plans "as necessary with changing production and
accommodation needs"; the 48-hour interpreter cancellation windows that make
`C-ACC-002` a commercial term rather than a preference.

`docs/COMPARISON.md` — where the line falls against Movie Magic and StudioBinder.
Both are strong at authoring and distributing a schedule. Neither decides whether
a revised schedule is *allowed*, and neither treats an approved access
arrangement as anything but a note.

## Minute 10 — one thing to try yourself

```bash
curl -s localhost:8765/api/about
curl -s -X POST localhost:8765/api/disruptions \
  -H 'Content-Type: application/json' -d '{"scenario_id":"SC-STORM-001"}'
```

Or break something and watch it fail closed. Take the hero storm and also remove
the only step-free vehicle:

```python
from allaccess.agents.coordinator import ProductionCoordinator
from allaccess.agents.core import build_reasoner
from allaccess.disruptions import STORM_SCENARIO, build_source_event, scenario_problem
from allaccess.production import world as w
from allaccess.stream.bus import build_bus
from allaccess.systems import build_systems
from allaccess.twin import build_twin

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


## Minute 10 — Gemini, if you have a Vertex project

Everything above runs offline. This is the one part that does not, and it is the
answer to the fair question about a benchmark that runs on the offline plane:

```bash
gcloud services enable aiplatform.googleapis.com --project $GOOGLE_CLOUD_PROJECT
pip install -e '.[cloud]'
GOOGLE_CLOUD_PROJECT=... python -m bench.reasoning_plane --count 8
```

It runs the same disruptions on both planes and diffs them. The decisions have
to be byte-identical — plan, hash, published set, conflict sets, access
preservation, verification, every finding's status — and the headlines have to
differ, because a run where the model changed nothing at all is a run that
quietly fell back. It exits non-zero on either failure. The committed result is
`bench/results/reasoning_plane.json` and `docs/BENCHMARK.md` §7 is generated
from it.
