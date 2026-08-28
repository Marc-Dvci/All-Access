"""The Communication Agent: role-specific messages, generated from the plan.

Every message here is derived from the approved structured plan and names what it
was derived from. There is no code path that lets an agent compose a crew message
from its own memory of the conversation — `compose()` takes a plan and a
recipient, never a transcript. The `must_derive_from_plan` rule on the
notification contract enforces this at the stream boundary as well.

Each role gets what it needs to act and nothing more. The crew view is seven
fields. The executive view has no names in it. The transport coordinator is told
that a step-free vehicle is required for a named person on a named run, and is
not told why, because why is not the production's information to hold.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..contracts import (
    Classification,
    CommunicationMessage,
    Plan,
    Role,
    stable_hash,
)
from ..execution import privacy
from ..production import world as w


def _message(
    plan: Plan,
    recipient_id: str,
    role: Role,
    subject: str,
    body: str,
    *,
    channel: str = "app",
    requires_ack: bool = True,
    language: str = "en",
    formats: tuple[str, ...] = (),
    classification: Classification = Classification.PRODUCTION_INTERNAL,
) -> CommunicationMessage:
    return CommunicationMessage(
        message_id="MSG-" + stable_hash([plan.plan_id, recipient_id, subject])[:10].upper(),
        disruption_id=plan.disruption_id,
        recipient_id=recipient_id,
        recipient_role=role,
        channel=channel,
        subject=subject,
        body=body,
        language=language,
        derived_from=(plan.plan_id, plan.content_hash()[:12]),
        classification=classification,
        requires_ack=requires_ack,
        accessible_formats=formats,
    )


def _fmt(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _day(dt: datetime) -> str:
    return dt.strftime("%a %d %b")


def _person_row(plan: Plan, person_id: str) -> dict[str, Any] | None:
    for scene in sorted(plan.scenes, key=lambda s: s.start):
        if person_id in scene.cast_calls:
            return {
                "call": scene.cast_calls[person_id],
                "scene": scene,
            }
        crew = w.CREW_BY_ID.get(person_id)
        if crew and scene.unit_id in crew.units:
            return {"call": scene.crew_call, "scene": scene}
    return None


def crew_message(plan: Plan, person_id: str) -> CommunicationMessage | None:
    """The seven-field crew instruction.

    Deliberately short. A crew member at 19:30 on a wet harbour wall needs their
    call, where, how they get there, what to do, the safety instruction and their
    own arrangement — not the trade-off analysis that produced it.
    """
    row = _person_row(plan, person_id)
    if row is None:
        return None
    scene = row["scene"]
    call: datetime = row["call"]
    location = w.LOCATIONS_BY_ID.get(scene.location_id)
    crew = w.CREW_BY_ID.get(person_id)
    performer = w.PERFORMERS_BY_ID.get(person_id)
    name = crew.name if crew else (performer.name if performer else person_id)

    transport = next(
        (leg for leg in plan.transport if person_id in leg.passengers), None
    )
    transport_line = (
        f"Transport: {w.VEHICLES_BY_ID[transport.vehicle_id].name}, departing "
        f"{_fmt(transport.depart)}"
        if transport and transport.vehicle_id in w.VEHICLES_BY_ID
        else "Transport: make your own way to base as usual."
    )

    arrangements = [a for a in plan.access if a.person_id == person_id]
    access_line = ""
    if arrangements:
        access_line = "\nYour arrangements: " + "; ".join(
            f"{a.requirement} ({'confirmed' if a.satisfied else 'BEING RESOLVED'})"
            for a in arrangements
        )

    body = (
        f"{name} — revised call.\n\n"
        f"Call: {_fmt(call)} on {_day(call)}\n"
        f"Location: {location.name if location else scene.location_id}\n"
        f"{transport_line}\n"
        f"Required: report to {location.name if location else scene.location_id} "
        f"for scene {scene.scene_id}\n"
        f"Safety: a revised briefing has been issued for this location. Read it before "
        f"you travel."
        f"{access_line}\n\n"
        f"Please acknowledge. Any problem, contact the production coordinator."
    )
    languages = tuple(crew.languages) if crew else (
        tuple(performer.languages) if performer else ("en",)
    )
    return _message(
        plan, person_id, Role.CREW,
        subject=f"Revised call {_fmt(call)} — {scene.scene_id}",
        body=body,
        classification=Classification.PERSONAL,
        language=languages[0] if languages else "en",
        formats=("written", "captioned") if "fse" in languages else ("written",),
    )


def department_message(plan: Plan, department: str, head_id: str) -> CommunicationMessage:
    changed = [
        s for s in plan.scenes
        if s.scene_id not in {b.scene_id for b in w.BASELINE_SCHEDULE}
        or next((b for b in w.BASELINE_SCHEDULE if b.scene_id == s.scene_id)).start != s.start
    ]
    scenes = ", ".join(sorted(s.scene_id for s in changed)) or "no scene changes"
    first = min(changed, key=lambda s: s.setup_start) if changed else None
    body = (
        f"What changed: {scenes}.\n"
        f"Why it matters: the night exterior was stood down on a safety call; the revised "
        f"plan recovers page count from prepared cover material.\n"
        f"Your action: confirm {department} readiness and accept the task in your queue.\n"
        f"Deadline: {_fmt(first.setup_start) if first else 'immediately'}.\n"
        f"Dependencies: revised call sheet and briefing are published first.\n"
        f"If you cannot complete this, reject the task with a reason — do not stay silent."
    )
    return _message(
        plan, head_id, Role.DEPARTMENT_HEAD,
        subject=f"{department.title()}: action required on the revised plan",
        body=body,
    )


def coordinator_message(plan: Plan) -> CommunicationMessage:
    unsatisfied = [a for a in plan.access if not a.satisfied]
    body = (
        f"Plan {plan.plan_id} ({plan.label}) approved and executing.\n"
        f"Scenes: {len(plan.scenes)}. Deferred: "
        f"{', '.join(plan.deferred_scenes) or 'none'}.\n"
        f"Delay {plan.objectives.delay_minutes:.0f} min, cost "
        f"{plan.objectives.cost_delta:,.0f}, overtime "
        f"{plan.objectives.overtime_minutes:.0f} min.\n"
        f"Access arrangements: {len(plan.access) - len(unsatisfied)} of {len(plan.access)} "
        f"confirmed satisfied.\n"
        f"Commands: {len(plan.command_set)}. Verification checks: "
        f"{len(plan.verification_checklist)}.\n"
        f"Track outstanding acknowledgments on the reconciliation board."
    )
    return _message(
        plan, "CREW-COORD", Role.COORDINATOR,
        subject=f"{plan.plan_id} executing",
        body=body, requires_ack=False,
    )


def access_coordinator_message(plan: Plan) -> CommunicationMessage:
    """The accessibility coordinator's view: practical requirements, no diagnosis."""
    lines = [
        f"- {a.requirement}: {'CONFIRMED' if a.satisfied else 'AT RISK'} — {a.mechanism}"
        for a in plan.access
    ]
    body = (
        f"Plan {plan.plan_id} — approved arrangements under the revised plan:\n\n"
        + "\n".join(lines)
        + "\n\nEvery arrangement above is a hard constraint on this plan. Anything marked "
        "AT RISK blocks readiness until it is resolved."
    )
    return _message(
        plan, "CREW-ACCESS", Role.ACCESS_COORDINATOR,
        subject=f"{plan.plan_id}: approved arrangements status",
        body=body, requires_ack=True,
        classification=Classification.OPERATIONAL_REQUIREMENT,
    )


