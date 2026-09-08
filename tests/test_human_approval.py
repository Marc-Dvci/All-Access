"""Nothing executes until a person signs, and the log says which kind of person.

The system can prove a signature is bound to the plan, bound to the constraint
set, unexpired and unused. It cannot prove from the signature alone that a human
produced it. So these tests cover the part that can be established: that the
workflow genuinely stops and waits, that the only way past it is the endpoints a
browser posts to, that a refusal ends the day, and that an unattended run says
so in every event it writes rather than borrowing a crew member's name.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from allaccess import api, identity
from allaccess.contracts import DisruptionState, EventType, Role
from allaccess.execution.approvals import (
    ApprovalError,
    HumanApprovalGateway,
    StandInApprover,
)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AA_APPROVAL_MODE", raising=False)
    api.reset()
    with TestClient(api.app) as c:
        yield c
    session = api._session  # noqa: SLF001
    if session is not None:
        session.release()


def as_person(client, person_id: str) -> None:
    """Sign the client in as one member of the production directory.

    Every write below goes through this, because there is no other way in. The
    client keeps the cookie, so signing in again as somebody else is how a
    second authority signs — which is exactly what happens at the workspace when
    the plan needs two.
    """
    response = client.post("/api/identity/session", json={
        "person_id": person_id, "access_code": identity.access_code(person_id),
    })
    assert response.status_code == 200, response.text


def _holder(role: str) -> str:
    """Whoever holds this authority on the production."""
    return next(e.person_id for e in identity.directory() if e.role.value == role)


def _settle(client, tries: int = 300):
    for _ in range(tries):
        state = client.get("/api/approval").json()
        if not state["awaiting"]:
            return state
        time.sleep(0.02)
    raise AssertionError("the workflow never left the approval gate")


def _pending(client, tries: int = 200):
    """The gate's current state, once it has one."""
    for _ in range(tries):
        pending = client.get("/api/approval").json().get("pending")
        if pending and pending.get("waiting_on"):
            return pending
        time.sleep(0.02)
    raise AssertionError("the workflow never reached the approval gate")


# ---------------------------------------------------------------------------
# The gate holds
# ---------------------------------------------------------------------------


def test_the_web_session_stops_and_waits_for_a_person(client) -> None:
    state = client.get("/api/approval").json()

    assert state["channel"] == "human"
    assert state["awaiting"] is True
    assert state["pending"]["waiting_on"] == "selection"
    assert state["selected"] is None

    # It stopped after doing all the work it can do alone.
    board = client.get("/api/control-board").json()
    assert board["disruption"]["state"] == DisruptionState.AWAITING_APPROVAL.value
    assert len(client.get("/api/plans").json()["feasible"]) > 1
    assert client.get("/api/findings").json()["findings"]

    # And before doing any of the work it may not.
    assert client.get("/api/execution").json()["commands"] == []


def test_only_plans_that_were_offered_can_be_chosen(client) -> None:
    as_person(client, _holder(Role.UPM.value))
    response = client.post("/api/approval/select", json={"plan_id": "PLAN-NOT-OFFERED"})
    assert response.status_code == 409


def test_signing_needs_a_plan_first(client) -> None:
    as_person(client, _holder(Role.UPM.value))
    response = client.post("/api/approval/sign", json={"role": Role.UPM.value})
    assert response.status_code == 409


def test_an_unrequired_authority_cannot_sign(client) -> None:
    """Holding the authority is not the same as the plan needing it.

    The signer here is a real, signed-in authority on this production with a
    session that genuinely holds the role. The refusal comes from the plan, and
    it has to, because an authority who may sign *something* is the ordinary
    case rather than the attack.
    """
    pending = _pending(client)
    as_person(client, _holder(Role.UPM.value))
    client.post(
        "/api/approval/select", json={"plan_id": pending["offered"][0]["plan_id"]},
    )
    roles = None
    for _ in range(200):
        roles = (client.get("/api/approval").json().get("pending") or {}).get("roles")
        if roles:
            break
        time.sleep(0.02)
    required = {row["role"] for row in roles or ()}
    assert required
    spare = next(
        e for e in identity.directory()
        if e.signs and e.role.value not in required
    )
    as_person(client, spare.person_id)

    response = client.post("/api/approval/sign", json={"role": spare.role.value})
    assert response.status_code == 409


# ---------------------------------------------------------------------------
# The gate opens, and records how
# ---------------------------------------------------------------------------


