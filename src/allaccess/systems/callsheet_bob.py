"""Typed, idempotent, event-driven call-sheet connector — the modernized replacement.

Written by Bob (Connector Modernization mode) against
bob-evidence/briefs/uc-03-callsheet-modernization.md, working only from
``callsheet_legacy.py`` and the brief. ``callsheet_modern.py`` was not consulted.

Defects fixed relative to ``callsheet_legacy.py``, each with a test that fails
without the fix:

* **D1** No schema — any dict accepted.
  Test: ``test_bob_malformed_entry_is_rejected_not_stored``
* **D2** Mutable module-level state shared between callers.
  Test: ``test_bob_two_connectors_do_not_interfere``
* **D3** Polling busy-loop (``poll_for_changes``).
  Structural fix: replaced by synchronous ``apply()`` — no polling test needed.
* **D4** No idempotency — same revision published twice.
  Test: ``test_bob_duplicate_publish_changes_nothing``
* **D5** Bare ``except`` swallows errors and returns ``None``.
  Test: ``test_bob_failures_are_typed_not_silent``
* **D6** Personal data (cast call times) written to the log.
  Test: ``test_bob_log_line_carries_no_personal_data``
* **D7** Off-by-one revision numbering.
  Test: ``test_bob_first_revision_is_two_and_supersedes_one``
* **D8** No contract tests, no failure tests, no acknowledgment path.
  Test: ``test_bob_result_carries_system_version``

Defect 3 is structural: the connector is no longer a polling loop. Its
``apply()`` method is called by the saga when a ``COMMAND_ISSUED`` event with
``target=CALL_SHEET`` reaches the execution layer. There is nothing to poll.

Defect 7 is the genuine bug the modernization found: ``publish_revision`` and
``set_call_sheet`` each increment ``REVISION_COUNTER``, so a normal flow skips
revision numbers. The correct model is that the store starts at revision 1
(the baseline), and the first publish produces revision 2.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..contracts import (
    Command,
    CommandResult,
    CommandStatus,
    TargetSystem,
    utcnow,
)

CONNECTOR_VERSION = "1.0.0"
_SUPPORTED_ACTIONS = frozenset({"publish_revision"})


# ---------------------------------------------------------------------------
# Schema (defect 1: previously absent)
# ---------------------------------------------------------------------------


class CallSheetEntry(BaseModel):
    """One scene's call-sheet row. Validated on ingestion; rejects silently wrong data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    scene_id: str
    location_id: str
    unit_id: str
    setup_start: datetime
    start: datetime
    end: datetime
    crew_call: datetime
    cast_calls: dict[str, datetime] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _end_after_start(self) -> "CallSheetEntry":
        if self.end <= self.start:
            raise ValueError(f"end {self.end} must be after start {self.start}")
        return self


