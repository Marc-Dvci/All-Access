# Three-minute demonstration — shot list

**Rule for the whole recording: everything on screen is the running system.** No
slides, no mockups, no cinematic trailer. The brief asks for the agent
functioning, and a judge can tell the difference in about four seconds.

**Setup**

```bash
uvicorn productionpulse.api:app --port 8765
```

Second terminal ready with `python -m productionpulse.cli hero`. Browser at
1440×900, dark theme, zoom 110% so text is readable when the video is scaled.

> **Before recording anything, run `python tools/ui_smoke.py`.** It opens all
> thirteen views in Chromium and fails on any console error, so a broken view is
> found before the camera is rolling rather than during a take.
> `docs/screenshots/` will hold a current image of every view — useful for
> planning shots without scrubbing the recording. `ACCESSIBILITY.md` §5 has the
> manual checklist for the things a machine cannot judge.

---

## 0:00–0:12 — Establish the production

**Screen:** Production Control Board.

**Voice:** "Shooting day fourteen of *Salt and Light*. Five scenes, two units,
three locations, twenty-seven crew, six approved access arrangements. Everything
is certified ready."

**Show:** the baseline certification badge — twelve checks, zero blocking issues.

---

## 0:12–0:28 — The disruption

**Screen:** Disruption Intake. Fire the storm.

**Voice:** "A verified storm reaches the harbour at eighteen thirty. Sixty-eight
kilometre winds, sea state six — outside every configured safety threshold, an
hour before the night exterior turns over."

**Show:** the source event landing on the stream, contract-validated, hash-chained.

---

## 0:28–0:58 — The consequences nobody would have found by hand

**Screen:** Impact Map. This is the money shot; give it the time.

**Voice:** "The twin traverses the dependency graph. A hundred and eighteen
affected entities, ranked by depth. Depth one is what the storm touched. Depth
five is what it reaches through four intermediaries."

**Show — expand three nodes and read the path:**

1. The accessible vehicle cannot reach the replacement location before the
   revised call.
2. The interpreter booking runs to 23:30 and covers the planned day exactly —
   any work moved outside it needs an extension with three hours' notice.
3. The refrigerated storage is at the current base, not the proposed one.

**Voice:** "Every one of those is a consequence for a specific person's approved
arrangement. A scheduling tool would have shown the replacement location as
free."

---

## 0:58–1:25 — It refuses the obvious answer

**Screen:** Infeasible Plan Explorer.

**Voice:** "The obvious move is the boatshed. It is available. The system will
not publish it."

**Show:** the rejection, and read the conflict set aloud:

> **C-ACC-001** — Ormsvik boatshed has no step-free route from arrival to the
> working position and no surveyed step-free alternate position.
> Source: approved access arrangement ACC-001. Owner: accessibility coordinator.
> Evidence: spatial twin, main door 140 mm cill.

**Voice:** "A minimal conflict set. It names the rule, the document it came from,
the person who owns it, and the measurement. Not 'infeasible' — *why*."

---

## 1:25–1:48 — Plans that are actually different

**Screen:** Plan Comparison.

**Voice:** "Three structurally different plans, each one proved feasible against
thirty-four constraints before it was shown. Delay, cost, continuity risk, access
impact, robustness under a two-hundred-sample simulation, and the approvals each
one requires."

**Show:** the recommended plan — shoot two prepared interiors tonight at the
accessible location, move the exterior to the next morning's verified weather
window, keep the child performer's end time, keep the interpreter window, keep
the accessible vehicle.

**Voice:** "Protecting safety and access produced the stronger operational
outcome, not a compromise on one."

---

## 1:48–2:10 — Human authority

**Screen:** Approval Workspace.

**Voice:** "The system does not approve anything. This is a major schedule change
and a location change, so it needs the first AD and the UPM. The approval is
signed, bound to this plan's hash and to the active constraint set, single-use
and expiring — it cannot be moved to another plan or replayed after the rules
change."

**Show:** the conflict set sitting above the approve control, then both approvals.

---

## 2:10–2:38 — Execution through the stream

**Screen:** Execution Board, then Stream Governance.

**Voice:** "Nine typed commands through the saga coordinator. Schedule updated,
transport rebooked, interpreter hours extended, an accessible briefing published
in written and captioned form, equipment reassigned, department queues updated,
and the call-sheet connector publishes revision two and returns an
acknowledgment."

**Show:** the lineage trace — weather alert → assessments → plan → approval →
commands → acknowledgments, derived from the log rather than drawn.

---

## 2:38–2:52 — The part most systems get wrong

**Screen:** Verification panel. **Do not rush this.**

**Voice:** "Every command completed. Every acknowledgment returned. A system that
trusted that would now say the day is ready."

**Show:** the block — **props has not accepted its task.**

**Voice:** "It refuses. There is no override. Across a thousand disruptions,
twelve point four percent of executions would have been declared complete by a
system that trusted acknowledgment alone."

**Show:** props accepts; twelve of twelve assertions pass; the board turns ready.

---

## 2:52–3:00 — Close on the evidence

**Screen:** split — the benchmark summary and the ablation table.

**Voice:** "A thousand disruptions. Zero hard-constraint violations across
sixteen hundred published plans. All access arrangements preserved. Remove the
independent feasibility check and every published plan breaks two hard rules,
twenty-two percent silently drop an approved arrangement, and it stops failing
closed entirely."

**Final frame:** the ablation table, held for two seconds.

---

## Notes for the edit

- **Subtitle it.** English subtitles are required, and a product that schedules
  around a deaf performer's interpretation arrangements should not ship an
  uncaptioned video. Burn them in.
- **Do not narrate the IBM Bob ledger as though sessions have been run.** They
  have not. If Bob is used before recording, show the real session; if not, show
  `.bob/custom_modes.yaml` and the two working MCP servers and describe them as
  configuration and tooling, which is what they are.
- Two numbers carry the argument: **0.124** false closure and **2.412** hard
  violations per plan without validation. If the edit runs long, cut the plan
  comparison detail, not these.
- Don't claim a Confluent Cloud or Vertex AI run unless one is on screen. Say
  "offline reasoning plane" if that is what is running — `GET /api/about` shows
  it, and being caught overstating costs more than the claim is worth.