def test_a_signed_plan_executes_and_the_events_name_the_channel(client) -> None:
    pending = _pending(client)
    front = [p for p in pending["offered"] if p["plan_id"] in pending["pareto_front"]]
    chosen = front[0]["plan_id"]
    as_person(client, _holder(Role.UPM.value))
    client.post("/api/approval/select", json={"plan_id": chosen})

    signed = []
    for _ in range(300):
        state = client.get("/api/approval").json()
        if not state["awaiting"]:
            break
        waiting = (state["pending"] or {}).get("waiting_on")
        if waiting and waiting != "selection":
            # Each authority signs from its own session. One session cannot
            # cover two of them, which is what makes a two-signature plan a
            # two-person decision rather than two clicks.
            as_person(client, _holder(waiting))
            assert client.post(
                "/api/approval/sign", json={"role": waiting}
            ).status_code == 200
            signed.append(waiting)
        else:
            time.sleep(0.02)

    final = _settle(client)
    assert signed
    assert final["channel"] == "human"
    assert final["selected"]["plan_id"] == chosen
    assert {a["role"] for a in final["approvals"]} == set(signed)

    # Signed by named people on this production, not by the system.
    assert all(a["actor"].startswith("CREW-") for a in final["approvals"])

    approvals = [
        e for e in api.session().events
        if e.envelope.event_type is EventType.PLAN_APPROVED
    ]
    assert approvals
    assert all(e.payload["approval_channel"] == "human" for e in approvals)
    assert client.get("/api/execution").json()["commands"]


def test_a_refusal_abandons_the_day_and_issues_nothing(client) -> None:
    pending = _pending(client)
    as_person(client, _holder(Role.UPM.value))
    client.post(
        "/api/approval/select", json={"plan_id": pending["offered"][0]["plan_id"]},
    )
    client.post("/api/approval/refuse", json={"reason": "not with that call time"})

    _settle(client)
    board = client.get("/api/control-board").json()
    assert board["disruption"]["state"] == DisruptionState.ABANDONED.value
    assert client.get("/api/execution").json()["commands"] == []


# ---------------------------------------------------------------------------
# The unattended path says what it is
# ---------------------------------------------------------------------------


def test_the_stand_in_never_signs_in_a_crew_members_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AA_APPROVAL_MODE", "stand_in")
    api.reset()
    with TestClient(api.app) as client:
        state = client.get("/api/approval").json()
        assert state["awaiting"] is False
        assert state["channel"] == "stand_in"
        assert state["approvals"]
        for approval in state["approvals"]:
            assert approval["actor"].startswith("STAND-IN/")
            assert "No person reviewed this plan" in approval["rationale"]

        response = client.post("/api/approval/select", json={"plan_id": "anything"})
        assert response.status_code == 409


def test_the_stream_refuses_an_approval_that_does_not_declare_its_channel() -> None:
    """The honesty is enforced at the boundary, not asked for in a document."""
    from allaccess.stream.registry import LocalSchemaRegistry

    registry = LocalSchemaRegistry()
    payload = {
        "approval_id": "APR-TEST", "request_id": "REQ-TEST",
        "disruption_id": "DISR-TEST", "plan_id": "PLAN-TEST",
        "plan_hash": "h" * 64, "constraint_hash": "c" * 64,
        "actor": "CREW-UPM", "role": Role.UPM.value,
        "approved_scope": "scope", "rationale": "because",
        "expires_at": "2026-09-08T21:00:00+00:00", "signature": "s" * 64,
    }
    missing = registry.validate(EventType.PLAN_APPROVED, payload)
    assert not missing.valid
    assert any("approval_channel" in e for e in missing.errors), missing.errors

    borrowed = registry.validate(
        EventType.PLAN_APPROVED, {**payload, "approval_channel": "stand_in"},
    )
    assert not borrowed.valid, "a stand-in approval may not wear a crew identifier"

    signed = registry.validate(
        EventType.PLAN_APPROVED, {**payload, "approval_channel": "human"},
    )
    assert signed.valid, signed.errors


# ---------------------------------------------------------------------------
# The gateways themselves
# ---------------------------------------------------------------------------


class _Candidate:
    def __init__(self, plan_id: str, feasible: bool = True) -> None:
        self.plan_id = plan_id
        self.feasible = feasible


def test_the_stand_in_picks_off_the_front_and_never_below_it() -> None:
    approver = StandInApprover()
    plans = [_Candidate("A"), _Candidate("B"), _Candidate("C")]
    assert approver.select(plans, ["B", "C"]).plan_id == "B"
    assert approver.select(plans, []).plan_id == "A"
    assert approver.select([], ["B"]) is None


def test_the_human_gateway_refuses_an_infeasible_plan() -> None:
    gateway = HumanApprovalGateway(timeout=0.1)
    gateway.offered = [_Candidate("PLAN-X", feasible=False)]
    with pytest.raises(ApprovalError):
        gateway.choose("PLAN-X")


def test_a_gateway_nobody_answers_approves_nothing() -> None:
    gateway = HumanApprovalGateway(timeout=0.05)
    assert gateway.select([], []) is None
