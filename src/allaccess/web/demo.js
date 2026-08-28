/* The guided demonstration.
 *
 * A three-minute walk through the product that runs itself. It is not a
 * recording and not a mock: it drives the same client a person drives, through
 * the same controls, against the same API, over a workflow run that starts when
 * the demonstration starts. If the solver changed its mind, this would show it.
 *
 * Why it exists. The alternative is a person clicking thirteen tabs live while
 * narrating, which is slower, different every take, and puts a fumbled click in
 * the middle of the one argument the video has to land. This plays the same way
 * every time, and the captions it burns in are the narration script, so the
 * recording ships with English subtitles without an edit pass.
 *
 * Determinism. Every beat has an explicit duration and the runner holds the
 * remainder after its actions complete, so the timeline does not drift with
 * machine speed; there is no random anywhere; and the run begins by putting the
 * server back on the hero scenario, so it does not matter what was clicked
 * before. `?speed=` divides every wait, which is how the browser smoke test
 * plays the whole thing in a few seconds.
 *
 *   http://127.0.0.1:8765/?demo=1            start on load
 *   http://127.0.0.1:8765/?demo=1&speed=12   the same beats, fast
 *   http://127.0.0.1:8765/?demo=1&from=8     start at beat 8
 *
 * Escape stops it and leaves the product exactly as it is. Nothing in this file
 * writes to the API except the one POST that starts the disruption — the same
 * one the "Run disruption" button sends.
 *
 * async/await here, rather than the promise chains app.js uses: this is a
 * sequence of thirty waits and the version without it is unreadable.
 */

