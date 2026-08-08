# The problem, in other people's words

Everything in this document comes from outside this project: trade press,
industry practitioners, professional service terms, and the people who do the
work. It exists because a system should be able to show that the problem it
solves is one somebody actually has.

Each section names the operational fact, then the part of ProductionPulse that
acts on it.

---

## 1. A lost shooting day is expensive, and disruption is normal

Weather disruption alone is estimated to cost a production **up to $500,000 a
day**, because the crew, the location and the rented equipment are all still
being paid while nothing is shot ([Filmustage, via
VisualCrossing](https://www.visualcrossing.com/resources/blog/managing-the-impact-of-weather-on-film-productions/)).
**85% of productions face scheduling hurdles**, and **43% of projects go over
budget** ([Filmustage](https://filmustage.com/blog/the-impact-of-weather-on-shooting-schedules-and-how-to-plan/)).
A single $20m production in Atlanta ran **$8m over** in part because summer
weather delays and the union overtime they triggered were not planned for
([ELEMENT CPAs](https://elementcpas.com/film-production-budgeting-mistakes-that-cost-millions/)).

The interesting number is not the daily cost. It is that overruns concentrate
where a delay *cascades* — weather into overtime, overtime into penalty rates.

**In this system.** Every plan carries `overtime_minutes` and `cost_delta` as
first-class objectives computed from the working-hours policy, not estimated
afterwards, and the executive view accumulates them across the shift. The
constraint-pressure table ranks the rules that removed the most options, which
is the difference between "the day was hard" and "the curfew at the harbour wall
cost us three options — renegotiate it."

---

## 2. The person whose job this is exists, and is doing it by hand

The role of **production accessibility coordinator** has emerged in the last few
years. Their published duties include identifying and removing access barriers
before they arise, and — the line that matters most here —

> "adapt Access Plans as necessary with **changing production and accommodation
> needs**"

along with ensuring "interpreters, personal care assistants, and other
Accessibility personnel are present and prepared" and maintaining "access spaces
like wheelchair pathways and sensory relief space"
([IndieVISIBLE Entertainment](https://www.indievisibleentertainment.com/production-accessibility-coordinators)).

That is a description of continuously re-validating a set of approved
arrangements against a schedule that keeps moving — performed manually, under
time pressure, by one person who is not in the room when the schedule changes.

Coordinators are reported to produce "fewer health and safety issues and more
efficient production processes," yet are "often seen as a luxury rather than a
necessity" ([TheWrap](https://www.thewrap.com/hollywoods-disability-coordinators-streamline-production-expand-access/)).

**In this system.** The access coordinator's approved arrangements are hard
constraints in the solver. When the schedule moves, they are re-checked
automatically as part of deciding whether the new schedule is a plan at all —
not re-checked afterwards by whoever remembers to. `C-ACC-001` through
`C-ACC-006` name the coordinator as owner and the approved arrangement as source,
so when one binds, the system says whose rule it is.

---

## 3. Access needs get absorbed by the people who have them

Actor Daryl Mitchell supplied his own wheelchair-accessible trailer rather than
request an accommodation. Accommodations sought by performers are frequently
modest — "a sign language interpreter, the opportunity to sit down and proximity
to a bathroom" — and fear of disclosure suppresses the requests that are made
([TheWrap](https://www.thewrap.com/hollywoods-disability-coordinators-streamline-production-expand-access/),
[Nolo](https://www.nolo.com/legal-encyclopedia/defying-gravity-and-discrimination-wicked-actress-puts-disability-rights-in-the-spotlight.html)).

Representation figures give the scale of the surrounding problem: roughly **95%
of disabled characters are played by non-disabled performers**
([Ruderman Family Foundation / Nielsen–RespectAbility, via
Variety](https://variety.com/2021/tv/news/nielsen-respectability-study-disability-tv-film-1235028966/)).

**In this system.** Two design decisions follow directly. First, an arrangement
is a property of the production's approved plan, not a favour a person has to
re-request every time the schedule moves — so it cannot be quietly dropped and
then re-asked-for. Second, there is **no field anywhere in the schema for why a
person needs an arrangement**: not a diagnosis, not a condition, not a category.
A system that stores a reason creates a disclosure the person did not choose,
and fear of disclosure is precisely what suppresses requests. The transport
coordinator is told "step-free transport; accessible vehicle VEH-ACC-1 with
powered lift" and nothing else, because dispatching a lift does not require
knowing why.

---

## 4. Interpreter bookings are governed by notice, not goodwill

Sign language interpreting agencies typically enforce a **48-hour or two
business day cancellation window**, billing the full originally-scheduled time
inside it. Requests with **less than five business days' notice** commonly incur
a rush premium and under 24 hours an urgent premium; multi-day assignments can
require **ten business days'** notice. A two-hour minimum is standard regardless
of time used ([Associates in Sign Language](https://aslmo.com/policies/),
[Sign Language Studios](https://www.signlanguagestudiosllc.com/interpreter-rates-and-policies),
[LinguaBee](https://www.linguabee.com/2018/09/5-costly-mistakes-to-avoid-when-booking-a-sign-language-interpreter/)).

This is the single clearest case of an access arrangement that is a **hard
scheduling constraint with a notice period**, not a soft preference. A schedule
change made at 18:00 for a 09:00 call cannot extend an interpreter booking, and
no amount of willingness changes that.

**In this system.** `C-ACC-002` requires interpretation covering **every called
minute** of the performer's day and is checked against the actual booking
window and the actual named interpreter's availability. A plan that extends a
call past the booked coverage is not published as a worse plan — it is not
published. When no compliant alternative exists, the disruption ends with the
named conflict set: *"the interpreter booking cannot be extended with the notice
available."* That is a real sentence about a real commercial term.

A defect found while building this: a confirmed booking whose registered
interpreter was reported unavailable still counted as coverage. Booking records
and people are now checked separately.

---

## 5. The call sheet is the failure point, and everyone knows it

> "One wrong digit in a call time or one mistyped address can derail an entire
> morning."
> — [Beverly Boy Productions](https://beverlyboy.com/film-technology/call-sheets-decoded-what-crew-should-check-first/)

Outdated information is the canonical call sheet defect: days blend together, a
location or a weather line goes unchanged, and the document ships. Guidance is
uniformly procedural — have a second AD check it, double-check before sending —
which is to say the control is a human remembering
([Filmustage](https://filmustage.com/blog/the-call-sheet-a-production-lifeline/),
[HowToFilmSchool](https://howtofilmschool.com/call-sheet-dos-and-donts/)).
The recommended mitigation is "cloud-based scheduling software with version
control and notification systems" ([Jungle
Software](https://junglesoftware.com/movie-magic-scheduling-alternative/)) —
which distributes the document faster without checking whether it is right.

**In this system.** The call sheet is not authored and sent; it is *derived from
an approved plan* and published by a typed, idempotent command carrying the plan
version. Republishing the same revision is suppressed rather than duplicated. And
distribution is not the end of the transaction: reconciliation compares intended
state against what each downstream system reports, and the day cannot be declared
ready while a department has not accepted. Sending is not landing.

---

## 6. What the industry does not currently have

Nothing found in the trade material describes a tool that:

- computes the **cross-department consequence** of a schedule change, rather than
  showing the change;
- **proves** a revised schedule satisfies the production's hard constraints
  before offering it;
- treats **approved access arrangements as hard constraints** the optimiser
  cannot trade against a saved hour;
- explains **why no option exists** with the measurement and the owning person;
- **verifies that a decision arrived** everywhere it was supposed to, and refuses
  to close the day until it did.

`docs/COMPARISON.md` sets this against what the incumbent tools actually do.

---

## Sources

- [Managing the Impact of Weather on Film Productions — VisualCrossing](https://www.visualcrossing.com/resources/blog/managing-the-impact-of-weather-on-film-productions/)
- [The Impact of Weather on Shooting Schedules — Filmustage](https://filmustage.com/blog/the-impact-of-weather-on-shooting-schedules-and-how-to-plan/)
- [The Call Sheet: A Production Lifeline — Filmustage](https://filmustage.com/blog/the-call-sheet-a-production-lifeline/)
- [Film Production Budgeting Mistakes That Cost Millions — ELEMENT CPAs](https://elementcpas.com/film-production-budgeting-mistakes-that-cost-millions/)
- [Production Accessibility Coordinators — IndieVISIBLE Entertainment](https://www.indievisibleentertainment.com/production-accessibility-coordinators)
- [Hollywood's Disability Coordinators Streamline Production, Expand Access — TheWrap](https://www.thewrap.com/hollywoods-disability-coordinators-streamline-production-expand-access/)
- [ADA Accommodations for Disabled Actors — Nolo](https://www.nolo.com/legal-encyclopedia/defying-gravity-and-discrimination-wicked-actress-puts-disability-rights-in-the-spotlight.html)
- [Nielsen/RespectAbility disability representation study — Variety](https://variety.com/2021/tv/news/nielsen-respectability-study-disability-tv-film-1235028966/)
- [Interpreter policies — Associates in Sign Language](https://aslmo.com/policies/)
- [Interpreter Rates and Policies — Sign Language Studios](https://www.signlanguagestudiosllc.com/interpreter-rates-and-policies)
- [5 Costly Mistakes When Requesting an Interpreter — LinguaBee](https://www.linguabee.com/2018/09/5-costly-mistakes-to-avoid-when-booking-a-sign-language-interpreter/)
- [Call Sheets Decoded — Beverly Boy Productions](https://beverlyboy.com/film-technology/call-sheets-decoded-what-crew-should-check-first/)
- [Call Sheet Do's and Don'ts — HowToFilmSchool](https://howtofilmschool.com/call-sheet-dos-and-donts/)
- [Movie Magic Scheduling Alternative — Jungle Software](https://junglesoftware.com/movie-magic-scheduling-alternative/)
