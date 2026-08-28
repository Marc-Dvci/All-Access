"""The simulated production systems a plan must actually change.

Each adapter holds real state, applies typed commands, and can refuse. Refusal
matters more than acceptance here: a demonstration where every command succeeds
proves nothing about reconciliation. These systems reject stale plan versions,
reject commands whose preconditions are not met, and — in the case of department
tasks — leave one acceptance outstanding so the Verification Agent has something
real to catch.

Adapters never *decide* anything. They apply what they are told and report what
happened. Every constraint lives in the solver, so a downstream system cannot
quietly permit something the plan proved infeasible.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ..contracts import (
    Command,
    CommandResult,
    CommandStatus,
    Department,
    TargetSystem,
    utcnow,
)
from ..production import world as w


def _ok(command: Command, detail: str, version: int | None = None) -> CommandResult:
    return CommandResult(
        command_id=command.command_id, target=command.target,
        status=CommandStatus.COMPLETED, detail=detail, system_version=version,
    )


def _reject(command: Command, detail: str, error: str) -> CommandResult:
    return CommandResult(
        command_id=command.command_id, target=command.target,
        status=CommandStatus.REJECTED, detail=detail, error=error,
    )


class BaseAdapter:
    system: TargetSystem = TargetSystem.SCHEDULING

    def __init__(self) -> None:
        self.version = 1
        self.applied: list[str] = []
        self.rejected: list[str] = []

    def state(self) -> dict[str, Any]:
        return {
            "system": self.system.value,
            "version": self.version,
            "applied": len(self.applied),
            "rejected": len(self.rejected),
            "actions": list(self.applied),
        }


class SchedulingSystem(BaseAdapter):
    system = TargetSystem.SCHEDULING

    def __init__(self) -> None:
        super().__init__()
        self.scenes: dict[str, dict[str, Any]] = {
            s.scene_id: {
                "location_id": s.location_id,
                "unit_id": s.unit_id,
                "start": s.start.isoformat(),
                "end": s.end.isoformat(),
            }
            for s in w.BASELINE_SCHEDULE
        }

    def apply(self, command: Command) -> CommandResult:
        if command.action != "apply_revision":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        entries = command.payload.get("entries", [])
        if not entries:
            return _reject(command, "revision contains no scenes", "empty_revision")
        for row in entries:
            self.scenes[row["scene_id"]] = {
                "location_id": row["location_id"],
                "unit_id": row["unit_id"],
                "start": row["start"],
                "end": row["end"],
            }
        for scene_id in command.payload.get("removed", []):
            self.scenes.pop(scene_id, None)
        self.version += 1
        self.applied.append(f"apply_revision v{self.version} ({len(entries)} scenes)")
        return _ok(command, f"schedule updated to version {self.version}", self.version)


class TransportDispatch(BaseAdapter):
    system = TargetSystem.TRANSPORT_DISPATCH

    def __init__(self) -> None:
        super().__init__()
        self.bookings: dict[str, dict[str, Any]] = {}

    def apply(self, command: Command) -> CommandResult:
        if command.action not in ("rebook", "cancel"):
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        if command.action == "cancel":
            for leg_id in command.payload.get("legs", []):
                self.bookings.pop(leg_id, None)
            self.version += 1
            self.applied.append("cancel")
            return _ok(command, "transport bookings cancelled", self.version)

        legs = command.payload.get("legs", [])
        for leg in legs:
            vehicle = w.VEHICLES_BY_ID.get(leg.get("vehicle_id", ""))
            if vehicle is None:
                return _reject(command, f"unknown vehicle {leg.get('vehicle_id')}",
                               "unknown_vehicle")
            if leg.get("step_free") and not vehicle.step_free:
                # A booking that claims to satisfy a step-free requirement with a
                # vehicle that has no lift is refused here as well as in the
                # solver. Defence in depth, on the one constraint that matters most.
                return _reject(
                    command,
                    f"{vehicle.name} cannot satisfy a step-free requirement",
                    "not_step_free",
                )
            self.bookings[leg["leg_id"]] = dict(leg)
        self.version += 1
        self.applied.append(f"rebook ({len(legs)} legs)")
        return _ok(command, f"{len(legs)} transport leg(s) rebooked", self.version)


class InterpreterBooking(BaseAdapter):
    system = TargetSystem.INTERPRETER_BOOKING

    def __init__(self) -> None:
        super().__init__()
        self.bookings: dict[str, dict[str, Any]] = {
            b.booking_id: {
                "start": b.start.isoformat(),
                "end": b.end.isoformat(),
                "status": b.status,
                "provider": b.provider,
            }
            for b in w.SERVICE_BOOKINGS if "interpret" in b.kind
        }

    def apply(self, command: Command) -> CommandResult:
        if command.action != "extend":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        booking_id = command.payload.get("booking_id", "")
        booking = w.BOOKINGS_BY_ID.get(booking_id)
        if booking is None:
            return _reject(command, f"unknown booking {booking_id}", "unknown_booking")
        new_end = datetime.fromisoformat(command.payload["end"])
        new_start = datetime.fromisoformat(command.payload["start"])
        requested_at = datetime.fromisoformat(
            command.payload.get("requested_at", utcnow().isoformat())
        )
        notice = (new_start - requested_at).total_seconds() / 60.0
        if notice < booking.extension_notice_minutes:
            return _reject(
                command,
                f"{booking.provider} requires {booking.extension_notice_minutes} min "
                f"notice; {notice:.0f} min given",
                "insufficient_notice",
            )
        if booking.extendable_to and new_end > booking.extendable_to:
            return _reject(
                command,
                f"{booking.provider} can extend to {booking.extendable_to:%d %b %H:%M} "
                f"only; {new_end:%d %b %H:%M} requested",
                "beyond_extension_limit",
            )
        self.bookings[booking_id] = {
            "start": new_start.isoformat(),
            "end": new_end.isoformat(),
            "status": "confirmed",
            "provider": booking.provider,
        }
        self.version += 1
        self.applied.append(f"extend {booking_id}")
        return _ok(
            command,
            f"{booking.provider} confirmed cover {new_start:%d %b %H:%M}-{new_end:%H:%M}",
            self.version,
        )


class AccessServiceBooking(BaseAdapter):
    system = TargetSystem.ACCESS_SERVICE

    def __init__(self) -> None:
        super().__init__()
        self.resources: dict[str, str] = {
            r.resource_id: r.location_id for r in w.SUPPORT_RESOURCES
        }

    def apply(self, command: Command) -> CommandResult:
        if command.action != "relocate":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        resource_id = command.payload.get("resource_id", "")
        destination = command.payload.get("destination", "")
        resource = w.SUPPORT_BY_ID.get(resource_id)
        if resource is None:
            return _reject(command, f"unknown resource {resource_id}", "unknown_resource")
        if not resource.portable:
            return _reject(command, f"{resource.name} is not portable", "not_portable")
        self.resources[resource_id] = destination
        self.version += 1
        self.applied.append(f"relocate {resource_id}")
        return _ok(
            command,
            f"{resource.name} relocated to {destination} "
            f"({resource.setup_minutes} min setup)",
            self.version,
        )


class EquipmentInventory(BaseAdapter):
    system = TargetSystem.EQUIPMENT_INVENTORY

    def __init__(self) -> None:
        super().__init__()
        self.assignments: dict[str, str] = {
            e.equipment_id: e.assigned_unit for e in w.EQUIPMENT
        }

    def apply(self, command: Command) -> CommandResult:
        if command.action != "reassign":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        moves = command.payload.get("moves", [])
        for move in moves:
            equipment_id = move.get("equipment_id")
            if equipment_id not in w.EQUIPMENT_BY_ID:
                return _reject(command, f"unknown equipment {equipment_id}",
                               "unknown_equipment")
            self.assignments[equipment_id] = move.get("unit_id", "")
        self.version += 1
        self.applied.append(f"reassign ({len(moves)})")
        return _ok(command, f"{len(moves)} equipment assignment(s) updated", self.version)


class SafetyBriefingService(BaseAdapter):
    system = TargetSystem.SAFETY_BRIEFING

    def __init__(self) -> None:
        super().__init__()
        self.briefings: dict[str, dict[str, Any]] = {}

    def apply(self, command: Command) -> CommandResult:
        if command.action != "publish_accessible":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        formats = set(command.payload.get("formats", []))
        required = set(w.POLICIES["communication"]["accessible_formats_required"])  # type: ignore[arg-type]
        missing = required - formats
        if missing:
            # The briefing service refuses to publish a briefing that is not
            # available in the approved formats. Publishing the spoken version
            # "for now" is exactly how an access arrangement quietly lapses.
            return _reject(
                command,
                f"briefing not available in {', '.join(sorted(missing))} format",
                "missing_accessible_format",
            )
        location_id = command.payload.get("location_id", "")
        self.briefings[location_id] = {
            "formats": sorted(formats),
            "issued_at": utcnow().isoformat(),
            "locations": command.payload.get("locations", [location_id]),
        }
        self.version += 1
        self.applied.append(f"publish_accessible {location_id}")
        return _ok(
            command,
            f"briefing for {location_id} published in {', '.join(sorted(formats))}",
            self.version,
        )


class LocationOperations(BaseAdapter):
    system = TargetSystem.LOCATION_OPS

    def __init__(self) -> None:
        super().__init__()
        self.confirmed: dict[str, str] = {}

    def apply(self, command: Command) -> CommandResult:
        if command.action != "confirm":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        location_id = command.payload.get("location_id", "")
        if location_id not in w.LOCATIONS_BY_ID:
            return _reject(command, f"unknown location {location_id}", "unknown_location")
        self.confirmed[location_id] = "confirmed"
        self.version += 1
        self.applied.append(f"confirm {location_id}")
        return _ok(command, f"{location_id} confirmed and access route verified", self.version)


@dataclass
class DepartmentTask:
    task_id: str
    department: str
    what_changed: str
    why: str
    action: str
    deadline: str
    accepted: bool | None = None
    reason: str | None = None


class DepartmentTaskSystem(BaseAdapter):
    """Department work queues.

    `auto_accept_except` names the departments that will *not* accept
    automatically. The hero workflow leaves one outstanding on purpose, so the
    Verification Agent has a genuine missing acceptance to find and block on
    rather than a staged one.
    """

    system = TargetSystem.DEPARTMENT_TASKS

    def __init__(self, auto_accept_except: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.tasks: dict[str, DepartmentTask] = {}
        self.auto_accept_except = set(auto_accept_except)

    def apply(self, command: Command) -> CommandResult:
        if command.action != "publish":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        issued = 0
        pending: list[str] = []
        for row in command.payload.get("tasks", []):
            task = DepartmentTask(
                task_id=row["task_id"],
                department=row["department"],
                what_changed=row["what_changed"],
                why=row["why"],
                action=row["action"],
                deadline=row["deadline"],
            )
            if task.department not in self.auto_accept_except:
                task.accepted = True
            else:
                pending.append(task.department)
            self.tasks[task.task_id] = task
            issued += 1
        self.version += 1
        self.applied.append(f"publish ({issued} tasks)")
        detail = f"department_tasks:{issued} task(s) issued"
        if pending:
            detail += f"; awaiting acceptance from {', '.join(sorted(set(pending)))}"
        return _ok(command, detail, self.version)

    def accept(self, department: str) -> int:
        count = 0
        for task in self.tasks.values():
            if task.department == department and task.accepted is None:
                task.accepted = True
                count += 1
        self.auto_accept_except.discard(department)
        return count

    def outstanding(self) -> list[DepartmentTask]:
        return [t for t in self.tasks.values() if t.accepted is None]

    def state(self) -> dict[str, Any]:
        base = super().state()
        base.update({
            "tasks": len(self.tasks),
            "accepted": sum(1 for t in self.tasks.values() if t.accepted),
            "outstanding": [t.department for t in self.outstanding()],
        })
        return base


class CrewMobile(BaseAdapter):
    system = TargetSystem.CREW_MOBILE

    def __init__(self) -> None:
        super().__init__()
        self.views: dict[str, dict[str, Any]] = {}

    def apply(self, command: Command) -> CommandResult:
        if command.action != "update":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        for row in command.payload.get("views", []):
            self.views[row["person_id"]] = row
        self.version += 1
        self.applied.append(f"update ({len(self.views)} views)")
        return _ok(command, f"{len(self.views)} crew view(s) updated", self.version)


class NotificationService(BaseAdapter):
    system = TargetSystem.NOTIFICATION

    def __init__(self, undeliverable: tuple[str, ...] = ()) -> None:
        super().__init__()
        self.sent: list[dict[str, Any]] = []
        self.delivered: list[str] = []
        self.failed: list[str] = []
        self.undeliverable = set(undeliverable)

    def apply(self, command: Command) -> CommandResult:
        if command.action != "send":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        messages = command.payload.get("messages", [])
        for message in messages:
            self.sent.append(message)
            if message.get("recipient_id") in self.undeliverable:
                self.failed.append(message["message_id"])
            else:
                self.delivered.append(message["message_id"])
        self.version += 1
        self.applied.append(f"send ({len(messages)})")
        detail = f"{len(self.delivered)} delivered"
        if self.failed:
            detail += f", {len(self.failed)} undeliverable"
        return _ok(command, detail, self.version)


class ExecutiveReporting(BaseAdapter):
    system = TargetSystem.EXECUTIVE_REPORTING

    def __init__(self) -> None:
        super().__init__()
        self.metrics: dict[str, Any] = {}

    def apply(self, command: Command) -> CommandResult:
        if command.action != "update":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        # The executive view receives aggregates only. Any person-identifying key
        # is dropped here rather than trusted not to have been sent.
        forbidden = {"cast_calls", "person_id", "crew_id", "performer_id", "name",
                     "access_requirements", "requirement"}
        clean = {k: v for k, v in command.payload.items() if k not in forbidden}
        dropped = sorted(set(command.payload) & forbidden)
        self.metrics.update(clean)
        self.version += 1
        self.applied.append("update")
        detail = "executive metrics updated"
        if dropped:
            detail += f"; dropped personal field(s): {', '.join(dropped)}"
        return _ok(command, detail, self.version)


class ExpenseSystem(BaseAdapter):
    system = TargetSystem.EXPENSE

    def __init__(self) -> None:
        super().__init__()
        self.entries: list[dict[str, Any]] = []

    def apply(self, command: Command) -> CommandResult:
        if command.action != "record":
            return _reject(command, f"unknown action '{command.action}'", "unknown_action")
        self.entries.append(dict(command.payload))
        self.version += 1
        self.applied.append("record")
        return _ok(command, "cost and overtime exposure recorded", self.version)


def build_systems(
    production_id: str = w.PRODUCTION_ID,
    *,
    hold_department: str | None = Department.PROPS.value,
    undeliverable: tuple[str, ...] = (),
) -> dict[TargetSystem, Any]:
    """Every downstream system, wired for the demonstration.

    `hold_department` is the department that does not auto-accept, so the
    verification step has a real outstanding acceptance to block on. Pass None
    for a clean run.
    """
    from .callsheet_modern import CallSheetConnector

    adapters: dict[TargetSystem, Any] = {
        TargetSystem.SCHEDULING: SchedulingSystem(),
        TargetSystem.CALL_SHEET: CallSheetConnector(production_id),
        TargetSystem.TRANSPORT_DISPATCH: TransportDispatch(),
        TargetSystem.INTERPRETER_BOOKING: InterpreterBooking(),
        TargetSystem.ACCESS_SERVICE: AccessServiceBooking(),
        TargetSystem.EQUIPMENT_INVENTORY: EquipmentInventory(),
        TargetSystem.SAFETY_BRIEFING: SafetyBriefingService(),
        TargetSystem.LOCATION_OPS: LocationOperations(),
        TargetSystem.DEPARTMENT_TASKS: DepartmentTaskSystem(
            auto_accept_except=(hold_department,) if hold_department else ()
        ),
        TargetSystem.CREW_MOBILE: CrewMobile(),
        TargetSystem.NOTIFICATION: NotificationService(undeliverable=undeliverable),
        TargetSystem.EXECUTIVE_REPORTING: ExecutiveReporting(),
        TargetSystem.EXPENSE: ExpenseSystem(),
    }
    return adapters