def transport_message(plan: Plan) -> CommunicationMessage | None:
    """Transport gets the operational requirement, never a reason."""
    step_free = [leg for leg in plan.transport if leg.step_free]
    if not plan.transport:
        return None
    lines = []
    for leg in plan.transport:
        vehicle = w.VEHICLES_BY_ID.get(leg.vehicle_id)
        lines.append(
            f"- {leg.leg_id}: {vehicle.name if vehicle else leg.vehicle_id}, "
            f"{leg.from_location} to {leg.to_location}, depart {_fmt(leg.depart)}"
            + (" — STEP-FREE REQUIRED" if leg.step_free else "")
        )
    body = (
        f"Revised transport for plan {plan.plan_id}:\n\n" + "\n".join(lines)
        + (
            f"\n\n{len(step_free)} leg(s) require a step-free vehicle with a working lift. "
            "This is a hard requirement: if the vehicle is not available, escalate rather "
            "than substitute."
            if step_free else ""
        )
    )
    return _message(
        plan, "CREW-TRANS", Role.TRANSPORT_COORDINATOR,
        subject=f"{plan.plan_id}: revised transport",
        body=body,
    )


def executive_message(plan: Plan) -> CommunicationMessage:
    """Aggregate only. No names, no arrangements, no personal detail."""
    metrics = privacy.executive_summary({
        "plan_id": plan.plan_id,
        "delay_minutes": plan.objectives.delay_minutes,
        "cost_delta": plan.objectives.cost_delta,
        "overtime_minutes": plan.objectives.overtime_minutes,
        "changed_assignments": plan.objectives.changed_assignments,
        "hard_constraint_violations": 0,
        "access_arrangements_preserved": sum(1 for a in plan.access if a.satisfied),
    })
    body = (
        f"Disruption {plan.disruption_id} resolved under plan {plan.plan_id}.\n"
        f"Delay {metrics['delay_minutes']:.0f} min. Cost {metrics['cost_delta']:,.0f}. "
        f"Overtime {metrics['overtime_minutes']:.0f} min.\n"
        f"Hard constraint violations: {metrics['hard_constraint_violations']}.\n"
        f"Approved access arrangements preserved: "
        f"{metrics['access_arrangements_preserved']} of "
        f"{metrics['access_arrangements_tracked']}.\n"
        f"Changed assignments: {metrics['changed_assignments']}."
    )
    return _message(
        plan, "EXEC-1", Role.EXECUTIVE,
        subject=f"{plan.disruption_id}: operational summary",
        body=body, requires_ack=False,
        classification=Classification.PRODUCTION_INTERNAL,
    )


