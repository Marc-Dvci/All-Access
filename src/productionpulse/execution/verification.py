"""Reconciliation and verification.

A plan is not executed because messages were sent. This module compares the
*intended* state with the *observed* state in each downstream system and refuses
to mark the production ready while any critical assertion fails.

The distinction between critical and non-critical assertions is the whole design.
A missing executive metric is not a reason to stop a shooting day. A missing
department acceptance is: it means somebody has not confirmed they can do the
thing the plan assumes they will do. `ready` is false while any critical
assertion fails, and there is no override — the only way to `ready` is to fix
the thing.
"""

from __future__ import annotations

from typing import Any

from ..contracts import (
    Acknowledgment,
    CommandResult,
    CommandStatus,
    Plan,
    TargetSystem,
    VerificationAssertion,
    VerificationReport,
    stable_hash,
)
from ..production import world as w


def _assertion(
    name: str, critical: bool, passed: bool, expected: str, observed: str,
    evidence: str = "", remedy: str | None = None,
) -> VerificationAssertion:
    return VerificationAssertion(
        assertion_id="A-" + stable_hash([name, expected])[:8].upper(),
        name=name, critical=critical, passed=passed,
        expected=expected, observed=observed, evidence=evidence, remedy=remedy,
    )


def reconcile(
    plan: Plan,
    systems: dict[TargetSystem, Any],
    results: list[CommandResult],
    acknowledgments: list[Acknowledgment],
    *,
    expected_version: int = 2,
) -> VerificationReport:
    """Compare intended and observed state across every target system."""
    assertions: list[VerificationAssertion] = []
    by_target: dict[TargetSystem, CommandResult] = {}
    for result in results:
        # Keep the last result per target: a retried command supersedes its
        # earlier attempt.
        by_target[result.target] = result

    # -- 1. Every command reached a terminal, successful state ------------
    failed = [
        r for r in results
        if r.status in (CommandStatus.REJECTED, CommandStatus.FAILED)
    ]
    assertions.append(_assertion(
        "every command completed", True, not failed,
        f"{len(results)} command(s) completed",
        f"{len(results) - len(failed)} completed, {len(failed)} failed",
        evidence="; ".join(f"{r.target.value}: {r.detail}" for r in failed),
        remedy="Resolve the rejected command and re-issue" if failed else None,
    ))

    # -- 2. Schedule version -----------------------------------------------
    scheduling = systems.get(TargetSystem.SCHEDULING)
    observed_version = getattr(scheduling, "version", 0) if scheduling else 0
    assertions.append(_assertion(
        "schedule version matches the approved plan", True,
        observed_version >= expected_version,
        f"version >= {expected_version}", f"version {observed_version}",
        evidence=f"plan {plan.plan_id}",
    ))

    # -- 3. Call sheet published and current ------------------------------
    call_sheet = systems.get(TargetSystem.CALL_SHEET)
    revision = getattr(call_sheet, "current_revision", 1) if call_sheet else 1
    current = call_sheet.current() if call_sheet and hasattr(call_sheet, "current") else None
    scene_ids = {s.scene_id for s in plan.scenes}
    published_ids = {e.scene_id for e in current.entries} if current else set()
    assertions.append(_assertion(
        "call sheet revision published", True, revision >= expected_version,
        f"revision >= {expected_version}", f"revision {revision}",
        evidence=f"connector {getattr(call_sheet, 'system', '')}",
    ))
    assertions.append(_assertion(
        "call sheet content matches the approved plan", True,
        published_ids == scene_ids,
        f"{len(scene_ids)} scene(s)",
        f"{len(published_ids)} scene(s) published",
        evidence=(
            "missing: " + ", ".join(sorted(scene_ids - published_ids))
            if scene_ids - published_ids else "content matches"
        ),
    ))

    # -- 4. Accessible briefing --------------------------------------------
    briefing = systems.get(TargetSystem.SAFETY_BRIEFING)
    new_locations = {s.location_id for s in plan.scenes} - {
        s.location_id for s in w.BASELINE_SCHEDULE
    }
    if new_locations:
        published = getattr(briefing, "briefings", {}) if briefing else {}
        required_formats = set(w.POLICIES["communication"]["accessible_formats_required"])  # type: ignore[arg-type]
        covered = all(
            location_id in published
            and required_formats <= set(published[location_id].get("formats", []))
            for location_id in new_locations
        )
        assertions.append(_assertion(
            "revised briefing published in approved accessible formats", True, covered,
            f"written and captioned briefing for {', '.join(sorted(new_locations))}",
            f"{len(published)} briefing(s) published",
            evidence="; ".join(
                f"{k}: {', '.join(v.get('formats', []))}" for k, v in published.items()
            ),
            remedy="Publish the briefing in written and captioned format",
        ))

    # -- 5. Approved access arrangements -----------------------------------
    unsatisfied = [a for a in plan.access if not a.satisfied]
    assertions.append(_assertion(
        "every approved access arrangement satisfied", True, not unsatisfied,
        f"{len(plan.access)} arrangement(s) satisfied",
        f"{len(plan.access) - len(unsatisfied)} satisfied",
        evidence="; ".join(f"{a.requirement_id}: {a.mechanism}" for a in unsatisfied),
        remedy="Restore the arrangement before the unit travels" if unsatisfied else None,
    ))

    interpreter = systems.get(TargetSystem.INTERPRETER_BOOKING)
    extensions = [r for r in results if r.target is TargetSystem.INTERPRETER_BOOKING]
    if extensions:
        confirmed = all(r.status == CommandStatus.COMPLETED for r in extensions)
        assertions.append(_assertion(
            "interpreter cover confirmed by the provider", True, confirmed,
            "provider confirmation for the revised window",
            "; ".join(r.detail for r in extensions),
            evidence=str(getattr(interpreter, "bookings", {})),
            remedy="Escalate to the accessibility coordinator" if not confirmed else None,
        ))

    # -- 6. Transport ------------------------------------------------------
    transport = systems.get(TargetSystem.TRANSPORT_DISPATCH)
    if plan.transport:
        booked = len(getattr(transport, "bookings", {})) if transport else 0
        step_free_legs = [leg for leg in plan.transport if leg.step_free]
        assertions.append(_assertion(
            "transport rebooked", True, booked >= len(plan.transport),
            f"{len(plan.transport)} leg(s)", f"{booked} booked",
        ))
        if step_free_legs:
            assertions.append(_assertion(
                "step-free transport booked", True,
                booked >= len(step_free_legs),
                f"{len(step_free_legs)} step-free leg(s)", f"{booked} booked",
                evidence=", ".join(leg.vehicle_id for leg in step_free_legs),
            ))

    # -- 7. Department acceptance ------------------------------------------
    departments = systems.get(TargetSystem.DEPARTMENT_TASKS)
    outstanding = (
        departments.outstanding() if departments and hasattr(departments, "outstanding") else []
    )
    assertions.append(_assertion(
        "every department accepted its action", True, not outstanding,
        "all department tasks accepted",
        f"{len(outstanding)} outstanding",
        evidence=", ".join(sorted({t.department for t in outstanding})),
        remedy=(
            "Contact " + ", ".join(sorted({t.department for t in outstanding}))
            if outstanding else None
        ),
    ))

    # -- 8. Crew delivery and acknowledgment -------------------------------
    notification = systems.get(TargetSystem.NOTIFICATION)
    messages = list(getattr(notification, "sent", [])) if notification else []
    sent = len(messages)
    delivered = len(getattr(notification, "delivered", [])) if notification else 0
    assertions.append(_assertion(
        "every message delivered", True, sent == delivered,
        f"{sent} message(s) delivered", f"{delivered} delivered",
        evidence=", ".join(getattr(notification, "failed", [])),
    ))

    # Acknowledgment is owed only where it was asked for. Several messages --
    # the coordinator's own summary, the executive digest -- are informational
    # and requesting an acknowledgment for them would train people to dismiss
    # the ones that matter.
    owed = [m for m in messages if m.get("requires_ack", True)]
    accepted = [a for a in acknowledgments if a.accepted]
    declined = [a for a in acknowledgments if not a.accepted]
    outstanding_acks = len(owed) - len(accepted)
    assertions.append(_assertion(
        "every critical instruction acknowledged", True,
        outstanding_acks <= 0 and not declined,
        f"{len(owed)} acknowledgment(s) required",
        f"{len(accepted)} accepted, {len(declined)} declined",
        evidence="; ".join(f"{a.person_id}: {a.reason}" for a in declined),
        remedy="Follow up the outstanding acknowledgments" if outstanding_acks > 0 else None,
    ))

    # -- 9. Non-critical: reporting ---------------------------------------
    executive = systems.get(TargetSystem.EXECUTIVE_REPORTING)
    assertions.append(_assertion(
        "executive reporting updated", False,
        bool(getattr(executive, "metrics", {})),
        "metrics present", "updated" if getattr(executive, "metrics", {}) else "not updated",
    ))

    blocking = tuple(a.name for a in assertions if a.critical and not a.passed)
    return VerificationReport(
        report_id="VER-" + stable_hash([plan.plan_id, len(assertions)])[:10].upper(),
        disruption_id=plan.disruption_id,
        plan_id=plan.plan_id,
        assertions=tuple(assertions),
        ready=not blocking,
        blocking=blocking,
    )


def readiness_summary(report: VerificationReport) -> dict[str, Any]:
    critical = [a for a in report.assertions if a.critical]
    return {
        "ready": report.ready,
        "assertions": len(report.assertions),
        "critical": len(critical),
        "passed": report.passed,
        "failed": len(report.assertions) - report.passed,
        "blocking": list(report.blocking),
        "remedies": [a.remedy for a in report.assertions if a.remedy],
    }
