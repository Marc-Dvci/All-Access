# Media rights and provenance

The competition rules forbid third-party content. This document accounts for
every piece of creative and production material in the repository.

---

## 1. The screenplay

***Salt and Light***, `src/productionpulse/production/script.py`. Written for
this project. 32 scenes across 3 story days, with sluglines, action, dialogue,
continuity notes, a prop breakdown and per-scene wardrobe and makeup states.

> On the last working weekend of a failing harbour, a deaf teenager and the
> grandfather who never learned to sign have to sell the boat that is the only
> language they still share.

**No adapted work. No licensed music. No real locations. No real people.**

The screenplay is not decoration and not filler. Scene metadata is the ground
truth the whole system runs on: `story_day` drives continuity constraints,
`exterior` and `weather_sensitivity` drive the weather and daylight constraints,
`characters` drives cast availability and the child-performer limits,
`page_eighths` drives the duration model, `props` drives the property and art
department dependencies, and `special_requirements` drives the marine safety,
confined space and access constraints. Change a scene and the solver sees a
different problem.

The deaf character and the sign-language content are not incidental either. They
are why `ACC-002` (interpretation covering every called minute) is a hard
constraint with two booked interpreters and a handover overlap, and the
interpreter booking window is the access conflict the hero scenario turns on.

## 2. The production world

`src/productionpulse/production/world.py`. Invented: 27 crew, 6 performers, 14
locations, 11 permits, 12 equipment packages, 5 vehicles, 5 support resources, 4
service bookings, 3 vendors, 6 approved access arrangements, and a baseline
schedule for shooting day 14.

Every person is fictional. Every rate, agreement, permit and policy is authored
for this demonstration and marked as such — `POLICIES` entries each carry a
`source` field that says `(fictional)` in the string.

**No real production's data has ever been in this system.** The privacy
mechanisms in `PRIVACY.md` are therefore demonstrated to fire, not demonstrated
to have protected anyone.

## 3. The spatial data

`src/productionpulse/production/spatial.py`. Authored access surveys: route
graphs, gradients, clear widths, threshold heights and egress routes for the
locations, in the form a real access survey produces.

The measurements are invented but the *thresholds* are not arbitrary — 1:15
gradient, 850 mm clear width, 20 mm threshold — they are the ordinary values such
a survey is assessed against, and they are declared as parameters on `C-ACC-001`
rather than buried in code.

## 4. The disruption corpus

`src/productionpulse/disruptions.py`. Eight templates expanded into a
reproducible 1,000-scenario corpus by seed. Authored; see `dataset_card.md`.

## 5. Software

| | |
|---|---|
| This repository | Apache-2.0, `LICENSE` at root |
| Dependencies | `sbom.json`, CycloneDX, 46 components, licences read from package metadata and never inferred |

`tools/generate_sbom.py --check` fails CI if the committed SBOM no longer matches
the installed environment. Where a package declares no licence it is recorded as
`unknown` rather than guessed at — a gap is actionable, a guess is not.

## 6. Interface assets

No images, icons, fonts or media files of any kind. The web client is HTML, CSS
and vanilla JavaScript with no external resources: no CDN, no web fonts, no
tracking. Every visual element is drawn from CSS or inline SVG written for this
project.

This is partly a rights decision and partly an accessibility one — see
`ACCESSIBILITY.md` — and partly a security one: there is no `innerHTML` anywhere
in `app.js`.

## 7. Model outputs

The default reasoning plane is offline and deterministic: templated narration
from structured facts, no model call. Every benchmark figure was produced in that
configuration, and `environment.reasoning_plane` in `bench/results/summary.json`
records it.

With `PP_REASONING_MODE=gemini`, Gemini on Vertex AI narrates findings the
deterministic layer has already decided. No model output is committed to this
repository, and no model output is on the feasibility path.

## 8. Attribution summary

Everything creative in this repository was authored for it. There is nothing here
to attribute to anyone else, and nothing that needs a licence beyond Apache-2.0
and the dependency licences in `sbom.json`.
