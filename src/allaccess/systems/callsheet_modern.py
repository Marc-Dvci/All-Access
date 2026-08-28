"""Call-sheet connector — the modernization of `callsheet_legacy.py`.

This is the "after" side of bob-evidence/USE_CASES.md#uc-03, and it is the
adapter that actually runs in the hero workflow: it publishes the revised call
sheet and returns an acknowledgment event.

**Authorship, stated exactly.** This module was written by hand. It is the
reference target for UC-03, the connector-modernization use case staged for IBM
Bob: the brief is written, the starting condition is preserved, and the
acceptance criteria are fixed — but **no Bob session has been run against this
repository yet**, so nothing here is attributed to one. When a session runs,
what it produced, what was accepted and what was rejected is recorded in
`bob-evidence/`. See `bob-evidence/README.md`.

What changed, defect by defect against the legacy module:

| Legacy defect | Resolution |
|---|---|
| No schema | `CallSheetRevision` is a validated model; bad input is rejected at the boundary |
| Shared mutable module state | State is instance-scoped; two connectors cannot interfere |
| Polling loop | Event-driven: the connector consumes commands and emits results |
| No idempotency | Idempotency key per revision; a repeat changes nothing and returns the original |
| Errors swallowed | Failures return a typed `CommandResult` with status and reason |
| Personal data in logs | `redacted_summary()` logs counts, never names or call times |
| Off-by-one revisions | First publish is revision 2 *of* revision 1; asserted in the tests |
| No tests | Contract tests, failure tests and a legacy-parity test |

The parity test is the one worth pointing at: `test_modern_matches_legacy_semantics`
asserts the modern connector produces the same *intended* call sheet content as
the legacy one for the same input, so the modernization is provably behaviour
preserving except where a defect was deliberately fixed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..contracts import (
    Classification,
    Command,
    CommandResult,
    CommandStatus,
    TargetSystem,
    stable_hash,
    utcnow,
)

CONNECTOR_VERSION = "callsheet-connector-2.0.0"


class CallSheetEntry(BaseModel):
    """One scene row on a call sheet."""

    model_config = ConfigDict(extra="forbid")

    scene_id: str
    location_id: str
    unit_id: str
    setup_start: datetime
    start: datetime
    end: datetime
    crew_call: datetime
    cast_calls: dict[str, datetime] = Field(default_factory=dict)

    @field_validator("end")
    @classmethod
    def _end_after_start(cls, v: datetime, info) -> datetime:
        start = info.data.get("start")
        if start is not None and v <= start:
            raise ValueError("end must be after start")
        return v


class CallSheetRevision(BaseModel):
    """A validated call-sheet revision. The contract the legacy module lacked."""

    model_config = ConfigDict(extra="forbid")

    production_id: str
    revision: int
    supersedes: int
    plan_id: str
    disruption_id: str
    issued_at: datetime = Field(default_factory=utcnow)
    entries: tuple[CallSheetEntry, ...] = ()
    notes: tuple[str, ...] = ()
    accessible_formats: tuple[str, ...] = ("written", "captioned")
    classification: Classification = Classification.PRODUCTION_INTERNAL

    @field_validator("revision")
    @classmethod
    def _revision_positive(cls, v: int) -> int:
        if v < 2:
            raise ValueError("a revision supersedes revision 1, so it starts at 2")
        return v

    def content_hash(self) -> str:
        return stable_hash({
            "production_id": self.production_id,
            "plan_id": self.plan_id,
            "entries": [e.model_dump(mode="json") for e in
                        sorted(self.entries, key=lambda x: x.scene_id)],
        })

    def redacted_summary(self) -> str:
        """What goes in the log. Counts, never names or individual call times.

        The legacy connector wrote the cast call dictionary into its log line.
        That is a person's whereabouts, in a log with a different retention
        policy and a different audience from the call sheet itself.
        """
        return (
            f"revision {self.revision} supersedes {self.supersedes}: "
            f"{len(self.entries)} scene(s), {sum(len(e.cast_calls) for e in self.entries)} "
            f"cast call(s), formats={','.join(self.accessible_formats)}"
        )


@dataclass
class PublishRecord:
    revision: int
    content_hash: str
    idempotency_key: str
    at: datetime = field(default_factory=utcnow)
    duplicate: bool = False


class CallSheetConnector:
    """Event-driven, idempotent, schema-validated call-sheet connector."""

    system = TargetSystem.CALL_SHEET

    def __init__(self, production_id: str, initial_revision: int = 1) -> None:
        self.production_id = production_id
        self.current_revision = initial_revision
        self.published: list[PublishRecord] = []
        self.log: list[str] = []
        self._by_key: dict[str, CommandResult] = {}
        self._current: CallSheetRevision | None = None
        self.rejections = 0

    # -- the command interface --------------------------------------------

    def apply(self, command: Command) -> CommandResult:
        if command.target is not TargetSystem.CALL_SHEET:
            return CommandResult(
                command_id=command.command_id, target=command.target,
                status=CommandStatus.REJECTED,
                detail=f"call-sheet connector cannot handle target {command.target.value}",
                error="wrong_target",
            )
        if command.action != "publish_revision":
            return CommandResult(
                command_id=command.command_id, target=self.system,
                status=CommandStatus.REJECTED,
                detail=f"unknown action '{command.action}'",
                error="unknown_action",
            )

        # Idempotency: a repeat returns the original outcome and changes nothing.
        previous = self._by_key.get(command.idempotency_key)
        if previous is not None:
            self.published.append(PublishRecord(
                revision=self.current_revision,
                content_hash=self._current.content_hash() if self._current else "",
                idempotency_key=command.idempotency_key,
                duplicate=True,
            ))
            return CommandResult(
                command_id=command.command_id, target=self.system,
                status=CommandStatus.COMPLETED,
                detail=(
                    f"duplicate suppressed; call sheet remains at revision "
                    f"{self.current_revision}"
                ),
                system_version=self.current_revision,
                duplicate_suppressed=True,
            )

        try:
            revision = self._build(command)
        except Exception as exc:
            self.rejections += 1
            return CommandResult(
                command_id=command.command_id, target=self.system,
                status=CommandStatus.REJECTED,
                detail=f"call sheet revision rejected: {exc}",
                error="schema_validation",
            )

        if self._current is not None and revision.content_hash() == self._current.content_hash():
            return CommandResult(
                command_id=command.command_id, target=self.system,
                status=CommandStatus.COMPLETED,
                detail=(
                    f"no material change; call sheet remains at revision "
                    f"{self.current_revision}"
                ),
                system_version=self.current_revision,
                duplicate_suppressed=True,
            )

        self._current = revision
        self.current_revision = revision.revision
        record = PublishRecord(
            revision=revision.revision,
            content_hash=revision.content_hash(),
            idempotency_key=command.idempotency_key,
        )
        self.published.append(record)
        self.log.append(revision.redacted_summary())
        result = CommandResult(
            command_id=command.command_id, target=self.system,
            status=CommandStatus.COMPLETED,
            detail=(
                f"call sheet revision {revision.revision} published "
                f"({len(revision.entries)} scenes, formats: "
                f"{', '.join(revision.accessible_formats)})"
            ),
            system_version=revision.revision,
        )
        self._by_key[command.idempotency_key] = result
        return result

    def _build(self, command: Command) -> CallSheetRevision:
        payload = command.payload
        entries = tuple(
            CallSheetEntry(
                scene_id=row["scene_id"],
                location_id=row["location_id"],
                unit_id=row["unit_id"],
                setup_start=_dt(row["setup_start"]),
                start=_dt(row["start"]),
                end=_dt(row["end"]),
                crew_call=_dt(row["crew_call"]),
                cast_calls={k: _dt(v) for k, v in (row.get("cast_calls") or {}).items()},
            )
            for row in payload.get("entries", [])
        )
        # Revision numbering: the next revision supersedes the current one. The
        # legacy module incremented a counter twice per publish and produced its
        # first revision as 2 while claiming to supersede 1 — the off-by-one this
        # modernization found.
        return CallSheetRevision(
            production_id=payload.get("production_id", self.production_id),
            revision=self.current_revision + 1,
            supersedes=self.current_revision,
            plan_id=command.plan_id,
            disruption_id=command.disruption_id,
            entries=entries,
            notes=tuple(payload.get("notes", ())),
            accessible_formats=tuple(
                payload.get("accessible_formats", ("written", "captioned"))
            ),
        )

    def state(self) -> dict[str, Any]:
        return {
            "system": self.system.value,
            "connector_version": CONNECTOR_VERSION,
            "revision": self.current_revision,
            "publishes": len([p for p in self.published if not p.duplicate]),
            "duplicates_suppressed": len([p for p in self.published if p.duplicate]),
            "rejections": self.rejections,
            "content_hash": self._current.content_hash() if self._current else None,
            "accessible_formats": list(self._current.accessible_formats)
            if self._current else [],
            "log": list(self.log),
        }

    def current(self) -> CallSheetRevision | None:
        return self._current


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
