"""Write docs/DEMO_SCRIPT.md from the demonstration that actually plays.

The narration, the chapter names and the cue times all live in
`src/allaccess/web/demo.js`. A shot list maintained by hand beside them
is a second copy of the same facts, and the copy is wrong from the first time a
beat is retimed — which is exactly the document somebody reads while recording.

So this loads the page in a real browser, reads `window.AllAccessDemo`,
and regenerates the script. Run it after changing any beat:

    python tools/demo_script.py                  # starts its own server
    python tools/demo_script.py --check          # fail if the file is stale

`--check` is what CI runs; it makes a retimed beat with a stale script a build
failure rather than a surprise on the day of the recording.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ui_smoke import free_port, start_server  # noqa: E402

OUT = ROOT / "docs" / "DEMO_SCRIPT.md"

PREAMBLE = """# The three-minute demonstration

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

"""

CLOSING = """
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
"""


def read_script(url: str) -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "playwright is not installed. `pip install -e \".[browser]\" && "
            "playwright install chromium`"
        ) from None
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_function("() => window.AllAccessDemo", timeout=20000)
        script = page.evaluate("() => window.AllAccessDemo.script")
        browser.close()
    return script


def render(script: list[dict]) -> str:
    total = sum(beat["ms"] for beat in script)
    lines = [PREAMBLE]
    lines.append(f"Runs **{total // 60000}:{total // 1000 % 60:02d}** over "
                 f"{len(script)} beats.\n")
    lines.append("| # | Cue | Chapter | Narration |")
    lines.append("|---|---|---|---|")
    for index, beat in enumerate(script, start=1):
        at = beat["at"]
        cue = f"{at // 60000}:{at // 1000 % 60:02d}"
        chapter = beat["chapter"] or "—"
        say = beat["say"].replace("|", "\\|") or "*title or closing card — no narration*"
        lines.append(f"| {index} | {cue} | {chapter} | {say} |")
    lines.append(CLOSING)
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="an already-running server; otherwise one is started")
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed script differs from the demo")
    args = parser.parse_args()

    server = None
    url = args.url
    if not url:
        port = free_port()
        server = start_server(port)
        url = f"http://127.0.0.1:{port}"
    try:
        rendered = render(read_script(url))
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != rendered:
            print(f"{OUT.relative_to(ROOT)} is stale — run `python tools/demo_script.py`")
            return 1
        print(f"{OUT.relative_to(ROOT)} matches the demonstration")
        return 0

    OUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
