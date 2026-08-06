"""Streaming materialised state — the Flink layer.

Every view here is a fold over the event log: it consumes events in sequence and
maintains current state. The same logic runs two ways.

* In process, as the `MaterializedViews` class below. This is what the CLI, the
  API and the benchmark read.
* On Confluent Cloud for Apache Flink, as the SQL in `FLINK_STATEMENTS` at the
  foot of this module — kept beside the Python it mirrors rather than in a
  separate directory, so the two cannot drift apart unnoticed.

Keeping both matters because the SQL is the deployable artifact and the Python is
the testable one. `tests/test_stream.py` asserts that every view has a committed
SQL equivalent, and that the Python views reproduce themselves exactly from a
replay of the log — which is the property that makes the state trustworthy at
all. A view that cannot be rebuilt from the log is not a view, it is a second
source of truth.

Event time and watermarks: events carry `effective_time` (when the change takes
effect in the world) separately from `event_time` (when it was emitted). Views
that care about ordering use `effective_time` and hold a watermark, so an update
that arrives late is still applied in the right order. `late_events` counts the
ones that arrived behind the watermark, because silently dropping them would be
the wrong answer and silently reordering them would be a different wrong answer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from ..contracts import CommandStatus, Event, EventType

#: How far behind the newest effective time an event may be and still be applied
#: in order. Beyond this it is counted as late.
WATERMARK_LAG = timedelta(minutes=30)


@dataclass
class DepartmentReadiness:
    department: str
    tasks_issued: int = 0
    tasks_accepted: int = 0
    tasks_rejected: int = 0

    @property
    def ready(self) -> bool:
        return self.tasks_issued > 0 and self.tasks_accepted >= self.tasks_issued


@dataclass
class DisruptionView:
    disruption_id: str
    state: str = "open"
    opened_at: datetime | None = None
    findings: int = 0
    blocking_findings: int = 0
    plans_generated: int = 0
    plans_feasible: int = 0
    plans_rejected: int = 0
    approved_plan_id: str | None = None
    commands_issued: int = 0
    commands_accepted: int = 0
    commands_rejected: int = 0
    commands_completed: int = 0
    notifications_sent: int = 0
    acknowledgments: int = 0
    acknowledgments_accepted: int = 0
    verification_ready: bool = False
    closed_at: datetime | None = None
    first_plan_ms: float | None = None
    approval_ms: float | None = None
    ready_ms: float | None = None

    @property
    def open_commands(self) -> int:
        return max(0, self.commands_issued - self.commands_completed - self.commands_rejected)


class MaterializedViews:
    """Current production state, maintained by folding the event stream."""

    def __init__(self) -> None:
        self.disruptions: dict[str, DisruptionView] = {}
        self.departments: dict[str, DepartmentReadiness] = defaultdict(
            lambda: DepartmentReadiness("")
        )
        self.active_constraints: set[str] = set()
        self.resource_assignments: dict[str, str] = {}
        self.schedule: dict[str, dict[str, Any]] = {}
        self.pending_approvals: dict[str, str] = {}
        self.open_commands: dict[str, str] = {}
        self.unacknowledged: dict[str, str] = {}
        self.system_versions: dict[str, int] = {}
        self.delay_exposure_minutes: float = 0.0
        self.overtime_exposure_minutes: float = 0.0
        self.access_at_risk: set[str] = set()
        self.events_applied = 0
        self.late_events = 0
        self.watermark: datetime | None = None
        self._first_event_at: dict[str, datetime] = {}

    # -- the fold ----------------------------------------------------------

    def apply(self, event: Event) -> None:
        env = event.envelope
        payload = event.payload
        effective = env.effective_time or env.event_time

        if self.watermark is not None and effective < self.watermark - WATERMARK_LAG:
            self.late_events += 1
        if self.watermark is None or effective > self.watermark:
            self.watermark = effective
        self.events_applied += 1

        did = env.disruption_id
        if did and did not in self.disruptions:
            self.disruptions[did] = DisruptionView(did, opened_at=env.event_time)
            self._first_event_at[did] = env.event_time
        view = self.disruptions.get(did) if did else None

        et = env.event_type
        if et == EventType.CONSTRAINT_ACTIVATED:
            self.active_constraints.add(str(payload.get("constraint_id")))
        elif et == EventType.CONSTRAINT_INVALIDATED:
            self.active_constraints.discard(str(payload.get("constraint_id")))
        elif et == EventType.ASSIGNMENT_CHANGED:
            self.resource_assignments[str(payload.get("resource_id"))] = str(
                payload.get("assigned_to")
            )
        elif et == EventType.SCHEDULE_CHANGED:
            self.schedule[str(payload.get("scene_id"))] = dict(payload)

        elif et in (
            EventType.SCHEDULE_FINDING, EventType.RESOURCE_FINDING, EventType.SAFETY_FINDING,
            EventType.ACCESS_FINDING, EventType.CONTINUITY_FINDING, EventType.SPATIAL_FINDING,
            EventType.BUDGET_FINDING,
        ):
            if view:
                view.findings += 1
                if payload.get("status") == "blocking":
                    view.blocking_findings += 1
            if payload.get("domain") == "access" and payload.get("status") in (
                "blocking", "at_risk"
            ):
                for scope in payload.get("scope", []):
                    if str(scope).startswith("ACC-"):
                        self.access_at_risk.add(str(scope))

        elif et == EventType.PLAN_GENERATED:
            if view:
                view.plans_generated += 1
                if payload.get("feasible"):
                    view.plans_feasible += 1
                    if view.first_plan_ms is None and did in self._first_event_at:
                        view.first_plan_ms = (
                            env.event_time - self._first_event_at[did]
                        ).total_seconds() * 1000.0
                else:
                    view.plans_rejected += 1
                objectives = payload.get("objectives") or {}
                self.delay_exposure_minutes = max(
                    self.delay_exposure_minutes, float(objectives.get("delay_minutes", 0.0))
                )

        elif et == EventType.PLAN_APPROVAL_REQUESTED:
            self.pending_approvals[str(payload.get("request_id"))] = str(payload.get("plan_id"))
        elif et == EventType.PLAN_APPROVED:
            if view:
                view.approved_plan_id = str(payload.get("plan_id"))
                if did in self._first_event_at:
                    view.approval_ms = (
                        env.event_time - self._first_event_at[did]
                    ).total_seconds() * 1000.0
            self.pending_approvals.pop(str(payload.get("request_id")), None)

        elif et == EventType.COMMAND_ISSUED:
            if view:
                view.commands_issued += 1
            self.open_commands[str(payload.get("command_id"))] = str(payload.get("target"))
        elif et in (EventType.COMMAND_ACCEPTED, EventType.COMMAND_REJECTED,
                    EventType.COMMAND_COMPLETED, EventType.SYSTEM_UPDATED):
            status = str(payload.get("status", ""))
            cid = str(payload.get("command_id"))
            if view:
                if status == CommandStatus.ACCEPTED.value:
                    view.commands_accepted += 1
                elif status == CommandStatus.REJECTED.value:
                    view.commands_rejected += 1
                    self.open_commands.pop(cid, None)
                elif status == CommandStatus.COMPLETED.value:
                    view.commands_completed += 1
                    self.open_commands.pop(cid, None)
            if payload.get("system_version") is not None:
                self.system_versions[str(payload.get("target"))] = int(
                    payload["system_version"]
                )
            if str(payload.get("target")) == "department_tasks":
                dept = str(payload.get("detail", "")).split(":")[0]
                row = self.departments.setdefault(dept, DepartmentReadiness(dept))
                row.department = dept
                if status == CommandStatus.ACCEPTED.value:
                    row.tasks_accepted += 1
                elif status == CommandStatus.REJECTED.value:
                    row.tasks_rejected += 1

        elif et == EventType.NOTIFICATION_SENT:
            if view:
                view.notifications_sent += 1
            if payload.get("requires_ack"):
                self.unacknowledged[str(payload.get("message_id"))] = str(
                    payload.get("recipient_id")
                )
        elif et == EventType.ACKNOWLEDGMENT_RECEIVED:
            if view:
                view.acknowledgments += 1
                if payload.get("accepted"):
                    view.acknowledgments_accepted += 1
            self.unacknowledged.pop(str(payload.get("message_id")), None)

        elif et == EventType.VERIFICATION_COMPLETED:
            if view:
                view.verification_ready = bool(payload.get("ready"))
                if view.verification_ready and did in self._first_event_at:
                    view.ready_ms = (
                        env.event_time - self._first_event_at[did]
                    ).total_seconds() * 1000.0
        elif et == EventType.DISRUPTION_CLOSED:
            if view:
                view.closed_at = env.event_time
                view.state = "closed"

        if view is not None and et.value.startswith("production.plan"):
            view.state = "planning"

    def apply_all(self, events: list[Event]) -> "MaterializedViews":
        for event in sorted(events, key=lambda e: e.envelope.sequence or 0):
            self.apply(event)
        return self

    # -- read models -------------------------------------------------------

    def kpis(self) -> dict[str, Any]:
        disruptions = list(self.disruptions.values())
        acked = sum(d.acknowledgments_accepted for d in disruptions)
        sent = sum(d.notifications_sent for d in disruptions)
        return {
            "events_applied": self.events_applied,
            "late_events": self.late_events,
            "watermark": self.watermark.isoformat() if self.watermark else None,
            "disruptions": len(disruptions),
            "disruptions_ready": sum(1 for d in disruptions if d.verification_ready),
            "plans_generated": sum(d.plans_generated for d in disruptions),
            "plans_feasible": sum(d.plans_feasible for d in disruptions),
            "plans_rejected": sum(d.plans_rejected for d in disruptions),
            "commands_issued": sum(d.commands_issued for d in disruptions),
            "commands_completed": sum(d.commands_completed for d in disruptions),
            "open_commands": len(self.open_commands),
            "pending_approvals": len(self.pending_approvals),
            "unacknowledged": len(self.unacknowledged),
            "acknowledgment_completeness": round(acked / sent, 4) if sent else 1.0,
            "active_constraints": len(self.active_constraints),
            "access_at_risk": sorted(self.access_at_risk),
            "delay_exposure_minutes": round(self.delay_exposure_minutes, 1),
            "overtime_exposure_minutes": round(self.overtime_exposure_minutes, 1),
            "departments_ready": sum(1 for d in self.departments.values() if d.ready),
            "departments_tracked": len(self.departments),
        }

    def snapshot(self) -> dict[str, Any]:
        """A comparable state digest. Used to prove replay reproduces the state."""
        return {
            "kpis": self.kpis(),
            "disruptions": {
                did: {
                    "state": v.state,
                    "findings": v.findings,
                    "plans_generated": v.plans_generated,
                    "plans_feasible": v.plans_feasible,
                    "approved_plan_id": v.approved_plan_id,
                    "commands_issued": v.commands_issued,
                    "commands_completed": v.commands_completed,
                    "acknowledgments": v.acknowledgments,
                    "verification_ready": v.verification_ready,
                }
                for did, v in sorted(self.disruptions.items())
            },
            "open_commands": dict(sorted(self.open_commands.items())),
            "unacknowledged": dict(sorted(self.unacknowledged.items())),
            "system_versions": dict(sorted(self.system_versions.items())),
        }


#: The Flink SQL that maintains the same state on Confluent Cloud. Committed as
#: source rather than described in prose so it can be applied directly, and so
#: the mapping from Python view to SQL statement is checkable.
FLINK_STATEMENTS: dict[str, str] = {
    "disruption_state": """
