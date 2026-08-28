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


Runs **1:52** over 11 beats.

| # | Cue | Chapter | Narration |
|---|---|---|---|
| 1 | 0:00 | — | Every film and television set runs on a fragile promise — that everyone who is called can actually do their job that day. |
| 2 | 0:09 | — | But sets change by the hour — weather, a delay, a location lost at short notice. And the fastest fix is often the one that quietly leaves someone behind. All-Access is built so that can't happen. |
| 3 | 0:22 | The day | Here is a real shoot day. Salt and Light — five scenes, three locations, and every access arrangement in place. Everyone can work. |
| 4 | 0:31 | The disruption | Then a storm rolls in and closes the harbour. Watch what All-Access does — live, in under a second. |
| 5 | 0:42 | The ripple | Instantly, it sees everything the storm touches — every scene, every department, and every person's access needs. |
| 6 | 0:50 | The refusal | The obvious fix is to move to the boatshed. It is free, and a scheduling tool would just take it. But there is no step-free way in — and someone on this crew depends on one. So All-Access refuses it. |
| 7 | 1:03 | A reason you can act on | And it does not just say no. It shows exactly why — the only route in has a step at the door — so a location manager can fix it. Not a vague note nobody can act on. |
| 8 | 1:15 | The options | Instead, it offers plans that all keep every access arrangement intact — because an access need is never something to trade away for a faster day. |
| 9 | 1:25 | The judgment stays human | All-Access never decides on its own. It proposes; the people responsible approve. |
| 10 | 1:32 | Everyone, or no one | Then it makes sure the new plan actually reaches every department — and it will not call the day ready until everyone has it. |
| 11 | 1:42 | — | All-Access. Recover any disruption — without ever leaving someone behind. For every production, and every person on it. |

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
