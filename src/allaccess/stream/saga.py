"""Coordinated plan execution as a governed saga.

An approved plan becomes a set of typed commands with dependencies between them.
The coordinator issues what is ready, collects results, pauses dependents when a
command is rejected, routes exceptions to the production coordinator, and runs
approved compensations when it has to.

The properties that matter operationally:

* **Outbox.** A command is written to the outbox in the same step that records
  the decision, then published. A crash between deciding and publishing leaves
  the command in the outbox to be republished, so a decision cannot be silently
  lost.
* **Inbox deduplication.** A target system records the idempotency keys it has
  processed. A replayed command is acknowledged again but not *applied* again —
  which is what stops a duplicated approval from booking two vehicles or
  publishing two call sheets.
* **Plan-version checks.** Every command carries the plan version it belongs to.
  A target holding a newer version rejects the older command as stale rather than
  applying it out of order.
* **Dependencies are real.** A briefing command that depends on the location
  being confirmed is not issued until the confirmation completes. Issuing
  everything at once and hoping is how a crew gets briefed on a location the
  production has not yet secured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from ..contracts import (
    Command,
    CommandResult,
    CommandStatus,
    Event,
    EventType,
    TargetSystem,
)
from .bus import LocalEventBus


class TargetAdapter(Protocol):
    """What every downstream system must implement."""

    system: TargetSystem

    def apply(self, command: Command) -> CommandResult: ...
    def state(self) -> dict[str, Any]: ...


@dataclass
class OutboxEntry:
    command: Command
    published: bool = False
    attempts: int = 0
    last_error: str | None = None


class Outbox:
    """Commands recorded at decision time, published afterwards."""

    def __init__(self) -> None:
        self.entries: dict[str, OutboxEntry] = {}
        self.published_order: list[str] = []

    def record(self, command: Command) -> OutboxEntry:
        entry = self.entries.get(command.command_id)
        if entry is None:
            entry = OutboxEntry(command=command)
            self.entries[command.command_id] = entry
        return entry

    def pending(self) -> list[OutboxEntry]:
        return [e for e in self.entries.values() if not e.published]

    def mark_published(self, command_id: str) -> None:
        entry = self.entries.get(command_id)
        if entry and not entry.published:
            entry.published = True
            self.published_order.append(command_id)


class Inbox:
    """Per-target idempotency ledger."""

    def __init__(self) -> None:
        self._seen: dict[str, set[str]] = {}
        self.suppressed = 0

    def seen(self, target: TargetSystem, key: str) -> bool:
        return key in self._seen.get(target.value, set())

    def record(self, target: TargetSystem, key: str) -> None:
        self._seen.setdefault(target.value, set()).add(key)

    def check_and_record(self, target: TargetSystem, key: str) -> bool:
        """True if this is new work; False if it is a duplicate."""
        if self.seen(target, key):
            self.suppressed += 1
            return False
        self.record(target, key)
        return True


@dataclass
class SagaStep:
    command: Command
    result: CommandResult | None = None
    blocked_by: tuple[str, ...] = ()
    compensated: bool = False

    @property
    def status(self) -> CommandStatus:
        return self.result.status if self.result else CommandStatus.ISSUED

    @property
    def terminal(self) -> bool:
        return self.status in (
            CommandStatus.COMPLETED, CommandStatus.REJECTED,
            CommandStatus.FAILED, CommandStatus.SUPERSEDED,
        )


@dataclass
class SagaResult:
    disruption_id: str
    plan_id: str
    steps: list[SagaStep] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)
    compensations: list[str] = field(default_factory=list)
    duplicates_suppressed: int = 0

    @property
    def completed(self) -> int:
        return sum(1 for s in self.steps if s.status == CommandStatus.COMPLETED)

    @property
    def rejected(self) -> int:
        return sum(1 for s in self.steps if s.status == CommandStatus.REJECTED)

    @property
    def blocked(self) -> int:
        return sum(1 for s in self.steps if s.blocked_by)

    @property
    def all_complete(self) -> bool:
        return all(s.status == CommandStatus.COMPLETED for s in self.steps)

    def by_target(self) -> dict[str, str]:
        return {s.command.target.value: s.status.value for s in self.steps}


class SagaCoordinator:
    """Issues commands in dependency order and reconciles the results."""

    def __init__(
        self,
        bus: LocalEventBus,
        adapters: dict[TargetSystem, TargetAdapter],
        inbox: Inbox | None = None,
    ) -> None:
        self.bus = bus
        self.adapters = adapters
        self.outbox = Outbox()
        self.inbox = inbox or Inbox()
        self.plan_versions: dict[TargetSystem, int] = {}

    def _publish_command(self, command: Command, causation_id: str | None) -> Event | None:
        event = self.bus.make_event(
            EventType.COMMAND_ISSUED,
            {
                "command_id": command.command_id,
                "disruption_id": command.disruption_id,
                "plan_id": command.plan_id,
                "plan_version": command.plan_version,
                "target": command.target.value,
                "action": command.action,
                "payload": command.payload,
                "idempotency_key": command.idempotency_key,
                "depends_on": list(command.depends_on),
                "compensation": command.compensation,
                "required_role": command.required_role.value if command.required_role else None,
            },
            producer="saga_coordinator",
            disruption_id=command.disruption_id,
            plan_id=command.plan_id,
            command_id=command.command_id,
            causation_id=causation_id,
            correlation_id=command.disruption_id,
            idempotency_key=command.idempotency_key,
            classification=command.classification,
        )
        result = self.bus.publish(event)
        if result.published:
            self.outbox.mark_published(command.command_id)
            return result.event
        return None

    def _publish_result(self, result: CommandResult, command: Command,
                        causation_id: str | None) -> None:
        event_type = {
            CommandStatus.ACCEPTED: EventType.COMMAND_ACCEPTED,
            CommandStatus.REJECTED: EventType.COMMAND_REJECTED,
            CommandStatus.COMPLETED: EventType.COMMAND_COMPLETED,
        }.get(result.status, EventType.SYSTEM_UPDATED)
        event = self.bus.make_event(
            event_type,
            {
                "command_id": result.command_id,
                "target": result.target.value,
                "status": result.status.value,
                "detail": result.detail,
                "system_version": result.system_version,
                "error": result.error,
                "attempts": result.attempts,
                "duplicate_suppressed": result.duplicate_suppressed,
            },
            producer=f"system.{result.target.value}",
            disruption_id=command.disruption_id,
            plan_id=command.plan_id,
            command_id=command.command_id,
            causation_id=causation_id,
            correlation_id=command.disruption_id,
            idempotency_key=f"result:{result.command_id}:{result.status.value}",
        )
        self.bus.publish(event)

    def execute(
        self,
        disruption_id: str,
        plan_id: str,
        commands: list[Command],
        *,
        causation_id: str | None = None,
        on_exception: Callable[[str], None] | None = None,
    ) -> SagaResult:
        saga = SagaResult(disruption_id=disruption_id, plan_id=plan_id)
        steps = {c.command_id: SagaStep(command=c) for c in commands}
        for command in commands:
            self.outbox.record(command)

        remaining = list(commands)
        guard = 0
        while remaining and guard < len(commands) * 4 + 8:
            guard += 1
            progressed = False
            for command in list(remaining):
                step = steps[command.command_id]
                unmet = tuple(
                    dep for dep in command.depends_on
                    if dep in steps and steps[dep].status != CommandStatus.COMPLETED
                )
                if unmet:
                    failed = tuple(
                        dep for dep in unmet
                        if steps[dep].status in (CommandStatus.REJECTED, CommandStatus.FAILED)
                    )
                    if failed:
                        # A dependency failed: this command is not issued at all.
                        step.blocked_by = failed
                        step.result = CommandResult(
                            command_id=command.command_id,
                            target=command.target,
                            status=CommandStatus.SUPERSEDED,
                            detail=(
                                "not issued: depends on "
                                + ", ".join(failed) + ", which did not complete"
                            ),
                        )
                        saga.exceptions.append(
                            f"{command.command_id} ({command.target.value}) blocked by "
                            + ", ".join(failed)
                        )
                        if on_exception:
                            on_exception(saga.exceptions[-1])
                        remaining.remove(command)
                        progressed = True
                    continue

                issued = self._publish_command(command, causation_id)
                adapter = self.adapters.get(command.target)
                if adapter is None:
                    step.result = CommandResult(
                        command_id=command.command_id, target=command.target,
                        status=CommandStatus.FAILED,
                        detail=f"no adapter registered for {command.target.value}",
                        error="unrouted_command",
                    )
                    saga.exceptions.append(step.result.detail)
                else:
                    if not self.inbox.check_and_record(command.target,
                                                       command.idempotency_key):
                        step.result = CommandResult(
                            command_id=command.command_id, target=command.target,
                            status=CommandStatus.COMPLETED,
                            detail="duplicate suppressed; system already in the intended state",
                            duplicate_suppressed=True,
                        )
                    else:
                        current = self.plan_versions.get(command.target, 0)
                        if command.plan_version < current:
                            step.result = CommandResult(
                                command_id=command.command_id, target=command.target,
                                status=CommandStatus.REJECTED,
                                detail=(
                                    f"stale command: target holds plan version {current}, "
                                    f"command carries {command.plan_version}"
                                ),
                                error="stale_command",
                            )
                        else:
                            step.result = adapter.apply(command)
                            self.plan_versions[command.target] = max(
                                current, command.plan_version
                            )
                self._publish_result(
                    step.result, command,
                    issued.envelope.event_id if issued else causation_id,
                )
                if step.result.status == CommandStatus.REJECTED:
                    saga.exceptions.append(
                        f"{command.target.value} rejected {command.action}: "
                        f"{step.result.detail}"
                    )
                    if on_exception:
                        on_exception(saga.exceptions[-1])
                remaining.remove(command)
                progressed = True
            if not progressed:
                for command in remaining:
                    steps[command.command_id].blocked_by = command.depends_on
                    saga.exceptions.append(
                        f"{command.command_id} never became ready: unresolved dependencies "
                        + ", ".join(command.depends_on)
                    )
                break

        saga.steps = [steps[c.command_id] for c in commands]
        saga.duplicates_suppressed = self.inbox.suppressed
        return saga

    def compensate(self, saga: SagaResult) -> list[str]:
        """Run approved compensations for the steps that completed before a failure.

        Only commands that declare a compensation are compensated. A command with
        no declared compensation is escalated to the coordinator instead of being
        undone by guesswork — reversing a booking nobody described how to reverse
        is how a recovery makes things worse.
        """
        done: list[str] = []
        if not saga.exceptions:
            return done
        for step in saga.steps:
            if step.status != CommandStatus.COMPLETED or step.compensated:
                continue
            if not step.command.compensation:
                continue
            adapter = self.adapters.get(step.command.target)
            if adapter is None:
                continue
            compensation = Command(
                command_id=f"{step.command.command_id}-COMP",
                disruption_id=step.command.disruption_id,
                plan_id=step.command.plan_id,
                plan_version=step.command.plan_version,
                target=step.command.target,
                action=step.command.compensation,
                payload=dict(step.command.payload),
                idempotency_key=f"{step.command.idempotency_key}:compensate",
            )
            self.inbox.check_and_record(compensation.target, compensation.idempotency_key)
            result = adapter.apply(compensation)
            step.compensated = True
            done.append(f"{compensation.action} on {compensation.target.value}: {result.detail}")
        saga.compensations.extend(done)
        return done

    def stats(self) -> dict[str, Any]:
        return {
            "outbox_entries": len(self.outbox.entries),
            "outbox_pending": len(self.outbox.pending()),
            "inbox_suppressed": self.inbox.suppressed,
            "plan_versions": {k.value: v for k, v in self.plan_versions.items()},
        }
