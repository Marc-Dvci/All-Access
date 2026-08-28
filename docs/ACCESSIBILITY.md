# Accessibility conformance

**Target:** WCAG 2.2 Level AA
**Audit:** `tools/a11y_audit.py`, 78 automated checks, **78 passing**
**Artifact:** `docs/accessibility_audit.json`, regenerated and diffed in CI

```bash
python tools/a11y_audit.py                                # human readable
python tools/a11y_audit.py --json docs/accessibility_audit.json
```

---

## 1. Why this document is unusually blunt about its limits

This product schedules around other people's access requirements. A product that
did that through an interface its own users could not operate would be making an
argument it does not believe. So the interface is audited — and the audit's
coverage is stated precisely, because an accessibility report that implies more
coverage than it has is worse than no report. It gives a team permission to stop
looking.

---

## 2. What is checked, and how

`tools/a11y_audit.py` is a **static source audit**. It parses
`src/allaccess/web/{index.html,styles.css,app.js}` and checks the success
criteria that are decidable from source.

| Criterion | Checks | What is verified |
|---|---|---|
| 1.4.3 Contrast (Minimum) | 21 | Every declared colour pair, in both themes |
| 1.4.11 Non-text Contrast | 12 | Control boundaries and focus indicators, both themes |
| 1.3.1 Info and Relationships | 4 | Headings, landmarks, table headers, form labels |
| 4.1.2 Name, Role, Value | 4 | Interactive elements have accessible names and roles |
| 2.1.1 Keyboard | 2 | No interaction is pointer-only |
| 3.3.2 Labels or Instructions | 2 | Inputs are labelled |
| 1.4.10 Reflow, 1.4.4 Resize | 2 | A breakpoint below 48rem exists; text scales |
| 2.4.1/2/7/11 | 4 | Skip link, page title, visible focus, focus not obscured |
| 1.4.1, 1.4.12, 1.4.13 | 3 | Colour is not the only signal; spacing overridable; hover content dismissible |
| 2.5.8 Target Size | 1 | Minimum 24×24 CSS px |
| 3.1.1 Language, 3.2.2 On Input | 2 | Declared language; no change of context on input |
| 4.1.1, 4.1.3 | 2 | Parsing; status messages announced via live regions |

**The contrast checks are real measurements.** Colour pairs are read out of the
declared custom properties in `styles.css`, converted to relative luminance per
the WCAG formula, and compared against 4.5:1 for body text, 3:1 for large text
and 3:1 for UI component boundaries. Both palettes are checked, because a product
that is accessible in one theme and not the other is accessible in neither.

There is **no `innerHTML` anywhere in `app.js`**. Every node is built with
`document.createElement` and `textContent`. That is an injection control first,
but it also means no view can accidentally emit markup that bypasses the
structure the audit checks.

---

## 3. Behaviour, checked in a real browser

Markup conformance is necessary and it is not sufficient. `tools/ui_smoke.py`
drives all thirteen views in Chromium on every CI run and holds them to the
behaviour the markup promises:

| Checked | How |
|---|---|
| Every view renders substantive content | Each panel must replace its placeholder within 20 s |
| Nothing fails silently | Any console error, uncaught exception or failed request fails the run |
| The APG tab pattern behaves | `ArrowRight`, `ArrowLeft` and `End` are driven and the resulting focus asserted |
| Re-entry paths work | Both in-view selects and a full disruption re-run are exercised |
| Text scaling engages | The large-text control is toggled and `data-textsize` asserted |
| The guided demonstration is whole | Every beat must reach its view and draw its narration caption |

This catches the class of defect that markup conformance cannot. **The outcome
of "Run disruption" used to be announced into the live region and then
overwritten by "Control board loaded" inside the same second**, because reloading
the view announced itself last — so a screen-reader user heard that a view had
loaded and never heard how many plans were feasible. The markup was correct
throughout: one polite live region, properly configured, which is all markup can
tell you. A pending notice now outranks the view-loaded message, and the
behaviour is asserted rather than assumed.

Screenshots of every view are written on each run to `docs/screenshots/`.

### The diagrams

Four views draw an inline SVG: the schedule strip on the control board, the
blast radius on the impact map, the surveyed route on the spatial survey, and
the objective bars on the plan cards. Three rules govern all of them.

