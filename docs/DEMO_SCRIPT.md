# The three-minute demonstration

**The demonstration runs itself.** Start the server, open one URL, and press
record. It drives the real client through the real API over a workflow run that
begins when the demonstration begins — same controls a person uses, same
endpoints, nothing pre-rendered. Every beat has a fixed duration, so two takes
are frame-comparable, and there is no click to fumble.

```bash
uvicorn allaccess.api:app --port 8765
# then open, full screen, at 1440x900 or larger:
http://127.0.0.1:8765/?demo=1
```

Escape stops it at any point. `&speed=12` plays the same beats in about fifteen
seconds, which is how `tools/ui_smoke.py` checks every one of them in CI.

**The captions are the narration, burned in.** English subtitles are a
submission requirement and this satisfies it without an edit pass. If a
voiceover is recorded, the table below is the read — the timings are the cue
sheet, and the words are word for word what is on screen.

## Before recording

1. `python tools/ui_smoke.py` — thirteen views plus the whole demonstration in a
   real browser, failing on any console error. A broken view is found before the
   camera rolls rather than during a take.
2. Browser at 1440x900 or larger, zoom 100%, full screen. The layout reflows to
   one column under 60 rem and the demonstration is written for the wide one.
3. Check `GET /api/about` and say what it says. It reports which reasoning plane
   and which event backbone are live. Do not claim a Vertex AI or Confluent
   Cloud run unless one is on screen; "offline reasoning plane" is what the
   default configuration is, and being caught overstating costs more than the
   claim is worth.
4. **Do not narrate the IBM Bob ledger as though sessions have been run.**
   `bob-evidence/` is a prepared ledger and says so in three places. If Bob is
   used before recording, show the real session; if not, show `.bob/` and the
   two working MCP servers and describe them as configuration and tooling,
   which is what they are.

## Two numbers carry the argument

**75 of 75** incomplete executions caught before closure, and **2.412** hard
violations per published plan once the independent recheck is removed. If the
edit runs long, cut a plan-comparison beat, not these.

---

## The script

Generated from `src/allaccess/web/demo.js` by `tools/demo_script.py`.
Editing this table by hand will be overwritten; change the beat instead.


Runs **2:53** over 22 beats.

| # | Cue | Chapter | Narration |
|---|---|---|---|
| 1 | 0:00 | — | *title or closing card — no narration* |
| 2 | 0:06 | The day | Shooting day fourteen of Salt and Light. Five scenes, two units, three locations — and every approved access arrangement satisfied. |
| 3 | 0:17 | The day | Weather and scenes on one axis. The amber bars are exterior work. |
| 4 | 0:22 | The disruption | A verified storm reaches the harbour at eighteen thirty. Sixty-eight kilometre winds, sea state six. |
| 5 | 0:29 | The disruption | Source event to verified readiness — the whole loop — in under half a second. Nothing on this screen is a recording. |
| 6 | 0:40 | Intake | The event arrives typed, contract-validated and hash-chained, carrying its authority — so the system knows whether it may act on it without a human confirming it first. |
| 7 | 0:48 | Impact | The digital twin traverses the dependency graph. A hundred and nineteen affected entities, across six levels. |
| 8 | 0:55 | Impact | Distance from the centre is how many relationships the storm had to travel. Each wedge is one kind of thing. |
| 9 | 1:00 | Impact | The purple rings are approved access arrangements. A scheduling tool would have shown the replacement location as free. |
| 10 | 1:06 | The refusal | The obvious move is the boatshed. It is available. The system will not publish it. |
| 11 | 1:13 | The refusal | A minimal conflict set. C-ACC-001: a step-free route to the working position. Owner, the accessibility coordinator. Source, approved arrangement ACC-001. |
| 12 | 1:21 | The refusal | Not “infeasible”. Why — and whether the rule may be waived. This one may not. |
| 13 | 1:26 | The measurement | And underneath it, the survey. The main shed door has a hundred and forty millimetre cill against a twenty millimetre limit. A location manager can act on that; nobody can act on “accessibility concern”. |
| 14 | 1:37 | The options | Three structurally different plans, each rechecked against all thirty-four constraints independently of the search that produced it, before any of them was shown to anyone. |
| 15 | 1:46 | The options | Objectives trade off against each other. Hard constraints trade off against nothing — which is why the access row reads the same on all three. |
| 16 | 1:54 | Authority | The system approves nothing. Two named authorities sign, and each signature is bound to the plan hash and to the constraint set in force — single use, and expiring. |
| 17 | 2:03 | Execution | Nine typed commands through the saga coordinator. Every one completed. Every acknowledgment returned. |
| 18 | 2:11 | Execution | A system that trusted that would now call the day ready. This one refuses — props has not accepted its task — and there is no override. |
| 19 | 2:20 | Execution | Across a thousand disruptions, verification caught seventy-five of seventy-five incomplete executions. Twelve point four percent of runs would otherwise have closed early. |
| 20 | 2:28 | The shift | And for the producer: not the incident, the shift. Which rules removed the most options, who owns each one, and which document it came from. That is a list you can spend money against. |
| 21 | 2:37 | The evidence | Every screen here is a fold over one event log. Replaying it into a fresh view reproduces live state exactly, and the hash chain is intact. |
| 22 | 2:45 | — | *title or closing card — no narration* |

---

## What is on screen during each chapter

| Chapter | View | What the demonstration points at |
|---|---|---|
| The day | Control board | The verdict, then weather and scenes on one axis |
| The disruption | Control board | The scenario control, the run, then the workflow rail |
| Intake | Disruption intake | Authority, classification, confidence |
| Impact | Impact map | The blast-radius diagram, then the primary-band counts |
| The refusal | Infeasible plans | The verdict, then the conflict set with its owner |
| The measurement | Spatial survey | The route graph, failing segments in red |
| The options | Plan comparison | The three plan cards, then the recommended one |
| Authority | Approval | The signed approvals, hash-bound and expiring |
| Execution | Execution and verification | The saga flow, the refusal, the counters |
| The shift | Executive | The constraint-pressure ranking |
| The evidence | Decision replay | Replay identical, hash chain intact |

## If a beat needs to change

Edit `BEATS` in `src/allaccess/web/demo.js`: `chapter` is the caption's
kicker, `say` is the narration, `ms` is the whole beat including whatever `run`
does. Then re-run `python tools/demo_script.py` to regenerate this file and
`python tools/ui_smoke.py` to confirm every beat still reaches its view and
draws its caption.