class CallSheetRevision(BaseModel):
    """A published call-sheet snapshot. ``revision`` 1 is the baseline; the first
    publish is always revision 2 (defect 7 fix)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    production_id: str
    revision: int
    supersedes: int
    plan_id: str
    disruption_id: str
    entries: tuple[CallSheetEntry, ...] = ()
    notes: tuple[str, ...] = ()
    accessible_formats: tuple[str, ...] = ()
    published_at: datetime = Field(default_factory=utcnow)

    @field_validator("revision")
    @classmethod
    def _minimum_revision(cls, v: int) -> int:
        if v < 2:
            raise ValueError("revision must be ≥ 2; revision 1 is the baseline state")
        return v


# ---------------------------------------------------------------------------
# Connector (defect 2 fix: no module-level state)
# ---------------------------------------------------------------------------


def _redacted_summary(entries: list[dict[str, Any]]) -> str:
    """A log-safe description of what changed. No personal data (defect 6 fix).

    Cast call *counts* are fine; the names and times of the individuals are not
    — those go to a different audience under a different retention policy.
    """
    scenes = len(entries)
    cast_count = sum(len(e.get("cast_calls", {})) for e in entries)
    return f"{scenes} scene(s), {cast_count} cast call(s)"


class CallSheetConnector:
    """Typed, idempotent call-sheet system connector.

    One instance per production. Instances do not share state (defect 2 fix).
    All failures surface as a typed ``CommandResult`` (defect 5 fix).
    """

    def __init__(self, production_id: str) -> None:
        self._production_id = production_id
        # Revision 1 is the implicit baseline. First publish produces revision 2.
        self._revision: int = 1
        self._current: CallSheetRevision | None = None
        # Idempotency: key → result already returned (defect 4 fix).
        self._seen: dict[str, CommandResult] = {}
        # Content hash → first result, for content-based deduplication.
        self._content_seen: dict[str, CommandResult] = {}
        self.log: list[str] = []
        self._publishes: int = 0

    # ------------------------------------------------------------------
    # Public read accessors
    # ------------------------------------------------------------------

    @property
    def current_revision(self) -> int:
        return self._revision

    def current(self) -> CallSheetRevision | None:
        return self._current

    def state(self) -> dict[str, Any]:
        formats: tuple[str, ...] = self._current.accessible_formats if self._current else ()
        return {
            "connector_version": CONNECTOR_VERSION,
            "production_id": self._production_id,
            "revision": self._revision,
            "publishes": self._publishes,
            "accessible_formats": list(formats),
        }

    # ------------------------------------------------------------------
    # Command entry point
    # ------------------------------------------------------------------

    def apply(self, command: Command) -> CommandResult:
        """Apply a typed command. Always returns a ``CommandResult`` (defect 5 fix)."""
        # Wrong target check (acceptance criterion 6 / defect 1 / defect 5).
        if command.target is not TargetSystem.CALL_SHEET:
            return self._reject(
                command,
                f"this connector serves {TargetSystem.CALL_SHEET.value}; "
                f"received {command.target.value}",
                "wrong_target",
            )

        if command.action not in _SUPPORTED_ACTIONS:
            return self._reject(
                command,
                f"unknown action '{command.action}'",
                "unknown_action",
            )

        # Idempotency: key-based (defect 4 fix).
        if command.idempotency_key in self._seen:
            prior = self._seen[command.idempotency_key]
            return CommandResult(
                command_id=command.command_id,
                target=command.target,
                status=prior.status,
                detail=prior.detail,
                system_version=prior.system_version,
                duplicate_suppressed=True,
                completed_at=utcnow(),
            )

        return self._publish_revision(command)

    # ------------------------------------------------------------------
    # Action handlers
    # ------------------------------------------------------------------

    def _publish_revision(self, command: Command) -> CommandResult:
        payload = command.payload

        # Schema validation (defect 1 fix): parse and reject bad entries.
        raw_entries: list[dict[str, Any]] = payload.get("entries", [])
        try:
            entries = [CallSheetEntry.model_validate(e) for e in raw_entries]
        except Exception as exc:
            return self._record(
                command,
                self._reject(command, str(exc), "schema_validation"),
            )

        if not entries:
            return self._record(
                command,
                self._reject(command, "revision contains no scenes", "empty_revision"),
            )

        # Content-based idempotency: same scenes under a different key = no-op
        # (acceptance criterion 4 / defect 4 extension).
        content_key = _content_hash(entries)
        if content_key in self._content_seen:
            prior = self._content_seen[content_key]
            result = CommandResult(
                command_id=command.command_id,
                target=command.target,
                status=prior.status,
                detail=prior.detail,
                system_version=prior.system_version,
                duplicate_suppressed=True,
                completed_at=utcnow(),
            )
            self._seen[command.idempotency_key] = result
            return result

        # Advance revision counter exactly once per logical publish (defect 7 fix).
        new_revision = self._revision + 1
        supersedes = self._revision

        revision = CallSheetRevision(
            production_id=self._production_id,
            revision=new_revision,
            supersedes=supersedes,
            plan_id=command.plan_id,
            disruption_id=command.disruption_id,
            entries=tuple(entries),
            notes=tuple(payload.get("notes", [])),
            accessible_formats=tuple(payload.get("accessible_formats", [])),
        )

        self._revision = new_revision
        self._current = revision
        self._publishes += 1

        # Privacy-safe log line (defect 6 fix).
        summary = _redacted_summary(raw_entries)
        line = f"published rev {new_revision} supersedes {supersedes}: {summary}"
        self.log.append(line)

        result = CommandResult(
            command_id=command.command_id,
            target=command.target,
            status=CommandStatus.COMPLETED,
            detail=line,
            system_version=new_revision,
        )
        self._record(command, result)
        self._content_seen[content_key] = result
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _reject(self, command: Command, detail: str, error: str) -> CommandResult:
        return CommandResult(
            command_id=command.command_id,
            target=command.target,
            status=CommandStatus.REJECTED,
            detail=detail,
            error=error,
        )

    def _record(self, command: Command, result: CommandResult) -> CommandResult:
        self._seen[command.idempotency_key] = result
        return result


def _content_hash(entries: list[CallSheetEntry]) -> str:
    """Stable hash of call-sheet content, independent of the command key."""
    payload = sorted(
        [
            {
                "scene_id": e.scene_id,
                "start": e.start.isoformat(),
                "end": e.end.isoformat(),
                "location_id": e.location_id,
                "crew_call": e.crew_call.isoformat(),
            }
            for e in entries
        ],
        key=lambda r: r["scene_id"],
    )
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