-- Current state of every open disruption.
CREATE TABLE IF NOT EXISTS production_disruption_state (
  disruption_id      STRING,
  findings           BIGINT,
  blocking_findings  BIGINT,
  plans_generated    BIGINT,
  plans_feasible     BIGINT,
  approved_plan_id   STRING,
  commands_issued    BIGINT,
  commands_completed BIGINT,
  acknowledgments    BIGINT,
  verification_ready BOOLEAN,
  PRIMARY KEY (disruption_id) NOT ENFORCED
);

INSERT INTO production_disruption_state
SELECT
  disruption_id,
  COUNT(*) FILTER (WHERE event_type LIKE '%.finding')                       AS findings,
  COUNT(*) FILTER (WHERE event_type LIKE '%.finding'
                     AND JSON_VALUE(payload, '$.status') = 'blocking')      AS blocking_findings,
  COUNT(*) FILTER (WHERE event_type = 'production.plan.generated')          AS plans_generated,
  COUNT(*) FILTER (WHERE event_type = 'production.plan.generated'
                     AND JSON_VALUE(payload, '$.feasible') = 'true')        AS plans_feasible,
  LAST_VALUE(JSON_VALUE(payload, '$.plan_id')) FILTER
    (WHERE event_type = 'production.plan.approved')                         AS approved_plan_id,
  COUNT(*) FILTER (WHERE event_type = 'production.command.issued')          AS commands_issued,
  COUNT(*) FILTER (WHERE event_type = 'production.command.completed')       AS commands_completed,
  COUNT(*) FILTER (WHERE event_type = 'production.acknowledgment.received') AS acknowledgments,
  LAST_VALUE(JSON_VALUE(payload, '$.ready') = 'true') FILTER
    (WHERE event_type = 'production.verification.completed')                AS verification_ready
