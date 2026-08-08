# Privacy and data minimisation

Implemented in `src/productionpulse/execution/privacy.py`. Measured by the
`inclusion_and_privacy` block of `bench/results/summary.json`. Every claim below
either names the code that enforces it or the artifact that measures it.

---

## 1. The design decision this document exists to explain

A production system that schedules around people's access requirements has to
know something about those people. The question is *what*, and this system's
answer is: **the operational fact, never the reason for it.**

`AccessRequirement` in `src/productionpulse/production/world.py` carries a
practical arrangement, its approving role, its mechanism, and the roles allowed
to see it. It has no field for a diagnosis, a condition, a category of
impairment, or an explanation. There is nowhere in the schema to put one, which
is a stronger guarantee than a policy saying nobody should.

So the transport coordinator is told:

> ACC-001 — step-free transport and a step-free route from vehicle to working
> position. Mechanism: accessible vehicle VEH-ACC-1 with powered lift.

They are not told why, because dispatching a lift-equipped vehicle does not
require knowing why, and the difference between those two sentences is the whole
of this section.

`PROHIBITED_CHANGES["infer_condition"]` in the constraint registry states the
same rule as an enforced decision boundary: the system does not infer or record
a reason for an access requirement, and no role can approve it doing so.

---

## 2. Three enforcement mechanisms

### 2.1 Audience clearance

`ROLE_CLEARANCE` maps each role to the most sensitive classification it may
receive. `redact()` removes anything above that level rather than trusting each
call site to remember.

| Classification | Who may receive it |
|---|---|
| `PERSONAL` | UPM, production coordinator |
| `OPERATIONAL_REQUIREMENT` | access coordinator, safety lead, first AD, location manager, transport coordinator, department heads, crew |
| `PRODUCTION_INTERNAL` | everyone, including the executive view |

The executive view is capped at `PRODUCTION_INTERNAL` deliberately. Personal
detail there serves no decision anyone at that level makes, and "the executive
can see everything" is how a data model becomes a disclosure.

### 2.2 Per-requirement visibility

`AccessRequirement.visible_to` names the roles for a specific arrangement, and
it is narrower than the clearance level for most of them. ACC-004 (refrigerated
storage) is visible to three roles; ACC-002 (interpretation) is visible to five,
because the first AD and the safety lead have to schedule around it.

A role not on the list has the arrangement **removed**, not summarised. There is
no "an access arrangement applies to this person" placeholder, because that
placeholder is itself a disclosure — it tells a reader there is something to
know about a named person, which is most of what they wanted.

The person → requirement edge in the twin carries the same classification, so
redaction removes the *relationship*, not just the label on it. A graph that
hides the label but keeps the edge has not hidden anything.

### 2.3 Prohibited fields

`PROHIBITED_FIELDS` is a tripwire, not a filter for expected data: no code in
this system populates any of these keys. If a future change ever introduces one,
it is stripped before serialisation and the strip is counted.

`prohibited_field_occurrences` in the benchmark summary is that count across
every event of every scenario. It is currently **0 across 52,775 events**.

> **A finding worth keeping.** The bare key `condition` was on this list
> originally. Every weather event carries `condition: storm_force`, so the
> tripwire fired on all 125 weather scenarios — a tripwire that fires on every
> forecast is one somebody switches off inside a week. It now names the medical
> senses explicitly (`medical_condition`, `health_condition`). This was found by
> running the metric across the corpus, which is the argument for having the
> metric.

---

## 3. Data separation

| Store | Contains | Reachable from |
|---|---|---|
| Twin facts classified `PERSONAL` | names, rates, availability windows, turnaround | the coordinator and the solver, in process |
| Twin facts classified `OPERATIONAL_REQUIREMENT` | approved arrangements and their mechanisms | agents with the matching authority |
| Event payloads | whatever the producer put there, validated against a contract that declares a classification per subject | anyone consuming the topic, after `redact()` |
| Executive aggregates | counts and durations | the executive view |

The classification travels on the event envelope, so a consumer can enforce it
without reading the payload, and the data contract for each subject declares the
classification of the subject as a whole. A producer that publishes personal data
to a subject not declared for it fails contract validation and is dead-lettered
rather than delivered.

`personal_events_to_unauthorised_audience` measures the case that matters most —
a `PERSONAL`-classified event produced by the executive reporting path. It is
**0 across the corpus**.

---

## 4. What a crew member sees about themselves

`GET /api/crew/{person_id}` returns that person's own call, their own
arrangements and the messages addressed to them. It does not return other
people's arrangements at any classification. This is checked by
`tests/test_workflow.py`.

Nobody, at any role, can see *why* an arrangement exists, because that fact is
not recorded anywhere in the system — including for the person themselves, who
knows it already and did not learn it here.

---

## 5. Limits of what is measured

Stated plainly, because a privacy document that implies more coverage than it has
is worse than none.

- **The corpus is authored and fictional.** Every person in it is invented. No
  real personal data has ever been in this system, so the measurements
  demonstrate that the mechanisms fire, not that they have protected anyone.
- **`prohibited_field_occurrences` counts keys, not meaning.** A free-text note
  that described someone's condition in prose would not be caught by a key-based
  tripwire. The mitigation is structural — there is no free-text field on an
  access requirement — but the metric does not prove it.
- **Redaction is enforced at the serialisation boundary**, not by the type
  system. A future code path that reads the twin directly and writes its own
  response would bypass `redact()`. `tests/test_workflow.py` covers the paths
  that exist today.
- **No formal privacy review, DPIA or legal assessment has been performed.**