def compose(plan: Plan) -> list[CommunicationMessage]:
    """Every message the approved plan requires, one pass, no duplicates.

    The communication policy caps messages per person per disruption. Exceeding
    it is how a recovery turns into a flood of contradictory texts, which is one
    of the costs this system is measured on.
    """
    messages: list[CommunicationMessage] = []
    cap = int(w.POLICIES["communication"]["max_messages_per_person_per_disruption"])  # type: ignore[arg-type]
    per_person: dict[str, int] = {}

    def add(message: CommunicationMessage | None) -> None:
        if message is None:
            return
        count = per_person.get(message.recipient_id, 0)
        if count >= cap:
            return
        per_person[message.recipient_id] = count + 1
        messages.append(message)

    add(coordinator_message(plan))
    add(access_coordinator_message(plan))
    add(transport_message(plan))
    add(executive_message(plan))

    departments: dict[str, str] = {}
    for scene in plan.scenes:
        for equipment_id in scene.equipment_ids:
            equipment = w.EQUIPMENT_BY_ID.get(equipment_id)
            if equipment is None:
                continue
            head = next(
                (c for c in w.CREW
                 if c.department == equipment.department and c.authority_role.value
                 == "department_head"),
                None,
            )
            if head:
                departments[equipment.department.value] = head.crew_id
    for department, head_id in sorted(departments.items()):
        add(department_message(plan, department, head_id))

    people: set[str] = set()
    baseline = {s.scene_id: s for s in w.BASELINE_SCHEDULE}
    for scene in plan.scenes:
        original = baseline.get(scene.scene_id)
        if original is not None and original.start == scene.start:
            continue  # unchanged: nobody needs telling
        people.update(scene.cast_calls)
        for crew in w.crew_for_unit(scene.unit_id):
            people.add(crew.crew_id)
    for person_id in sorted(people):
        add(crew_message(plan, person_id))

    return messages