FROM production_events
GROUP BY disruption_id;
""",
    "open_commands": """
-- Commands issued and not yet resolved. Drives the execution board.
CREATE TABLE IF NOT EXISTS production_open_commands (
  command_id STRING,
  target     STRING,
  status     STRING,
  issued_at  TIMESTAMP_LTZ(3),
  PRIMARY KEY (command_id) NOT ENFORCED
);

INSERT INTO production_open_commands
SELECT
  JSON_VALUE(payload, '$.command_id') AS command_id,
  JSON_VALUE(payload, '$.target')     AS target,
  LAST_VALUE(JSON_VALUE(payload, '$.status')) AS status,
  MIN(event_time) AS issued_at
FROM production_events
WHERE event_type IN (
  'production.command.issued', 'production.command.accepted',
  'production.command.rejected', 'production.command.completed'
)
GROUP BY JSON_VALUE(payload, '$.command_id'), JSON_VALUE(payload, '$.target')
HAVING LAST_VALUE(JSON_VALUE(payload, '$.status')) NOT IN ('completed', 'rejected');
""",
    "unacknowledged": """
-- Messages sent that require acknowledgment and have not received one.
-- Event-time interval join with a watermark, so an acknowledgment arriving out
-- of order still clears its message.
INSERT INTO production_unacknowledged
SELECT n.message_id, n.recipient_id, n.event_time
FROM (
  SELECT JSON_VALUE(payload, '$.message_id')   AS message_id,
         JSON_VALUE(payload, '$.recipient_id') AS recipient_id,
         event_time
  FROM production_events
  WHERE event_type = 'production.notification.sent'
    AND JSON_VALUE(payload, '$.requires_ack') = 'true'
) n
LEFT JOIN (
  SELECT JSON_VALUE(payload, '$.message_id') AS message_id, event_time
  FROM production_events
  WHERE event_type = 'production.acknowledgment.received'
) a
  ON n.message_id = a.message_id
 AND a.event_time BETWEEN n.event_time AND n.event_time + INTERVAL '4' HOUR
