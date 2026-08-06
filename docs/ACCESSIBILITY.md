# Accessibility conformance

**Target:** WCAG 2.2 Level AA
**Audit:** `tools/a11y_audit.py`, 62 automated checks, **62 passing**
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
`src/productionpulse/web/{index.html,styles.css,app.js}` and checks the success
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

## 3. What this audit cannot check

Taken directly from `not_covered` in the artifact:

- Anything requiring a rendered layout or computed style
- Screen-reader announcement order and quality
- Focus order under a real assistive technology
- Contrast of any colour set outside `styles.css`
- 1.4.10 Reflow verified visually at 320 CSS pixels

**A browser has never rendered this interface.** No session in this project has
had browser tooling available. All 15 API endpoints return 200 with substantive
payloads, the markup and stylesheet pass 62 static checks, and there is no
`innerHTML` — but nobody has watched it draw, tabbed through it, or put a screen
reader on it.

That is a gap, it is the first thing to close, and it is recorded here rather
than left for someone to discover.

---

## 4. Four real failures this audit found and fixed

Each was a genuine AA failure in code that looked fine.

1. **Focus indicator at 1.47:1.** A single orange ring measured against the
   *selected* tab's blue background rather than the page background. It is now
   two-tone, and both rings are checked in both themes.
2. **The audit's own false positive.** It failed on a comment in `app.js` that
   explains `innerHTML` is not used. It now strips comments before scanning —
   an audit that fails on a comment about the thing it is checking will be
   silenced rather than fixed.
3. **Control borders below 3:1** against their surrounding surface in the dark
   theme.
4. **No reflow breakpoint below 48rem**, so the plan comparison table forced
   horizontal scrolling on a narrow viewport.

---

## 5. Manual checklist, for whoever opens it first

Run `uvicorn productionpulse.api:app --port 8765`, then:

- [ ] Walk all thirteen view tabs. Arrow keys should move between them; the
      tablist is `role="tab"` with `aria-selected`.
- [ ] The impact map at ~110 nodes: is it legible, and is the depth ranking
      visible? Recall is complete but the map is broad by nature — depth is the
      signal that makes it usable, so check that it reads as ranked.
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
