# All-Access — automated three-minute demo

A deterministic, narrated walkthrough of the real product. Playwright drives the
product's own guided demonstration (the same code a visitor runs at `/?demo=1`)
against a running server; the product renders every caption, cursor move,
spotlight and diagram itself. Nothing on the product screen is mocked or added
in post — the storm, the impact traversal, the refusal with its named conflict
set, the survey measurement, the three plans, the signed approval and the
verification that will not call the day ready are all produced by the same API a
person drives.

## Build

Requires `edge-tts`, `playwright` (with a Chromium browser), and `ffmpeg` /
`ffprobe` on `PATH`.

```bash
python demo_video/narrate.py     # 1. voice-over + timing.json  (needs network for Edge TTS)
python demo_video/record.py      # 2. record + mux  ->  all-access-demo.mp4
```

`record.py` starts a local server by default. To record another deployment:

```bash
python demo_video/record.py https://<cloud-run-url>/
```

Output: `all-access-demo.mp4`, 1920×1080, H.264/AAC, **2:54** — safely under the
3:00 judging limit.

## Why every take is identical

- The narration is one clock. `narrate.py` speaks each beat's caption with Edge
  TTS (`en-US-AndrewMultilingualNeural`, +9% — natural pace), measures each
  clip, and writes `timing.json`. `record.py` injects those per-beat durations as
  `window.__AA_TIMING`, so the visuals pace themselves to the voice and both
  share one timeline.
- The product's demonstration is deterministic: it resets the server to the hero
  scenario before the first frame, has no random anywhere, and holds the
  remainder of each beat after its actions complete, so a fast machine and a slow
  one draw the same frames.
- The opening states the product, the value and the differentiator inside 13
  seconds, before the example begins.
- The captions the product burns in are word-for-word the narration, so the
  video ships with English subtitles with no edit pass. `demo_subtitles.srt` is
  written from the same timing for upload alongside the video.

## Truthfulness

The narration claims only what the product proves. Every number spoken —
`0.000`, `1.000`, `75/75`, `2.412` — is read from `bench/results/` and
reproduced by `python -m bench.run_benchmark`. The recording shows the product in
its offline reasoning mode (no credentials required); the runtime boundary
between the deterministic engine and the Gemini reasoning plane is unchanged.
