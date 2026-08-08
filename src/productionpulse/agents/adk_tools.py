"""The tools the hosted Gemini agent is given, and the ADK agent that holds them.

Every function here **reads**. None of them can approve a plan, issue a command,
waive a constraint or declare a day ready. That is the same boundary the rest of
the system enforces in the call graph — `engine.publish` takes its verdict from
`engine.validate`, never from a model — expressed here as the only capabilities
the model plane is handed in the first place.

The tools read the application's own read model over HTTP (`/api/*`), which
means three things worth stating:

1. **They see exactly what the product's own views see.** There is no separate
   "agent database" that can drift from what a human is shown, and no query path
   into the twin that bypasses redaction. `/api/crew/{id}` is built through
   `execution/privacy.py`, so a tool asking about a person gets the minimum
   necessary record and nothing else.
2. **They cannot write, because the API has no write path for them.** The only
   mutating endpoint is `POST /api/disruptions`, which starts a new scenario, and
   it is not exposed as a tool. Read-only is a property of the surface, not a
   promise in a prompt.
3. **A tool that cannot reach the application says so.** It returns an `error`
   key rather than an empty result, because a model handed `{}` will narrate
   around the hole.

`TOOLS` is the single source of truth for what the agent may do.
`tools/deploy_agent_engine.py` refuses to deploy if it and the allowlist ever
disagree, so the boundary cannot drift by someone adding a function here.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

#: Where the read model lives. The hosted agent is given the deployed service's
#: URL; locally this is the uvicorn process from `docs/JUDGE.md`.
API_BASE = os.environ.get("PP_API_BASE", "http://127.0.0.1:8765")

_TIMEOUT = 15.0


def _get(path: str) -> dict[str, Any]:
    url = f"{API_BASE.rstrip('/')}{path}"
    try:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            return dict(json.loads(response.read().decode("utf-8")))
    except urllib.error.HTTPError as exc:
        return {"error": f"{path} returned {exc.code}", "detail": exc.reason}
    except Exception as exc:  # noqa: BLE001 - the model needs the reason, not a trace
        return {"error": f"could not reach the production read model at {url}",
                "detail": str(exc)[:200]}


# ---------------------------------------------------------------------------
# The tools
#
# Type hints and docstrings are load-bearing: ADK builds the function
# declaration Gemini sees from exactly these, so a vague docstring here becomes
# a tool the model misuses.
# ---------------------------------------------------------------------------


def describe_disruption() -> dict[str, Any]:
    """Return the disruption currently being handled and the state of the day.

    Use this first, for any question about what has happened. Includes the
    disruption's title and workflow state, the size of the digital twin, the
    number of constraints in force, delay and overtime exposure, which access
    arrangements are at risk, and the departments that have not yet accepted
    their revised tasks.
    """
    board = _get("/api/control-board")
    if "error" in board:
        return board
    return {
        "disruption": board.get("disruption"),
        "production": board.get("production"),
        "exposure": board.get("exposure"),
        "departments": board.get("departments"),
        "constraints_in_force": (board.get("constraints") or {}).get("count"),
        "baseline": board.get("baseline"),
    }


def describe_impact() -> dict[str, Any]:
    """Return everything the disruption reaches, grouped by how directly.

    Depth 1 is what the change touched directly; deeper entries were reached
    through intermediaries. This is a wide recall instrument rather than a
    shortlist — say so if you summarise it, and prefer depth 1 and 2 when
    naming consequences to a person.
    """
    impact = _get("/api/impact")
    if "error" in impact:
        return impact
    return {
        "entities_reached": len(impact.get("nodes", [])),
        "max_depth": impact.get("max_depth"),
        "counts_by_depth": impact.get("counts_by_depth"),
        "departments": impact.get("departments"),
        "scenes": impact.get("scenes"),
        "access_requirements": impact.get("access_requirements"),
        "direct_consequences": [
            {"entity_id": n.get("entity_id"), "label": n.get("label"),
             "type": n.get("entity_type"), "reached_via": n.get("path")}
            for n in impact.get("nodes", []) if n.get("depth") == 1
        ][:40],
    }


def describe_plan() -> dict[str, Any]:
    """Return the recovery plans proved feasible, and which one was approved.

    Every plan listed here passed an independent recheck against every hard
    constraint. Report the objectives as trade-offs between plans. Never
    describe a plan as feasible or infeasible on your own judgement — that
    verdict is already in the data and it is not yours to revise.
    """
    plans = _get("/api/plans")
    if "error" in plans:
        return plans
    return {
        "selected_plan_id": plans.get("selected_plan_id"),
        "feasible": [
            {"plan_id": p.get("plan_id"), "label": p.get("label"),
             "strategy": p.get("strategy"), "rationale": p.get("rationale"),
             "objectives": p.get("objectives"), "selected": p.get("selected"),
             "required_approvals": p.get("required_approvals"),
             "access": p.get("access")}
            for p in plans.get("feasible", [])
        ],
        "rejected_count": len(plans.get("rejected", [])),
    }


def describe_conflict_set() -> dict[str, Any]:
    """Return why each rejected plan cannot be used.

    Each rejection carries a *minimal* set of constraints that cannot be
    satisfied together, the measurement that decides it, whether the rule may be
    waived, and who owns it. When explaining a rejection, give the measurement
    and the owner. "Not accessible" is not an explanation a location manager can
    act on; "the threshold is 45 mm against a 25 mm limit" is.
    """
    plans = _get("/api/plans")
    if "error" in plans:
        return plans
    return {
        "rejected": [
            {
                "label": p.get("label"),
                "conflicts": [
                    {"constraint_ids": c.get("constraint_ids"),
                     "production_language": c.get("production_language"),
                     "explanation": c.get("explanation"),
                     "minimal": c.get("minimal"),
                     "required_change": c.get("required_change"),
                     "change_permitted": c.get("change_permitted"),
                     "change_authority": c.get("change_authority")}
                    for c in p.get("conflicts", [])
                ],
            }
            for p in plans.get("rejected", [])
        ],
    }


def describe_access_arrangements() -> dict[str, Any]:
    """Return the approved access arrangements and whether the plan preserves them.

    These are hard constraints with no soft weight: the objective function
    cannot trade one away for a saved hour. Report whether each is preserved and
    by what mechanism.

    Never speculate about why a person requires an arrangement. The system does
    not record a reason, there is no field that could hold one, and inventing
    one would be both wrong and a disclosure.
    """
    plans = _get("/api/plans")
    if "error" in plans:
        return plans
    selected = next(
        (p for p in plans.get("feasible", []) if p.get("selected")), None
    )
    if selected is None:
        return {"selected_plan": None,
                "note": "no plan reached approval for this disruption"}
    return {
        "selected_plan": selected.get("label"),
        "arrangements": selected.get("access"),
        "all_preserved": all(
            a.get("satisfied") for a in selected.get("access", [])
        ),
    }


def summarise_findings() -> dict[str, Any]:
    """Return the expert agents' typed findings, including their abstentions.

    An abstention is a real result: an agent with no evidence records that it
    had none. Do not fill an abstention in with a plausible opinion, and do not
    drop it from a summary — a reader needs to know which questions went
    unanswered.
    """
    findings = _get("/api/findings")
    if "error" in findings:
        return findings
    rows = findings.get("findings", [])
    return {
        "reasoning_plane": findings.get("reasoning_plane"),
        "counts": {
            status: sum(1 for f in rows if f.get("status") == status)
            for status in sorted({str(f.get("status")) for f in rows})
        },
        "findings": [
            {"producer": f.get("producer"), "domain": f.get("domain"),
             "status": f.get("status"), "headline": f.get("headline"),
             "evidence": f.get("evidence"),
             "applicable_constraints": f.get("applicable_constraints")}
            for f in rows
        ],
    }


def draft_role_communication(role: str) -> dict[str, Any]:
    """Return the material for a message to one role, already redacted for them.

    `role` is one of: department_head, coordinator, crew, transport_coordinator,
    access_coordinator, safety_lead, first_ad, location_manager, upm, executive.

    The returned material has already been through the redaction layer for that
    audience. Draft the message from what is returned and from nothing else — do
    not add detail from other tool calls, because the other tools answer for a
    different audience and combining them is how a personal fact reaches someone
    who was never cleared for it.
    """
    normalised = (role or "").strip().lower().replace(" ", "_").replace("-", "_")
    if normalised == "executive":
        payload = _get("/api/executive")
        if "error" in payload:
            return payload
        return {"role": normalised, "audience": "aggregate only",
                "metrics": payload.get("metrics"),
                "constraint": "no personal detail is available at this level"}

    payload = _get("/api/departments")
    if "error" in payload:
        return payload
    return {
        "role": normalised,
        "tasks": payload.get("tasks"),
        "messages": [
            m for m in payload.get("messages", [])
            if not normalised or m.get("recipient_role") == normalised
        ] or payload.get("messages"),
        "constraint": (
            "state what changed, why it matters and the required action; "
            "do not state why any person requires an access arrangement"
        ),
    }


#: The agent's complete capability surface. Read-only, by construction.
TOOLS = (
    describe_disruption,
    describe_impact,
    describe_plan,
    describe_conflict_set,
    describe_access_arrangements,
    summarise_findings,
    draft_role_communication,
)

TOOL_NAMES: frozenset[str] = frozenset(t.__name__ for t in TOOLS)


def build_agent(model: str = "gemini-2.5-flash", *, name: str = "productionpulse_reasoning"):
    """Construct the ADK agent. Requires `google-adk`; see the `cloud` extra.

    Kept separate from `TOOLS` so the tool surface can be tested, and the
    deployment manifest validated, with no cloud dependency installed at all.
    """
    from google.adk.agents import Agent

    from .core import GeminiReasoner

    return Agent(
        name=name,
        model=model,
        description=(
            "Interpretation and explanation plane for ProductionPulse Inclusive. "
            "Explains deterministic decisions; does not make them."
        ),
        instruction=GeminiReasoner.SYSTEM_INSTRUCTION,
        tools=list(TOOLS),
    )
