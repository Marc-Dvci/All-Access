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
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

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


# ---------------------------------------------------------------------------
# Who is signing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signature:
    """One named person putting their authority behind one role on one plan.

    `channel` is how *this* signature was obtained, and it is per-signature
    rather than per-gateway because one gateway can collect signatures from
    more than one kind of identity: a production authority signing at the
    workspace, and an evaluation identity signing on the judging link. A
    channel read off the gateway would have called both of those `human`.
    """

    actor: str
    rationale: str
    channel: str = "human"


class ApprovalGateway(Protocol):
    """Where the coordinator goes to find out what a human decided.

    The workflow can prove a great deal about an approval — that it is bound to
    this plan and this constraint set, that it has not been used before, that it
    has not expired, that every required authority is present. It cannot prove
    that a person was at the other end of it. That is not a property of a
    signature; it is a property of how the signature was obtained.

    So the workflow stops asserting it and records it instead. Every gateway
    declares a `channel`, the channel is written onto the approval-requested and
    approval-granted events, and the interface prints it next to the signature.
    A run signed at a browser says `human`. A run signed by the stand-in says
    `stand_in`, in the log, in the API and on the screen.
    """

    #: How these signatures were obtained. Written onto every approval event.
    channel: str

    def select(self, plans: list[Plan], pareto: list[str]) -> Plan | None:
        """Which plan to route for approval, or `None` to abandon."""
        ...

    def sign(self, request: ApprovalRequest, role: Role) -> Signature | None:
        """The signature for one required role, or `None` if it is refused."""
        ...


class StandInApprover:
    """The unattended path: no human is present, and the log says so.

    This is what runs the thousand-scenario benchmark, the test suite and any
    CLI invocation that nobody is watching. It exists because a workflow that
    could only complete with somebody clicking could not be measured a thousand
    times, and a system whose recovery numbers cannot be measured is a demo.

    Two things it deliberately does not do. It does not choose a dominated plan
    — the selection comes off the Pareto front, so an unattended run is never
    quietly worse than the front it was offered. And it does not sign in a crew
    member's name: the actor on a stand-in approval is `STAND-IN/<role>`, which
    is not the identifier of any person in the production and cannot be mistaken
    for one when someone reads the ledger back.
    """

    channel = "stand_in"

    def select(self, plans: list[Plan], pareto: list[str]) -> Plan | None:
        front = [p for p in plans if p.plan_id in pareto] or plans
        return front[0] if front else None

    def sign(self, request: ApprovalRequest, role: Role) -> Signature | None:
        return Signature(
            channel=self.channel,
            actor=f"STAND-IN/{role.value}",
            rationale=(
                f"Unattended run: {request.summary}. No person reviewed this plan. "
                f"The plan is on the Pareto front, preserves every approved access "
                f"arrangement and satisfies every active constraint."
            ),
        )


class ApprovalRefused(RuntimeError):
    """A person declined. Not an error in the system; an answer from outside it."""


class HumanApprovalGateway:
    """The workflow stops here until a person decides, and blocks if none does.

    The gateway is deliberately the dullest object in the system: two waits and
    a handful of state. Its whole value is that it cannot be satisfied from
    inside the process. `select` returns when somebody has chosen a plan;
    `sign` returns when somebody has put their name to one role. Nothing here
    supplies a default, and nothing here times out into one — a wait that runs
    out abandons the disruption, because a plan nobody approved is a plan that
    does not execute.

    That is the entire difference between this and `StandInApprover`, and it is
    the difference the headline claim rests on. The signature integrity is the
    same either way: hash-bound, single-use, expiring. What changes is who was
    at the other end, and the channel written onto every event is how a reader
    of the log tells the two apart.

    One gateway serves one disruption. `cancel` releases a workflow still
    waiting on a session that has been replaced.
    """

    channel = "human"

    def __init__(self, *, timeout: float = 1800.0,
                 on_pause: Callable[[], None] | None = None) -> None:
        self.timeout = timeout
        self._on_pause = on_pause
        self._state = threading.Condition()
        self._selected: Plan | None = None
        self._signatures: dict[Role, Signature] = {}
        self._refusal: str | None = None
        self._cancelled = False

        #: What the workflow is waiting for right now, for the interface to
        #: render: `None`, `"selection"`, or the role whose signature is due.
        self.waiting_on: str | None = None
        #: The plans offered for selection, and the front among them.
        self.offered: list[Plan] = []
        self.pareto: list[str] = []
        #: The approval request under signature, once a plan has been chosen.
        self.request: ApprovalRequest | None = None

    # -- the workflow side -------------------------------------------------

    def select(self, plans: list[Plan], pareto: list[str]) -> Plan | None:
        with self._state:
            self.offered = list(plans)
            self.pareto = list(pareto)
            self._wait_for("selection", lambda: self._selected is not None)
            return self._selected

    def sign(self, request: ApprovalRequest, role: Role) -> Signature | None:
        with self._state:
            self.request = request
            self._wait_for(role.value, lambda: role in self._signatures)
            return self._signatures.get(role)

    def _wait_for(self, what: str, done: Callable[[], bool]) -> None:
        """Hold the workflow until `done`, a refusal, a cancellation or the clock."""
        self.waiting_on = what
        if self._on_pause is not None:
            self._on_pause()
        try:
            self._state.wait_for(
                lambda: done() or self._refusal is not None or self._cancelled,
                timeout=self.timeout,
            )
        finally:
            self.waiting_on = None

    # -- the person's side -------------------------------------------------

    def choose(self, plan_id: str) -> Plan:
        with self._state:
            plan = next((p for p in self.offered if p.plan_id == plan_id), None)
            if plan is None:
                raise ApprovalError(f"{plan_id} was not offered for approval")
            if not plan.feasible:
                raise ApprovalError(f"{plan_id} is not feasible and cannot be approved")
            self._selected = plan
            self._state.notify_all()
            return plan

    def endorse(self, role: Role, actor: str, rationale: str,
                channel: str = "human") -> Signature:
        with self._state:
            if self.request is None:
                raise ApprovalError("no plan has been selected for approval yet")
            if role not in self.request.required_roles:
                raise ApprovalError(
                    f"{role.value} is not a required authority for this plan"
                )
            if not rationale.strip():
                raise ApprovalError("an approval requires a rationale")
            signature = Signature(actor=actor, rationale=rationale, channel=channel)
            self._signatures[role] = signature
            self._state.notify_all()
            return signature

    def refuse(self, reason: str) -> None:
        with self._state:
            self._refusal = reason or "declined"
            self._state.notify_all()

    def cancel(self) -> None:
        with self._state:
            self._cancelled = True
            self._state.notify_all()

    # -- what the interface reads ------------------------------------------

    @property
    def signed_roles(self) -> tuple[Role, ...]:
        return tuple(self._signatures)

    @property
    def refusal(self) -> str | None:
        return self._refusal
