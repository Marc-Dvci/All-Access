"""Explaining why a plan cannot work.

When the engine rejects a plan, it owes the production an answer of the form
"these three specific rules cannot all hold, here is where each of them comes
from, and here is what would have to change." That is a *minimal conflict set*,
and computing one is a different problem from detecting a violation.

The implementation is QuickXplain (Junker, 2004), which finds a minimal
conflicting subset in O(log) calls to the consistency check relative to the naive
approach. The naive approach — drop one constraint at a time and re-check —
would also work at this scale, but it returns the constraints in registry order
rather than the ones that actually interact, and the difference shows up
immediately in the quality of the explanation.

`minimal` on the returned `ConflictSet` records whether the reduction actually
completed. If the call budget runs out the set is still a genuine conflict, just
not proven minimal, and it says so. Claiming minimality you did not verify is
exactly the kind of thing this project does not do.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Callable, Sequence

from ..contracts import ConflictSet, ConstraintRecord, ConstraintViolation, Role
from ..production import spatial as sp
from ..production import world as w
from .model import CandidatePlan, SchedulingProblem

#: Maximum consistency checks one explanation may cost.
DEFAULT_CHECK_BUDGET = 400


class _Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def spend(self) -> bool:
        self.used += 1
        return self.used <= self.limit

    @property
    def exhausted(self) -> bool:
        return self.used > self.limit


def quickxplain(
    background: Sequence[ConstraintRecord],
    candidates: Sequence[ConstraintRecord],
    consistent: Callable[[Sequence[ConstraintRecord]], bool],
    budget: _Budget | None = None,
) -> tuple[list[ConstraintRecord], bool]:
    """Minimal subset of `candidates` that is inconsistent with `background`.

    Returns the subset and whether minimality was actually established.
    """
    bud = budget or _Budget(DEFAULT_CHECK_BUDGET)
    if not candidates:
        return [], True
    if not bud.spend():
        return list(candidates), False
    if consistent(list(background) + list(candidates)):
        return [], True  # not actually a conflict
    result, proven = _qx(list(background), list(background), list(candidates), consistent, bud)
    return result, proven and not bud.exhausted


def _qx(
    background: list[ConstraintRecord],
    delta: list[ConstraintRecord],
    candidates: list[ConstraintRecord],
    consistent: Callable[[Sequence[ConstraintRecord]], bool],
    budget: _Budget,
) -> tuple[list[ConstraintRecord], bool]:
    if delta and not budget.spend():
        return candidates, False
    if delta and not consistent(background):
        return [], True
    if len(candidates) == 1:
        return list(candidates), True
    if budget.exhausted:
        return list(candidates), False

    split = len(candidates) // 2
    first, second = candidates[:split], candidates[split:]
    d1, ok1 = _qx(background + first, first, second, consistent, budget)
    d2, ok2 = _qx(background + d1, d1, first, consistent, budget)
    return d2 + d1, ok1 and ok2


# ---------------------------------------------------------------------------
# Turning a conflict set into production language
# ---------------------------------------------------------------------------


def _plain(violations: list[ConstraintViolation]) -> str:
    """One sentence a first AD would actually say.

    Joined from the violation messages rather than the constraint titles,
    because the message carries the measurement and the title carries only the
    category.
    """
    if not violations:
        return "The plan does not satisfy the active constraints."
    if len(violations) == 1:
        return violations[0].message + "."
    heads = [v.message for v in violations[:3]]
    joined = "; ".join(heads)
    if len(violations) > 3:
        joined += f"; and {len(violations) - 3} further conflict(s)"
    return joined + "."


def _also_blocking(minimal_ids: set[str], all_ids: list[str]) -> str:
    """A sentence naming the constraints beyond the minimal explanation."""
    from ..constraints.registry import CONSTRAINTS_BY_ID  # local: avoids a cycle

    extra = [cid for cid in all_ids if cid not in minimal_ids]
    if not extra:
        return ""
    titles = "; ".join(
        f"{cid} ({CONSTRAINTS_BY_ID[cid].title})"
        for cid in extra if cid in CONSTRAINTS_BY_ID
    )
    return f" This plan also breaks {len(extra)} further constraint(s): {titles}."


def _required_change(
    conflict: list[ConstraintRecord],
    violations: list[ConstraintViolation],
    plan: CandidatePlan,
    problem: SchedulingProblem,
) -> tuple[str | None, bool | None, Role | None]:
    """What would have to change for this plan to become feasible, and whether
    anyone is permitted to make that change.

    The second half is the important one. Several of the changes that would
    "fix" a rejected plan are changes the system must never propose — removing
    an approved access arrangement, waiving a child-performer limit, overriding
    a safety threshold. Naming the change and then saying plainly that it is not
    permitted is more useful than pretending no change exists.
    """
    ids = {c.constraint_id for c in conflict}
    from ..constraints.registry import PROHIBITED_CHANGES  # local: avoids a cycle

    if ids & {"C-ACC-001", "C-ACC-002", "C-ACC-003", "C-ACC-005", "C-ACC-006"}:
        return (
            "This plan could only proceed by setting aside an approved access arrangement. "
            + PROHIBITED_CHANGES["remove_access_arrangement"],
            False,
            None,
        )
    if ids & {"C-CHILD-001", "C-CHILD-002", "C-CHILD-003"}:
        return (
            "This plan could only proceed by exceeding a configured child performer limit. "
            + PROHIBITED_CHANGES["override_child_limit"],
            False,
            None,
        )
    if "C-SAFE-001" in ids or "C-SAFE-002" in ids:
        return (
            "This plan requires exterior or on-water work in conditions the safety plan "
            "prohibits. " + PROHIBITED_CHANGES["waive_safety_control"],
            False,
            Role.SAFETY_LEAD,
        )
    if "C-PERM-002" in ids:
        subject = next((v.subject_id for v in violations
                        if v.constraint_id == "C-PERM-002"), "the permit")
        return (
            f"A variation to {subject} lifting the setup cutoff would be required, from the "
            "issuing authority, before the cutoff passes.",
            True,
            Role.LOCATION_MANAGER,
        )
    if "C-PERM-001" in ids:
        return ("A permit valid for the proposed window would be required.", True,
                Role.LOCATION_MANAGER)
    if "C-HOUR-001" in ids:
        return ("UPM approval for an extended day would be required, within the configured "
                "maximum.", True, Role.UPM)
    if "C-HOUR-002" in ids:
        return ("A later call the following day, restoring the minimum turnaround.", True,
                Role.UPM)
    if "C-RES-001" in ids or "C-RES-002" in ids:
        subject = next((v.subject_id for v in violations
                        if v.constraint_id in ("C-RES-001", "C-RES-002")), "the resource")
        eq = w.EQUIPMENT_BY_ID.get(subject)
        alternatives = [
            w.EQUIPMENT_BY_ID[s].name for s in (eq.substitutes if eq else ())
            if s in w.EQUIPMENT_BY_ID
        ]
        if alternatives:
            return (
                f"A substitute for {eq.name if eq else subject} "
                f"({', '.join(alternatives)}) or a revised time for one of the scenes.",
                True, Role.UPM,
            )
        return (
            f"Releasing {eq.name if eq else subject} from its other assignment, or moving "
            "one of the two scenes.",
            True, Role.UPM,
        )
    if "C-TIME-001" in ids:
        return ("A start time inside the required daylight or darkness window.", True,
                Role.FIRST_AD)
    if "C-CONT-001" in ids or "C-CONT-002" in ids:
        return ("A scene order that respects the continuity chain.", True,
                Role.DEPARTMENT_HEAD)
    return (None, None, None)


def explain(
    plan: CandidatePlan,
    problem: SchedulingProblem,
    violations: list[ConstraintViolation],
    *,
    budget: int = DEFAULT_CHECK_BUDGET,
) -> ConflictSet:
    """Build a minimal, evidence-backed explanation of why `plan` is rejected."""
    from ..constraints.registry import CONSTRAINTS_BY_ID, evaluate  # local: avoids a cycle

    blocking = [v for v in violations if v.severity == "blocking"]
    if not blocking:
        return ConflictSet(
            constraint_ids=(),
            explanation="No blocking constraint is violated.",
            production_language="This plan is feasible.",
            minimal=True,
        )

    involved_ids = sorted({v.constraint_id for v in blocking})
    involved = [CONSTRAINTS_BY_ID[cid] for cid in involved_ids if cid in CONSTRAINTS_BY_ID]

    def consistent(subset: Sequence[ConstraintRecord]) -> bool:
        found = evaluate(plan, problem, tuple(subset))
        return not any(v.severity == "blocking" for v in found)

    bud = _Budget(budget)
    conflict, minimal = quickxplain([], involved, consistent, bud)
    if not conflict:
        conflict, minimal = involved, False

    conflict_ids = {c.constraint_id for c in conflict}
    relevant = [v for v in blocking if v.constraint_id in conflict_ids]

    evidence: dict[str, str] = {}
    for record in conflict:
        evidence[record.constraint_id] = f"{record.source} -- {record.source_evidence}"
    # Attach the concrete measurement alongside the rule it came from. A route
    # failure that names a doorway width is the difference between an
    # explanation and a citation.
    for v in relevant:
        if v.constraint_id in evidence and v.evidence:
            evidence[v.constraint_id] += f" | observed: {v.evidence}"

    required, permitted, authority = _required_change(conflict, relevant, plan, problem)

    titles = ", ".join(f"{c.constraint_id} ({c.title})" for c in conflict)
    explanation = (
        f"{len(conflict)} constraint(s) cannot be satisfied together: {titles}."
        if minimal
        else f"At least {len(conflict)} constraint(s) conflict: {titles}. "
             "Minimality was not established within the check budget."
    )

    return ConflictSet(
        constraint_ids=tuple(sorted(conflict_ids)),
        all_blocking_ids=tuple(involved_ids),
        explanation=explanation,
        production_language=_plain(relevant) + _also_blocking(conflict_ids, involved_ids),
        evidence=evidence,
        minimal=minimal,
        required_change=required,
        change_permitted=permitted,
        change_authority=authority,
    )


def spatial_evidence(location_id: str) -> dict[str, str]:
    """Access-survey evidence for a location, for attaching to an explanation."""
    assessment = sp.assess_location_access(location_id)
    if not assessment.get("modelled"):
        return {}
    out = {
        "step_free_route": str(assessment.get("step_free_route")),
        "egress_routes": str(assessment.get("egress_route_count")),
    }
    blockers = assessment.get("step_free_blockers") or []
    for i, blocker in enumerate(blockers[:3], start=1):
        out[f"blocker_{i}"] = str(blocker)
    return out


def near_miss(
    plan: CandidatePlan,
    problem: SchedulingProblem,
    violations: list[ConstraintViolation],
) -> str | None:
    """How close a rejected plan came, when the answer is 'not by much'.

    A coordinator reading "the interpreter booking ends 25 minutes before wrap"
    can act on it. "Infeasible" sends them looking for a different location.
    """
    for v in violations:
        if v.severity != "blocking":
            continue
        if v.constraint_id == "C-ACC-003" and "gap_start" in v.detail:
            from datetime import datetime as _dt
            gap_start = _dt.fromisoformat(str(v.detail["gap_start"]))
            gap_end = _dt.fromisoformat(str(v.detail["gap_end"]))
            minutes = (gap_end - gap_start).total_seconds() / 60.0
            if minutes <= 120:
                return (
                    f"Interpretation is short by {minutes:.0f} minutes "
                    f"({gap_start:%H:%M}-{gap_end:%H:%M}). An extension may close this."
                )
        if v.constraint_id == "C-PERM-002":
            return (
                "The permit setup cutoff is the only timing conflict; an earlier setup or a "
                "permit variation would resolve it."
            )
        if v.constraint_id == "C-HOUR-001" and "span" in v.detail:
            span = float(v.detail["span"])
            limit = float(v.detail.get("limit", 0.0))
            if span - limit <= 60:
                return (
                    f"The day is {span - limit:.0f} minutes over the limit; trimming one "
                    "setup would bring it inside."
                )
    return None


def scene_shortfall(problem: SchedulingProblem, scene_id: str,
                    available_minutes: float) -> str:
    """A readable statement of how much time a scene is short by."""
    req = problem.requirements.get(scene_id)
    if req is None:
        return f"{scene_id} is not in scope"
    needed = req.total_minutes
    short = needed - available_minutes
    if short <= 0:
        return f"{scene_id} fits in the available window"
    return (
        f"{scene_id} needs {needed} min (setup {req.setup_minutes} + shoot "
        f"{req.shoot_minutes}) and has {available_minutes:.0f} min: short by "
        f"{short:.0f} min"
    )


def window_for(problem: SchedulingProblem, scene_id: str) -> tuple[str, str]:
    """The earliest and latest a scene could legally run, as strings."""
    req = problem.requirements.get(scene_id)
    if req is None:
        return ("", "")
    if req.night_required:
        return (f"{w.CIVIL_DUSK:%H:%M}", f"{w.CIVIL_DAWN + timedelta(days=1):%H:%M}")
    if req.daylight_required:
        return (f"{w.DAYLIGHT_SUNRISE:%H:%M}", f"{w.DAYLIGHT_SUNSET:%H:%M}")
    return (f"{problem.horizon_start:%H:%M}", f"{problem.horizon_end:%H:%M}")
