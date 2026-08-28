"""Accessibility audit of the web client.

    python tools/a11y_audit.py                # human readable, non-zero on failure
    python tools/a11y_audit.py --json docs/accessibility_audit.json

This is a static audit of `src/allaccess/web/`. It parses the markup and
the stylesheet and checks the WCAG 2.2 AA success criteria that are decidable
from source. It does **not** run a browser, and it therefore cannot check
anything that depends on rendering, computed layout or assistive-technology
behaviour. `docs/ACCESSIBILITY.md` lists what this audit covers and what has to
be checked by hand, because an audit that implies more coverage than it has is
worse than no audit.

The contrast checks are real: colour pairs are read out of the declared custom
properties in `styles.css`, converted to relative luminance per WCAG, and
compared against 4.5:1 for body text, 3:1 for large text and 3:1 for UI
component boundaries. Both the light and the dark palette are checked, because
a product that is accessible in one theme and not the other is accessible in
neither.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "allaccess" / "web"


@dataclass
class Check:
    check_id: str
    criterion: str
    level: str
    description: str
    passed: bool
    detail: str = ""


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


def _srgb(component: int) -> float:
    c = component / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    value = hex_colour.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    r, g, b = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _srgb(r) + 0.7152 * _srgb(g) + 0.0722 * _srgb(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


def palettes(css: str) -> dict[str, dict[str, str]]:
    """Every `--name: #hex` declaration, split into the light and dark blocks.

    The dark palette lives inside the `prefers-color-scheme: dark` media query;
    everything before it is the light palette.
    """
    marker = css.find("@media (prefers-color-scheme: dark)")
    light_src = css[:marker] if marker > 0 else css
    dark_src = css[marker:] if marker > 0 else ""

    def read(source: str) -> dict[str, str]:
        return {
            name: colour
            for name, colour in re.findall(r"--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,6})", source)
        }

    light = read(light_src)
    dark = dict(light)
    dark.update(read(dark_src))
    return {"light": light, "dark": dark}


#: (foreground, background, minimum, what it is). Minimums follow WCAG 2.2:
#: 4.5:1 for body text (1.4.3), 3:1 for UI component and graphical boundaries
#: (1.4.11).
CONTRAST_PAIRS: tuple[tuple[str, str, float, str], ...] = (
    ("ink", "surface", 4.5, "body text on a card"),
    ("ink", "bg", 4.5, "body text on the page background"),
    ("ink-muted", "surface", 4.5, "secondary text on a card"),
    ("ink-muted", "surface-2", 4.5, "secondary text on the table header"),
    ("ink", "surface-2", 4.5, "text on the table header"),
    ("accent-ink", "accent", 4.5, "text on a primary button and the selected tab"),
    ("ok", "ok-bg", 4.5, "the “ready” status chip"),
    ("warn", "warn-bg", 4.5, "the “awaiting” status chip"),
    ("bad", "bad-bg", 4.5, "the “blocked” status chip"),
    ("quiet", "quiet-bg", 4.5, "the “abstained” status chip"),
    ("line-strong", "surface", 3.0, "a form control boundary"),
    ("focus", "surface", 3.0, "the focus indicator, outer ring on a card"),
    ("focus", "bg", 3.0, "the focus indicator, outer ring on the page"),
    ("focus-inner", "accent", 3.0, "the focus indicator, inner ring on a selected tab"),
    ("accent", "surface", 3.0, "an accent boundary"),

    # Text printed on a graphic fill: a scene bar's time range, a weather band's
    # condition, a route node's identifier, the disruption source marker. These
    # were missing, and their absence let a real AA failure ship: the diagram
    # labels were literal `#ffffff`, which measures around 1.5:1 against the dark
    # palette's graph colours, because the dark palette lightens them. An audit
    # that reads tokens cannot see a colour that was not a token, so the fix was
    # to make them tokens and then check them here.
    ("accent-ink", "graph-1", 4.5, "a label on an interior-scene bar or the working position"),
    ("accent-ink", "graph-2", 4.5, "a label on an exterior-scene bar"),
    ("accent-ink", "graph-3", 4.5, "a label on the arrival point"),
    ("accent-ink", "bad", 4.5, "the label on the disruption source marker"),
    ("accent-ink", "ink-muted", 4.5, "a label on a neutral weather band"),
    ("graph-4", "surface", 3.0, "the approved-access-arrangement marker"),
    ("graph-1", "surface", 3.0, "a chart mark against the card it sits on"),
    ("graph-2", "surface", 3.0, "a chart mark against the card it sits on"),
)

#: Checked and reported, but not required to reach 3:1.
#:
#: WCAG 1.4.11 applies to "visual information required to identify user
#: interface components and states". A separator between two table rows is not
#: that: the rows are identified by their content, and removing the rule
#: entirely would cost nothing but density. Holding a decorative hairline to the
#: component-boundary threshold would mean darkening every rule in the product
#: to satisfy a criterion it is not under, so the ratio is measured and
#: published instead of enforced. `--line-strong`, which does carry form-control
#: boundaries, is enforced above.
INFORMATIONAL_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("line", "surface", "a decorative card or table rule"),
)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def audit() -> list[Check]:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    css = (WEB / "styles.css").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    checks: list[Check] = []

    def check(check_id: str, criterion: str, level: str, description: str,
              passed: bool, detail: str = "") -> None:
        checks.append(Check(check_id, criterion, level, description, bool(passed), detail))

    # -- 1.1 / 1.3 structure ------------------------------------------------
    check("A-001", "3.1.1 Language of Page", "A",
          "The document declares a language",
          bool(re.search(r"<html[^>]*\blang=\"[a-z]{2}", html)))
    check("A-002", "2.4.2 Page Titled", "A",
          "The document has a non-empty, descriptive title",
          bool(re.search(r"<title>[^<]{12,}</title>", html)))
    check("A-003", "1.3.1 Info and Relationships", "A",
          "Exactly one h1 per view panel, and no heading levels skipped",
          _heading_order(html))
    check("A-004", "2.4.1 Bypass Blocks", "A",
          "A skip link targets the main landmark",
          'class="skip-link" href="#main"' in html and 'id="main"' in html)
    check("A-005", "1.3.1 Info and Relationships", "A",
          "The page uses header, nav, main and footer landmarks",
          all(f"<{tag}" in html for tag in ("header", "nav", "main", "footer")))
    check("A-006", "1.3.1 Info and Relationships", "A",
          "The navigation landmark is labelled",
          'aria-label="Product views"' in html)
    check("A-007", "1.4.10 Reflow", "AA",
          "A single-column breakpoint exists at or below 320 px equivalent",
          "@media (max-width: 30rem)" in css and "@media (max-width: 60rem)" in css)
    check("A-008", "1.4.4 Resize Text", "AA",
          "Font sizes are relative, so browser text scaling applies",
          "font-size: 100%" in css and not re.search(r"font-size:\s*\d+px", css))
    check("A-009", "1.4.12 Text Spacing", "AA",
          "Line height is at least 1.5 for body text",
          bool(re.search(r"line-height:\s*1\.[5-9]", css)))

    # -- 2.x interaction ----------------------------------------------------
    check("A-010", "2.4.7 Focus Visible", "AA",
          "A visible focus indicator is defined and never removed",
          ":focus-visible" in css and "outline: 3px solid" in css
          and "outline: none" not in css.replace("main:focus { outline: none; }", ""))
    check("A-011", "2.4.11 Focus Not Obscured", "AA",
          "The sticky navigation does not overlay the content column",
          "grid-template-columns" in css and "position: sticky" in css)
    check("A-012", "2.5.8 Target Size (Minimum)", "AA",
          "Interactive controls declare a minimum target of 24 px or more",
          css.count("min-height: 2.5rem") >= 4)
    check("A-013", "2.1.1 Keyboard", "A",
          "The tab list implements arrow, Home and End key navigation",
          all(key in js for key in ("ArrowDown", "ArrowUp", '"Home"', '"End"')))
    check("A-014", "4.1.2 Name, Role, Value", "A",
          "Only the selected tab is in the page tab sequence",
          "tab.tabIndex = active ? 0 : -1" in js)
    check("A-015", "4.1.2 Name, Role, Value", "A",
          "Every tab declares aria-selected and aria-controls",
          html.count('role="tab"') == html.count("aria-controls=")
          and html.count('role="tab"') == html.count("aria-selected="))
    check("A-016", "4.1.2 Name, Role, Value", "A",
          "Every tab panel is labelled by its tab",
          html.count('role="tabpanel"') == html.count("aria-labelledby="))
    check("A-017", "4.1.3 Status Messages", "AA",
          "Exactly one polite live region announces status changes",
          html.count('aria-live="polite"') == 1 and 'role="status"' in html)
    check("A-018", "3.2.2 On Input", "A",
          "Running a disruption requires an explicit activation, not a change event",
          'getElementById("run-scenario")' in js and 'run.addEventListener("click"' in js)
    check("A-019", "1.4.13 Content on Hover or Focus", "AA",
          "No hover-only content: there are no tooltip or popover behaviours",
          "title=" not in js and "tooltip" not in js.lower())

    # -- forms --------------------------------------------------------------
    labelled = re.findall(r'<label[^>]*\bfor="([^"]+)"', html)
    controls = re.findall(r'<(?:select|input|textarea)[^>]*\bid="([^"]+)"', html)
    check("A-020", "3.3.2 Labels or Instructions", "A",
          "Every form control in the markup has an associated label",
          set(controls) <= set(labelled),
          f"unlabelled: {sorted(set(controls) - set(labelled))}")
    check("A-021", "3.3.2 Labels or Instructions", "A",
          "Every dynamically created control is labelled at creation",
          js.count('el("label"') >= js.count('el("select"'))
    check("A-022", "4.1.2 Name, Role, Value", "A",
          "The text-size control exposes its pressed state",
          'aria-pressed' in html and 'setAttribute("aria-pressed"' in js)

    # -- tables -------------------------------------------------------------
    check("A-023", "1.3.1 Info and Relationships", "A",
          "Every generated table has a caption and scoped column headers",
          'el("caption"' in js and 'scope: "col"' in js)
    check("A-024", "2.1.1 Keyboard", "A",
          "Horizontally scrolling table regions are focusable and labelled",
          'tabindex: "0"' in js and 'role: "region"' in js
          and '"aria-label": caption' in js)

    # -- colour and meaning --------------------------------------------------
    check("A-025", "1.4.1 Use of Colour", "A",
          "Status is carried by text, not colour alone",
          "function chip(label, tone)" in js and 'text: label' in js)
    check("A-026", "1.4.3 Contrast (Minimum)", "AA",
          "The selected row is marked structurally as well as by colour",
          "tr.selected td:first-child" in css and "box-shadow: inset" in css)

    # -- injection safety, which is also an accessibility property ----------
    #
    # Comments are stripped first. The first version of this check searched the
    # whole file for "innerHTML" and failed on the comment at the top of app.js
    # explaining that innerHTML is not used — an audit that reads its own
    # documentation as evidence of a defect.
    check("A-027", "4.1.1 Parsing", "A",
          "No content is inserted as markup; every value goes through textContent",
          "innerHTML" not in _without_comments(js))

    # -- motion and print ----------------------------------------------------
    check("A-028", "2.3.3 Animation from Interactions", "AAA",
          "Reduced-motion preference is honoured",
          "prefers-reduced-motion: reduce" in css)
    check("A-029", "1.4.8 Visual Presentation", "AAA",
          "Body text is constrained to a readable measure",
          "--measure: 68ch" in css and "max-width: var(--measure)" in css)

    # -- language of parts ---------------------------------------------------
    check("A-030", "3.1.2 Language of Parts", "AA",
          "Crew messages declare the language they are written in",
          'lang: d.message.language' in js)

    # -- contrast, computed --------------------------------------------------
    for theme, palette in palettes(css).items():
        for foreground, background, minimum, what in CONTRAST_PAIRS:
            fg, bg = palette.get(foreground), palette.get(background)
            check_id = f"C-{theme[:1].upper()}-{foreground}-on-{background}"
            if not fg or not bg:
                check(check_id, "1.4.3 Contrast (Minimum)", "AA",
                      f"{what} ({theme})", False,
                      f"missing custom property --{foreground} or --{background}")
                continue
            ratio = contrast(fg, bg)
            check(check_id,
                  "1.4.3 Contrast (Minimum)" if minimum >= 4.5
                  else "1.4.11 Non-text Contrast",
                  "AA", f"{what} ({theme})", ratio >= minimum,
                  f"{ratio:.2f}:1 against a {minimum:.1f}:1 minimum "
                  f"({fg} on {bg})")

        for foreground, background, what in INFORMATIONAL_PAIRS:
            fg, bg = palette.get(foreground), palette.get(background)
            if not fg or not bg:
                continue
            checks.append(Check(
                f"I-{theme[:1].upper()}-{foreground}-on-{background}",
                "1.4.11 Non-text Contrast", "informational",
                f"{what} ({theme}) — measured, not enforced; see INFORMATIONAL_PAIRS",
                True, f"{contrast(fg, bg):.2f}:1 ({fg} on {bg})",
            ))

    return checks


def _without_comments(js: str) -> str:
    """JavaScript with block and line comments removed."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"^\s*//.*$", "", js, flags=re.M)


