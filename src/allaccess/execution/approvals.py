"""Approval integrity.

An approval here is a signed, single-use, hash-bound authorisation. Four
properties, each of which closes a specific way an approval can be misused:

* **Hash-bound to the plan.** The signature covers `plan_hash`, so an approval
  cannot be moved to a different plan.
* **Hash-bound to the constraint set.** It also covers `constraint_hash`. An
  approval granted while a constraint was inactive cannot be replayed once that
  constraint returns — the hash will not match and the approval is refused.
* **Single use.** `consume()` marks it spent. A replayed approval event does not
  authorise a second execution.
* **Expiring.** An approval is valid for a bounded window, because a decision
  taken against conditions at 19:00 should not silently authorise an action at
  midnight.

Authority is checked separately, in `policy.py`: holding a valid signature does
not make someone the right person to sign.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..contracts import (
    DEFAULT_APPROVAL_TTL,
    Approval,
    ApprovalRequest,
    Plan,
    Role,
    stable_hash,
    utcnow,
)


def _key() -> bytes:
    configured = os.environ.get("AA_APPROVAL_KEY")
    if configured:
        return configured.encode("utf-8")
    # Per-process. A deployment supplies AA_APPROVAL_KEY from Secret Manager so
    # approvals stay verifiable across restarts; within a demonstration run this
    # is sufficient and requires no configuration.
    return hashlib.sha256(f"pp-approval-{os.getpid()}".encode()).digest()


_APPROVAL_KEY = _key()


def signature_for(
    plan_id: str, plan_hash: str, constraint_hash: str, actor: str, role: Role,
    scope: str, expires_at: datetime,
) -> str:
    body = "|".join([
        plan_id, plan_hash, constraint_hash, actor, role.value, scope,
        expires_at.isoformat(),
    ])
    return hmac.new(_APPROVAL_KEY, body.encode("utf-8"), hashlib.sha256).hexdigest()


class ApprovalError(RuntimeError):
    pass


@dataclass
class ApprovalLedger:
    """Requests, grants and the single-use record."""

    requests: dict[str, ApprovalRequest] = field(default_factory=dict)
    approvals: dict[str, Approval] = field(default_factory=dict)
    consumed: set[str] = field(default_factory=set)
    refusals: list[str] = field(default_factory=list)

    def request(
        self,
        plan: Plan,
        constraint_hash: str,
        *,
        scope: str,
        summary: str,
        ttl: timedelta = DEFAULT_APPROVAL_TTL,
    ) -> ApprovalRequest:
        if not plan.feasible:
            # An infeasible plan is never routed for approval. The alternative —
            # letting a human "approve anyway" — is precisely the failure mode
            # the whole system exists to prevent.
            raise ApprovalError(
                f"{plan.plan_id} is not feasible and cannot be routed for approval"
            )
        request = ApprovalRequest(
            request_id="REQ-" + stable_hash(
                [plan.plan_id, scope, utcnow().isoformat()]
            )[:10].upper(),
            disruption_id=plan.disruption_id,
            plan_id=plan.plan_id,
            plan_hash=plan.content_hash(),
            constraint_hash=constraint_hash,
            required_roles=plan.required_approvals,
            scope=scope,
            summary=summary,
            expires_at=utcnow() + ttl,
        )
        self.requests[request.request_id] = request
        return request

    def grant(
        self,
        request_id: str,
        actor: str,
        role: Role,
        rationale: str,
        production_id: str,
    ) -> Approval:
        request = self.requests.get(request_id)
        if request is None:
            raise ApprovalError(f"unknown approval request {request_id}")
        if utcnow() > request.expires_at:
            raise ApprovalError(f"approval request {request_id} expired")
        if role not in request.required_roles:
            raise ApprovalError(
                f"{role.value} is not among the required authorities for {request_id}: "
                + ", ".join(r.value for r in request.required_roles)
            )
        if not rationale.strip():
            raise ApprovalError("an approval requires a rationale")

        approval = Approval(
            approval_id="APR-" + stable_hash([request_id, actor, role.value])[:10].upper(),
            request_id=request_id,
            disruption_id=request.disruption_id,
            plan_id=request.plan_id,
            plan_hash=request.plan_hash,
            constraint_hash=request.constraint_hash,
            actor=actor,
            role=role,
            production_id=production_id,
            approved_scope=request.scope,
            rationale=rationale,
            expires_at=request.expires_at,
            signature=signature_for(
                request.plan_id, request.plan_hash, request.constraint_hash,
                actor, role, request.scope, request.expires_at,
            ),
        )
        self.approvals[approval.approval_id] = approval
        return approval

    def verify(
        self,
        approval: Approval,
        plan: Plan,
        constraint_hash: str,
    ) -> tuple[bool, str]:
        """Check an approval against the plan and constraint set it claims to cover."""
        expected = signature_for(
            approval.plan_id, approval.plan_hash, approval.constraint_hash,
            approval.actor, approval.role, approval.approved_scope, approval.expires_at,
        )
        if not hmac.compare_digest(expected, approval.signature):
            return False, "signature does not verify"
        if approval.approval_id in self.consumed:
            return False, "approval has already been used"
        if utcnow() > approval.expires_at:
            return False, f"approval expired at {approval.expires_at:%H:%M}"
        if approval.plan_id != plan.plan_id:
            return False, f"approval is for {approval.plan_id}, not {plan.plan_id}"
        if approval.plan_hash != plan.content_hash():
            return False, "the plan has changed since it was approved"
        if approval.constraint_hash != constraint_hash:
            return False, (
                "the active constraint set has changed since the approval was granted"
            )
        return True, ""

    def consume(self, approval: Approval, plan: Plan, constraint_hash: str) -> Approval:
        ok, reason = self.verify(approval, plan, constraint_hash)
        if not ok:
            self.refusals.append(f"{approval.approval_id}: {reason}")
            raise ApprovalError(reason)
        self.consumed.add(approval.approval_id)
        return approval.model_copy(update={"consumed": True})

    def satisfied(self, plan: Plan, granted: list[Approval]) -> tuple[bool, list[Role]]:
        """Whether every required authority has signed."""
        signed = {a.role for a in granted if a.plan_id == plan.plan_id}
        missing = [r for r in plan.required_approvals if r not in signed]
        return (not missing), missing
