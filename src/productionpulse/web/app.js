/* ProductionPulse Inclusive — the browser client.
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
 */

(function () {
  "use strict";

  var state = { view: "board", loaded: {}, crewPerson: null, spatialLocation: null,
                notice: null };

  // -- tiny DOM helpers ---------------------------------------------------

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    if (attrs) {
      Object.keys(attrs).forEach(function (key) {
        var value = attrs[key];
        if (value === null || value === undefined || value === false) return;
        if (key === "class") node.className = value;
        else if (key === "text") node.textContent = String(value);
        else node.setAttribute(key, value === true ? "" : String(value));
      });
    }
    (children || []).forEach(function (child) {
      if (child === null || child === undefined) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
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

  function chip(label, tone) { return el("span", { class: "chip " + tone, text: label }); }

  function card(title, value, note) {
    return el("div", { class: "card" }, [
      el("h3", { text: title }),
      el("p", { class: "value", text: value }),
      note ? el("p", { class: "note", text: note }) : null
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

  // -- views --------------------------------------------------------------

  var renderers = {};

  renderers.board = function (root) {
    return get("/api/control-board").then(function (d) {
      clear(root);
      document.getElementById("production-line").textContent =
        d.production.title + " — unit " + d.production.unit +
        ", production clock " + clock(d.production.clock);

      root.appendChild(el("div", { class: "cards" }, [
        card("Disruption", d.disruption.state.replace(/_/g, " "), d.disruption.title),
        card("Digital twin", num(d.twin.entities) + " entities",
             num(d.twin.relationships) + " relationships, " +
             num(d.twin.temporal_facts) + " temporal facts"),
        card("Baseline", d.baseline.state, d.baseline.checks + " checks, " +
             d.baseline.issues + " issue(s)"),
        card("Constraint set", num(d.constraints.count) + " constraints",
             "hash " + d.constraints.hash.slice(0, 16)),
        card("Delay exposure", num(d.exposure.delay_minutes) + " min",
             num(d.exposure.overtime_minutes) + " min overtime exposure"),
        card("Access at risk", String(d.exposure.access_at_risk.length),
             d.exposure.access_at_risk.length
               ? d.exposure.access_at_risk.join(", ")
               : "every approved arrangement satisfied")
      ]));

      root.appendChild(el("h2", { text: "Next scenes under the approved plan" }));
      root.appendChild(table(
        "Scenes, in order of call",
        ["Scene", "Slugline", "Location", "Crew call", "Shoot", "Ext."],
        d.next_scenes.map(function (s) {
          return [s.scene_id, s.slugline, s.location, clock(s.crew_call),
                  clock(s.start) + " – " + timeOnly(s.end),
                  s.exterior ? "exterior" : "interior"];
        })
      ));

      root.appendChild(el("h2", { text: "Department readiness" }));
      root.appendChild(table(
        "Department readiness",
        ["Department", "Tasks", "Accepted", "State"],
        d.departments.map(function (r) {
          return [r.department.replace("DEPT-", ""), r.tasks, r.accepted,
                  chip(r.ready ? "ready" : "awaiting acceptance", r.ready ? "ok" : "warn")];
        }),
        [null, "num", "num", null]
      ));

      root.appendChild(el("h2", { text: "Weather and daylight" }));
      root.appendChild(table(
        "Weather windows",
        ["From", "To", "Condition", "Wind kph", "Rain mm", "Sea state"],
        d.weather.map(function (win) {
          return [clock(win.start), clock(win.end), win.condition.replace(/_/g, " "),
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

      root.appendChild(el("h2", { text: "Workflow states traversed" }));
      root.appendChild(el("ol", { class: "plain" }, d.disruption.history.map(function (h) {
        return el("li", null, [
          el("strong", { text: h.state.replace(/_/g, " ") }),
          " — " + h.detail
        ]);
      })));
    });
  };

  renderers.intake = function (root) {
    return get("/api/intake").then(function (d) {
      clear(root);
      root.appendChild(el("div", { class: "cards" }, [
        card("Authority", d.event.authority,
             d.requires_confirmation
               ? "requires human confirmation before it may become effective"
               : "may be acted on directly"),
        card("Confidence", d.confidence === undefined || d.confidence === null
               ? "—" : pct(d.confidence), "as reported by the source"),
        card("Classification", d.event.classification.replace(/_/g, " "),
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

  renderers.impact = function (root) {
    return get("/api/impact").then(function (d) {
      clear(root);
      var counts = d.counts_by_relevance || {};
      var primary = d.primary || {};
      root.appendChild(el("div", { class: "cards" }, [
        card("Act on these", num(counts.primary || 0),
             "of " + num(d.nodes.length) + " reached, across " + d.max_depth + " levels"),
        card("Departments", String((primary.departments || []).length),
             (primary.departments || []).join(", ") || "none directly affected"),
        card("Access arrangements",
             String((primary.access_requirements || []).length),
             (primary.access_requirements || []).join(", ") || "none reached directly"),
        card("Scenes", String((primary.scenes || []).length), "on the shooting day")
      ]));

      root.appendChild(el("div", { class: "note-block" }, [
        "A shooting day is a dense graph: five scenes, three locations, two units " +
        "and one call sheet put almost everything within a few hops of everything " +
        "else. The traversal reports all of it — every labelled consequence in the " +
        "corpus is found — and ranks it, so the screen leads with what to act on " +
        "and keeps the rest one click away."
      ]));

      var byBand = { primary: [], secondary: [], contextual: [] };
      d.nodes.forEach(function (n) {
        (byBand[n.relevance] || byBand.contextual).push(n);
      });

      BANDS.forEach(function (band) {
        var key = band[0], title = band[1], blurb = band[2];
        var nodes = byBand[key];
        if (!nodes.length) return;
        var details = el("details", key === "primary" ? { open: true } : null, [
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
            return [n.entity_id, n.entity_type.replace(/_/g, " "), n.label,
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

  renderers.plans = function (root) {
    return get("/api/plans").then(function (d) {
      clear(root);
      root.appendChild(el("div", { class: "note-block" }, [
        "Every plan below passed an independent recheck of all " +
        d.hard_constraints.length + " hard constraints, run from the finished plan " +
        "rather than from the search that produced it. Objectives are traded off " +
        "against each other; hard constraints are not traded off against anything."
      ]));

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
            ].concat(robustnessCells(p)).concat([p.required_approvals.join(", ")])
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
        details.appendChild(el("h3", { text: "Approved access arrangements under this plan" }));
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
        root.appendChild(el("p", { text: "No plan was rejected for this disruption." }));
        return;
      }
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
              return el("li", null, [el("strong", { text: k + ": " }), c.evidence[k]]);
            })));
          }
        });
        root.appendChild(details);
      });
    });
  };

  renderers.spatial = function (root) {
    var location = state.spatialLocation || "LOC-BOATSHED";
    return get("/api/spatial/" + encodeURIComponent(location)).then(function (d) {
      clear(root);
      var select = el("select", { id: "spatial-select" },
        d.locations.map(function (id) {
          return el("option", { value: id, selected: id === location, text: id });
        }));
      select.addEventListener("change", function () {
        state.spatialLocation = select.value;
        state.loaded.spatial = false;
        show("spatial");
      });
      root.appendChild(el("div", { class: "field" }, [
        el("label", { for: "spatial-select", text: "Location" }), select
      ]));

      var a = d.assessment;
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

      root.appendChild(el("h2", { text: "Surveyed routes" }));
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

      root.appendChild(el("h2", { text: "Nodes" }));
      root.appendChild(table(
        "Nodes at " + location,
        ["Node", "Kind", "Name", "Covered", "Capacity", "Notes"],
        d.nodes.map(function (n) {
          return [n.node_id, n.kind.replace(/_/g, " "), n.name,
                  n.covered ? "yes" : "no", n.capacity || "—", n.notes || "—"];
        }),
        [null, null, null, null, "num", null]
      ));
    });
  };

  renderers.approval = function (root) {
    return get("/api/approval").then(function (d) {
      clear(root);
      if (!d.selected) {
        root.appendChild(el("p", { text: "No plan reached approval for this disruption." }));
        return;
      }
      var p = d.selected;
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
          ["Required authorities", d.required_roles.join(", ")]
        ])
      ]));

      root.appendChild(el("h2", { text: "Signed approvals" }));
      root.appendChild(table(
        "Approvals granted",
        ["Role", "Actor", "Scope", "Expires", "Bound to plan", "Signature"],
        d.approvals.map(function (a) {
          return [a.role.replace(/_/g, " "), a.actor, a.approved_scope, clock(a.expires_at),
                  el("code", { text: a.plan_hash.slice(0, 16) }),
                  el("code", { text: (a.signature || "").slice(0, 16) })];
        })
      ));
      root.appendChild(el("p", { class: "evidence",
        text: "Each approval is single use and bound to both the plan hash and the " +
              "constraint-set hash. If either changes, the approval no longer applies " +
              "and execution stops." }));

      root.appendChild(el("h2", { text: "Command set this approval authorises" }));
      root.appendChild(el("ul", { class: "plain" }, p.command_set.map(function (c) {
        return el("li", null, [el("code", { text: c })]);
      })));

      root.appendChild(el("h2", { text: "Verification plan" }));
      root.appendChild(el("ol", null, p.verification_checklist.map(function (c) {
        return el("li", { text: c });
      })));
    });
  };

  renderers.execution = function (root) {
    return Promise.all([get("/api/execution"), get("/api/findings")]).then(function (both) {
      var d = both[0], f = both[1];
      clear(root);
      var v = d.verification;
      root.appendChild(el("div", { class: "cards" }, [
        card("Commands", String(d.commands.length),
             d.commands.filter(function (c) { return c.status === "completed"; }).length +
             " completed"),
        card("Verification", v ? (v.ready ? "ready" : "blocked") : "—",
             v ? v.passed + " of " + v.total + " assertions pass" : ""),
        card("Blocked then resolved", d.blocked_then_resolved ? "yes" : "no",
             d.blocked_then_resolved
               ? "a real missing acceptance held readiness back"
               : "nothing outstanding"),
        card("Duplicate commands suppressed", String(d.inbox_suppressed),
             "by the consumer inbox")
      ]));

      root.appendChild(table(
        "Command execution",
        ["Target system", "Action", "Status", "Version", "Depends on", "Result"],
        d.commands.map(function (c) {
          return [c.target.replace(/_/g, " "), c.action,
                  chip(c.status, statusTone(c.status)),
                  c.system_version === null ? "—" : c.system_version,
                  c.depends_on.length ? String(c.depends_on.length) + " command(s)" : "none",
                  c.error ? c.error + " — " + c.detail : c.detail];
        }),
        [null, null, null, "num", null, null]
      ));

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

      root.appendChild(el("h2", { text: "Expert findings" }));
      root.appendChild(table(
        "Findings from the parallel expert assessment",
        ["Agent", "Domain", "Status", "Headline", "Constraints cited"],
        f.findings.map(function (x) {
          return [x.producer.replace(/_agent$/, "").replace(/_/g, " "),
                  x.domain.replace(/_/g, " "),
                  chip(x.status, statusTone(x.status)),
                  x.headline,
                  x.applicable_constraints.join(", ") || "—"];
        })
      ));
      var r = f.reasoning || {};
      root.appendChild(el("h2", { text: "Reasoning plane" }));
      root.appendChild(el("div", { class: "panel" }, [
        pairs([
          ["Plane", r.plane || f.reasoning_plane],
          ["Model", r.model || "deterministic templates"],
          ["Calls", num(r.calls || 0)],
          ["Responses rejected as ungrounded",
           String(r.responses_rejected_as_ungrounded || 0)],
          ["Claims rejected",
           (r.rejected_claims && r.rejected_claims.length)
             ? r.rejected_claims.join(", ") : "none"],
          ["Tokens", r.tokens_in ? num(r.tokens_in) + " in / " + num(r.tokens_out) + " out"
                                 : "—"]
        ]),
        el("p", { class: "evidence",
          text: "Every response from the model plane is read for identifiers and " +
                "measurements that do not appear in the facts it was given. One " +
                "that carries an invented constraint id or an invented threshold " +
                "is discarded and the deterministic text is used instead. An " +
                "abstention is recorded as an abstention — an agent with nothing " +
                "to say does not manufacture a finding." })
      ]));
    });
  };

  renderers.departments = function (root) {
    return get("/api/departments").then(function (d) {
      clear(root);
      root.appendChild(table(
        "Department tasks",
        ["Department", "What changed", "Why it matters", "Required action", "Deadline", "Accepted"],
        d.tasks.map(function (t) {
          return [t.department, t.what_changed, t.why, t.action, t.deadline,
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
            ["Role", m.recipient_role.replace(/_/g, " ")],
            ["Channel", m.channel],
            ["Language", m.language],
            ["Accessible formats", m.accessible_formats.join(", ")],
            ["Classification", m.classification.replace(/_/g, " ")],
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
      var select = el("select", { id: "crew-select" }, d.people.map(function (p) {
        return el("option", { value: p, selected: p === person, text: p });
      }));
      select.addEventListener("change", function () {
        state.crewPerson = select.value;
        state.loaded.crew = false;
        show("crew");
      });
      root.appendChild(el("div", { class: "field" }, [
        el("label", { for: "crew-select", text: "Person" }), select
      ]));

      var v = d.view;
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

      root.appendChild(el("h2", { text: "The shift so far" }));
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
             pct(p.access_preservation_rate) + " across every disruption"),
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
        root.appendChild(table(
          "Constraints ranked by how often they were binding",
          ["Constraint", "Times binding", "Rule", "Owner", "Source", "Waivable"],
          d.constraint_pressure.map(function (c) {
            return [
              el("code", { text: c.constraint_id }),
              c.times_binding,
              c.title,
              (c.owner || "—").replace(/_/g, " "),
              c.source || "—",
              c.waivable === null ? "—"
                : (c.waivable ? chip("with authority", "warn")
                              : chip("no", "bad"))
            ];
          }),
          [null, "num", null, null, null, null]
        ));
      }

      root.appendChild(el("h2", { text: "Every disruption this shift" }));
      root.appendChild(table(
        "Disruptions handled, most recent first",
        ["When", "Disruption", "Family", "Severity", "Plans", "Refused",
         "Delay", "Cost", "Access", "State"],
        (d.timeline || []).map(function (t) {
          return [
            clock(t.at), t.title, t.family.replace(/_/g, " "), t.severity,
            t.feasible_plans, t.rejected_plans,
            num(t.delay_minutes), num(t.cost_delta), t.access,
            chip(t.state.replace(/_/g, " "), t.ready ? "ok" : "warn")
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

      root.appendChild(el("div", { class: "note-block" }, [
        "Everything on this screen is aggregate. Prohibited personal fields found " +
        "in this payload: " +
        (d.prohibited_fields_found.length ? d.prohibited_fields_found.join(", ") : "none") +
        ". The check runs on every request rather than being asserted once."
      ]));
    });
  };

  renderers.replay = function (root) {
    return get("/api/replay").then(function (d) {
      clear(root);
      root.appendChild(el("div", { class: "cards" }, [
        card("Events", num(d.timeline.length), "in this disruption's log"),
        card("Replay", d.replay.identical ? "identical" : "differs",
             num(d.replay.replayed_events) + " events replayed into a fresh view"),
        card("Hash chain", d.hash_chain.intact ? "intact" : "broken",
             d.hash_chain.intact ? "no historical event has been altered"
                                 : d.hash_chain.problems.join("; ")),
        card("Lineage", num(d.lineage.nodes) + " downstream",
             "depth " + d.lineage.depth + " from the source event")
      ]));

      root.appendChild(el("h2", { text: "Workflow timeline" }));
      root.appendChild(table(
        "Coordinator steps",
        ["State", "Detail", "Elapsed ms"],
        d.steps.map(function (s) {
          return [s.state.replace(/_/g, " "), s.detail, num(s.elapsed_ms, 1)];
        }),
        [null, null, "num"]
      ));

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
                  e.authority, e.classification.replace(/_/g, " "),
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
      root.appendChild(el("div", { class: "cards" }, [
        card("Backbone", d.backbone, "same interface as Confluent Cloud"),
        card("Schema registry", d.registry,
             d.summary.contracts + " contracts governing " +
             d.summary.governed_by_contract + " of " + d.summary.topics + " subjects"),
        card("Events", num(d.total_events), "published in this run"),
        card("Dead letters", String(d.dead_letters.length),
             d.duplicates_suppressed + " duplicate(s) suppressed on write")
      ]));

      root.appendChild(table(
        "Stream catalogue",
        ["Domain", "Topic", "Owner", "Classification", "Compatibility", "Description"],
        d.catalog.map(function (c) {
          return [c.domain, el("code", { text: c.topic }), c.owner,
                  c.classification.replace(/_/g, " "), c.compatibility, c.description];
        })
      ));

      root.appendChild(el("h2", { text: "Events by type" }));
      root.appendChild(table(
        "Event counts",
        ["Topic", "Events"],
        Object.keys(d.event_counts).map(function (k) {
          return [el("code", { text: k }), num(d.event_counts[k])];
        }),
        [null, "num"]
      ));

      if (d.dead_letters.length) {
        root.appendChild(el("h2", { text: "Dead-letter queue" }));
        root.appendChild(table(
          "Dead-lettered events",
          ["Topic", "Category", "Reason"],
          d.dead_letters.map(function (x) { return [x.topic, x.category, x.reason]; })
        ));
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
          text: s.title + " (" + s.family.replace(/_/g, " ") + ")"
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
