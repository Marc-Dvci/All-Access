"""Render the web interface in a real browser and assert every view draws.

The static accessibility audit (`tools/a11y_audit.py`) reads the markup. It
cannot tell you that a renderer read `d.summary.contracts` when the API returns
`d.catalog_summary.contracts`, because that failure happens at runtime in a
browser and nowhere else. Every endpoint in this project returned 200 with a
substantive payload long before anything had drawn a single pixel.

So this tool drives the actual client:

* every one of the thirteen views is opened and required to replace its
  "Loading…" placeholder with substantive content;
* the client's own error path is treated as a failure — `show()` renders an
  `error` chip when a renderer throws, and this looks for it;
* **any** console error, uncaught exception or failed network request fails the
  run, including ones a view swallows;
* the two in-view selects (spatial location, crew member) and the "Run
  disruption" control are exercised, because they re-enter the render path with
  different data;
* keyboard tab navigation is driven with arrow keys, since the APG pattern in
  `app.js` is a claim about behaviour, not markup.

Screenshots of every view land in `--shots` so the render can be inspected
rather than taken on trust.

    python tools/ui_smoke.py                 # starts its own server
    python tools/ui_smoke.py --url http://127.0.0.1:8765 --shots docs/screenshots

Exit status is 0 only if every view drew and nothing was logged.
"""

from __future__ import annotations

import argparse
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

#: (tab id, content container id, human name). Mirrors TABS in web/app.js.
VIEWS: list[tuple[str, str, str]] = [
    ("board", "board-content", "Control board"),
    ("intake", "intake-content", "Intake"),
    ("impact", "impact-content", "Impact map"),
    ("plans", "plans-content", "Plan comparison"),
    ("rejected", "rejected-content", "Infeasible plans"),
    ("spatial", "spatial-content", "Spatial"),
    ("approval", "approval-content", "Approval"),
    ("execution", "execution-content", "Execution"),
    ("departments", "departments-content", "Departments"),
    ("crew", "crew-content", "Crew view"),
    ("executive", "executive-content", "Executive"),
    ("replay", "replay-content", "Decision replay"),
    ("streams", "streams-content", "Streams"),
]

#: A view that draws fewer characters than this has not really drawn. Set well
#: below the smallest real view (the crew view, ~600 chars) and well above the
#: "Loading…" placeholder.
MIN_CONTENT_CHARS = 200


class Failures:
    def __init__(self) -> None:
        self.items: list[str] = []

    def add(self, where: str, detail: str) -> None:
        self.items.append(f"{where}: {detail}")

    def __bool__(self) -> bool:
        return bool(self.items)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def wait_for(url: str, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.4)
    return False