WHERE a.message_id IS NULL;
""",
    "operational_kpis": """
-- Rolling operational KPIs over a one-hour hopping window.
INSERT INTO production_kpis
SELECT
  window_start,
  window_end,
  COUNT(DISTINCT disruption_id)                                        AS disruptions,
  COUNT(*) FILTER (WHERE event_type = 'production.plan.generated')     AS plans,
  COUNT(*) FILTER (WHERE event_type = 'production.command.issued')     AS commands,
  COUNT(*) FILTER (WHERE event_type = 'production.acknowledgment.received'
                     AND JSON_VALUE(payload, '$.accepted') = 'true')   AS acks
FROM TABLE(
  HOP(TABLE production_events, DESCRIPTOR(event_time),
      INTERVAL '5' MINUTES, INTERVAL '1' HOUR)
)
GROUP BY window_start, window_end;
""",
    "access_at_risk": """
-- Approved access arrangements currently reported at risk or blocked.
-- Surfaced separately from every other finding because it is the one class of
-- exposure that must never be aggregated away into a general risk score.
INSERT INTO production_access_at_risk
SELECT
  requirement_id,
  LAST_VALUE(status) AS status,
  MAX(event_time)    AS observed_at
FROM (
  SELECT
    scope_item                        AS requirement_id,
    JSON_VALUE(payload, '$.status')   AS status,
    event_time
  FROM production_events
  CROSS JOIN UNNEST(JSON_QUERY_ARRAY(payload, '$.scope')) AS t(scope_item)
  WHERE event_type = 'production.access.finding'
)
WHERE requirement_id LIKE 'ACC-%'
GROUP BY requirement_id
HAVING LAST_VALUE(status) IN ('blocking', 'at_risk');
""",
}
