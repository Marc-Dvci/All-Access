"""Turning an approved plan into typed commands.

Every command carries an idempotency key derived from the plan hash and its own
content, so re-issuing the same plan produces the same keys and the inbox
suppresses the duplicates. Dependencies are declared, not implied: the briefing
command depends on the location confirmation, and the crew view depends on the
call sheet, because telling a crew member where to be before the location is
confirmed is a message you have to retract.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from ..contracts import (
    Classification,
    Command,
    Plan,
    Role,
    TargetSystem,
    stable_hash,
    utcnow,
)
from ..production import script as scr
from ..production import world as w


def _key(plan: Plan, target: TargetSystem, action: str, payload: dict[str, Any]) -> str:
    return stable_hash([plan.plan_id, plan.content_hash(), target.value, action, payload])[:24]


def _cmd(
    plan: Plan,
    target: TargetSystem,
    action: str,
    payload: dict[str, Any],
    *,
    version: int,
    depends_on: tuple[str, ...] = (),
    compensation: str | None = None,
    required_role: Role | None = None,
    classification: Classification = Classification.PRODUCTION_INTERNAL,
) -> Command:
    key = _key(plan, target, action, payload)
    return Command(
        command_id=f"CMD-{target.value}-{key[:8]}".upper(),
        disruption_id=plan.disruption_id,
        plan_id=plan.plan_id,
        plan_version=version,
        target=target,
        action=action,
        payload=payload,
        idempotency_key=key,
        depends_on=depends_on,
        compensation=compensation,
        required_role=required_role,
        classification=classification,
    )


def build_commands(plan: Plan, *, version: int = 2,
                   now: Any = None) -> list[Command]:
    """The full command set for an approved plan, in dependency order."""
    moment = now or utcnow()
    commands: list[Command] = []
    baseline_locations = {s.location_id for s in w.BASELINE_SCHEDULE}
    new_locations = sorted({s.location_id for s in plan.scenes} - baseline_locations)

    entries = [
        {
            "scene_id": s.scene_id,
            "location_id": s.location_id,
            "unit_id": s.unit_id,
            "setup_start": s.setup_start.isoformat(),
            "start": s.start.isoformat(),
            "end": s.end.isoformat(),
            "crew_call": s.crew_call.isoformat(),
            "cast_calls": {k: v.isoformat() for k, v in s.cast_calls.items()},
        }
        for s in plan.scenes
    ]

    # 1. Location confirmation comes first: nothing downstream is safe to issue
    #    until the production actually holds the place it is sending people to.
    location_ids: list[str] = []
    for location_id in new_locations:
        command = _cmd(
            plan, TargetSystem.LOCATION_OPS, "confirm",
            {"location_id": location_id, "plan_id": plan.plan_id},
            version=version, required_role=Role.LOCATION_MANAGER,
        )
        commands.append(command)
        location_ids.append(command.command_id)

    # 2. Access arrangements. Issued early and made a dependency of the crew
    #    communications, so nobody is told to travel before the means to travel
    #    is confirmed.
    access_ids: list[str] = []
    for booking_id, start, end in _interpreter_extensions(plan):
        command = _cmd(
            plan, TargetSystem.INTERPRETER_BOOKING, "extend",
            {
                "booking_id": booking_id,
                "start": start,
                "end": end,
                "requested_at": moment.isoformat(),
            },
            version=version, required_role=Role.ACCESS_COORDINATOR,
            compensation="cancel_extension",
            classification=Classification.OPERATIONAL_REQUIREMENT,
        )
        commands.append(command)
        access_ids.append(command.command_id)

    legs = [
        {
            "leg_id": leg.leg_id,
            "vehicle_id": leg.vehicle_id,
            "from_location": leg.from_location,
            "to_location": leg.to_location,
            "depart": leg.depart.isoformat(),
            "arrive": leg.arrive.isoformat(),
            "step_free": leg.step_free,
            "purpose": leg.purpose,
        }
        for leg in plan.transport
    ]
    if legs:
        command = _cmd(
            plan, TargetSystem.TRANSPORT_DISPATCH, "rebook", {"legs": legs},
            version=version, depends_on=tuple(location_ids),
            required_role=Role.TRANSPORT_COORDINATOR, compensation="cancel",
        )
        commands.append(command)
        access_ids.append(command.command_id)

    # 3. The revised safety briefing, in the approved accessible formats.
    briefing_ids: list[str] = []
    for location_id in new_locations:
        command = _cmd(
            plan, TargetSystem.SAFETY_BRIEFING, "publish_accessible",
            {
                "location_id": location_id,
                "locations": new_locations,
                "formats": ["spoken", "written", "captioned"],
                "plan_id": plan.plan_id,
            },
            version=version, depends_on=tuple(location_ids),
            required_role=Role.SAFETY_LEAD,
        )
        commands.append(command)
        briefing_ids.append(command.command_id)

    # 4. Schedule and equipment.
    schedule_command = _cmd(
        plan, TargetSystem.SCHEDULING, "apply_revision",
        {"entries": entries, "removed": list(plan.deferred_scenes)},
        version=version, required_role=Role.FIRST_AD,
    )
    commands.append(schedule_command)

    moves = _equipment_moves(plan)
    if moves:
        commands.append(_cmd(
            plan, TargetSystem.EQUIPMENT_INVENTORY, "reassign", {"moves": moves},
            version=version, depends_on=(schedule_command.command_id,),
            required_role=Role.UPM,
        ))

    # 5. The call sheet — the Bob-modernized connector.
    call_sheet_command = _cmd(
        plan, TargetSystem.CALL_SHEET, "publish_revision",
        {
            "production_id": w.PRODUCTION_ID,
            "entries": entries,
            "notes": list(plan.continuity_notes),
            "accessible_formats": ["written", "captioned"],
        },
        version=version,
        depends_on=(schedule_command.command_id, *briefing_ids),
        required_role=Role.COORDINATOR,
        classification=Classification.PERSONAL,
    )
    commands.append(call_sheet_command)

    # 6. Department work queues.
    tasks = _department_tasks(plan)
    department_command = _cmd(
        plan, TargetSystem.DEPARTMENT_TASKS, "publish", {"tasks": tasks},
        version=version, depends_on=(call_sheet_command.command_id,),
        required_role=Role.COORDINATOR,
    )
    commands.append(department_command)

    # 7. Crew views and notifications, last, and dependent on everything that
    #    has to be true before a person is told to act on it.
    views = _crew_views(plan)
    commands.append(_cmd(
        plan, TargetSystem.CREW_MOBILE, "update", {"views": views},
        version=version,
        depends_on=(call_sheet_command.command_id, *access_ids),
        classification=Classification.PERSONAL,
    ))

    commands.append(_cmd(
        plan, TargetSystem.EXPENSE, "record",
        {
            "plan_id": plan.plan_id,
            "cost_delta": plan.objectives.cost_delta,
            "overtime_minutes": plan.objectives.overtime_minutes,
        },
        version=version, required_role=Role.UPM,
    ))

    commands.append(_cmd(
        plan, TargetSystem.EXECUTIVE_REPORTING, "update",
        {
            "plan_id": plan.plan_id,
            "disruption_id": plan.disruption_id,
            "delay_minutes": plan.objectives.delay_minutes,
            "cost_delta": plan.objectives.cost_delta,
            "overtime_minutes": plan.objectives.overtime_minutes,
            "changed_assignments": plan.objectives.changed_assignments,
            "access_arrangements_preserved": sum(1 for a in plan.access if a.satisfied),
            "hard_constraint_violations": 0,
        },
        version=version, depends_on=(schedule_command.command_id,),
    ))
    return commands


def notification_command(plan: Plan, messages: list[Any], *, version: int = 2) -> Command:
    """The delivery command for a composed message set.

    Delivery is issued as a command like everything else, and the notification
    system reports what it actually delivered. The coordinator does not decide
    that a message arrived — that is the whole difference between a system that
    verifies and a system that assumes, and it is the reason a person who never
    received an instruction cannot be counted as having acknowledged it.

    It sits outside `build_commands` because the messages are composed from the
    approved plan after the saga has changed the systems the messages describe.
    Telling somebody about a call time that the scheduling system has not
    accepted yet is a message you have to retract.
    """
    payload = {
        "plan_id": plan.plan_id,
        "disruption_id": plan.disruption_id,
        "messages": [
            {
                "message_id": m.message_id,
                "recipient_id": m.recipient_id,
                "recipient_role": m.recipient_role.value,
                "channel": m.channel,
                "requires_ack": m.requires_ack,
                "accessible_formats": list(m.accessible_formats),
            }
            for m in messages
        ],
    }
    return _cmd(
        plan, TargetSystem.NOTIFICATION, "send", payload,
        version=version, required_role=Role.COORDINATOR,
        classification=Classification.PERSONAL,
    )


def _interpreter_extensions(plan: Plan) -> list[tuple[str, str, str]]:
    """Interpreter cover the plan needs, derived from its access implementations."""
    out: list[tuple[str, str, str]] = []
    for access in plan.access:
        if access.requirement_id != "ACC-002" or not access.satisfied:
            continue
        if "extended" not in access.evidence:
            continue
        for part in access.evidence.split(";"):
            part = part.strip()
            if " extended to " not in part:
                continue
            booking_id = part.split(" extended to ")[0].strip()
            # The window comes from the scenes the person is actually called for.
            rows = [s for s in plan.scenes if any(
                pid == "CAST-001" for pid in s.cast_calls
            )]
            if not rows:
                continue
            later = [s for s in rows if s.start.date() > w.SHOOT_DATE]
            target = later or rows
            start = min(s.cast_calls.get("CAST-001", s.setup_start) for s in target)
            end = max(s.end for s in target)
            out.append((booking_id, start.isoformat(), end.isoformat()))
    return out


def _equipment_moves(plan: Plan) -> list[dict[str, Any]]:
    baseline = {s.scene_id: s for s in w.BASELINE_SCHEDULE}
    moves: list[dict[str, Any]] = []
    for scene in plan.scenes:
        original = baseline.get(scene.scene_id)
        if original is None or set(original.equipment_ids) != set(scene.equipment_ids):
            for equipment_id in scene.equipment_ids:
                moves.append({"equipment_id": equipment_id, "unit_id": scene.unit_id,
                              "scene_id": scene.scene_id})
    # De-duplicate: one move per package, not one per scene that uses it.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for move in moves:
        if move["equipment_id"] in seen:
            continue
        seen.add(move["equipment_id"])
        unique.append(move)
    return unique


def _department_tasks(plan: Plan) -> list[dict[str, Any]]:
    """One task per department that has something to do differently.

    Each carries what changed, why it matters, the exact action and a deadline —
    §14.9. A task that says only "schedule updated" makes a department head go
    and work out their own change, which is the coordination cost this system
    exists to remove.
    """
    baseline = {s.scene_id: s for s in w.BASELINE_SCHEDULE}
    changed_scenes = [
        s for s in plan.scenes
        if s.scene_id not in baseline
        or baseline[s.scene_id].start != s.start
        or baseline[s.scene_id].location_id != s.location_id
    ]
    if not changed_scenes:
        return []

    first = min(changed_scenes, key=lambda s: s.setup_start)
    departments: dict[str, dict[str, Any]] = {}

    def department_keys(scene: Any) -> set[str]:
        """Every department a scene change actually lands on.

        Equipment is only half of it. A scene moved into the night needs its
        props on the floor and its wardrobe and makeup continuity established —
        those departments have real work to do and a real reason to reject the
        task if they cannot. Deriving the queue from equipment alone silently
        omits them, which is how a department finds out at the call.
        """
        keys: set[str] = set()
        for equipment_id in scene.equipment_ids:
            equipment = w.EQUIPMENT_BY_ID.get(equipment_id)
            if equipment is not None:
                keys.add(equipment.department.value)
        source = scr.SCENES_BY_ID.get(scene.scene_id)
        if source is not None:
            if source.props:
                keys.add("props")
            if source.wardrobe_state:
                keys.add("wardrobe")
            if source.makeup_state:
                keys.add("makeup")
        return keys

    for scene in changed_scenes:
        for key in sorted(department_keys(scene)):
            departments.setdefault(key, {
                "task_id": f"TASK-{key.upper()}-{plan.plan_id[-6:]}",
                "department": key,
                "what_changed": "",
                "why": "",
                "action": "",
                "deadline": (first.setup_start - timedelta(minutes=30)).isoformat(),
                "scenes": [],
            })
            departments[key]["scenes"].append(scene.scene_id)


    for key, task in departments.items():
        scenes = ", ".join(sorted(set(task["scenes"])))
        task["what_changed"] = f"{scenes} moved or added to tonight's plan"
        task["why"] = (
            "The night exterior stood down on a safety call; the revised plan recovers "
            "page count from prepared cover material."
        )
        task["action"] = f"Confirm {key} readiness for {scenes} and accept this task"
        task.pop("scenes")

    # The production department always has a task: someone has to run the change.
    departments.setdefault("production", {
        "task_id": f"TASK-PRODUCTION-{plan.plan_id[-6:]}",
        "department": "production",
        "what_changed": "Revised call sheet issued",
        "why": "Plan revision approved",
        "action": "Distribute and track acknowledgments",
        "deadline": (first.setup_start - timedelta(minutes=30)).isoformat(),
    })
    return sorted(departments.values(), key=lambda t: t["department"])


def _crew_views(plan: Plan) -> list[dict[str, Any]]:
    """The minimum-necessary view for every affected person."""
    views: list[dict[str, Any]] = []
    baseline = {s.scene_id: s for s in w.BASELINE_SCHEDULE}
    changed = [
        s for s in plan.scenes
        if s.scene_id not in baseline or baseline[s.scene_id].start != s.start
    ]
    if not changed:
        return views

    people: dict[str, dict[str, Any]] = {}
    for scene in changed:
        for cast_id, call in scene.cast_calls.items():
            people.setdefault(cast_id, {
                "person_id": cast_id,
                "call_time": call.isoformat(),
                "location": scene.location_id,
                "scene_id": scene.scene_id,
            })
        for crew in w.crew_for_unit(scene.unit_id):
            people.setdefault(crew.crew_id, {
                "person_id": crew.crew_id,
                "call_time": (scene.crew_call or scene.setup_start).isoformat(),
                "location": scene.location_id,
                "scene_id": scene.scene_id,
            })

    for person_id, row in people.items():
        arrangements = [
            a for a in plan.access if a.person_id == person_id
        ]
        views.append({
            **row,
            "transport": next(
                (leg.vehicle_id for leg in plan.transport if person_id in leg.passengers),
                "own transport",
            ),
            "required_action": f"Report to {row['location']} for {row['scene_id']}",
            "safety_instruction": "Revised briefing issued; acknowledge before travelling.",
            "access_arrangement": [
                {"requirement": a.requirement, "mechanism": a.mechanism}
                for a in arrangements
            ],
            "acknowledgment_required": True,
            "revision": 2,
        })
    return views