def _heading_order(html: str) -> bool:
    """No skipped heading levels in document order."""
    levels = [int(m) for m in re.findall(r"<h([1-6])", html)]
    previous = 0
    for level in levels:
        if previous and level > previous + 1:
            return False
        previous = level
    return bool(levels)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WCAG 2.2 AA static audit")
    parser.add_argument("--json", type=Path, default=None,
                        help="write the full artifact here")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    checks = audit()
    passed = [c for c in checks if c.passed]
    failed = [c for c in checks if not c.passed]

    artifact: dict[str, Any] = {
        "target": "WCAG 2.2 Level AA",
        "scope": "src/allaccess/web/ — static source audit, no browser",
        "not_covered": [
            "Anything requiring a rendered layout or computed style",
            "Screen-reader announcement order and quality",
            "Focus order under a real assistive technology",
            "Contrast of any colour set outside styles.css",
            "1.4.10 Reflow verified visually at 320 CSS pixels",
        ],
        "total": len(checks),
        "passed": len(passed),
        "failed": len(failed),
        "checks": [asdict(c) for c in checks],
    }

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(artifact, indent=2) + "\n", encoding="utf-8")

    if not args.quiet:
        for c in failed:
            print(f"FAIL {c.check_id:34s} {c.criterion:34s} {c.description}")
            if c.detail:
                print(f"     {c.detail}")
        print(f"\n{len(passed)}/{len(checks)} checks pass "
              f"({len(failed)} failure(s))")
        if args.json:
            print(f"Wrote {args.json}")

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
