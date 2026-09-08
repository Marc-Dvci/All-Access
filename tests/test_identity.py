"""Authority is a claim the server establishes, not a field the client sends.

`docs/IAM.md` used to say the quiet part in its own words: the web application
had no identity provider, and a role was a parameter rather than a claim. Every
control below the approval gate was sound and none of them established who was
at the keyboard, so the system could prove an approval had been recorded and
could not prove a first AD recorded it.

These tests cover the boundary that closes it, and they are written against the
failure rather than the feature: what an unauthenticated caller can do to the
gate, what a session that holds one authority can do about another, what a
forged or edited token establishes, and whether the identity that may sign for
everything can hide inside a crew member's name.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from allaccess import api, identity
from allaccess.contracts import EventType, Role
from allaccess.stream.registry import LocalSchemaRegistry

JUDGE_KEY = "test-evaluation-key-0123456789"


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AA_APPROVAL_MODE", raising=False)
    monkeypatch.setenv("AA_AUTH_MODE", "demo")
    monkeypatch.setenv("AA_JUDGE_KEY", JUDGE_KEY)
    api.reset()
    with TestClient(api.app) as c:
        yield c
    session = api._session  # noqa: SLF001
    if session is not None:
        session.release()


def _pending(client, tries: int = 200):
    for _ in range(tries):
        pending = client.get("/api/approval").json().get("pending")
        if pending and pending.get("waiting_on"):
            return pending
        time.sleep(0.02)
    raise AssertionError("the workflow never reached the approval gate")


def _sign_in(client, person_id: str):
    return client.post("/api/identity/session", json={
        "person_id": person_id, "access_code": identity.access_code(person_id),
    })


def _holder(role: Role) -> str:
    return next(e.person_id for e in identity.directory() if e.role is role)


# ---------------------------------------------------------------------------
# Nothing without an identity
# ---------------------------------------------------------------------------


def test_an_anonymous_caller_cannot_touch_the_gate(client) -> None:
    """The three endpoints that change anything all need a session first."""
    pending = _pending(client)
    plan_id = pending["offered"][0]["plan_id"]

    assert client.get("/api/identity").json()["principal"] is None
    assert client.post(
        "/api/approval/select", json={"plan_id": plan_id}
    ).status_code == 401
    assert client.post(
        "/api/approval/sign", json={"role": Role.UPM.value}
    ).status_code == 401
    assert client.post(
        "/api/approval/refuse", json={"reason": "no"}
    ).status_code == 401

    # And the refusal is not cosmetic: the gate is still shut and nothing ran.
    assert client.get("/api/approval").json()["awaiting"] is True
    assert client.get("/api/execution").json()["commands"] == []


def test_reading_the_product_never_needs_an_identity(client) -> None:
    """Everything that is a read model over a decision stays open.

    The gate is the boundary, not the site. A visitor with no credential can
    still see every plan, every conflict set and every rejected option — which
    is the part of this product that is worth showing.
    """
    for path in ("/api/control-board", "/api/plans", "/api/findings", "/api/impact",
                 "/api/replay", "/api/streams", "/api/executive"):
        assert client.get(path).status_code == 200, path


# ---------------------------------------------------------------------------
# A session cannot widen itself
# ---------------------------------------------------------------------------


def test_a_session_cannot_sign_for_an_authority_it_does_not_hold(client) -> None:
    pending = _pending(client)
    _sign_in(client, _holder(Role.UPM))
    client.post("/api/approval/select", json={"plan_id": pending["offered"][0]["plan_id"]})

    # The location manager's session, asked to sign as the UPM.
    _sign_in(client, _holder(Role.LOCATION_MANAGER))
    response = client.post("/api/approval/sign", json={"role": Role.UPM.value})
    assert response.status_code == 403
    assert "does not hold" in response.json()["error"]

    approved = [
        e for e in api.session().events
        if e.envelope.event_type is EventType.PLAN_APPROVED
    ]
    assert approved == []


def test_the_client_cannot_name_its_own_actor(client) -> None:
    """The body used to carry `actor`. Sending one now changes nothing."""
    pending = _pending(client)
    upm = _holder(Role.UPM)
    _sign_in(client, upm)
    client.post("/api/approval/select", json={"plan_id": pending["offered"][0]["plan_id"]})

    for _ in range(200):
        waiting = (client.get("/api/approval").json().get("pending") or {}).get(
            "waiting_on")
        if waiting and waiting != "selection":
            break
        time.sleep(0.02)

    _sign_in(client, _holder(Role(waiting)))
    response = client.post("/api/approval/sign", json={
        "role": waiting, "actor": "CREW-SOMEBODY-ELSE",
    })
    assert response.status_code == 200
    assert response.json()["actor"] == _holder(Role(waiting))


def test_an_edited_token_establishes_nothing(client) -> None:
    """Roles travel in the token, and the token is signed over its own roles."""
    upm = _holder(Role.UPM)
    principal = identity.sign_in(upm, identity.access_code(upm))
    good = identity.mint(principal)
    assert identity.verify(good) is not None

    widened = identity.mint(identity.Principal(
        **{**principal.__dict__, "roles": identity.SIGNING_AUTHORITIES}))
    # Minted with the same key, so this one *is* valid — the point is that a
    # client cannot mint it. Edit the payload of a token it was given instead.
    assert identity.verify(widened) is not None

    encoded, _, signature = good.partition(".")
    forged = encoded[:-4] + "AAAA" + "." + signature
    assert identity.verify(forged) is None
    assert identity.verify(encoded + ".not-a-signature") is None
    assert identity.verify("") is None

    client.cookies.set(api.SESSION_COOKIE, forged)
    assert client.get("/api/identity").json()["principal"] is None
    assert client.post(
        "/api/approval/sign", json={"role": Role.UPM.value}
    ).status_code == 401


def test_an_expired_session_stops_working() -> None:
    from datetime import timedelta

    from allaccess.contracts import utcnow

    upm = _holder(Role.UPM)
    principal = identity.sign_in(upm, identity.access_code(upm))
    stale = identity.Principal(**{
        **principal.__dict__,
        "issued_at": utcnow() - timedelta(hours=24),
        "expires_at": utcnow() - timedelta(minutes=1),
    })
    assert identity.verify(identity.mint(stale)) is None


def test_a_wrong_access_code_is_refused(client) -> None:
    upm = _holder(Role.UPM)
    assert client.post("/api/identity/session", json={
        "person_id": upm, "access_code": "NOPE12",
    }).status_code == 401
    assert client.post("/api/identity/session", json={
        "person_id": "CREW-NOBODY", "access_code": identity.access_code("CREW-NOBODY"),
    }).status_code == 401
    # A crew member with no approving authority is not in the directory at all,
    # so there is no credential to issue them.
    assert client.post("/api/identity/session", json={
        "person_id": "CREW-AC1", "access_code": identity.access_code("CREW-AC1"),
    }).status_code == 401


def test_signing_out_ends_the_session(client) -> None:
    _sign_in(client, _holder(Role.UPM))
    assert client.get("/api/identity").json()["principal"]["subject"]
    client.delete("/api/identity/session")
    assert client.get("/api/identity").json()["principal"] is None


# ---------------------------------------------------------------------------
# Routing is not approving
# ---------------------------------------------------------------------------


def test_the_coordinator_routes_and_can_never_sign(client) -> None:
    """`IAM.md` §1.1 says the coordinator approves nothing. This is that sentence."""
    pending = _pending(client)
    _sign_in(client, _holder(Role.COORDINATOR))

    assert client.post(
        "/api/approval/select", json={"plan_id": pending["offered"][0]["plan_id"]},
    ).status_code == 200

    for role in identity.SIGNING_AUTHORITIES:
        response = client.post("/api/approval/sign", json={"role": role.value})
        assert response.status_code == 403, role


# ---------------------------------------------------------------------------
# The evaluation identity
# ---------------------------------------------------------------------------


def test_the_evaluation_key_mints_an_identity_that_names_itself(client) -> None:
    """A judge can complete the loop alone, and the ledger says one did.

    This is the trade the judging link makes and the reason it is visible: an
    evaluation identity holds every authority, which is a real weakening of
    separation of duty, so every approval it produces is `JUDGE/<role>` on
    channel `judge` rather than a crew member's name.
    """
    pending = _pending(client)
    response = client.post("/api/identity/session", json={"judge_key": JUDGE_KEY})
    assert response.status_code == 200
    who = response.json()["principal"]
    assert who["channel"] == "judge"
    assert who["subject"].startswith("JUDGE-")
    assert set(who["roles"]) == {r.value for r in identity.SIGNING_AUTHORITIES}

    front = [p for p in pending["offered"] if p["plan_id"] in pending["pareto_front"]]
    client.post("/api/approval/select", json={"plan_id": front[0]["plan_id"]})

    signed = []
    for _ in range(300):
        state = client.get("/api/approval").json()
        if not state["awaiting"]:
            break
        waiting = (state["pending"] or {}).get("waiting_on")
        if waiting and waiting != "selection":
            assert client.post(
                "/api/approval/sign", json={"role": waiting}
            ).status_code == 200
            signed.append(waiting)
        else:
            time.sleep(0.02)

    assert len(signed) >= 1
    final = client.get("/api/approval").json()
    assert final["approvals"]
    for approval in final["approvals"]:
        assert approval["actor"].startswith("JUDGE/")
        assert approval["channel"] == "judge"

    events = [
        e for e in api.session().events
        if e.envelope.event_type is EventType.PLAN_APPROVED
    ]
    assert events
    assert all(e.payload["approval_channel"] == "judge" for e in events)
    assert client.get("/api/execution").json()["commands"]


def test_a_wrong_evaluation_key_is_refused(client) -> None:
    assert client.post("/api/identity/session", json={
        "judge_key": JUDGE_KEY + "x",
    }).status_code == 401


def test_no_evaluation_key_configured_means_no_evaluation_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AA_JUDGE_KEY", raising=False)
    with pytest.raises(identity.IdentityError):
        identity.judge_sign_in("")
    with pytest.raises(identity.IdentityError):
        identity.judge_sign_in(JUDGE_KEY)


def test_the_stream_refuses_an_evaluation_approval_wearing_a_crew_name() -> None:
    """The mirror of the stand-in rule, enforced at the same boundary."""
    registry = LocalSchemaRegistry()
    payload = {
        "approval_id": "APR-TEST", "request_id": "REQ-TEST",
        "disruption_id": "DISR-TEST", "plan_id": "PLAN-TEST",
        "plan_hash": "h" * 64, "constraint_hash": "c" * 64,
        "actor": "CREW-UPM", "role": Role.UPM.value,
        "approved_scope": "scope", "rationale": "because",
        "expires_at": "2026-09-08T21:00:00+00:00", "signature": "s" * 64,
    }
    borrowed = registry.validate(
        EventType.PLAN_APPROVED, {**payload, "approval_channel": "judge"})
    assert not borrowed.valid, "an evaluation approval may not wear a crew identifier"

    named = registry.validate(EventType.PLAN_APPROVED, {
        **payload, "approval_channel": "judge", "actor": "JUDGE/unit_production_manager",
    })
    assert named.valid, named.errors


# ---------------------------------------------------------------------------
# The deployment says what it is
# ---------------------------------------------------------------------------


def test_the_gemini_entitlement_is_computed_not_asserted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A judge session never claims a plane the deployment cannot reach."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    plane, reason = identity.gemini_entitlement()
    assert plane == "offline"
    assert "GOOGLE_CLOUD_PROJECT" in reason

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "a-project")
    monkeypatch.setenv("AA_JUDGE_PLANE", "offline")
    assert identity.gemini_entitlement()[0] == "offline"


def test_codes_are_published_only_in_the_demonstration_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AA_AUTH_MODE", "closed")
    assert identity.codes_are_published() is False
    api.reset()
    with TestClient(api.app) as client:
        listed = client.get("/api/identity").json()["directory"]
        assert listed and all(row["access_code"] is None for row in listed)
    session = api._session  # noqa: SLF001
    if session is not None:
        session.release()


def test_proxy_headers_are_ignored_unless_the_deployment_asked_for_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A header is an authority claim only where a proxy is known to set it."""
    headers = {
        "x-goog-authenticated-user-email": "accounts.google.com:sofie@example.com",
    }
    monkeypatch.setenv("AA_AUTH_MODE", "demo")
    monkeypatch.setenv("AA_TRUST_IAP_HEADER", "1")
    assert identity.iap_principal(headers) is None

    monkeypatch.setenv("AA_AUTH_MODE", "iap")
    monkeypatch.setenv("AA_DIRECTORY_EMAILS", '{"sofie@example.com": "CREW-UPM"}')
    who = identity.iap_principal(headers)
    assert who is not None
    assert who.subject == "CREW-UPM"
    assert who.provider == "iap"
    assert who.roles == (Role.UPM,)

    # Authenticated upstream, and holding no authority here.
    stranger = identity.iap_principal({
        "x-goog-authenticated-user-email": "accounts.google.com:nobody@example.com",
    })
    assert stranger is not None
    assert stranger.roles == ()

    monkeypatch.setenv("AA_TRUST_IAP_HEADER", "0")
    assert identity.iap_principal(headers) is None


def test_code_sign_in_is_refused_where_the_proxy_owns_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AA_AUTH_MODE", "iap")
    upm = _holder(Role.UPM)
    with pytest.raises(identity.IdentityError):
        identity.sign_in(upm, identity.access_code(upm))
