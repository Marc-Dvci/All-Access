"""Generate the narration track and per-beat timing for the All-Access demo.

The product ships a self-driving demonstration (``window.AllAccessDemo``) that
plays 22 beats against the real API. This script speaks each beat's caption with
Edge TTS and produces two artifacts:

  * ``narration.wav`` — one 48 kHz master, each beat's speech placed at its cue.
  * ``timing.json``   — per-beat target durations. ``record.py`` injects these as
    ``window.__AA_TIMING`` so the visuals pace themselves to the voice, and both
    share one clock.

The captions the product burns in are word-for-word the same text, so the
recording ships with English subtitles with no edit pass. Run ``record.py``
after this.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import subprocess
import sys

import edge_tts
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "tools"))
from ui_smoke import free_port, start_server  # noqa: E402

VOICE = "en-US-AndrewMultilingualNeural"
RATE = "+9%"
LEAD_SILENCE = 0.5          # silence before the first word
GAP_SECONDS = 0.35          # trailing silence after a spoken beat
SILENT_SECONDS = 3.0       # a beat with no narration (a wordless transition)
HARD_LIMIT_SECONDS = 178.0
OPENING_LIMIT_SECONDS = 15.5
SPEECH_DIR = HERE / "speech"


def probe_duration(path: pathlib.Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nk=1:nw=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


async def render_clip(text: str, out: pathlib.Path) -> tuple[float, list[dict]]:
    audio = bytearray()
    boundaries: list[dict] = []
    async for chunk in edge_tts.Communicate(text, VOICE, rate=RATE).stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] in {"WordBoundary", "SentenceBoundary"}:
            boundaries.append({
                "t": round(chunk["offset"] / 10_000_000, 3),
                "d": round(chunk["duration"] / 10_000_000, 3),
                "text": chunk["text"],
            })
    out.write_bytes(audio)
    duration = probe_duration(out)
    if boundaries:
        duration = max(duration, boundaries[-1]["t"] + boundaries[-1]["d"])
    return duration, boundaries


def read_beats() -> list[dict]:
    """Read the beats the product actually plays, from a real page."""
    port = free_port()
    proc = start_server(port)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
            page.wait_for_function("() => window.AllAccessDemo && window.AllAccessDemo.script")
            script = page.evaluate("() => window.AllAccessDemo.script")
            browser.close()
        return script
    finally:
        proc.terminate()


def assemble_master(clips: list[tuple[float, pathlib.Path]], total: float) -> None:
    """Mix every spoken clip onto one bed at its cue, then master to 48 kHz."""
    inputs: list[str] = []
    parts: list[str] = []
    labels: list[str] = []
    for index, (offset, clip) in enumerate(clips):
        inputs += ["-i", str(clip)]
        delay = int(round(offset * 1000))
        parts.append(f"[{index}]adelay={delay}|{delay}[a{index}]")
        labels.append(f"[a{index}]")
    mix = "".join(labels) + f"amix=inputs={len(clips)}:normalize=0[raw]"
    master = (
        "[raw]highpass=f=80,"
        "equalizer=f=3200:t=q:w=1.0:g=3.0,"
        "equalizer=f=7200:t=q:w=1.0:g=1.8,"
        "acompressor=threshold=0.125:ratio=2:attack=8:release=100:makeup=1.35,"
        "loudnorm=I=-16:TP=-1.5:LRA=7,"
        f"apad,atrim=0:{total:.3f},aresample=48000[out]"
    )
    graph = ";".join(parts + [mix, master])
    subprocess.run(
        ["ffmpeg", "-y", *inputs, "-filter_complex", graph,
         "-map", "[out]", "-c:a", "pcm_s24le", str(HERE / "narration.wav")],
        capture_output=True, text=True, check=True,
    )


def write_srt(timeline: list[dict]) -> None:
    def stamp(seconds: float) -> str:
        ms = int(round(seconds * 1000))
        h, ms = divmod(ms, 3_600_000)
        m, ms = divmod(ms, 60_000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines: list[str] = []
    index = 1
    for beat in timeline:
        if not beat["say"]:
            continue
        start = beat["at"]
        end = beat["at"] + beat["dur"] - GAP_SECONDS / 2
        lines += [str(index), f"{stamp(start)} --> {stamp(end)}", beat["say"], ""]
        index += 1
    (HERE / "demo_subtitles.srt").write_text("\n".join(lines), encoding="utf-8")


async def main(beats: list[dict]) -> None:
    SPEECH_DIR.mkdir(exist_ok=True)
    durations: list[int] = []
    clips: list[tuple[float, pathlib.Path]] = []
    timeline: list[dict] = []
    offset = 0.0
    for i, beat in enumerate(beats):
        say = (beat.get("say") or "").strip()
        lead = LEAD_SILENCE if i == 0 else 0.0
        if say:
            clip = SPEECH_DIR / f"b{i:02d}.mp3"
            speech, _ = await render_clip(say, clip)
            beat_dur = lead + speech + GAP_SECONDS
            clips.append((offset + lead, clip))
        else:
            speech = 0.0
            beat_dur = lead + SILENT_SECONDS
        durations.append(int(round(beat_dur * 1000)))
        timeline.append({
            "i": i, "at": round(offset, 3), "chapter": beat.get("chapter", ""),
            "say": say, "dur": round(beat_dur, 3), "speech": round(speech, 3),
        })
        print(f"beat {i:02d}  {beat_dur:5.1f}s  {beat.get('chapter', ''):12}  {say[:44]}")
        offset += beat_dur

    total = round(offset, 3)
    if timeline[0]["dur"] > OPENING_LIMIT_SECONDS:
        raise SystemExit(
            f"Opening beat is {timeline[0]['dur']:.1f}s; keep it under "
            f"{OPENING_LIMIT_SECONDS:.0f}s so the value lands immediately."
        )
    if total > HARD_LIMIT_SECONDS:
        raise SystemExit(
            f"Narration totals {total:.1f}s; tighten the captions or raise RATE "
            f"to stay under {HARD_LIMIT_SECONDS:.0f}s (3-minute limit with margin)."
        )

    assemble_master(clips, total)
    write_srt(timeline)
    payload = {
        "total": total,
        "voice": VOICE,
        "rate": RATE,
        "beats": len(beats),
        "durations_ms": durations,
        "timeline": timeline,
    }
    (HERE / "timing.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"\nTotal narration: {int(total // 60)}:{total % 60:05.2f}  ({len(beats)} beats)")
    print(f"Master: {probe_duration(HERE / 'narration.wav'):.2f}s -> narration.wav")


if __name__ == "__main__":
    asyncio.run(main(read_beats()))