**No number appears only in a picture.** Every diagram sits above the table that
holds the same payload — the scene table, the consequence bands, the edge
survey, the objectives table. Nobody is sent to an image to read a measurement,
which is the failure mode of a dashboard that has been made pretty.

**Each carries a name and a description.** `role="img"` with an `aria-label`
that states what the drawing shows and how many things are in it, and a `<desc>`
that states the finding in words — "no step-free route exists from the arrival
point to the working position; failing segments are drawn in red with the
measurement that failed".

**Colour is never the carrier.** A failing route segment is red *and* dashed
*and* thicker *and* labelled with the measurement. A band in the blast radius is
a colour *and* a marker size, and the band names and counts are in the panel
above it. The graphic tokens are held to the 3:1 non-text boundary rather than
the 4.5:1 text minimum, which is the criterion that actually applies to them,
and both themes are computed by the audit.

---

## 4. Five real failures this audit found and fixed

Each was a genuine AA failure in code that looked fine.

1. **Diagram labels at 1.73:1 in the dark theme, and the audit could not see
   them.** The route nodes, the schedule bars and the disruption marker printed
   their text as a literal `#ffffff`. The light palette's graphic fills are dark,
   so it looked right; the dark palette lightens them, and white on `#9cc9f0`
   measures 1.75:1, on `#ecbe6d` 1.73:1, on `#f2909a` 2.27:1. The audit reads
   custom properties, and a colour written as a literal is not one — **it was
   blind to the whole class**. The literals became `var(--accent-ink)`, and the
   text-on-graphic-fill pairs are now in `CONTRAST_PAIRS`, which took the audit
   from 62 checks to 78. Confirmed by putting the old value back and watching
   six checks go red.

2. **Focus indicator at 1.47:1.** A single orange ring measured against the
   *selected* tab's blue background rather than the page background. It is now
   two-tone, and both rings are checked in both themes.
3. **The audit's own false positive.** It failed on a comment in `app.js` that
   explains `innerHTML` is not used. It now strips comments before scanning —
   an audit that fails on a comment about the thing it is checking will be
   silenced rather than fixed.
4. **Control borders below 3:1** against their surrounding surface in the dark
   theme.
5. **No reflow breakpoint below 48rem**, so the plan comparison table forced
   horizontal scrolling on a narrow viewport.

---

## 5. Manual verification pass

The automated render covers behaviour a machine can assert. This is the pass a
person runs against a build before it ships. Run
`uvicorn allaccess.api:app --port 8765`, then:

- [ ] Walk all thirteen view tabs. Arrow keys should move between them; the
      tablist is `role="tab"` with `aria-selected`.
- [ ] The impact map: the "What to act on" panel names the scenes, departments
      and access arrangements, and the three consequence bands sit collapsed
      beneath it. Confirm the ranking reads clearly enough that the panel is
      obviously where to start and the bands are obviously the evidence.
- [ ] Each of the four diagrams, with images disabled and then with a screen
      reader: is the finding still available in words, and is the table under it
      reachable?
- [ ] Start the guided demonstration and press Escape mid-beat. Focus must stay
      where it was and every control must still work.
- [ ] The plan comparison table below 48rem — does it reflow rather than scroll
      the page horizontally?
- [ ] Tab order through the approval workspace: does focus reach the conflict
      set before the approve control?
- [ ] Zoom to 200% and to 400%; check nothing is clipped.
- [ ] One screen-reader pass (NVDA or VoiceOver) over the control board and the
      plan comparison. Are status changes announced once, not repeatedly?
- [ ] Windows High Contrast Mode.

---

## 6. Accessibility in the product, not just the interface

Worth separating, because they are different claims.

The interface conformance above is one thing. The other is that **approved access
arrangements are hard constraints in the solver**: `C-ACC-001` through
`C-ACC-006` carry `ConstraintKind.HARD` and no soft weight, so the objective
function cannot trade a step-free route against a saved hour. They are the
constraints a rushed plan drops first, and this system fails closed instead —
31.4% of disruptions in the benchmark end with no feasible plan and a named
minimal conflict set, and access constraints are a common member of those sets.

Access preservation across approved plans is **1.000**. With the independent
feasibility recheck removed it falls to **0.780**. That difference is the
measured value of checking.

See `BENCHMARK.md` §4 and §5.