(function () {
  "use strict";

  var HERO = "SC-STORM-001";

  var params = new URLSearchParams(window.location.search);
  var speed = Math.max(1, Number(params.get("speed")) || 1);
  var running = false;
  var cancelled = false;
  var ui = {};

  // -- primitives ----------------------------------------------------------

  function wait(ms) {
    return new Promise(function (resolve) { setTimeout(resolve, ms / speed); });
  }

  function $(selector) { return document.querySelector(selector); }

  async function until(predicate, timeoutMs) {
    var deadline = Date.now() + (timeoutMs || 20000);
    while (Date.now() < deadline) {
      if (cancelled) return false;
      if (predicate()) return true;
      await new Promise(function (r) { setTimeout(r, 60); });
    }
    return false;
  }

  // -- overlay -------------------------------------------------------------

  function build() {
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = "/static/demo.css";
    document.head.appendChild(link);

    ui.progress = document.createElement("div");
    ui.progress.id = "demo-progress";
    ui.progressFill = document.createElement("span");
    ui.progress.appendChild(ui.progressFill);

    ui.hud = document.createElement("div");
    ui.hud.id = "demo-hud";
    var dot = document.createElement("span");
    dot.className = "h-dot";
    ui.hudLabel = document.createElement("span");
    var stop = document.createElement("button");
    stop.type = "button";
    stop.textContent = "Stop (Esc)";
    stop.addEventListener("click", function () { end(); });
    ui.hud.appendChild(dot);
    ui.hud.appendChild(ui.hudLabel);
    ui.hud.appendChild(stop);

    ui.caption = document.createElement("div");
    ui.caption.id = "demo-caption";
    ui.capChapter = document.createElement("span");
    ui.capChapter.className = "c-chapter";
    ui.capLine = document.createElement("span");
    ui.capLine.className = "c-line";
    ui.caption.appendChild(ui.capChapter);
    ui.caption.appendChild(ui.capLine);

    ui.cursor = document.createElement("div");
    ui.cursor.id = "demo-cursor";
    var ring = document.createElement("div");
    ring.className = "ring";
    ui.cursor.appendChild(ring);
    var arrow = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    arrow.setAttribute("viewBox", "0 0 24 24");
    arrow.setAttribute("width", "22");
    arrow.setAttribute("height", "22");
    var path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", "M4 2l14 8.4-6.1 1.2 3.3 6.4-2.9 1.5-3.3-6.4L4 17.6z");
    path.setAttribute("fill", "#ffffff");
    path.setAttribute("stroke", "#101418");
    path.setAttribute("stroke-width", "1.4");
    path.setAttribute("stroke-linejoin", "round");
    arrow.appendChild(path);
    ui.cursor.appendChild(arrow);

    ui.spot = document.createElement("div");
    ui.spot.id = "demo-spot";

    ui.card = document.createElement("div");
    ui.card.id = "demo-card";

    [ui.progress, ui.hud, ui.caption, ui.cursor, ui.spot, ui.card].forEach(function (node) {
      document.body.appendChild(node);
    });
  }

  function caption(chapter, line) {
    ui.capChapter.textContent = chapter;
    ui.capLine.textContent = line;
    ui.caption.classList.toggle("visible", Boolean(line));
  }

  function showCard(children) {
    while (ui.card.firstChild) ui.card.removeChild(ui.card.firstChild);
    var inner = document.createElement("div");
    children.forEach(function (c) { inner.appendChild(c); });
    ui.card.appendChild(inner);
    ui.card.classList.add("visible");
  }

  function hideCard() { ui.card.classList.remove("visible"); }

  function node(tag, className, text) {
    var n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  // -- pointer and spotlight ------------------------------------------------

  async function moveTo(target, settle) {
    var element = typeof target === "string" ? $(target) : target;
    if (!element) return null;
    element.scrollIntoView({ block: "center", behavior: "auto" });
    await wait(140);
    var box = element.getBoundingClientRect();
    ui.cursor.classList.add("visible");
    ui.cursor.style.transform =
      "translate(" + (box.left + box.width / 2) + "px," + (box.top + box.height / 2) + "px)";
    await wait(settle === undefined ? 680 : settle);
    return element;
  }

  async function click(target) {
    var element = await moveTo(target);
    if (!element) return;
    ui.cursor.classList.add("click");
    await wait(220);
    element.click();
    ui.cursor.classList.remove("click");
    await wait(180);
  }

  async function spot(target, padding) {
    var element = typeof target === "string" ? $(target) : target;
    if (!element) { unspot(); return; }
    element.scrollIntoView({ block: "center", behavior: "auto" });
    await wait(160);
    var p = padding === undefined ? 10 : padding;
    var box = element.getBoundingClientRect();
    ui.spot.style.top = (box.top - p) + "px";
    ui.spot.style.left = (box.left - p) + "px";
    ui.spot.style.width = (box.width + p * 2) + "px";
    ui.spot.style.height = (box.height + p * 2) + "px";
    ui.spot.classList.add("visible");
  }

  function unspot() { ui.spot.classList.remove("visible"); }

  // -- navigation -----------------------------------------------------------

  function loaded(view) {
    var content = document.getElementById(view + "-content");
    return content && !content.classList.contains("loading") && content.textContent.length > 200;
  }

  async function goto(view) {
    unspot();
    await click("#tab-" + view);
    await until(function () { return loaded(view); }, 25000);
    window.scrollTo(0, 0);
    await wait(200);
  }

  /** Whichever of these selectors resolves first. Views differ in how many
   *  cards they draw, so a beat aims at a concept rather than an nth-child. */
  function first(selectors) {
    for (var i = 0; i < selectors.length; i++) {
      var found = $(selectors[i]);
      if (found) return found;
    }
    return null;
  }

  function panel(view) { return "#panel-" + view + " "; }

  // -- the script -----------------------------------------------------------
  //
  // `say` is the narration, word for word. It is displayed as a caption while it
  // is being said, which is what makes the recording captioned without an edit
  // pass. `ms` is the whole beat including whatever `run` does; the runner holds
  // the remainder, so a fast machine and a slow one produce the same timeline.

  var BEATS = [
    {
      chapter: "",
      say: "When a shoot falls apart, the fastest fix often quietly drops someone " +
           "— a step-free route, an interpreter. All-Access recovers the day without " +
           "trading those away, and proves the plan reached everyone.",
      ms: 12000,
      run: async function () {
        showCard([
          node("div", "k-mark", "AA"),
          node("h2", null, "All-Access"),
          node("p", null,
            "The production control system that recovers a disrupted shoot day " +
            "without ever dropping an approved access arrangement — and proves the " +
            "plan reached every department."),
          node("p", null, "Agentic Cinema · IBM track")
        ]);
      }
    },

    {
      chapter: "The day", ms: 11000,
      say: "Day fourteen of Salt and Light. Five scenes, three locations — " +
           "every approved access arrangement satisfied.",
      run: async function () {
        hideCard();
        await wait(300);
        await goto("board");
        await spot(panel("board") + ".headline");
      }
    },
    {
      chapter: "The day", ms: 5000,
      say: "Weather and scenes on one axis. The amber bars are exterior work.",
      run: async function () {
        await spot(first([panel("board") + "figure.figure"]));
      }
    },

    {
      chapter: "The disruption", ms: 7000,
      say: "A verified storm reaches the harbour at eighteen thirty. " +
           "Sixty-eight kilometre winds, sea state six.",
      run: async function () {
        unspot();
        window.scrollTo(0, 0);
        var select = $("#scenario-select");
        if (select) { select.value = HERO; }
        await moveTo("#scenario-select");
      }
    },
    {
      chapter: "The disruption", ms: 11000,
      say: "Source event to verified readiness — the whole loop — in under half " +
           "a second. Nothing on this screen is a recording.",
      run: async function () {
        await click("#run-scenario");
        await until(function () {
          return /feasible plan/.test($("#live-status").textContent);
        }, 60000);
        await until(function () { return loaded("board"); }, 25000);
        await wait(400);
        await spot("#statusbar", 6);
      }
    },

    {
      chapter: "Intake", ms: 8000,
      say: "The event arrives typed, contract-validated and hash-chained, " +
           "carrying the authority that says whether the system may act " +
           "without a human first.",
      run: async function () {
        await goto("intake");
        await spot(panel("intake") + ".cards");
      }
    },

    {
      chapter: "Impact", ms: 7000,
      say: "The digital twin traverses the dependency graph — a hundred and " +
           "nineteen affected entities across six levels.",
      run: async function () {
        await goto("impact");
        await spot(panel("impact") + "figure.figure");
      }
    },
    {
      chapter: "Impact", ms: 5000,
      say: "Distance from the centre is how far the storm had to travel. " +
           "Each wedge is one kind of thing.",
      run: async function () { await wait(200); }
    },
    {
      chapter: "Impact", ms: 6000,
      say: "The purple rings are approved access arrangements. A scheduling tool " +
           "would have shown the replacement location as free.",
      run: async function () {
        await spot(panel("impact") + ".cards");
      }
    },

    {
      chapter: "The refusal", ms: 7000,
      say: "The obvious move is the boatshed. It is available. " +
           "The system will not publish it.",
      run: async function () {
        await goto("rejected");
        await spot(panel("rejected") + ".headline");
      }
    },
    {
      chapter: "The refusal", ms: 8000,
      say: "A minimal conflict set: C-ACC-001, a step-free route to the working " +
           "position — with the owner and the approved arrangement it comes from.",
      run: async function () {
        await spot(first([panel("rejected") + "details", panel("rejected") + ".headline"]));
      }
    },
    {
      chapter: "The refusal", ms: 5000,
      say: "Not “infeasible”. Why — and whether the rule may be waived. " +
           "This one may not.",
      run: async function () { await wait(200); }
    },

    {
      chapter: "The measurement", ms: 11000,
      say: "Underneath it, the survey: the shed door's cill is a hundred and forty " +
           "millimetres against a twenty limit. A location manager can act on that " +
           "— not on 'accessibility concern'.",
      run: async function () {
        await goto("spatial");
        await spot(panel("spatial") + "figure.figure");
      }
    },

    {
      chapter: "The options", ms: 9000,
      say: "Three structurally different plans, each rechecked against all " +
           "thirty-four constraints independently, before any was shown to anyone.",
      run: async function () {
        await goto("plans");
        await spot(panel("plans") + ".plangrid");
      }
    },
    {
      chapter: "The options", ms: 8000,
      say: "Objectives trade off. Hard constraints trade off against nothing — " +
           "which is why the access row reads the same on all three.",
      run: async function () {
        await spot(first([panel("plans") + ".plancard.chosen", panel("plans") + ".plangrid"]));
      }
    },

    {
      chapter: "Authority", ms: 9000,
      say: "The system approves nothing. Two named authorities sign, and each " +
           "signature is bound to the plan hash and the constraints in force " +
           "— single use, expiring.",
      run: async function () {
        await goto("approval");
        await spot(first([panel("approval") + ".table-scroll", panel("approval") + ".headline"]));
      }
    },

    {
      chapter: "Execution", ms: 8000,
      say: "Nine typed commands through the saga coordinator. Every one " +
           "completed. Every acknowledgment returned.",
      run: async function () {
        await goto("execution");
        await spot(panel("execution") + ".flow");
      }
    },
    {
      chapter: "Execution", ms: 9000,
      say: "A system that trusted that would call the day ready. This one refuses " +
           "— props hasn't accepted — and there is no override.",
      run: async function () {
        await spot(panel("execution") + ".headline");
      }
    },
    {
      chapter: "Execution", ms: 8000,
      say: "Across a thousand disruptions, verification caught seventy-five of " +
           "seventy-five incomplete executions — twelve percent of runs that " +
           "would otherwise have closed early.",
      run: async function () {
        await spot(panel("execution") + ".cards");
      }
    },

    {
      chapter: "The shift", ms: 9000,
      say: "For the producer, not the incident but the shift: which rules removed " +
           "the most options, who owns them, and where they came from — a list " +
           "you can spend money against.",
      run: async function () {
        await goto("executive");
        await spot(first([panel("executive") + ".panel", panel("executive") + ".cards"]));
      }
    },

    {
      chapter: "The evidence", ms: 8000,
      say: "Every screen is a fold over one event log. Replay it into a fresh view " +
           "and it reproduces live state exactly, hash chain intact.",
      run: async function () {
        await goto("replay");
        await spot(panel("replay") + ".cards");
      }
    },

    {
      chapter: "", say: "", ms: 8000,
      run: async function () {
        unspot();
        ui.cursor.classList.remove("visible");
        var stats = node("div", "k-stats");
        [["0.000", "hard-constraint violations in 1,629 published plans"],
         ["1.000", "access preservation across 3,630 arrangements"],
         ["75/75", "incomplete executions caught before closure"],
         ["2.412", "violations per plan without the independent recheck"]
        ].forEach(function (pair) {
          var stat = node("div", "k-stat");
          stat.appendChild(node("b", null, pair[0]));
          stat.appendChild(node("span", null, pair[1]));
          stats.appendChild(stat);
        });
        showCard([
          node("h2", null, "One thousand disruptions."),
          node("p", null,
            "Remove the independent feasibility recheck — which is what a plan " +
            "authored by a language model or a spreadsheet actually is — and it " +
            "stops failing closed entirely, because it stops checking."),
          stats
        ]);
      }
    }
  ];

  // -- runner ---------------------------------------------------------------

  async function play(from) {
    for (var i = from; i < BEATS.length; i++) {
      if (cancelled) return;
      var beat = BEATS[i];
      var started = Date.now();
      ui.progressFill.style.width = ((i / BEATS.length) * 100).toFixed(1) + "%";
      ui.hudLabel.textContent = "Guided demo · " + (i + 1) + " of " + BEATS.length;
      caption(beat.chapter, beat.say);
      if (beat.run) {
        try { await beat.run(); } catch (err) { /* a beat never stops the run */ }
      }
      if (cancelled) return;
      // A recording pipeline may inject per-beat target durations (window.__AA_TIMING)
      // so the beats pace to a narration track; absent it, the authored ms is used.
      var target = (window.__AA_TIMING && window.__AA_TIMING[i]) || beat.ms;
      var spent = (Date.now() - started) * speed;
      await wait(Math.max(400, target - spent));
    }
    ui.progressFill.style.width = "100%";
    await wait(600);
    end();
  }

  async function start(from) {
    if (running) return;
    running = true;
    cancelled = false;
    document.body.classList.add("demo-on");
    var button = document.getElementById("play-demo");
    if (button) button.disabled = true;
    // Put the server back on the hero scenario before the first frame, so the
    // demonstration is the same run every time regardless of what was clicked
    // before it. This is the same request the "Run disruption" control sends.
    try {
      await fetch("/api/disruptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: HERO })
      });
      if (window.AllAccess) window.AllAccess.reload();
    } catch (err) { /* offline is still demonstrable; the views will say so */ }
    await play(from || 0);
  }

  function end() {
    cancelled = true;
    running = false;
    document.body.classList.remove("demo-on");
    hideCard();
    unspot();
    caption("", "");
    ui.cursor.classList.remove("visible");
    ui.progressFill.style.width = "0%";
    ui.hudLabel.textContent = "";
    ui.hud.style.display = "none";
    var button = document.getElementById("play-demo");
    if (button) button.disabled = false;
  }

  function boot() {
    build();
    ui.hud.style.display = "none";

    var button = document.getElementById("play-demo");
    if (button) {
      button.addEventListener("click", function () {
        ui.hud.style.display = "";
        start(0);
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && running) end();
    });

    if (params.get("demo")) {
      ui.hud.style.display = "";
      // Let the client finish its own boot before taking the controls.
      setTimeout(function () { start(Number(params.get("from")) || 0); }, 900);
    }
  }

  window.AllAccessDemo = {
    start: start,
    stop: end,
    beats: BEATS.length,
    seconds: BEATS.reduce(function (total, b) { return total + b.ms; }, 0) / 1000,
    // The narration with its cue times, so tools/demo_script.py can write
    // docs/DEMO_SCRIPT.md from the thing that actually plays rather than from a
    // transcription of it that drifts the first time a beat is retimed.
    script: (function () {
      var at = 0;
      return BEATS.map(function (b) {
        var entry = { at: at, chapter: b.chapter || "", say: b.say || "", ms: b.ms };
        at += b.ms;
        return entry;
      });
    }())
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