def start_server(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "allaccess.api:app",
         "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if not wait_for(f"http://127.0.0.1:{port}/healthz"):
        proc.terminate()
        raise SystemExit("server did not become healthy within 60 s")
    return proc


#: The guided demonstration is what a judge watches, so it is checked the same
#: way the product is: played end to end in a real browser, at speed, with every
#: beat required to put a caption on screen. A demonstration that silently skips
#: a chapter is a three-minute video with a hole in it, and nothing else in this
#: repository would notice.
DEMO_SPEED = 14
DEMO_MAX_SECONDS = 180


def drive_demo(page: Any, failures: "Failures", shots: Path | None) -> None:
    page.goto(f"{page.url.split('?')[0]}?demo=1&speed={DEMO_SPEED}", wait_until="networkidle")

    declared = page.evaluate("() => window.AllAccessDemo.seconds")
    beats = page.evaluate("() => window.AllAccessDemo.beats")
    if declared > DEMO_MAX_SECONDS:
        failures.add("demo", f"runs {declared:.0f} s, over the {DEMO_MAX_SECONDS} s limit")

    seen: set[int] = set()
    captioned: set[int] = set()
    budget = int((declared / DEMO_SPEED + 30) / 0.12)
    for _ in range(budget):
        page.wait_for_timeout(120)
        label = page.inner_text("#demo-hud")
        match = re.search(r"(\d+) of (\d+)", label)
        if match:
            index = int(match.group(1))
            seen.add(index)
            # The narration line specifically, not the caption box: the box also
            # holds the chapter name, so reading the whole thing reports a
            # caption for a beat whose narration is empty. Confirmed by blanking
            # one beat's `say` and watching this fail.
            if page.inner_text("#demo-caption .c-line").strip():
                captioned.add(index)
        if not page.evaluate("() => document.body.classList.contains('demo-on')") and seen:
            break
    else:
        failures.add("demo", "never finished")

    missing = sorted(set(range(1, beats + 1)) - seen)
    if missing:
        failures.add("demo", f"beats never reached: {missing}")
    # The title and closing cards carry their text in the card, not the caption.
    silent = sorted(seen - captioned - {1, beats})
    if silent:
        failures.add("demo", f"beats that drew no caption: {silent}")

    # The demonstration restarts the hero disruption on its first frame, so it
    # meets the same shut gate a person does, and its approval beat is what
    # opens it. If that beat ever stopped signing, the banner would still be up
    # here and the two beats after it would have been narrated over an empty
    # execution view — which is the one failure a caption check cannot see.
    if page.locator("#gate-banner").get_attribute("hidden") is None:
        failures.add("demo", "finished with the approval gate still open")

    if shots:
        page.screenshot(path=str(shots / "demo.png"))
    print(f"  ok   guided demo         {len(seen)}/{beats} beats, {declared:.0f} s at 1x")


def sign_off_at_the_gate(page: Any, failures: "Failures", shots: Path | None) -> None:
    """Take the day past the approval gate by clicking, the way a person does.

    The application stops before it executes anything and waits for a named
    authority. There is no test hook past it and no environment variable this
    tool sets to skip it — if the gate can be opened by anything other than the
    buttons on the screen, that is the thing worth knowing, so this drives the
    buttons.

    It also asserts the shape of the stop: the banner has to be up, more than
    one plan has to be on offer, and the gate has to refuse a browser that has
    not signed in as anybody. A gate that presents a single option is a rubber
    stamp with extra steps, and a gate that accepts an anonymous click is not a
    gate.
    """
    # Start from no identity every time this runs, including on the second
    # disruption. A session left over from the last decision would hide the
    # thing worth asserting, which is that the gate is shut for a browser that
    # has not signed in as anybody.
    leftover = page.locator("#whoami button", has_text="Sign out")
    if leftover.count():
        leftover.first.click()
        page.wait_for_timeout(500)

    page.click("#tab-approval")
    page.wait_for_function(
        "() => { const n = document.getElementById('approval-content');"
        " return n && !n.classList.contains('loading'); }",
        timeout=20000,
    )

    if page.locator("#gate-banner").get_attribute("hidden") is not None:
        failures.add("approval gate", "the workflow did not stop to ask anybody")
        return

    # Before anything else: the browser arrives with no session, and the gate
    # has to say so rather than offering a decision it would then refuse.
    if not page.locator("#approval-content .signin", has_text="Sign in to decide").count():
        failures.add("approval gate", "offered the decision to a browser with no identity")
    if page.locator("#approval-content button", has_text="Take this plan").count():
        failures.add("approval gate", "a plan could be routed before anybody signed in")
    if shots:
        page.screenshot(path=str(shots / "approval-signin.png"), full_page=True)

    entry = page.locator("#approval-content .signin button", has_text="Sign in as ")
    if not entry.count():
        failures.add("approval gate", "no way to establish an identity at the gate")
        return
    entry.first.click()
    page.wait_for_selector(
        "#approval-content .signin h2:text-matches('Signed in as')", timeout=20000,
    )

    choices = page.locator("#approval-content button", has_text="Take this plan")
    offered = choices.count()
    if offered < 2:
        failures.add("approval gate", f"offered {offered} plan(s) to choose between")
    if not offered:
        return
    if shots:
        page.screenshot(path=str(shots / "approval-gate.png"), full_page=True)
    choices.first.click()

    # Two kinds of button now sit on a signature row, and the difference is the
    # point: "Sign as" belongs to a session that holds the authority, and "Sign
    # in as" is the hand-off to the person who does. A plan needing two
    # authorities cannot be cleared without at least one of the second kind.
    signed = 0
    handovers = 0
    for _ in range(24):
        page.wait_for_timeout(300)
        pending = page.locator(
            "#approval-content .signrow button:not([disabled])", has_text="Sign as ")
        if pending.count():
            if shots and not signed:
                page.screenshot(path=str(shots / "approval-signing.png"), full_page=True)
            pending.first.click()
            signed += 1
            continue
        handover = page.locator(
            "#approval-content .signrow button:not([disabled])", has_text="Sign in as ")
        if not handover.count():
            break
        handover.first.click()
        handovers += 1
    else:
        failures.add("approval gate", "never ran out of signatures to collect")

    if not signed:
        failures.add("approval gate", "no authority was ever asked to sign")

    try:
        page.wait_for_function(
            "() => document.getElementById('gate-banner').hidden", timeout=30000,
        )
    except Exception:
        failures.add("approval gate", "stayed open after every authority had signed")
        return

    page.wait_for_timeout(400)
    text = page.locator("#approval-content").inner_text()
    if "Authorised by" not in text:
        failures.add("approval gate", f"signed, but the view does not say so: {text[:160]!r}")
    print(f"  ok   approval gate       {offered} plans offered, {signed} signature(s) "
          f"given across {handovers + 1} session(s)")


def run(url: str, shots: Path | None, headed: bool) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "playwright is not installed. `pip install playwright && "
            "playwright install chromium`"
        ) from None

    failures = Failures()
    console: list[str] = []
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headed)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})

        page.on("console", lambda m: (
            console.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None
        ))
        page.on("pageerror", lambda e: failures.add("uncaught exception", str(e)))
        page.on("requestfailed", lambda r: failures.add(
            "request failed", f"{r.url} — {r.failure}"
        ))

        page.goto(url, wait_until="networkidle")

        # The masthead and footer are written by boot(), so a blank one means
        # boot never completed even if a panel later renders.
        for element_id, placeholder in (
            ("production-line", "Loading production"),
            ("about-line", "a decision and execution operating system"),
        ):
            text = page.inner_text(f"#{element_id}").strip()
            if placeholder.lower() in text.lower():
                failures.add(element_id, f"still shows its placeholder: {text!r}")

        scenarios = page.eval_on_selector_all(
            "#scenario-select option", "els => els.length"
        )
        if scenarios < 2:
            failures.add("scenario-select", f"only {scenarios} option(s) populated")

        # Nothing downstream of the gate exists until somebody opens it, so this
        # comes before the views that read what execution produced.
        sign_off_at_the_gate(page, failures, shots)

        for tab, container, name in VIEWS:
            page.click(f"#tab-{tab}")
            try:
                page.wait_for_function(
                    f"() => {{ const n = document.getElementById('{container}');"
                    f" return n && !n.classList.contains('loading'); }}",
                    timeout=20000,
                )
            except Exception:
                failures.add(name, "never left the loading state")
                continue

            panel = page.locator(f"#panel-{tab}")
            if panel.get_attribute("hidden") is not None:
                failures.add(name, "panel stayed hidden after its tab was selected")

            root = page.locator(f"#{container}")
            text = root.inner_text().strip()
            if len(text) < MIN_CONTENT_CHARS:
                failures.add(name, f"drew only {len(text)} characters: {text[:120]!r}")

            # app.js renders `chip("error", "bad")` when a renderer rejects.
            errors = root.locator("span.chip.bad", has_text="error").count()
            if errors:
                failures.add(name, f"rendered {errors} error chip(s): {text[:160]!r}")

            # A dash where a value belongs usually means a field name that does
            # not exist in the payload. Counted on table cells whose whole
            # content is the placeholder, not on the rendered text: an em-dash
            # is also ordinary punctuation, and counting those made a view fail
            # for the prose in its own captions.
            dashes = page.eval_on_selector_all(
                f"#{container} td",
                "els => els.filter(e => e.textContent.trim() === '\\u2014').length",
            )
            if dashes > 40:
                failures.add(name, f"{dashes} placeholder cells — likely missing fields")

            if shots:
                page.screenshot(path=str(shots / f"{tab}.png"), full_page=True)
            print(f"  ok   {name:<20} {len(text):>6} chars")

        # The two in-view selects re-enter the render path with a different key.
        page.click("#tab-spatial")
        page.wait_for_selector("#spatial-select")
        options = page.eval_on_selector_all(
            "#spatial-select option", "els => els.map(e => e.value)"
        )
        for value in options:
            page.select_option("#spatial-select", value)
            page.wait_for_function(
                "() => { const n = document.getElementById('spatial-content');"
                " return n && !n.classList.contains('loading'); }",
                timeout=20000,
            )
            text = page.locator("#spatial-content").inner_text()
            if len(text.strip()) < MIN_CONTENT_CHARS:
                failures.add(f"spatial/{value}", "drew nothing substantive")
            else:
                print(f"  ok   spatial {value:<12} {len(text):>6} chars")

        page.click("#tab-crew")
        page.wait_for_selector("#crew-select")
        people = page.eval_on_selector_all(
            "#crew-select option", "els => els.map(e => e.value)"
        )
        for value in people[:6]:
            page.select_option("#crew-select", value)
            page.wait_for_timeout(250)
            text = page.locator("#crew-content").inner_text()
            if len(text.strip()) < MIN_CONTENT_CHARS:
                failures.add(f"crew/{value}", "drew nothing substantive")
            else:
                print(f"  ok   crew {value:<15} {len(text):>6} chars")

        # Keyboard navigation: the APG tab pattern is a behavioural claim.
        page.click("#tab-board")
        page.focus("#tab-board")
        page.keyboard.press("ArrowRight")
        page.wait_for_timeout(200)
        focused = page.evaluate("() => document.activeElement.id")
        if focused != "tab-intake":
            failures.add("keyboard", f"ArrowRight from tab-board focused {focused!r}")
        page.keyboard.press("End")
        page.wait_for_timeout(200)
        focused = page.evaluate("() => document.activeElement.id")
        if focused != "tab-streams":
            failures.add("keyboard", f"End focused {focused!r}, expected tab-streams")

        # Large-text control.
        page.click("#text-size")
        page.wait_for_timeout(150)
        if page.get_attribute("html", "data-textsize") != "large":
            failures.add("text-size", "did not set data-textsize=large")
        page.click("#text-size")

        # Run a different disruption end to end through the UI.
        page.click("#tab-board")
        second = page.eval_on_selector_all(
            "#scenario-select option", "els => els.map(e => e.value)"
        )[1]
        page.select_option("#scenario-select", second)
        page.click("#run-scenario")
        try:
            page.wait_for_function(
                "() => { const s = document.getElementById('live-status').textContent;"
                " return s.includes('feasible plan'); }",
                timeout=60000,
            )
            status = page.inner_text("#live-status")
            print(f"  ok   run disruption      {status.strip()[:80]}")
        except Exception:
            failures.add("run disruption",
                         f"status never reported a result: {page.inner_text('#live-status')!r}")

        page.wait_for_function(
            "() => { const n = document.getElementById('board-content');"
            " return n && !n.classList.contains('loading'); }",
            timeout=30000,
        )
        if len(page.locator("#board-content").inner_text().strip()) < MIN_CONTENT_CHARS:
            failures.add("board after re-run", "drew nothing substantive")

        if shots:
            page.screenshot(path=str(shots / "board-after-rerun.png"), full_page=True)

        # The second disruption stops at the same gate. It has to be signed off
        # too, or the guided demonstration below plays over a day that never ran.
        sign_off_at_the_gate(page, failures, shots=None)

        drive_demo(page, failures, shots)

        browser.close()

    for line in console:
        if line.startswith("[error]"):
            failures.add("console", line)

    print()
    if console:
        print(f"Console output ({len(console)}):")
        for line in console:
            print(f"  {line}")
        print()

    if failures:
        print(f"{len(failures.items)} failure(s):")
        for item in failures.items:
            print(f"  FAIL {item}")
        return 1

    print(f"{len(VIEWS)}/{len(VIEWS)} views rendered, no console errors, "
          f"no failed requests, no uncaught exceptions.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", help="an already-running server; otherwise one is started")
    parser.add_argument("--shots", type=Path, default=ROOT / "docs" / "screenshots",
                        help="directory for screenshots ('none' to skip)")
    parser.add_argument("--headed", action="store_true", help="show the browser")
    args = parser.parse_args()

    shots = None if str(args.shots).lower() == "none" else args.shots

    server = None
    url = args.url
    if not url:
        port = free_port()
        print(f"Starting server on port {port}…")
        server = start_server(port)
        url = f"http://127.0.0.1:{port}"

    print(f"Driving {url}\n")
    try:
        return run(url, shots, args.headed)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    raise SystemExit(main())
