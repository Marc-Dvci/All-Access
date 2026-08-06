"""Minimum-necessary disclosure.

The rule this module enforces: a recipient receives the operational fact they
need to do their job, and nothing else. A transport coordinator needs to know
that a step-free vehicle is required for a named person on a named run. They do
not need to know why, and there is nowhere in this system that records why.

Three mechanisms:

* **Audience clearance.** Every role has a maximum classification it may
  receive. `redact()` removes fields above it rather than trusting each call
  site to remember.
* **Per-requirement visibility.** An approved access arrangement names the roles
  that may see it, in `AccessRequirement.visible_to`. A role not on that list
  gets the arrangement removed entirely, not summarised.
* **Prohibited fields.** Some keys must never leave the system regardless of
  audience — anything that would record a reason for an access requirement. They
  are stripped, and the strip is counted, so `docs/PRIVACY.md`'s claim that the
  count is zero is checkable rather than asserted.

`audit` records every redaction, which is what the benchmark's
"unauthorized_field_exposure" metric is computed from.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..contracts import CLASSIFICATION_ORDER, Classification, Role
from ..production import world as w

#: The most sensitive classification each role may receive.
ROLE_CLEARANCE: dict[Role, Classification] = {
    Role.UPM: Classification.PERSONAL,
    Role.COORDINATOR: Classification.PERSONAL,
    Role.ACCESS_COORDINATOR: Classification.OPERATIONAL_REQUIREMENT,
    Role.SAFETY_LEAD: Classification.OPERATIONAL_REQUIREMENT,
    Role.FIRST_AD: Classification.OPERATIONAL_REQUIREMENT,
    Role.LOCATION_MANAGER: Classification.OPERATIONAL_REQUIREMENT,
    Role.TRANSPORT_COORDINATOR: Classification.OPERATIONAL_REQUIREMENT,
    Role.DEPARTMENT_HEAD: Classification.OPERATIONAL_REQUIREMENT,
    # The executive view is aggregate by design. Personal detail there serves no
    # decision anyone at that level makes.
    Role.EXECUTIVE: Classification.PRODUCTION_INTERNAL,
    Role.CREW: Classification.OPERATIONAL_REQUIREMENT,
    Role.SYSTEM: Classification.PRODUCTION_INTERNAL,
}

#: Keys that must never be serialised to any audience. There is no code that
#: populates these — they exist as a tripwire, so that if a future change ever
#: introduces one, it is stripped and counted rather than sent.
#:
#: The bare key `condition` is deliberately *not* on this list. A weather event
#: carries `condition: storm_force`, and a tripwire that fires on every forecast
#: is a tripwire somebody switches off inside a week. The medical senses are
#: named explicitly instead. This was found by running the benchmark's
#: `prohibited_field_occurrences` metric across the corpus, where it read one
#: hit on every weather scenario; see docs/BENCHMARK.md §7.
PROHIBITED_FIELDS: frozenset[str] = frozenset({
    "diagnosis", "medical_condition", "health_condition", "medical_history",
    "impairment", "disability", "medication", "prognosis", "treatment",
    "reason_for_requirement", "health_note", "clinical_note",
})

#: Keys carrying personal data, redacted above their audience's clearance.
FIELD_CLASSIFICATION: dict[str, Classification] = {
    "person_id": Classification.PERSONAL,
    "performer_id": Classification.PERSONAL,
    "crew_id": Classification.PERSONAL,
    "name": Classification.PERSONAL,
    "cast_calls": Classification.PERSONAL,
    "phone": Classification.PERSONAL,
    "email": Classification.PERSONAL,
    "requirement": Classification.OPERATIONAL_REQUIREMENT,
    "mechanism": Classification.OPERATIONAL_REQUIREMENT,
    "access": Classification.OPERATIONAL_REQUIREMENT,
    "access_requirements": Classification.OPERATIONAL_REQUIREMENT,
}


@dataclass
class RedactionAudit:
    removed: list[str] = field(default_factory=list)
    prohibited_removed: list[str] = field(default_factory=list)
    requirements_hidden: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.prohibited_removed

    def summary(self) -> dict[str, Any]:
        return {
            "fields_removed": len(self.removed),
            "prohibited_fields_removed": len(self.prohibited_removed),
            "requirements_hidden": len(self.requirements_hidden),
            "detail": sorted(set(self.removed)),
        }


def may_see(role: Role, classification: Classification) -> bool:
    clearance = ROLE_CLEARANCE.get(role, Classification.PRODUCTION_INTERNAL)
    return CLASSIFICATION_ORDER[classification] <= CLASSIFICATION_ORDER[clearance]


def requirement_visible(requirement_id: str, role: Role) -> bool:
    """Whether a role may see one specific approved arrangement."""
    requirement = w.ACCESS_BY_ID.get(requirement_id)
    if requirement is None:
        return False
    return role in requirement.visible_to


def redact(
    payload: dict[str, Any],
    role: Role,
    *,
    audit: RedactionAudit | None = None,
    path: str = "",
) -> dict[str, Any]:
    """Return a copy of `payload` containing only what `role` may receive."""
    log = audit or RedactionAudit()
    out: dict[str, Any] = {}
    for key, value in payload.items():
        here = f"{path}.{key}" if path else key

        if key in PROHIBITED_FIELDS:
            log.prohibited_removed.append(here)
            continue

        classification = FIELD_CLASSIFICATION.get(key)
        if classification is not None and not may_see(role, classification):
            log.removed.append(here)
            continue

        # An access-requirement id gates on that requirement's own visibility
        # list, not just on the role's clearance level.
        if key == "requirement_id" and isinstance(value, str):
            if not requirement_visible(value, role):
                log.requirements_hidden.append(value)
                return {}

        if isinstance(value, dict):
            out[key] = redact(value, role, audit=log, path=here)
        elif isinstance(value, list):
            cleaned = []
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    reduced = redact(item, role, audit=log, path=f"{here}[{i}]")
                    if reduced:
                        cleaned.append(reduced)
                else:
                    cleaned.append(item)
            out[key] = cleaned
        else:
            out[key] = value
    return out


def access_view(role: Role, audit: RedactionAudit | None = None) -> list[dict[str, Any]]:
    """The approved arrangements a role may see, as operational facts only."""
    log = audit or RedactionAudit()
    out: list[dict[str, Any]] = []
    for requirement in w.ACCESS_REQUIREMENTS:
        if role not in requirement.visible_to:
            log.requirements_hidden.append(requirement.requirement_id)
            continue
        row: dict[str, Any] = {
            "requirement_id": requirement.requirement_id,
            "requirement": requirement.requirement,
            "category": requirement.category,
            "mechanism": requirement.mechanism,
            "critical": requirement.critical,
        }
        # The person is named only to audiences who have to act on their behalf.
        if may_see(role, Classification.PERSONAL):
            row["person_id"] = requirement.person_id
            crew = w.CREW_BY_ID.get(requirement.person_id)
            performer = w.PERFORMERS_BY_ID.get(requirement.person_id)
            row["name"] = crew.name if crew else (performer.name if performer else None)
        out.append(row)
    return out


def executive_summary(metrics: dict[str, Any]) -> dict[str, Any]:
    """Aggregate-only view for the production executive.

    Access arrangements appear as a count and a preserved/at-risk status. Never
    as a list of people, and never as a description of an arrangement.
    """
    audit = RedactionAudit()
    clean = redact(metrics, Role.EXECUTIVE, audit=audit)
    clean["access_arrangements_tracked"] = len(w.ACCESS_REQUIREMENTS)
    clean["_redaction"] = audit.summary()
    return clean


def crew_view(person_id: str, plan_row: dict[str, Any]) -> dict[str, Any]:
    """What one crew member sees. Seven fields, by design.

    Their own call, where, how they get there, what to do, the safety
    instruction, their own access arrangement, and who to call. Nothing about
    anyone else, nothing about cost, nothing about the other options that were
    considered.
    """
    own_requirements = [
        {
            "requirement": r.requirement,
            "mechanism": r.mechanism,
        }
        for r in w.ACCESS_REQUIREMENTS if r.person_id == person_id
    ]
    return {
        "person_id": person_id,
        "call_time": plan_row.get("call_time"),
        "location": plan_row.get("location"),
        "transport": plan_row.get("transport"),
        "required_action": plan_row.get("required_action"),
        "safety_instruction": plan_row.get("safety_instruction"),
        "access_arrangement": own_requirements,
        "acknowledgment_required": True,
        "escalation_contact": "Production coordinator",
        "revision": plan_row.get("revision"),
    }


def check_no_prohibited_fields(payloads: list[dict[str, Any]]) -> list[str]:
    """Scan payloads for anything that should never exist. Used by the benchmark.

    Returns the paths found. The published figure for this is zero, and it is
    zero because there is no code that writes such a field — this proves it
    rather than asserting it.
    """
    found: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                here = f"{path}.{key}" if path else key
                if key in PROHIBITED_FIELDS:
                    found.append(here)
                walk(value, here)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    for payload in payloads:
        walk(payload, "")
    return found
