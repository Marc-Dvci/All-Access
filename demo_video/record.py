"""Record the deterministic All-Access walkthrough as an MP4.

Playwright drives the product's own guided demonstration (the same code a visitor
runs at ``/?demo=1``) against a real server, paced to the narration produced by
``narrate.py`` via ``window.__AA_TIMING``. The product renders every caption,
cursor move, spotlight and diagram itself — nothing on screen is added in post.
The narration is muxed on and the result is faded and encoded to H.264/AAC.

    python demo_video/narrate.py     # first: voice + timing.json
    python demo_video/record.py      # then: this, against a local server
    python demo_video/record.py https://<cloud-run-url>/   # or a deployment
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
import time

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
from ui_smoke import free_port, start_server  # noqa: E402

VIEWPORT = (1600, 900)
TAIL_SECONDS = 2.2
# The public deployment is the canonical target. Pass "local" to spin up a
# throwaway server, or pass any other URL to record that instead.
DEFAULT_URL = "https://all-access-1022938933263.europe-west1.run.app/"
URL_ARG = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL


def probe_duration(path: pathlib.Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def run_media(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        diagnostic = result.stderr[-6000:] if result.stderr else "no FFmpeg diagnostic"
        raise RuntimeError(f"Media command failed ({result.returncode}):\n{diagnostic}")


def record_browser(url: str, durations: list[int], total: float) -> tuple[pathlib.Path, float]:
    raw_dir = HERE / "_raw"
    raw_dir.mkdir(exist_ok=True)
    span = total + TAIL_SECONDS
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--autoplay-policy=no-user-gesture-required", "--force-color-profile=srgb"],
        )
        context = browser.new_context(
            viewport={"width": VIEWPORT[0], "height": VIEWPORT[1]},
            device_scale_factor=1,
            record_video_dir=str(raw_dir),
            record_video_size={"width": VIEWPORT[0], "height": VIEWPORT[1]},
        )
        page = context.new_page()
        page.set_default_timeout(30_000)
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("() => window.AllAccessDemo && window.AllAccessDemo.beats")

        beats = page.evaluate("() => window.AllAccessDemo.beats")
        if beats != len(durations):
            raise RuntimeError(f"timing has {len(durations)} beats, product plays {beats}")

        # Inject the narration-derived pacing, then drive the product's own demo.
        # Fire-and-forget: start() returns a promise that resolves only when the
        # whole demo ends, and page.evaluate awaits returned promises — returning
        # nothing keeps the timed window over the playback, not the end screen.
        page.evaluate("timing => { window.__AA_TIMING = timing; }", durations)
        started = time.monotonic()
        page.evaluate("() => { window.AllAccessDemo.start(0); }")
        print(f"Recording {span:.1f}s from {url}")
        page.wait_for_timeout(int(span * 1000))
        elapsed = time.monotonic() - started
        print(f"Demo ran {elapsed:.1f}s")
        video = page.video
        context.close()
        raw_path = pathlib.Path(video.path())
        browser.close()
    return raw_path, span


def mux(raw_path: pathlib.Path, span: float) -> pathlib.Path:
    narration = HERE / "narration.wav"
    if not narration.exists():
        raise FileNotFoundError("narration.wav is missing; run narrate.py first")
    padded = HERE / "_narration_padded.wav"
    run_media([
        "ffmpeg", "-y", "-i", str(narration),
        "-af", f"apad=pad_dur={TAIL_SECONDS}", "-t", f"{span:.3f}",
        "-c:a", "pcm_s24le", str(padded),
    ])
    output = HERE / "all-access-demo.mp4"
    # Playwright's WebM clock starts at the first painted frame, not our timer;
    # anchor to the known end (the browser closes right after the fixed tail).
    trim_start = max(0.0, probe_duration(raw_path) - span)
    fade_start = span - 1.0
    run_media([
        "ffmpeg", "-y",
        "-ss", f"{trim_start:.3f}", "-i", str(raw_path),
        "-i", str(padded),
        "-map", "0:v:0", "-map", "1:a:0", "-t", f"{span:.3f}",
        "-vf", (
            f"scale=1920:1080:flags=lanczos,fade=t=in:st=0:d=0.45,"
            f"fade=t=out:st={fade_start:.2f}:d=1,format=yuv420p"
        ),
        "-af", f"afade=t=out:st={fade_start:.2f}:d=1",
        "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-r", "30",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-movflags", "+faststart", str(output),
    ])
    return output


def main() -> None:
    timing = json.loads((HERE / "timing.json").read_text(encoding="utf-8"))
    durations = timing["durations_ms"]
    total = float(timing["total"])

    proc = None
    url = URL_ARG
    if url == "local":
        port = free_port()
        proc = start_server(port)
        url = f"http://127.0.0.1:{port}/"
    try:
        raw, span = record_browser(url, durations, total)
    finally:
        if proc is not None:
            proc.terminate()
    print(f"Raw capture: {raw}")
    final = mux(raw, span)
    print(
        f"Final: {final} — {probe_duration(final):.2f}s — "
        f"{final.stat().st_size / 1_000_000:.1f} MB"
    )


if __name__ == "__main__":
    main()
