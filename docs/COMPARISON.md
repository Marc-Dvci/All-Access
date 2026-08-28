# Against what productions use today

The incumbent tools are good at what they do, and what they do is a different
job. This document is specific about where the line falls, using their own
published descriptions.

---

## The three things productions run on

**Movie Magic Scheduling** (Entertainment Partners) is the industry standard,
with a forty-year track record. It turns a script into a breakdown and a digital
stripboard, supports multi-unit and multi-episode work, and includes **red-flag
conflict detection** — it will tell you a cast member is double-booked or unavailable
([Entertainment Partners](https://www.ep.com/movie-magic-scheduling/),
[SoftExpo](https://softexpo.com/softwares/office-productivity/344-movie-magic-scheduling.html)).

**StudioBinder** is the modern cloud equivalent. Breakdown, stripboard,
scheduling, call sheets integrated with the schedule, contacts and locations,
electronic distribution by email and SMS with per-recipient variants and
**delivery tracking on a dashboard** ([StudioBinder](https://www.studiobinder.com/call-sheet-software/)).

**Current practice** is the first AD, the UPM and the production coordinator on
the phone, holding the consequences of a change in their heads and calling the
departments they can think of.

All three are strong at *authoring and distributing a schedule*. None of them
decides whether a revised schedule is **allowed**.

---

## Where the line falls

| | Movie Magic | StudioBinder | Phone + spreadsheet | All-Access |
|---|---|---|---|---|
| Script breakdown, stripboard, scheduling | ● | ● | ○ | ○ |
| Call sheet generation and distribution | ◐ | ● | ◐ | ● |
| Delivery tracking (was it opened / confirmed) | ○ | ● | ○ | ● |
| Resource conflict detection (cast double-booked) | ● | ◐ | ◐ | ● |
| **Cross-department consequence of a change** | ○ | ○ | ◐ *(in someone's head)* | ● |
| **Feasibility proved before an option is offered** | ○ | ○ | ○ | ● |
| **Access arrangements as hard constraints** | ○ | ○ | ○ | ● |
| **Named reason when no option exists** | ○ | ○ | ◐ | ● |
| **Reconciliation of intended vs. observed state** | ○ | ○ | ○ | ● |
| **Replayable decision record** | ○ | ○ | ○ | ● |

● full · ◐ partial · ○ absent

---

## The four differences that matter

### 1. Conflict detection is not feasibility

Movie Magic's red flags catch **resource conflicts**: this actor is in two places,
this location is unavailable. That is real and useful, and it is a different
question from *"does this revised day satisfy the safety thresholds, the permit
conditions, the working-hours policy and the approved access arrangements,
simultaneously?"*

A red flag warns you. It does not stop the schedule being published, and it has
no concept of a rule that may not be waived. All-Access will not publish a
plan it cannot prove satisfies all 34 constraints — and re-checks the finished
plan against the registry independently of the search that produced it. Remove
that recheck and every published plan breaks roughly two hard rules.

### 2. Distribution is not arrival

StudioBinder's dashboard tells you a call sheet was delivered and who confirmed.
That is genuinely ahead of the field. It still stops at the document: it tracks
whether a **message** landed, not whether the **state change** did.

All-Access issues typed commands to each downstream system, then reconciles
the state it intended against the state those systems report, and blocks
readiness on the difference. In the reference run the day was refused because
props had accepted nothing — while every command had completed successfully.
Across 1,000 disruptions, every incomplete execution the harness created was
caught; a system that trusted command acknowledgment would have closed all of
them.

### 3. Nobody else models an access arrangement as a constraint

This is the substantive gap. In Movie Magic and StudioBinder, an approved access
arrangement lives where every other special requirement lives: a note. Notes do
not participate in scheduling. When the schedule moves at 18:00, the note does
not object.

The industry's answer is a **person** — the production accessibility
coordinator, whose published duties include adapting access plans "as necessary
with changing production and accommodation needs"
([IndieVISIBLE](https://www.indievisibleentertainment.com/production-accessibility-coordinators)).
That person is real, skilled, frequently treated as a luxury line item, and not
in the room at 18:00.

All-Access encodes their approved arrangements as hard constraints with no
soft weight. The objective function has no coefficient with which to trade a
step-free route against a saved hour. A plan that drops one is not a worse plan;
it is not a plan. Across 3,630 approved arrangements in the corpus, preservation
is total — and removing the independent recheck drops it to 0.780, which is the
measured cost of treating them as a note.

### 4. "No" without a reason is not an answer

When a scheduling tool cannot resolve something it shows a conflict marker. When
a first AD cannot resolve something they say "we can't do the boatshed."

All-Access returns the **minimal set of constraints that cannot be satisfied
together**, with the measurement that decides it, the document it comes from and
the person who owns it:

> *Ormsvik boatshed has no step-free route from arrival to the working position
> and no surveyed step-free alternate position.*

The boatshed is free, obvious, and exactly what a conventional scheduler would
offer. This one refuses, and says why in a sentence a location manager can act
on — a threshold in millimetres is actionable; "accessibility concern" is not.

---

## What All-Access is not

It does not break down a script, build a stripboard, or replace Movie Magic. It
assumes a schedule already exists and a production already runs on one of these
tools. It is the layer that sits **after** the schedule and **before** the crew:
the thing that decides whether a proposed change to an existing day is allowed,
what it costs across every department, who has to approve it, and whether it
actually happened.

The integration surface reflects that. The call-sheet connector consumes and
republishes revisions with version control and idempotency; the twin is built
from records a production already keeps. Nothing here asks a production to stop
using the tool its ADs know.

---

## Sources

- [Movie Magic Scheduling — Entertainment Partners](https://www.ep.com/movie-magic-scheduling/)
- [Movie Magic Scheduling feature list — SoftExpo](https://softexpo.com/softwares/office-productivity/344-movie-magic-scheduling.html)
- [Movie Magic Scheduling Alternative — Jungle Software](https://junglesoftware.com/movie-magic-scheduling-alternative/)
- [Call Sheet Software — StudioBinder](https://www.studiobinder.com/call-sheet-software/)
- [Production Scheduling Software — StudioBinder](https://www.studiobinder.com/production-scheduling-software-filmmaker/)
- [Production Accessibility Coordinators — IndieVISIBLE Entertainment](https://www.indievisibleentertainment.com/production-accessibility-coordinators)
- [Hollywood's Disability Coordinators — TheWrap](https://www.thewrap.com/hollywoods-disability-coordinators-streamline-production-expand-access/)
