# IBM Bob — do this once (the eligibility runbook)

The IBM track has one hard gate:

> *"Projects that do not demonstrate usage of IBM Bob will not meet the
> requirements for the IBM track, regardless of how the code was written."*

This page is the shortest honest path to satisfy it: **one real Bob session on
this repo, recorded.** Everything Bob needs is already committed — 7 scoped modes
(`.bob/custom_modes.yaml`), engineering rules (`.bob/rules*/`), and 2 working MCP
servers (`.bob/mcp.json`). Budget ~15 minutes.

---

## 1. Install and open

1. Download IBM Bob — <https://bob.ibm.com/download> — and sign in with your
   IBMid (the free trial is enough).
2. **Open this folder** in Bob:
   `the project folder`.
3. Open the mode picker. You should see the 7 project modes: *Production
   Architecture, Event Contract, Connector Modernization, Solver Engineering,
   Security Review, Test and Evaluation, Documentation and Submission.* Seeing
   them proves Bob loaded `.bob/custom_modes.yaml` — that alone is real evidence.

**(Optional, stronger) connect the MCP servers.** Bob reads `.bob/mcp.json`
automatically. The two Python servers (`test-results`, `schema-registry-dev`) run
with `python -m tools.mcp_*`; if they don't connect, activate the venv first so
`python` resolves to it (`.venv\Scripts\activate`) and reload — they are
supporting evidence, not the requirement, so don't lose time on them.

---

## 2. The session (this is the evidence)

Switch to **Connector Modernization** mode and paste:

> Read `bob-evidence/briefs/uc-03-callsheet-modernization.md`. Do NOT open
> `src/allaccess/systems/callsheet_modern.py`. Working only from
> `src/allaccess/systems/callsheet_legacy.py` and this brief, produce a typed,
> idempotent, event-driven replacement in a new file
> `src/allaccess/systems/callsheet_bob.py`, plus a parity test. Fix each of the 8
> documented defects one at a time, each with a failing-first test, and list every
> defect you fixed with the test that covers it.

This is safe — a new file, so the green build (which uses the reference
`callsheet_modern.py`) is untouched — and it produces genuine before/after
evidence. Let Bob plan first, approve the plan, then let it implement.

Then switch to **Security Review** and **Test and Evaluation** modes and ask Bob
to review its own diff and find anything still wrong. Recording the parts that go
badly (Bob proposes something, you reject it) is *better* evidence of a real
process than a clean run.

---

## 3. Record it

- **Screen-record steps 1–2** (2–4 minutes is plenty). This becomes the "built
  with IBM Bob" beat in the demo.
- **Save the Bob transcript** (Bob keeps conversation history; export or copy it).

---

## 4. Hand back

Send me the transcript/summary and I will:

- write the session record into `bob-evidence/sessions/` (from
  `SESSION_TEMPLATE.md`),
- fill `CONTRIBUTION_MAP.md` (change → code → tests),
- diff Bob's `callsheet_bob.py` against the hand-written reference and record what
  matched and what differed,
- rewrite the **IBM** paragraph of `docs/DEVPOST.md` to describe what actually
  happened.

That closes the only open eligibility requirement for the IBM track.
