/* All-Access — the browser client.
 *
 * No framework and no build step: the whole application is this file, and it is
 * served from the same process that runs the workflow. Everything rendered here
 * comes from `/api/*`, which derives it from the event log of a real
 * coordinator run. There is no fixture data in this file.
 *
 * Accessibility decisions that are structural rather than cosmetic:
 *
 * - The tab list implements the APG pattern properly: arrow keys move between
 *   tabs, Home and End jump to the ends, and only the selected tab is in the
 *   page tab sequence.
 * - Every value inserted into the DOM goes through `text()` or `el()`. There is
 *   no innerHTML with interpolated data anywhere, which keeps a crew message or
 *   a location note from becoming markup.
 * - Wide tables are wrapped in a labelled, focusable scroll region, so a
 *   keyboard user can reach the horizontal scroll.
 * - Status changes are announced once, through a single polite live region.
 *   Multiple live regions compete and end up announcing nothing useful.
 *
 * Every diagram here is drawn from the same payload as the table beside it, with
 * a deterministic layout — no physics, no random seed, no animated reflow. A
 * picture that moves is a picture two viewers cannot compare. And no diagram is
 * ever the only place a number appears: the table under it carries the data, so
 * nobody is sent to an image to read a measurement.
 */

(function () {
  "use strict";

  var state = { view: "board", loaded: {}, crewPerson: null, spatialLocation: null,
                notice: null };

  var SVGNS = "http://www.w3.org/2000/svg";

  // -- tiny DOM helpers ---------------------------------------------------

  function apply(node, attrs) {
    if (!attrs) return node;
    Object.keys(attrs).forEach(function (key) {
      var value = attrs[key];
      if (value === null || value === undefined || value === false) return;
      if (key === "class") node.setAttribute("class", value);
      else if (key === "text") node.textContent = String(value);
      else node.setAttribute(key, value === true ? "" : String(value));
    });
    return node;
  }

  function adopt(node, children) {
    (children || []).forEach(function (child) {
      if (child === null || child === undefined || child === false) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function el(tag, attrs, children) {
    return adopt(apply(document.createElement(tag), attrs), children);
  }

  /** The same, in the SVG namespace. `createElement` produces an HTML element
   *  called "circle" that renders as nothing at all, which is a difficult ten
   *  minutes the first time. */
  function sv(tag, attrs, children) {
    return adopt(apply(document.createElementNS(SVGNS, tag), attrs), children);
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  function announce(message) {
    document.getElementById("live-status").textContent = message;
  }

  function get(path) {
    return fetch(path, { headers: { "Accept": "application/json" } }).then(function (r) {
      if (!r.ok) throw new Error(path + " returned " + r.status);
      return r.json();
    });
  }

  function num(value, digits) {
    if (value === null || value === undefined) return "—";
    var n = Number(value);
    if (!isFinite(n)) return "—";
    return n.toLocaleString(undefined, {
      minimumFractionDigits: digits === undefined ? 0 : digits,
      maximumFractionDigits: digits === undefined ? 0 : digits
    });
  }

  function clock(iso) {
    if (!iso) return "—";
    var d = new Date(iso);
    return d.toLocaleString(undefined, {
      day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit"
    });
  }

  // Time of day only, for the end of a window whose date the start already
  // gave. Slicing the last five characters off a formatted datetime does not
  // do this — under a 12-hour locale "Mar 14, 11:50 AM" ends "50 AM", which is
  // what the scene table shipped before a browser rendered it.
  function timeOnly(iso) {
    if (!iso) return "—";
    return new Date(iso).toLocaleTimeString(undefined, {
      hour: "2-digit", minute: "2-digit"
    });
  }

  function pct(value) {
    if (value === null || value === undefined) return "—";
    return (Number(value) * 100).toFixed(1) + "%";
  }

  function words(value) {
    return String(value === null || value === undefined ? "" : value).replace(/_/g, " ");
  }

  /** The measured quantity out of a survey failure, without the limit it was
   *  compared against: "threshold 140 mm exceeds the 20 mm limit" → "threshold
   *  140 mm". The full sentence is in the blocker list and the edge table; the
   *  drawing only has room for the thing that was measured. */
  function shortReason(reason) {
    return String(reason || "").replace(/\s+(exceeds|is below|is steeper than|has)\b.*$/, "");
  }

  function chip(label, tone) { return el("span", { class: "chip " + tone, text: label }); }

  function card(title, value, note, tone) {
    return el("div", { class: "card" + (tone ? " " + tone : "") }, [
      el("h3", { text: title }),
      el("p", { class: "value", text: value }),
      note ? el("p", { class: "note", text: note }) : null
    ]);
  }

  /** The one sentence a view concluded, above everything that supports it.
   *  A screen that makes the reader derive the verdict from a table has not
   *  finished the job the table started. */
  function headline(tone, verdict, detail) {
    return el("div", { class: "headline " + tone }, [
      el("span", { class: "h-verdict", text: verdict }),
      detail ? el("span", { class: "h-detail", text: detail }) : null
    ]);
  }

  function table(caption, headers, rows, aligns) {
    var thead = el("thead", null, [
      el("tr", null, headers.map(function (h, i) {
        return el("th", { scope: "col", class: (aligns && aligns[i] === "num") ? "num" : null,
                          text: h });
      }))
    ]);
    var tbody = el("tbody", null, rows.map(function (row) {
      var attrs = row.selected ? { class: "selected" } : null;
      return el("tr", attrs, (row.cells || row).map(function (cell, i) {
        var klass = (aligns && aligns[i] === "num") ? "num" : null;
        if (cell && cell.nodeType) return el("td", { class: klass }, [cell]);
        return el("td", { class: klass, text: cell === null || cell === undefined ? "—" : String(cell) });
      }));
    }));
    var wrapper = el("div", {
      class: "table-scroll", tabindex: "0", role: "region", "aria-label": caption
    }, [el("table", null, [el("caption", { text: caption }), thead, tbody])]);
    return wrapper;
  }

  /** A table folded into a disclosure. Every diagram in this product has one of
   *  these under it holding the same numbers. */
  function tableDetails(summaryText, node) {
    return el("details", null, [el("summary", null, [summaryText]), node]);
  }

  function pairs(entries) {
    var dl = el("dl", { class: "pairs" });
    entries.forEach(function (entry) {
      if (entry[1] === null || entry[1] === undefined) return;
      dl.appendChild(el("dt", { text: entry[0] }));
      var value = entry[1];
      dl.appendChild(el("dd", null, [value && value.nodeType ? value : String(value)]));
    });
    return dl;
  }

  function statusTone(status) {
    if (status === "blocking" || status === "rejected" || status === "abandoned") return "bad";
    if (status === "at_risk" || status === "pending" || status === "verifying") return "warn";
    if (status === "abstained") return "quiet";
    return "ok";
  }

  /** Text on a diagram, with a stroke of the surface colour painted underneath
   *  it. Labels in a graph drawing land on lines and on each other; without the
   *  halo the reader loses the one word that matters at exactly the crossing
   *  where it matters most. */
  function haloText(x, y, content, fill, weight) {
    return sv("text", {
      x: x, y: y, "text-anchor": "middle", "font-size": 11,
      "font-weight": weight || "400",
      stroke: "var(--surface)", "stroke-width": 4.5, "paint-order": "stroke",
      fill: fill, text: content
    });
  }

  function figure(node, captionText) {
    return el("figure", { class: "figure" }, [
      el("div", { class: "diagram" }, [node]),
      captionText ? el("figcaption", { text: captionText }) : null
    ]);
  }

  function legend(items) {
    return el("ul", { class: "legend" }, items.map(function (item) {
      return el("li", null, [
        el("span", { class: "swatch", style: "background:" + item[1] }),
        item[0]
      ]);
    }));
  }

  function meter(name, value, fraction, tone) {
    var width = Math.max(0, Math.min(1, fraction || 0)) * 100;
    return el("div", { class: "metric" }, [
      el("span", { class: "m-name", text: name }),
      el("span", { class: "m-value", text: value }),
      el("div", { class: "m-bar bar" }, [
        el("span", { style: "width:" + width.toFixed(1) + "%" +
                            (tone ? ";background:var(--" + tone + ")" : "") })
      ])
    ]);
  }

  function flow(steps) {
    return el("div", { class: "flow" }, steps.map(function (s) {
      return el("div", { class: "step " + (s.tone || "") }, [
        el("span", { class: "s-name", text: s.name }),
        el("span", { class: "s-note", text: s.note })
      ]);
    }));
  }

  // -- the workflow rail --------------------------------------------------
  //
  // The coordinator's own macro states, in the order the state machine defines
  // them, with the ones this disruption actually traversed marked. Read from
  // the history rather than assumed: a run that ends at "no feasible plan"
  // shows exactly that, which is the honest thing for a rail to do.

  var PHASES = [
    ["qualifying", "Qualify"], ["scoping", "Scope"], ["assessing", "Assess"],
    ["planning", "Plan"], ["comparing", "Compare"], ["awaiting_approval", "Approve"],
    ["executing", "Execute"], ["reconciling", "Reconcile"], ["verifying", "Verify"],
    ["ready", "Ready"], ["closed", "Closed"]
  ];

  function renderPhases(history, current) {
    var rail = document.getElementById("phase-rail");
    if (!rail) return;
    var reached = {};
    (history || []).forEach(function (h) { reached[h.state] = true; });
    clear(rail);
    PHASES.forEach(function (phase) {
      var key = phase[0];
      var klass = "phase";
      if (key === current) klass += " here";
      else if (reached[key]) klass += " done";
      rail.appendChild(el("span", { class: klass, text: phase[1] }));
    });
  }

  // -- schedule strip -----------------------------------------------------

  function ms(iso) { return new Date(iso).getTime(); }

  function weatherTone(w) {
    var c = String(w.condition || "");
    if (w.sea_state >= 5 || /storm|gale|lightning/.test(c)) return "bad";
    if (w.precipitation_mm > 1 || /rain|squall/.test(c)) return "warn";
    if (/clear|fine/.test(c)) return "ok";
    return "quiet";
  }

  /** The shooting day on one axis: the weather across the top, the scenes under
   *  it on the same scale. The reason the storm row is there is that the whole
   *  argument of the product is a collision between two rows of this picture,
   *  and a reader should be able to see it before reading a word. */
  function scheduleStrip(scenes, weather) {
    if (!scenes.length) return null;
    var starts = scenes.map(function (s) { return ms(s.crew_call || s.start); });
    var ends = scenes.map(function (s) { return ms(s.end); });
    var t0 = Math.min.apply(null, starts) - 45 * 60000;
    var t1 = Math.max.apply(null, ends) + 45 * 60000;
    var span = Math.max(1, t1 - t0);
    function at(t) { return ((t - t0) / span) * 100; }

    var grid = el("div", { class: "gantt" });

    // Day boundaries, drawn behind every row so the eye can tell that the last
    // scene is on the following evening rather than late the same night — which
    // is the whole content of the recovery plan.
    // Ticks and day rules are stepped in local time, not by adding six hours of
    // milliseconds to the epoch. The arithmetic version lands on 01:00 and 07:00
    // wherever the viewer is not on UTC, so the midnight label — the one that
    // says the exterior moved to the following evening — never appears at all.
    function localSteps(hours, callback) {
      var anchor = new Date(t0);
      anchor.setHours(0, 0, 0, 0);
      for (var k = 0; k < 96; k++) {
        var stamp = new Date(anchor.getTime());
        stamp.setHours(k * hours);
        var t = stamp.getTime();
        if (t >= t1) return;
        if (t > t0) callback(t, stamp);
      }
    }

    function dayRules(track) {
      localSteps(24, function (t) {
        track.appendChild(el("span", {
          class: "g-rule day", style: "left:" + at(t).toFixed(2) + "%"
        }));
      });
    }

    // A bar narrower than its own label — which every one-hour scene is, on an
    // axis two days wide — puts the label outside it instead of clipping it.
    function bar(track, a, b, klass, label) {
      var left = at(a), width = Math.max(0.5, at(b) - at(a));
      var wide = width > 14;
      track.appendChild(el("div", {
        class: "g-bar " + klass + (wide ? "" : " narrow"),
        style: "left:" + left.toFixed(2) + "%;width:" + width.toFixed(2) + "%",
        text: wide ? label : ""
      }));
      if (!wide) {
        track.appendChild(el("span", {
          class: "g-cap" + (left + width > 62 ? " left" : ""),
          style: (left + width > 62
            ? "right:" + (100 - left).toFixed(2) + "%"
            : "left:" + (left + width).toFixed(2) + "%"),
          text: label
        }));
      }
    }

    // The weather windows tile the axis end to end, so their labels go inside
    // the bar and are clipped rather than printed outside it — outside is where
    // the next window already is. Only the window that closed the exterior
    // carries its wind speed; the rest are in the table below.
    var wTrack = el("div", { class: "g-track" });
    dayRules(wTrack);
    (weather || []).forEach(function (w) {
      var a = Math.max(t0, ms(w.start)), b = Math.min(t1, ms(w.end));
      if (b <= a) return;
      var tone = weatherTone(w);
      wTrack.appendChild(el("div", {
        class: "g-bar",
        style: "left:" + at(a).toFixed(2) + "%;width:" + (at(b) - at(a)).toFixed(2) +
               "%;background:" + (tone === "bad" ? "var(--bad)"
                 : tone === "warn" ? "var(--warn)"
                 : tone === "ok" ? "var(--ok)" : "var(--ink-muted)"),
        text: words(w.condition) + (tone === "bad" ? " · " + num(w.wind_kph, 0) + " kph" : "")
      }));
    });
    grid.appendChild(el("span", { class: "g-label", text: "Weather" }));
    grid.appendChild(wTrack);

    scenes.forEach(function (s) {
      var track = el("div", { class: "g-track" });
      dayRules(track);
      bar(track, ms(s.start), ms(s.end), s.exterior ? "exterior" : "",
          timeOnly(s.start) + "–" + timeOnly(s.end));
      grid.appendChild(el("span", {
        class: "g-label", text: s.scene_id + " · " + (s.exterior ? "EXT" : "INT")
      }));
      grid.appendChild(track);
    });

    // Axis: a tick every six hours, and the date wherever the day turns over.
    var axis = el("div", { class: "g-axis" });
    localSteps(6, function (t, stamp) {
      var newDay = stamp.getHours() === 0;
      axis.appendChild(el("span", {
        class: "g-tick" + (newDay ? " day" : ""), style: "left:" + at(t).toFixed(2) + "%",
        text: newDay
          ? stamp.toLocaleDateString(undefined, { day: "2-digit", month: "short" })
          : timeOnly(stamp.toISOString())
      }));
    });
    grid.appendChild(el("span", { class: "g-label" }));
    grid.appendChild(axis);
    return grid;
  }

  // -- views --------------------------------------------------------------

  var renderers = {};

  renderers.board = function (root) {
    return get("/api/control-board").then(function (d) {
      clear(root);
      document.getElementById("production-line").textContent =
        d.production.title + " — unit " + d.production.unit +
        ", production clock " + clock(d.production.clock);
      renderPhases(d.disruption.history, d.disruption.state);

      var ready = d.disruption.state === "ready" || d.disruption.state === "closed";
      var atRisk = d.exposure.access_at_risk.length;
      root.appendChild(headline(
        atRisk ? "bad" : (ready ? "ok" : "warn"),
        ready ? "The day is ready." : "The day is not ready.",
        (atRisk
          ? atRisk + " approved access arrangement(s) are at risk. "
          : "Every approved access arrangement is satisfied. ") +
        d.disruption.title + " was taken from source event to verified readiness through " +
        d.disruption.history.length + " workflow states."
      ));

      root.appendChild(el("div", { class: "cards" }, [
        card("Disruption", words(d.disruption.state), d.disruption.title),
        card("Delay exposure", num(d.exposure.delay_minutes) + " min",
             num(d.exposure.overtime_minutes) + " min overtime exposure"),
        card("Access at risk", String(atRisk),
             atRisk ? d.exposure.access_at_risk.join(", ")
                    : "every approved arrangement satisfied",
             atRisk ? null : "emphatic"),
        card("Departments ready", d.kpis.departments_ready + " of " + d.kpis.departments_tracked,
             d.kpis.unacknowledged + " message(s) unacknowledged"),
        card("Digital twin", num(d.twin.entities) + " entities",
             num(d.twin.relationships) + " relationships, " +
             num(d.twin.temporal_facts) + " temporal facts"),
        card("Constraint set", num(d.constraints.count) + " constraints",
             "hash " + d.constraints.hash.slice(0, 16))
      ]));

      root.appendChild(el("h2", { text: "The shooting day" }));
      var strip = scheduleStrip(d.next_scenes, d.weather);
      if (strip) {
        root.appendChild(figure(strip,
          "Weather and scenes on one axis. Amber bars are exterior work; blue are " +
          "interiors. The storm band is the collision this disruption is about."));
      }
      root.appendChild(tableDetails(
        "Scene detail — " + d.next_scenes.length + " scene(s), with sluglines and locations",
        table(
          "Scenes, in order of call",
          ["Scene", "Slugline", "Location", "Crew call", "Shoot", "Ext."],
          d.next_scenes.map(function (s) {
            return [s.scene_id, s.slugline, s.location, clock(s.crew_call),
                    clock(s.start) + " – " + timeOnly(s.end),
                    s.exterior ? "exterior" : "interior"];
          })
        )
      ));

      root.appendChild(el("h2", { text: "Department readiness" }));
      root.appendChild(table(
        "Department readiness",
        ["Department", "Tasks", "Accepted", "State"],
        d.departments.map(function (r) {
          return [words(r.department.replace("DEPT-", "")), r.tasks, r.accepted,
                  chip(r.ready ? "ready" : "awaiting acceptance", r.ready ? "ok" : "warn")];
        }),
        [null, "num", "num", null]
      ));

      root.appendChild(el("h2", { text: "Workflow states traversed" }));
      root.appendChild(flow(d.disruption.history.map(function (h, i) {
        var last = i === d.disruption.history.length - 1;
        return {
          name: words(h.state),
          note: h.detail,
          tone: last ? "ok" : (/resolving|re-/.test(h.detail) ? "warn" : "")
        };
      })));
      root.appendChild(el("p", { class: "evidence",
        text: "Verify appears twice. The first pass blocked on a department that had " +
              "not accepted its task; the second ran after it did. The system will not " +
              "leave that loop by being asked to." }));

      root.appendChild(el("h2", { text: "Weather and daylight" }));
      root.appendChild(table(
        "Weather windows",
        ["From", "To", "Condition", "Wind kph", "Rain mm", "Sea state"],
        d.weather.map(function (win) {
          return [clock(win.start), clock(win.end), words(win.condition),
                  num(win.wind_kph, 1), num(win.precipitation_mm, 1), win.sea_state];
        }),
        [null, null, null, "num", "num", "num"]
      ));
      root.appendChild(pairs([
        ["Civil dawn", clock(d.daylight.civil_dawn)],
        ["Sunrise", clock(d.daylight.sunrise)],
        ["Sunset", clock(d.daylight.sunset)],
        ["Civil dusk", clock(d.daylight.civil_dusk)]
      ]));
    });
  };

  renderers.intake = function (root) {
    return get("/api/intake").then(function (d) {
      clear(root);
      root.appendChild(headline(
        d.requires_confirmation ? "warn" : "ok",
        words(d.event.classification) + " event from " + d.event.producer + ".",
        d.requires_confirmation
          ? "Authority " + d.event.authority + " — it may not become effective without a human confirming it."
          : "Authority " + d.event.authority + " — it may be acted on directly. " +
            d.operational_consequence
      ));

      root.appendChild(el("div", { class: "cards" }, [
        card("Authority", d.event.authority,
             d.requires_confirmation
               ? "requires human confirmation before it may become effective"
               : "may be acted on directly"),
        card("Confidence", d.confidence === undefined || d.confidence === null
               ? "—" : pct(d.confidence), "as reported by the source"),
        card("Classification", words(d.event.classification),
             "governs who may receive it"),
        card("Consequence", d.operational_consequence, "computed, not asserted")
      ]));

      root.appendChild(el("h2", { text: "The event as received" }));
      root.appendChild(el("div", { class: "panel" }, [pairs([
        ["Event id", el("code", { text: d.event.event_id })],
        ["Type", el("code", { text: d.event.event_type })],
        ["Producer", d.event.producer],
        ["Reported by", d.event.actor],
        ["Effective", clock(d.event.effective_time)],
        ["Emitted", clock(d.event.event_time)],
        ["Schema version", d.event.schema_version],
        ["Partition key", el("code", { text: d.event.partition_key })],
        ["Payload hash", el("code", { text: d.event.payload_hash.slice(0, 32) })],
        ["Signature", el("code", { text: (d.event.signature || "").slice(0, 32) })]
      ])]));

      root.appendChild(el("h2", { text: "Original evidence" }));
      root.appendChild(el("div", { class: "panel" }, [
        el("pre", { class: "mono", text: JSON.stringify(d.payload, null, 2) })
      ]));
    });
  };

  var BANDS = [
    ["primary", "Act on these",
     "Reached directly, without passing through a call sheet or a department " +
     "roster on the way. These are the consequences to work first."],
    ["secondary", "Check these",
     "One intermediary further out, or reached through a single shared record. " +
     "Real dependencies that usually need confirming rather than acting on."],
    ["contextual", "Context",
     "Everything else the change can reach. Kept because the list is complete " +
     "by design — a department missed here is a scene nobody re-dressed."]
  ];

  var BAND_FILL = {
    primary: "var(--graph-1)", secondary: "var(--graph-2)", contextual: "var(--graph-track)"
  };
  var BAND_RADIUS = { primary: 6.2, secondary: 4.4, contextual: 3.2 };

  /** The blast radius, drawn as one.
   *
   *  Distance from the centre is the number of relationships the disruption had
   *  to traverse to reach a thing. Angle is the kind of thing: every entity of a
   *  type occupies one contiguous wedge, so a reader can see at a glance that
   *  the access requirements sit at depth two and the crew at depth three, which
   *  is the shape of the problem and is invisible in a sorted table.
   *
   *  Layout is a pure function of the payload: types ordered by size then name,
   *  members ordered by depth then id. Two runs of the same disruption produce
   *  the same picture, pixel for pixel.
   */
  function impactDiagram(d) {
    var W = 940, H = 600, cx = W / 2, cy = H / 2, rMin = 62, rMax = 232;
    var maxDepth = Math.max(1, d.max_depth || 1);
    function radius(depth) {
      if (maxDepth <= 1) return rMax;
      return rMin + (rMax - rMin) * ((depth - 1) / (maxDepth - 1));
    }

    var byType = {};
    d.nodes.forEach(function (n) {
      (byType[n.entity_type] = byType[n.entity_type] || []).push(n);
    });
    var types = Object.keys(byType).sort(function (a, b) {
      return byType[b].length - byType[a].length || (a < b ? -1 : 1);
    });
    types.forEach(function (t) {
      byType[t].sort(function (a, b) {
        return a.depth - b.depth || (a.entity_id < b.entity_id ? -1 : 1);
      });
    });

    var svg = sv("svg", {
      viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Blast radius diagram: " + d.nodes.length + " affected entities " +
                    "arranged by how many relationships the disruption traversed to " +
                    "reach each one. The same entities are listed in the tables below."
    });
    svg.appendChild(sv("desc", {
      text: "Rings are depth from the disruption, one to " + maxDepth + ". Each wedge " +
            "is one kind of entity. Filled blue marks act-on-these, amber marks " +
            "check-these, hollow marks context."
    }));

    // Depth rings, with the depth number written once along the upward axis.
    for (var depth = 1; depth <= maxDepth; depth++) {
      var r = radius(depth);
      svg.appendChild(sv("circle", {
        cx: cx, cy: cy, r: r, fill: "none",
        stroke: "var(--line)", "stroke-width": 1
      }));
      svg.appendChild(sv("text", {
        x: cx + 6, y: cy - r - 4, "font-size": 11, fill: "var(--ink-muted)",
        stroke: "var(--surface)", "stroke-width": 4, "paint-order": "stroke",
        text: String(depth)
      }));
    }

    var total = d.nodes.length || 1;
    var angle = -Math.PI / 2;   // start at twelve o'clock, sweep clockwise
    var gap = 0.012;

    types.forEach(function (type) {
      var members = byType[type];
      var wedge = (2 * Math.PI) * (members.length / total);
      var inner = Math.max(0, wedge - gap);
      var start = angle + gap / 2;

      // A faint separator so the wedges read as groups rather than a scatter.
      svg.appendChild(sv("line", {
        x1: cx + Math.cos(angle) * rMin * 0.55, y1: cy + Math.sin(angle) * rMin * 0.55,
        x2: cx + Math.cos(angle) * (rMax + 8), y2: cy + Math.sin(angle) * (rMax + 8),
        stroke: "var(--line)", "stroke-width": 1
      }));

      members.forEach(function (n, i) {
        var a = members.length === 1
          ? start + inner / 2
          : start + inner * (i / (members.length - 1));
        var r2 = radius(n.depth);
        var x = cx + Math.cos(a) * r2, y = cy + Math.sin(a) * r2;
        var isAccess = n.entity_type === "access_requirement";
        svg.appendChild(sv("circle", {
          cx: x.toFixed(1), cy: y.toFixed(1),
          r: isAccess ? 7.5 : BAND_RADIUS[n.relevance] || 3.2,
          fill: isAccess ? "var(--graph-4)" : (BAND_FILL[n.relevance] || "var(--graph-track)"),
          stroke: n.relevance === "contextual" ? "var(--line-strong)" : "var(--surface)",
          "stroke-width": isAccess ? 2 : 1
        }));
      });

      // Label the wedges big enough to carry one.
      if (members.length >= 4) {
        var mid = start + inner / 2;
        var lx = cx + Math.cos(mid) * (rMax + 28);
        var ly = cy + Math.sin(mid) * (rMax + 28);
        svg.appendChild(sv("text", {
          x: lx.toFixed(1), y: ly.toFixed(1),
          "font-size": 12, fill: "var(--ink-muted)",
          stroke: "var(--surface)", "stroke-width": 4, "paint-order": "stroke",
          "text-anchor": Math.cos(mid) < -0.2 ? "end" : (Math.cos(mid) > 0.2 ? "start" : "middle"),
          "dominant-baseline": "middle",
          text: words(type) + " " + members.length
        }));
      }
      angle += wedge;
    });

    svg.appendChild(sv("circle", {
      cx: cx, cy: cy, r: 34, fill: "var(--bad)", stroke: "var(--surface)", "stroke-width": 3
    }));
    svg.appendChild(sv("text", {
      x: cx, y: cy - 3, "text-anchor": "middle", "font-size": 12,
      "font-weight": "700", fill: "var(--accent-ink)", text: "SOURCE"
    }));
    svg.appendChild(sv("text", {
      x: cx, y: cy + 12, "text-anchor": "middle", "font-size": 11,
      fill: "var(--accent-ink)", text: d.origin_ids.length + " origin" + (d.origin_ids.length === 1 ? "" : "s")
    }));
    return svg;
  }

  renderers.impact = function (root) {
    return get("/api/impact").then(function (d) {
      clear(root);
      var counts = d.counts_by_relevance || {};
      var primary = d.primary || {};

      root.appendChild(headline(
        "warn",
        d.nodes.length + " things this change reaches, " + (counts.primary || 0) + " of them directly.",
        "Traversal is complete by design and then ranked, so nothing is discarded and " +
        "the screen still opens on the short list. Depth runs to " + d.max_depth +
        " — the far edge is reached through " + (d.max_depth - 1) + " intermediaries."
      ));

      root.appendChild(el("div", { class: "cards" }, [
        card("Act on these", num(counts.primary || 0),
             "of " + num(d.nodes.length) + " reached, across " + d.max_depth + " levels",
             "emphatic"),
        card("Departments", String((primary.departments || []).length),
             (primary.departments || []).join(", ") || "none directly affected"),
        card("Access arrangements",
             String((primary.access_requirements || []).length),
             (primary.access_requirements || []).join(", ") || "none reached directly"),
        card("Scenes", String((primary.scenes || []).length), "on the shooting day")
      ]));

      root.appendChild(figure(impactDiagram(d),
        "Every affected entity, placed by how far the disruption had to travel to " +
        "reach it and grouped by what kind of thing it is. The numbered rings are " +
        "depth from the source. Purple marks are approved access arrangements — " +
        "the constraints a rushed plan drops first."));
      root.appendChild(legend([
        ["Act on these", "var(--graph-1)"],
        ["Check these", "var(--graph-2)"],
        ["Context", "var(--graph-track)"],
        ["Approved access arrangement", "var(--graph-4)"],
        ["Source of the disruption", "var(--bad)"]
      ]));

      // The named things somebody has to do something about, before the
      // exhaustive lists. Forty-two rows of identifiers is the evidence for this
      // panel, not a substitute for it.
      root.appendChild(el("h2", { text: "What to act on" }));
      root.appendChild(el("div", { class: "panel" }, [
        pairs([
          ["Scenes", (primary.scenes || []).join(", ") || "none"],
          ["Departments", (primary.departments || []).map(words).join(", ") || "none"],
          ["Access arrangements", (primary.access_requirements || []).join(", ") || "none"],
          ["Documents", (d.documents || []).join(", ") || "none"],
          ["People reached", String((d.people || []).length) + " — named in the crew view, " +
                             "not here, because this screen has no need for them"]
        ])
      ]));

      root.appendChild(el("h2", { text: "The consequences, by band" }));
      var byBand = { primary: [], secondary: [], contextual: [] };
      d.nodes.forEach(function (n) {
        (byBand[n.relevance] || byBand.contextual).push(n);
      });

      BANDS.forEach(function (band) {
        var key = band[0], title = band[1], blurb = band[2];
        var nodes = byBand[key];
        if (!nodes.length) return;
        var details = el("details", null, [
          el("summary", null, [
            title + " — " + nodes.length + " consequence(s) ",
            chip(key, key === "primary" ? "ok" : (key === "secondary" ? "warn" : "quiet"))
          ])
        ]);
        details.appendChild(el("p", { class: "evidence", text: blurb }));
        details.appendChild(table(
          title,
          ["Entity", "Type", "Label", "Depth", "Reached via"],
          nodes.slice(0, 60).map(function (n) {
            return [n.entity_id, words(n.entity_type), n.label,
                    n.depth, n.path.join(" → ")];
          }),
          [null, null, null, "num", null]
        ));
        if (nodes.length > 60) {
          details.appendChild(el("p", { class: "evidence",
            text: "Showing the first 60 of " + nodes.length + "." }));
        }
        root.appendChild(details);
      });
    });
  };

  function robustnessCells(plan) {
    var r = plan.robustness;
    if (!r) return ["—", "—", "—"];
    return [num(r.expected_delay_minutes), num(r.worst_credible_delay_minutes),
            num(r.recovery_margin_minutes)];
  }

  /** The comparison a producer actually makes, as cards rather than an eleven
   *  column table. Every bar is scaled against the worst value across the plans
   *  on screen, so shorter is always better and the three are comparable at a
   *  glance; the exact figures are in the table below and in each disclosure. */
  function planCards(plans) {
    var worst = { delay: 1, cost: 1, over: 1, risk: 1 };
    plans.forEach(function (p) {
      worst.delay = Math.max(worst.delay, p.objectives.delay_minutes);
      worst.cost = Math.max(worst.cost, Math.abs(p.objectives.cost_delta));
      worst.over = Math.max(worst.over, p.objectives.overtime_minutes);
      worst.risk = Math.max(worst.risk, p.objectives.operational_risk);
    });
    return el("div", { class: "plangrid" }, plans.map(function (p) {
      var preserved = p.access.filter(function (a) { return a.satisfied; }).length;
      var allKept = preserved === p.access.length;
      return el("div", { class: "plancard" + (p.selected ? " chosen" : "") }, [
        el("div", { class: "p-head" }, [
          el("span", { class: "p-title", text: p.label }),
          p.selected ? chip("approved", "ok")
                     : (p.on_pareto_front ? chip("front", "quiet") : chip("feasible", "quiet"))
        ]),
        el("p", { class: "p-why", text: p.rationale }),
        meter("Delay", num(p.objectives.delay_minutes) + " min",
              p.objectives.delay_minutes / worst.delay),
        meter("Incremental cost", num(p.objectives.cost_delta),
              Math.abs(p.objectives.cost_delta) / worst.cost),
        meter("Overtime", num(p.objectives.overtime_minutes) + " min",
              p.objectives.overtime_minutes / worst.over),
        meter("Operational risk", num(p.objectives.operational_risk, 2),
              p.objectives.operational_risk / worst.risk),
        el("div", { class: "metric" }, [
          el("span", { class: "m-name", text: "Access arrangements" }),
          el("span", { class: "m-value" }, [
            chip(preserved + " of " + p.access.length + (allKept ? " preserved" : " kept"),
                 allKept ? "ok" : "bad")
          ])
        ]),
        el("p", { class: "evidence",
          text: "Needs " + (p.required_approvals.map(words).join(" and ") || "no approval") + "." })
      ]);
    }));
  }

  renderers.plans = function (root) {
    return get("/api/plans").then(function (d) {
      clear(root);
      var chosen = d.feasible.filter(function (p) { return p.selected; })[0];
      root.appendChild(headline(
        "ok",
        d.feasible.length + " plans survived every hard constraint. " +
        d.rejected.length + " did not and were never offered.",
        "Each of the " + d.feasible.length + " below passed an independent recheck of all " +
        d.hard_constraints.length + " hard constraints, run from the finished plan rather " +
        "than from the search that produced it. " +
        (chosen ? "The recommendation is “" + chosen.label + "”." : "")
      ));

      root.appendChild(planCards(d.feasible));

      root.appendChild(el("div", { class: "note-block" }, [
        "Objectives are traded off against each other; hard constraints are not " +
        "traded off against anything. There is no weight that lets a saved hour " +
        "buy out an approved access arrangement, which is why the arrangement row " +
        "on every card above reads the same."
      ]));

      root.appendChild(el("h2", { text: "Objectives and simulated outcome" }));
      root.appendChild(table(
        "Feasible plans — objectives and simulated outcome",
        ["", "Strategy", "Delay min", "Cost", "Overtime", "Changed", "Risk",
         "Sim. delay", "Worst", "Margin", "Approvals"],
        d.feasible.map(function (p) {
          return {
            selected: p.selected,
            cells: [
              p.selected ? chip("approved", "ok")
                         : (p.on_pareto_front ? chip("front", "quiet") : ""),
              p.label,
              num(p.objectives.delay_minutes),
              num(p.objectives.cost_delta),
              num(p.objectives.overtime_minutes),
              p.objectives.changed_assignments,
              num(p.objectives.operational_risk)
            ].concat(robustnessCells(p)).concat([p.required_approvals.map(words).join(", ")])
          };
        }),
        [null, null, "num", "num", "num", "num", "num", "num", "num", "num", null]
      ));

      root.appendChild(el("h2", { text: "What each plan actually does" }));
      d.feasible.forEach(function (p) {
        var details = el("details", p.selected ? { open: true } : null, [
          el("summary", null, [p.label + " ", p.selected ? chip("approved", "ok") : ""])
        ]);
        details.appendChild(el("p", { text: p.rationale }));
        details.appendChild(pairs([
          ["Plan id", el("code", { text: p.plan_id })],
          ["Plan hash", el("code", { text: p.plan_hash.slice(0, 24) })],
          ["Solver", p.proof ? p.proof.solver_version : "—"],
          ["Constraints checked", p.proof ? p.proof.validator_report.constraints_checked : "—"],
          ["Search nodes", p.proof ? num(p.proof.search_nodes) : "—"],
          ["Solve time", p.proof ? num(p.proof.solve_ms, 1) + " ms" : "—"],
          ["Deferred scenes", p.deferred_scenes.join(", ") || "none"],
          ["Safety controls", p.safety_controls.join("; ") || "none added"],
          ["Sensitive assumptions",
           p.robustness ? (p.robustness.sensitive_assumptions.join("; ") || "none measurable") : "—"]
        ]));
        details.appendChild(table(
          "Access arrangements — " + p.label,
          ["Requirement", "State", "Mechanism"],
          p.access.map(function (a) {
            return [a.requirement, chip(a.satisfied ? "preserved" : "at risk",
                                        a.satisfied ? "ok" : "bad"), a.mechanism];
          })
        ));
        root.appendChild(details);
      });
    });
  };

  renderers.rejected = function (root) {
    return get("/api/plans").then(function (d) {
      clear(root);
      if (!d.rejected.length) {
        root.appendChild(headline("ok", "No plan was rejected for this disruption.",
          "Every option the search produced satisfied all " + d.hard_constraints.length +
          " hard constraints."));
        return;
      }
      var ids = {};
      d.rejected.forEach(function (p) {
        p.conflicts.forEach(function (c) {
          c.constraint_ids.forEach(function (i) { ids[i] = true; });
        });
      });
      root.appendChild(headline(
        "bad",
        d.rejected.length + " option(s) refused, each with the minimal set of rules that " +
        "cannot hold together.",
        "The binding rules are " + Object.keys(ids).join(", ") + ". “Infeasible” without " +
        "provenance is an assertion; each card below names the rule, the document it came " +
        "from, the person who owns it, and the measurement that decides it."
      ));

      d.rejected.forEach(function (p) {
        var details = el("details", { open: true }, [
          el("summary", null, [p.label + " ", chip("rejected", "bad")])
        ]);
        p.conflicts.forEach(function (c) {
          details.appendChild(el("h3", { text: "Minimal conflict set: " + c.constraint_ids.join(", ") }));
          details.appendChild(el("p", { text: c.production_language }));
          details.appendChild(pairs([
            ["Explanation", c.explanation],
            ["Minimal", c.minimal ? "yes — removing any one constraint makes it satisfiable"
                                  : "not reduced"],
            ["All blocking constraints", c.all_blocking_ids.join(", ") || "—"],
            ["Required change", c.required_change || "—"],
            ["Change permitted", c.change_permitted === null || c.change_permitted === undefined
                                 ? "—"
                                 : (c.change_permitted ? "yes" : "no — this rule may not be waived")],
            ["Authority for the change", c.change_authority || "—"]
          ]));
          var evidence = Object.keys(c.evidence || {});
          if (evidence.length) {
            details.appendChild(el("h3", { text: "Source evidence" }));
            details.appendChild(el("ul", { class: "plain" }, evidence.map(function (k) {
              return el("li", null, [el("strong", { text: words(k) + ": " }), c.evidence[k]]);
            })));
          }
        });
        root.appendChild(details);
      });
    });
  };

  /** The surveyed route, drawn as the graph it is.
   *
   *  Columns are breadth-first distance from the arrival point, so the picture
   *  reads left to right the way a person walks it. An edge that fails the
   *  step-free requirement is drawn red and carries the measurement that failed
   *  — a location manager can act on "140 mm cill"; nobody can act on
   *  "accessibility concern".
   */
  function routeDiagram(d) {
    var a = d.assessment;
    var nodes = d.nodes, edges = d.edges;
    var index = {};
    nodes.forEach(function (n) { index[n.node_id] = n; });

    var adjacency = {};
    edges.forEach(function (e) {
      (adjacency[e.a] = adjacency[e.a] || []).push(e.b);
      (adjacency[e.b] = adjacency[e.b] || []).push(e.a);
    });

    var layer = {}, queue = [a.arrival_node || nodes[0].node_id];
    layer[queue[0]] = 0;
    while (queue.length) {
      var current = queue.shift();
      (adjacency[current] || []).forEach(function (next) {
        if (layer[next] === undefined) { layer[next] = layer[current] + 1; queue.push(next); }
      });
    }
    nodes.forEach(function (n) { if (layer[n.node_id] === undefined) layer[n.node_id] = 0; });

    var columns = {};
    nodes.forEach(function (n) {
      (columns[layer[n.node_id]] = columns[layer[n.node_id]] || []).push(n);
    });
    var depths = Object.keys(columns).map(Number).sort(function (x, y) { return x - y; });

    var W = 940, colW = W / Math.max(1, depths.length), rowH = 116;
    var tallest = Math.max.apply(null, depths.map(function (k) { return columns[k].length; }));
    var H = Math.max(280, tallest * rowH + 80);
    var at = {};
    depths.forEach(function (k, ci) {
      columns[k].sort(function (x, y) { return x.node_id < y.node_id ? -1 : 1; });
      columns[k].forEach(function (n, ri) {
        at[n.node_id] = {
          x: colW * ci + colW / 2,
          y: 46 + (H - 76) * ((ri + 0.5) / columns[k].length)
        };
      });
    });

    var svg = sv("svg", {
      viewBox: "0 0 " + W + " " + H, role: "img",
      "aria-label": "Surveyed route graph for " + d.location.location_id + ". " +
                    edges.length + " surveyed segments between " + nodes.length +
                    " points. The same measurements are in the edge table below."
    });
    svg.appendChild(sv("desc", {
      text: a.step_free_satisfied
        ? "A step-free route exists from the arrival point to the working position."
        : "No step-free route exists from the arrival point to the working position. " +
          "Failing segments are drawn in red with the measurement that failed."
    }));

    // Lines, then boxes, then labels. Painting order is the whole trick here:
    // the first version drew each edge's label with the edge, so the node boxes
    // that came afterwards covered half of them — "threshold 140 mm" sat behind
    // BS-MAIN-DOOR and could not be read at all. Labels are collected and
    // appended last so they sit above everything.
    var labels = [];
    edges.forEach(function (e) {
      var p = at[e.a], q = at[e.b];
      if (!p || !q) return;
      svg.appendChild(sv("line", {
        x1: p.x, y1: p.y, x2: q.x, y2: q.y,
        stroke: e.step_free ? "var(--ok)" : "var(--bad)",
        "stroke-width": e.step_free ? 2.5 : 4,
        "stroke-dasharray": e.step_free ? null : "9 5"
      }));
      var mx = (p.x + q.x) / 2, my = (p.y + q.y) / 2;
      labels.push(haloText(mx, my - 8, e.edge_id +
                           (e.step_free ? " · " + num(e.metres, 0) + " m" : ""),
                           e.step_free ? "var(--ink-muted)" : "var(--bad)",
                           e.step_free ? "400" : "700"));
      if (!e.step_free && e.step_free_reason) {
        labels.push(haloText(mx, my + 13, shortReason(e.step_free_reason), "var(--bad)", "400"));
      }
    });

    nodes.forEach(function (n) {
      var p = at[n.node_id];
      var isArrival = n.node_id === a.arrival_node;
      var isWorking = n.node_id === a.working_node;
      var fill = isWorking ? "var(--graph-1)" : (isArrival ? "var(--graph-3)" : "var(--surface)");
      svg.appendChild(sv("rect", {
        x: p.x - 62, y: p.y - 17, width: 124, height: 34, rx: 8,
        fill: fill, stroke: "var(--line-strong)", "stroke-width": 1.5
      }));
      svg.appendChild(sv("text", {
        x: p.x, y: p.y - 2, "text-anchor": "middle", "font-size": 11.5, "font-weight": "700",
        fill: (isWorking || isArrival) ? "var(--accent-ink)" : "var(--graph-ink)",
        text: n.node_id
      }));
      svg.appendChild(sv("text", {
        x: p.x, y: p.y + 11, "text-anchor": "middle", "font-size": 10,
        fill: (isWorking || isArrival) ? "var(--accent-ink)" : "var(--ink-muted)",
        text: isArrival ? "arrival · " + words(n.kind)
            : isWorking ? "working position" : words(n.kind)
      }));
    });
    labels.forEach(function (label) { svg.appendChild(label); });
    return svg;
  }

  renderers.spatial = function (root) {
    var location = state.spatialLocation || "LOC-BOATSHED";
    return get("/api/spatial/" + encodeURIComponent(location)).then(function (d) {
      clear(root);
      var a = d.assessment;
      var here = (d.location && d.location.name) || location;

      root.appendChild(headline(
        a.step_free_satisfied ? "ok" : "bad",
        a.step_free_satisfied
          ? "A step-free route to the working position exists at " + here + "."
          : "No step-free route to the working position exists at " + here + ".",
        a.step_free_satisfied
          ? "Surveyed and within every limit, so this location does not remove any option."
          : (a.step_free_blockers || []).length + " surveyed segments fail, and no compliant " +
            "alternate working position was surveyed. This is what C-ACC-001 measures."
      ));

      var select = el("select", { id: "spatial-select" },
        d.locations.map(function (id) {
          return el("option", { value: id, selected: id === location, text: id });
        }));
      select.addEventListener("change", function () {
        state.spatialLocation = select.value;
        state.loaded.spatial = false;
        show("spatial");
      });
      root.appendChild(el("div", { class: "toolbar" }, [
        el("div", { class: "field" }, [
          el("label", { for: "spatial-select", text: "Location" }), select
        ])
      ]));

      root.appendChild(el("div", { class: "cards" }, [
        card("Step-free route", a.step_free_satisfied ? "satisfied" : "not satisfied",
             a.step_free_satisfied ? "surveyed and within limits"
                                   : "no compliant route from arrival to working position"),
        card("Walk", num(a.walk_minutes, 1) + " min",
             num(a.walk_metres, 0) + " m, " + num(a.uncovered_metres, 0) + " m uncovered"),
        card("Heavy equipment", a.heavy_equipment_route_found ? "route found" : "no route",
             num(a.equipment_minutes, 1) + " min"),
        card("Egress routes", String(a.egress_route_count),
             "fastest " + num((a.egress_minutes || [0])[0], 1) + " min")
      ]));

      root.appendChild(figure(routeDiagram(d),
        "The surveyed graph, laid out by walking distance from the arrival point. " +
        "Red segments fail the step-free requirement and carry the measurement that " +
        "failed it."));
      root.appendChild(legend([
        ["Arrival point", "var(--graph-3)"],
        ["Working position", "var(--graph-1)"],
        ["Step-free segment", "var(--ok)"],
        ["Fails the requirement", "var(--bad)"]
      ]));

      if ((a.step_free_blockers || []).length) {
        root.appendChild(el("h2", { text: "Why the step-free route fails" }));
        root.appendChild(el("ul", { class: "plain" }, a.step_free_blockers.map(function (b) {
          return el("li", null, [chip("blocked", "bad"), " ", b]);
        })));
        root.appendChild(el("p", { class: "evidence",
          text: "Each line is the measurement that failed and the limit it failed against. " +
                "A location manager can act on a threshold height; they cannot act on " +
                "“accessibility concern”." }));
      }

      root.appendChild(el("h2", { text: "The survey" }));
      root.appendChild(table(
        "Edges at " + location,
        ["Edge", "From", "To", "Metres", "Gradient", "Clear width mm", "Threshold mm",
         "Steps", "Step-free"],
        d.edges.map(function (e) {
          return [e.edge_id, e.a, e.b, num(e.metres, 1),
                  e.gradient ? "1:" + Math.round(1 / Math.abs(e.gradient)) : "level",
                  num(e.clear_width_mm), num(e.threshold_mm), e.steps,
                  e.step_free ? chip("yes", "ok") : chip("no", "bad")];
        }),
        [null, null, null, "num", null, "num", "num", "num", null]
      ));

      root.appendChild(tableDetails("Points at " + location, table(
        "Nodes at " + location,
        ["Node", "Kind", "Name", "Covered", "Capacity", "Notes"],
        d.nodes.map(function (n) {
          return [n.node_id, words(n.kind), n.name,
                  n.covered ? "yes" : "no", n.capacity || "—", n.notes || "—"];
        }),
        [null, null, null, null, "num", null]
      )));
    });
  };

  renderers.approval = function (root) {
    return get("/api/approval").then(function (d) {
      clear(root);
      if (!d.selected) {
        root.appendChild(headline("warn", "No plan reached approval for this disruption.",
          "Nothing was published, so there was nothing to authorise."));
        return;
      }
      var p = d.selected;
      root.appendChild(headline(
        "ok",
        "Authorised by " + d.approvals.length + " named " +
        (d.approvals.length === 1 ? "person" : "people") + ", not by the system.",
        "Each signature is bound to this plan's hash and to the constraint-set hash in " +
        "force when it was given. It is single use and it expires. Change either hash and " +
        "the approval no longer applies, and execution stops."
      ));

      root.appendChild(el("div", { class: "panel" }, [
        el("h2", { text: p.label }),
        el("p", { text: p.rationale }),
        pairs([
          ["Plan hash", el("code", { text: p.plan_hash })],
          ["Constraint set hash", el("code", { text: d.constraint_hash })],
          ["Delay", num(p.objectives.delay_minutes) + " min"],
          ["Incremental cost", num(p.objectives.cost_delta)],
          ["Overtime", num(p.objectives.overtime_minutes) + " min"],
          ["Changed assignments", p.objectives.changed_assignments],
          ["Required authorities", d.required_roles.map(words).join(", ")]
        ])
      ]));

      root.appendChild(el("h2", { text: "Signed approvals" }));
      root.appendChild(table(
        "Approvals granted",
        ["Role", "Actor", "Scope", "Expires", "Bound to plan", "Signature"],
        d.approvals.map(function (a) {
          return [words(a.role), a.actor, a.approved_scope, clock(a.expires_at),
                  el("code", { text: a.plan_hash.slice(0, 16) }),
                  el("code", { text: (a.signature || "").slice(0, 16) })];
        })
      ));

      root.appendChild(el("h2", { text: "What this authorises" }));
      root.appendChild(el("div", { class: "cards" }, [
        card("Commands", String(p.command_set.length), "typed, and no others"),
        card("Verification checks", String(p.verification_checklist.length),
             "run before the day may be called ready")
      ]));
      root.appendChild(el("div", { class: "panel" }, [
        el("h3", { text: "Command set" }),
        el("ul", { class: "plain" }, p.command_set.map(function (c) {
          return el("li", null, [el("code", { text: c })]);
        })),
        el("h3", { text: "Verification plan" }),
        el("ol", null, p.verification_checklist.map(function (c) {
          return el("li", { text: c });
        }))
      ]));
    });
  };

  renderers.execution = function (root) {
    return Promise.all([get("/api/execution"), get("/api/findings")]).then(function (both) {
      var d = both[0], f = both[1];
      clear(root);
      var v = d.verification;
      var completed = d.commands.filter(function (c) { return c.status === "completed"; }).length;

      root.appendChild(headline(
        d.blocked_then_resolved ? "warn" : (v && v.ready ? "ok" : "bad"),
        d.blocked_then_resolved
          ? "Every command completed — and the day was still refused."
          : (v && v.ready ? "Verified ready." : "Not ready."),
        d.blocked_then_resolved
          ? "All " + completed + " commands returned success and every acknowledgment came " +
            "back. Verification blocked anyway, on a department that had not accepted its " +
            "task. There is no override; it cleared only when the acceptance arrived."
          : (v ? v.passed + " of " + v.total + " assertions pass." : "")
      ));

      root.appendChild(flow([
        { name: "Commands", note: completed + " of " + d.commands.length + " completed", tone: "ok" },
        { name: "Acknowledgments", note: "returned by every target system", tone: "ok" },
        { name: "Reconcile", note: "intended state compared with observed", tone: "ok" },
        // Amber, not red, and the note says why: this step blocked and then
        // cleared. Red beside a green "Ready" reads as a contradiction rather
        // than as the sequence it is.
        { name: "Verify",
          note: (d.blocked_then_resolved ? "blocked once, then " : "") +
                (v ? v.passed + " of " + v.total + " assertions" : "—"),
          tone: d.blocked_then_resolved ? "warn" : (v && v.ready ? "ok" : "bad") },
        { name: "Ready", note: v && v.ready ? "all critical assertions pass" : "withheld",
          tone: v && v.ready ? "ok" : "bad" }
      ]));

      root.appendChild(el("div", { class: "cards" }, [
        card("Commands", String(d.commands.length), completed + " completed"),
        card("Verification", v ? (v.ready ? "ready" : "blocked") : "—",
             v ? v.passed + " of " + v.total + " assertions pass" : "",
             "emphatic"),
        card("Blocked then resolved", d.blocked_then_resolved ? "yes" : "no",
             d.blocked_then_resolved
               ? "a real missing acceptance held readiness back"
               : "nothing outstanding"),
        card("Duplicate commands suppressed", String(d.inbox_suppressed),
             "by the consumer inbox")
      ]));

      if (v) {
        root.appendChild(el("h2", { text: "Verification assertions" }));
        root.appendChild(table(
          "Verification assertions",
          ["", "Assertion", "Expected", "Observed", "Critical"],
          v.assertions.map(function (a) {
            return [chip(a.passed ? "pass" : "fail", a.passed ? "ok" : (a.critical ? "bad" : "warn")),
                    a.name, a.expected, a.observed, a.critical ? "yes" : "no"];
          })
        ));
        if (v.blocking.length) {
          root.appendChild(el("h3", { text: "Blocking" }));
          root.appendChild(el("ul", { class: "plain" }, v.blocking.map(function (b) {
            return el("li", null, [chip("blocking", "bad"), " ", b]);
          })));
        }
      }

      root.appendChild(el("h2", { text: "Commands issued" }));
      root.appendChild(table(
        "Command execution",
        ["Target system", "Action", "Status", "Version", "Depends on", "Result"],
        d.commands.map(function (c) {
          return [words(c.target), c.action,
                  chip(c.status, statusTone(c.status)),
                  c.system_version === null ? "—" : c.system_version,
                  c.depends_on.length ? String(c.depends_on.length) + " command(s)" : "none",
                  c.error ? c.error + " — " + c.detail : c.detail];
        }),
        [null, null, null, "num", null, null]
      ));

      root.appendChild(el("h2", { text: "The reasoning plane" }));
      var r = f.reasoning || {};
      root.appendChild(el("div", { class: "cards" }, [
        card("Plane", r.plane || f.reasoning_plane, r.model || "deterministic templates"),
        card("Calls", num(r.calls || 0), "to the model plane this run"),
        card("Rejected as ungrounded", String(r.responses_rejected_as_ungrounded || 0),
             (r.rejected_claims && r.rejected_claims.length)
               ? r.rejected_claims.join(", ") : "no response carried an unsupported token"),
        card("Findings", String(f.findings.length), "typed, with evidence")
      ]));
      root.appendChild(el("p", { class: "evidence",
        text: "Every response from the model plane is read for identifiers and " +
              "measurements that do not appear in the facts it was given. One " +
              "that carries an invented constraint id or an invented threshold " +
              "is discarded and the deterministic text is used instead. An " +
              "abstention is recorded as an abstention — an agent with nothing " +
              "to say does not manufacture a finding. No model output reaches the " +
              "feasibility decision at all." }));

      root.appendChild(tableDetails(
        "Expert findings — " + f.findings.length + " assessments",
        table(
          "Findings from the parallel expert assessment",
          ["Agent", "Domain", "Status", "Headline", "Constraints cited"],
          f.findings.map(function (x) {
            return [words(x.producer.replace(/_agent$/, "")),
                    words(x.domain),
                    chip(x.status, statusTone(x.status)),
                    x.headline,
                    x.applicable_constraints.join(", ") || "—"];
          })
        )
      ));
    });
  };

  renderers.departments = function (root) {
    return get("/api/departments").then(function (d) {
      clear(root);
      var outstanding = d.tasks.filter(function (t) { return t.accepted !== true; }).length;
      root.appendChild(headline(
        outstanding ? "warn" : "ok",
        outstanding ? outstanding + " department task(s) still outstanding."
                    : "Every department has accepted its task.",
        "Each task states what changed, why it matters and the exact action — because a " +
        "department that is told a call time moved cannot tell whether its own work changed."
      ));
      root.appendChild(table(
        "Department tasks",
        ["Department", "What changed", "Why it matters", "Required action", "Deadline", "Accepted"],
        d.tasks.map(function (t) {
          return [words(t.department), t.what_changed, t.why, t.action, t.deadline,
                  t.accepted === null ? chip("awaiting", "warn")
                                      : chip(t.accepted ? "accepted" : "rejected",
                                             t.accepted ? "ok" : "bad")];
        })
      ));

      root.appendChild(el("h2", { text: "Messages issued" }));
      d.messages.forEach(function (m) {
        root.appendChild(el("details", null, [
          el("summary", null, [m.subject + " — " + m.recipient_id + " ",
                               m.requires_ack ? chip("acknowledgment required", "warn") : ""]),
          el("p", { class: "mono", text: m.body }),
          pairs([
            ["Role", words(m.recipient_role)],
            ["Channel", m.channel],
            ["Language", m.language],
            ["Accessible formats", m.accessible_formats.join(", ")],
            ["Classification", words(m.classification)],
            ["Derived from", m.derived_from.join(", ")]
          ])
        ]));
      });
    });
  };

  renderers.crew = function (root) {
    var person = state.crewPerson || "CAST-001";
    return get("/api/crew/" + encodeURIComponent(person)).then(function (d) {
      clear(root);
      var v = d.view;

      root.appendChild(headline(
        "ok",
        "One person, one call, and nothing they did not need to be sent.",
        "This is the whole record " + person + " receives. It is built by the redaction " +
        "layer, so what a role may not see is never serialised — not hidden with CSS."
      ));

      var select = el("select", { id: "crew-select" }, d.people.map(function (p) {
        return el("option", { value: p, selected: p === person, text: p });
      }));
      select.addEventListener("change", function () {
        state.crewPerson = select.value;
        state.loaded.crew = false;
        show("crew");
      });
      root.appendChild(el("div", { class: "toolbar" }, [
        el("div", { class: "field" }, [
          el("label", { for: "crew-select", text: "Person" }), select
        ])
      ]));

      root.appendChild(el("div", { class: "panel" }, [
        el("h2", { text: "Call sheet revision " + (v.revision || 2) }),
        pairs([
          ["Call time", clock(v.call_time)],
          ["Location", v.location],
          ["Transport", v.transport || "no change"],
          ["Required action", v.required_action || "none"],
          ["Safety instruction", v.safety_instruction || "none"],
          ["Escalation", v.escalation_contact],
          ["Acknowledgment", d.acknowledged ? "received" : "outstanding"]
        ])
      ]));

      if ((v.access_arrangement || []).length) {
        root.appendChild(el("h2", { text: "Practical arrangements in place" }));
        root.appendChild(el("ul", { class: "plain" }, v.access_arrangement.map(function (a) {
          return el("li", null, [
            el("strong", { text: a.requirement }),
            el("p", { class: "evidence", text: a.mechanism })
          ]);
        })));
        root.appendChild(el("div", { class: "note-block" }, [
          "What is shown is the arrangement and the mechanism that delivers it. " +
          "There is no field anywhere in this system that records why a person " +
          "needs one, and the redaction layer counts any attempt to add one."
        ]));
      }

      if (d.message) {
        root.appendChild(el("h2", { text: "Message issued" }));
        root.appendChild(el("div", { class: "panel", lang: d.message.language }, [
          el("h3", { text: d.message.subject }),
          el("p", { class: "mono", text: d.message.body }),
          el("p", { class: "evidence",
            text: "Available in: " + d.message.accessible_formats.join(", ") })
        ]));
      }
    });
  };

  renderers.executive = function (root) {
    return get("/api/executive").then(function (d) {
      clear(root);
      var p = d.portfolio;

      root.appendChild(headline(
        "ok",
        p.disruptions_handled + " disruption(s) this shift, " +
        pct(p.access_preservation_rate) + " of approved arrangements preserved.",
        "Aggregate only. Prohibited personal fields found in this payload: " +
        (d.prohibited_fields_found.length ? d.prohibited_fields_found.join(", ") : "none") +
        ". That check runs on every request rather than being asserted once."
      ));

      root.appendChild(el("div", { class: "cards" }, [
        card("Disruptions handled", num(p.disruptions_handled),
             p.closed + " closed, " + p.held_for_a_reason + " held for a stated reason"),
        card("Schedule impact", num(p.total_delay_minutes) + " min",
             num(p.total_overtime_minutes) + " min overtime across the shift"),
        card("Cost impact", num(p.total_cost_delta),
             "cumulative, against the baseline day"),
        card("Options refused", num(p.options_refused),
             "plans that broke a hard rule and were never offered"),
        card("Access preserved",
             p.access_arrangements_preserved + " of " + p.access_arrangements_checked,
             pct(p.access_preservation_rate) + " across every disruption", "emphatic"),
        card("Decision time", num(p.median_decision_ms) + " ms",
             "median; slowest " + num(p.slowest_decision_ms) + " ms")
      ]));

      if (d.constraint_pressure && d.constraint_pressure.length) {
        root.appendChild(el("h2", { text: "What is removing your options" }));
        root.appendChild(el("div", { class: "note-block" }, [
          "Ranked by how often each rule was the reason an option could not be " +
          "used. This is the list to spend money against: a second interpreter, " +
          "a ramp, a later curfew. Each row names the person who owns the rule " +
          "and the document it comes from, so the next conversation has somewhere " +
          "to start."
        ]));
        var worst = Math.max.apply(null, d.constraint_pressure.map(function (c) {
          return c.times_binding;
        }).concat([1]));
        root.appendChild(el("div", { class: "panel" },
          d.constraint_pressure.map(function (c) {
            return el("div", { class: "metric", style: "margin-bottom:0.6rem" }, [
              el("span", { class: "m-name" }, [
                el("code", { text: c.constraint_id }), " " + c.title +
                " — " + words(c.owner || "unowned")
              ]),
              el("span", { class: "m-value" }, [
                String(c.times_binding) + "× ",
                c.waivable === null || c.waivable === undefined ? chip("—", "quiet")
                  : (c.waivable ? chip("waivable with authority", "warn")
                                : chip("may not be waived", "bad"))
              ]),
              el("div", { class: "m-bar bar" }, [
                el("span", { style: "width:" + ((c.times_binding / worst) * 100).toFixed(1) +
                                    "%;background:var(--bad)" })
              ])
            ]);
          })
        ));
        root.appendChild(tableDetails("Constraint pressure — sources and owners", table(
          "Constraints ranked by how often they were binding",
          ["Constraint", "Times binding", "Rule", "Owner", "Source", "Waivable"],
          d.constraint_pressure.map(function (c) {
            return [
              el("code", { text: c.constraint_id }),
              c.times_binding,
              c.title,
              words(c.owner || "—"),
              c.source || "—",
              c.waivable === null ? "—"
                : (c.waivable ? chip("with authority", "warn")
                              : chip("no", "bad"))
            ];
          }),
          [null, "num", null, null, null, null]
        )));
      }

      root.appendChild(el("h2", { text: "Every disruption this shift" }));
      root.appendChild(table(
        "Disruptions handled, most recent first",
        ["When", "Disruption", "Family", "Severity", "Plans", "Refused",
         "Delay", "Cost", "Access", "State"],
        (d.timeline || []).map(function (t) {
          return [
            clock(t.at), t.title, words(t.family), t.severity,
            t.feasible_plans, t.rejected_plans,
            num(t.delay_minutes), num(t.cost_delta), t.access,
            chip(words(t.state), t.ready ? "ok" : "warn")
          ];
        }),
        [null, null, null, null, "num", "num", "num", "num", null, null]
      ));

      root.appendChild(el("h2", { text: "This disruption" }));
      var m = d.metrics;
      root.appendChild(el("div", { class: "cards" }, [
        card("Decision latency", num(m.decision_latency_ms) + " ms",
             "source event to verified readiness"),
        card("Solver latency", num(m.solver_latency_ms) + " ms", "plan generation only"),
        card("Acknowledgment", pct(m.acknowledgment_completion), "of required responses"),
        card("Assertions", m.assertions_passed + " of " + m.assertions_total,
             "verification checks passing")
      ]));
    });
  };

  renderers.replay = function (root) {
    return get("/api/replay").then(function (d) {
      clear(root);
      root.appendChild(headline(
        d.replay.identical && d.hash_chain.intact ? "ok" : "bad",
        d.replay.identical
          ? "Replaying " + num(d.replay.replayed_events) + " events into a fresh view " +
            "reproduces live state exactly."
          : "Replay does not reproduce live state.",
        d.hash_chain.intact
          ? "The hash chain is intact: no historical event has been altered. Every screen " +
            "in this product is a fold over this log, which is why the log is the thing " +
            "worth checking."
          : d.hash_chain.problems.join("; ")
      ));

      root.appendChild(el("div", { class: "cards" }, [
        card("Events", num(d.timeline.length), "in this disruption's log"),
        card("Replay", d.replay.identical ? "identical" : "differs",
             num(d.replay.replayed_events) + " events replayed into a fresh view", "emphatic"),
        card("Hash chain", d.hash_chain.intact ? "intact" : "broken",
             d.hash_chain.intact ? "no historical event has been altered"
                                 : d.hash_chain.problems.join("; ")),
        card("Lineage", num(d.lineage.nodes) + " downstream",
             "depth " + d.lineage.depth + " from the source event")
      ]));

      root.appendChild(el("h2", { text: "Coordinator steps" }));
      root.appendChild(flow(d.steps.map(function (s) {
        return { name: words(s.state), note: s.detail + " (" + num(s.elapsed_ms, 1) + " ms)" };
      })));

      root.appendChild(el("h2", { text: "Event log" }));
      root.appendChild(table(
        "Every event, in sequence",
        ["#", "Type", "Producer", "Authority", "Class", "Emitted", "Effective", "Summary"],
        d.timeline.map(function (e) {
          // Two clocks, deliberately. Most events take effect when they are
          // emitted and carry no separate effective time; the ones that do are
          // the bitemporal cases — a forecast issued now for 18:30, a fact
          // backdated to when it actually became true.
          return [e.sequence, el("code", { text: e.event_type }), e.producer,
                  e.authority, words(e.classification),
                  clock(e.event_time),
                  e.effective_time ? clock(e.effective_time)
                                   : el("span", { class: "quiet-cell", text: "as emitted" }),
                  e.summary];
        }),
        ["num", null, null, null, null, null, null, null]
      ));
      root.appendChild(el("p", { class: "evidence",
        text: "Emitted is when the event was published; Effective is when the fact " +
              "it records became true. They differ only where the production " +
              "records make them differ — a forecast issued at 17:12 for an 18:30 " +
              "arrival, an availability change backdated to when it happened. " +
              "The twin stores both, which is what lets replay reconstruct what " +
              "was known at a moment rather than only what is known now." }));
    });
  };

  renderers.streams = function (root) {
    return get("/api/streams").then(function (d) {
      clear(root);
      root.appendChild(headline(
        "ok",
        d.summary.governed_by_contract + " of " + d.summary.topics +
        " subjects are governed by a registered data contract.",
        "Backbone " + d.backbone + ", registry " + d.registry + ". Every payload is " +
        "validated before it is appended, duplicates are suppressed on write, and what " +
        "fails goes to a dead-letter queue rather than into the twin."
      ));

      root.appendChild(el("div", { class: "cards" }, [
        card("Backbone", d.backbone, "same interface as Confluent Cloud"),
        card("Schema registry", d.registry,
             d.summary.contracts + " contracts governing " +
             d.summary.governed_by_contract + " of " + d.summary.topics + " subjects"),
        card("Events", num(d.total_events), "published in this run"),
        card("Dead letters", String(d.dead_letters.length),
             d.duplicates_suppressed + " duplicate(s) suppressed on write")
      ]));

      root.appendChild(el("h2", { text: "Stream catalogue" }));
      root.appendChild(table(
        "Stream catalogue",
        ["Domain", "Topic", "Owner", "Classification", "Compatibility", "Description"],
        d.catalog.map(function (c) {
          return [c.domain, el("code", { text: c.topic }), words(c.owner),
                  words(c.classification), c.compatibility, c.description];
        })
      ));

      root.appendChild(tableDetails("Events by type", table(
        "Event counts",
        ["Topic", "Events"],
        Object.keys(d.event_counts).map(function (k) {
          return [el("code", { text: k }), num(d.event_counts[k])];
        }),
        [null, "num"]
      )));

      if (d.dead_letters.length) {
        root.appendChild(el("h2", { text: "Dead-letter queue" }));
        root.appendChild(table(
          "Dead-lettered events",
          ["Topic", "Category", "Reason"],
          d.dead_letters.map(function (x) { return [x.topic, x.category, x.reason]; })
        ));
        root.appendChild(el("p", { class: "evidence",
          text: "Everything in this queue is a deliberate injection from the corpus — a " +
                "payload that fails its contract, an event whose producer is not " +
                "authorised for its topic. The value of the queue is that everything in " +
                "it is worth reading." }));
      }
    });
  };

  // -- tabs ---------------------------------------------------------------

  var TABS = ["board", "intake", "impact", "plans", "rejected", "spatial", "approval",
              "execution", "departments", "crew", "executive", "replay", "streams"];

  function show(name) {
    state.view = name;
    TABS.forEach(function (key) {
      var tab = document.getElementById("tab-" + key);
      var panel = document.getElementById("panel-" + key);
      var active = key === name;
      tab.setAttribute("aria-selected", active ? "true" : "false");
      tab.tabIndex = active ? 0 : -1;
      panel.hidden = !active;
    });
    var root = document.getElementById(name + "-content");
    if (state.loaded[name]) return;
    root.className = "loading";
    root.textContent = "Loading…";
    renderers[name](root).then(function () {
      state.loaded[name] = true;
      root.className = "";
      // A pending notice outranks "view loaded". Running a new disruption
      // announces its outcome and then reloads the view, and the reload's
      // announcement used to overwrite the result inside the same second —
      // so a screen-reader user heard "Control board loaded" and never heard
      // how many plans were feasible. Found by driving the real page; see
      // tools/ui_smoke.py.
      if (state.notice) {
        announce(state.notice);
        state.notice = null;
      } else {
        announce(document.getElementById("tab-" + name).textContent + " loaded.");
      }
    }).catch(function (err) {
      root.className = "";
      clear(root);
      root.appendChild(el("p", null, [chip("error", "bad"), " ", err.message]));
      announce("Could not load this view: " + err.message);
    });
  }

  function wireTabs() {
    TABS.forEach(function (key, index) {
      var tab = document.getElementById("tab-" + key);
      tab.addEventListener("click", function () { show(key); });
      tab.addEventListener("keydown", function (event) {
        var next = null;
        if (event.key === "ArrowDown" || event.key === "ArrowRight") next = (index + 1) % TABS.length;
        else if (event.key === "ArrowUp" || event.key === "ArrowLeft") next = (index - 1 + TABS.length) % TABS.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = TABS.length - 1;
        if (next === null) return;
        event.preventDefault();
        var target = document.getElementById("tab-" + TABS[next]);
        show(TABS[next]);
        target.focus();
      });
    });
  }

  function wireControls() {
    var select = document.getElementById("scenario-select");
    var run = document.getElementById("run-scenario");
    var size = document.getElementById("text-size");

    size.addEventListener("click", function () {
      var on = size.getAttribute("aria-pressed") === "true";
      size.setAttribute("aria-pressed", on ? "false" : "true");
      document.documentElement.setAttribute("data-textsize", on ? "normal" : "large");
      announce(on ? "Standard text size." : "Large text size.");
    });

    run.addEventListener("click", function () {
      var id = select.value;
      run.disabled = true;
      announce("Running " + id + " through the full workflow…");
      fetch("/api/disruptions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario_id: id })
      }).then(function (r) { return r.json(); }).then(function (d) {
        state.loaded = {};
        state.crewPerson = null;
        state.spatialLocation = null;
        state.notice = d.title + " — " + d.feasible_plans + " feasible plan(s), " +
                       d.rejected_plans + " rejected, " + d.events + " events.";
        announce(state.notice);
        show(state.view);
      }).catch(function (err) {
        announce("Could not run that disruption: " + err.message);
      }).then(function () { run.disabled = false; });
    });

    return get("/api/intake").then(function (d) {
      d.library.forEach(function (s) {
        select.appendChild(el("option", {
          value: s.scenario_id, selected: s.scenario_id === d.active,
          text: s.title + " (" + words(s.family) + ")"
        }));
      });
    });
  }

  function boot() {
    wireTabs();
    wireControls();
    get("/api/about").then(function (d) {
      document.getElementById("about-line").textContent =
        d.production + " — reasoning plane: " + d.reasoning_plane +
        ", event backbone: " + d.event_backbone +
        ", " + d.constraints + " constraints (hash " + d.constraint_hash.slice(0, 12) + ").";
    });
    show("board");
  }

  // The guided demo drives this client rather than a copy of it, so it needs
  // the same entry points a person uses and nothing more. Nothing here can
  // approve, execute or override anything; `show` changes which view is on
  // screen and `state` reports which one that is.
  window.AllAccess = {
    show: function (name) { return show(name); },
    view: function () { return state.view; },
    reload: function () { state.loaded = {}; show(state.view); }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
