"""Who is signing, and how the system knows it.

`IAM.md` used to open its "not done" list with the honest admission that the web
application had no identity provider and that a role arrived as a request
parameter rather than as a claim. That is closed here, and closing it is worth
more than it looks: every other control in this system — the approval matrix,
the hash binding, the single-use ledger, the prohibited changes — establishes
that *this role* authorised *this plan*. None of them establishes that the
person at the keyboard holds the role. Signing an approval payload proves the
application recorded an approval. It does not prove a first AD was there.

So authority now arrives the same way in every deployment:

    request -> provider -> Principal(subject, roles) -> approval

and `POST /api/approval/sign` reads the role off the **principal**, never off
the body. There is no request shape that names its own actor, which means the
worst an unauthenticated caller can do to the approval gate is fail at it.

Three providers, one `Principal`
--------------------------------

* **`directory`** — the production's own crew directory, with a per-person
  access code. This is the demonstration deployment's provider. Its codes are
  *published in the interface on purpose*: a public demonstration whose
  credentials are secret is a demonstration nobody can run. The control being
  demonstrated is not the secrecy of the code, it is that the **server** decides
  which roles a session may sign for and the client cannot assert one.
* **`judge`** — one bearer key, held in Secret Manager and delivered as a link,
  which mints an evaluation identity that may sign for every authority and is
  entitled to the Gemini reasoning plane. It never wears a crew member's name:
  its actor is `JUDGE/<role>`, exactly as the unattended approver's is
  `STAND-IN/<role>`, and the data contract enforces both at the stream boundary.
* **`iap`** — Identity-Aware Proxy in front of Cloud Run. The email is taken
  from the IAP assertion, verified against Google's published keys where
  `google-auth` is installed, and mapped to a person in the production's
  directory. Roles still come from the directory: being able to sign in is not
  the same as holding an authority, which is the whole reason the two are
  separate lookups.

What a session is
-----------------

An HMAC-signed, expiring bearer token carrying the subject, the roles and the
plane entitlement — the same discipline as `execution/approvals.py`, and for the
same reason. Verification recomputes the signature over the payload, so a client
that edits its own roles invalidates it. The key comes from `AA_AUTH_KEY`; a
multi-instance deployment must supply one or sessions stop verifying across
instances, which is called out in `docs/IAM.md`.

What this is not
----------------

It is not a user store, and it deliberately does not become one. There are no
passwords, no registration, no password reset and no self-service role change.
Roles are read from the production's directory on every sign-in, so revoking an
authority is a directory edit rather than a data migration — and a session that
outlives the revocation still cannot sign, because the gate re-checks the role
against the directory at signature time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from .constraints.registry import APPROVAL_MATRIX
from .contracts import Role, utcnow
from .execution.privacy import ROLE_CLEARANCE
from .production import world as w

#: How long a session lasts. Long enough to evaluate the product without signing
#: in twice, short enough that a link pasted into a chat log stops working. A
#: judge who is timed out re-opens the same link.
SESSION_TTL = timedelta(hours=12)

#: The roles that can appear on the right-hand side of the approval matrix.
#: Anybody else in the directory may sign in and read; nobody outside this set
#: can ever be asked to sign, so nobody outside it is offered a credential.
SIGNING_AUTHORITIES: tuple[Role, ...] = tuple(
    dict.fromkeys(role for roles in APPROVAL_MATRIX.values() for role in roles)
)

#: Who may take a plan to signature, or decline it, without being able to sign
#: it. The production coordinator routes and communicates and approves nothing —
#: `IAM.md` §1.1 says so, and this is where that sentence is enforced rather
#: than described. Nothing else is needed to make it true: `may_sign` reads the
#: approval matrix, and the coordinator never appears in it.
ROUTING_AUTHORITIES: tuple[Role, ...] = (*SIGNING_AUTHORITIES, Role.COORDINATOR)


class IdentityError(RuntimeError):
    """A sign-in that did not establish an identity."""


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def auth_mode() -> str:
    """`demo`, `closed` or `iap`.

    `demo` publishes the directory's access codes so the hosted product can be
    driven by anyone; `closed` reads them from `AA_ACCESS_CODES` and publishes
    nothing; `iap` refuses code sign-in altogether and takes identity from the
    proxy. The three differ only in where a subject is established — the
    authority lookup and every check after it are identical.
    """
    mode = os.environ.get("AA_AUTH_MODE", "demo").strip().lower()
    return mode if mode in ("demo", "closed", "iap") else "demo"


def _key() -> bytes:
    configured = os.environ.get("AA_AUTH_KEY")
    if configured:
        return configured.encode("utf-8")
    # Per-process, like the approval key. Sufficient for a single-instance
    # demonstration and explicitly insufficient for a deployment that scales: a
    # session minted on one instance would not verify on the next.
    return hashlib.sha256(f"aa-identity-{os.getpid()}".encode()).digest()


def judge_key() -> str:
    """The one bearer key that mints an evaluation identity, or empty."""
    return os.environ.get("AA_JUDGE_KEY", "").strip()


def gemini_entitlement() -> tuple[str, str]:
    """The plane a judge session gets, and why.

    A deployment with no Vertex project reachable would hand a judge a session
    that claims Gemini and quietly narrates from templates. The entitlement is
    therefore computed from what is actually installed and configured, and the
    reason travels with it to `/api/identity`, so the answer to "which plane am
    I on" is never inferred from a banner.
    """
    if os.environ.get("AA_JUDGE_PLANE", "gemini").strip().lower() != "gemini":
        return "offline", "this deployment pins evaluation sessions to the offline plane"
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return "offline", "no GOOGLE_CLOUD_PROJECT is configured on this deployment"
    try:
        __import__("google.genai")
    except Exception:
        return "offline", "google-genai is not installed in this image"
    return "gemini", "Vertex AI is configured for evaluation sessions"


# ---------------------------------------------------------------------------
# The production directory
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DirectoryEntry:
    person_id: str
    name: str
    title: str
    role: Role

    @property
    def signs(self) -> bool:
        return self.role in SIGNING_AUTHORITIES


def directory() -> tuple[DirectoryEntry, ...]:
    """Everyone in the production who holds an approving authority.

    Two people hold `first_assistant_director` here, and that is the point of
    reading a directory rather than a role table: an authority is held by
    people, sometimes more than one, and either may sign. The approval matrix
    names the authority; the directory names who currently holds it.

    The production coordinator is in the directory and signs nothing. They can
    route a plan to the authorities and they can decline it, and no session they
    hold will ever satisfy a required approval, because the matrix does not name
    them.
    """
    return tuple(
        DirectoryEntry(c.crew_id, c.name, c.role_title, c.authority_role)
        for c in w.CREW
        if c.authority_role in ROUTING_AUTHORITIES
    )


def _entry(person_id: str) -> DirectoryEntry | None:
    return next((e for e in directory() if e.person_id == person_id), None)


def _configured_codes() -> dict[str, str]:
    raw = os.environ.get("AA_ACCESS_CODES", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


def access_code(person_id: str) -> str:
    """This deployment's access code for one person.

    Derived from the deployment's identity key rather than stored, so there is
    no credential file to leak and rotating `AA_AUTH_KEY` rotates every code at
    once. `AA_ACCESS_CODES` — a JSON object of person id to code — overrides it
    for a deployment that issues its own.
    """
    override = _configured_codes().get(person_id)
    if override:
        return override
    digest = hmac.new(_key(), f"code|{person_id}".encode(), hashlib.sha256).digest()
    return base64.b32encode(digest).decode("ascii")[:6]


def codes_are_published() -> bool:
    """Does this deployment show its access codes on the sign-in screen?

    True only in `demo`. The hosted demonstration publishes them so the product
    can be driven by anyone who opens it; every other mode keeps them.
    """
    return auth_mode() == "demo"


# ---------------------------------------------------------------------------
# Principals and sessions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Principal:
    """An established identity and the authorities it holds.

    `roles` is what the approval gate reads. It is never taken from a request
    body, never widened by a query parameter, and re-derived from the directory
    on every sign-in rather than carried forward from an older session.
    """

    subject: str
    name: str
    title: str
    roles: tuple[Role, ...]
    provider: str
    channel: str
    plane: str
    issued_at: datetime
    expires_at: datetime

    def may_sign(self, role: Role) -> bool:
        return role in self.roles

    def may_route(self, required: tuple[Role, ...]) -> bool:
        """May this principal take a plan to signature, or decline it?

        An authority the plan needs, or the coordinator whose job is routing.
        A signed-in crew member who holds neither is a reader.
        """
        return Role.COORDINATOR in self.roles or bool(set(required) & set(self.roles))

    @property
    def clearance(self) -> str:
        """The most permissive classification any of this principal's roles reads.

        Reported, not enforced here: `execution/privacy.py` owns redaction and
        keeps owning it. This is what the interface prints next to the name, so
        a person can see which audience they are reading the product as.
        """
        order = ["production_internal", "operational_requirement", "personal"]
        best = "production_internal"
        for role in self.roles:
            value = ROLE_CLEARANCE.get(role)
            if value is not None and order.index(value.value) > order.index(best):
                best = value.value
        return best

    def actor(self, role: Role) -> str:
        """The identifier written onto the approval event.

        An evaluation identity signs as `JUDGE/<role>` for the same reason the
        unattended approver signs as `STAND-IN/<role>`: a reader of the ledger
        must be able to tell a production authority from an identity that was
        issued to look at the product, without inferring it from context. The
        data contract refuses a `judge` approval that does not.
        """
        if self.channel == "judge":
            return f"JUDGE/{role.value}"
        return self.subject

    def public(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "name": self.name,
            "title": self.title,
            "roles": [r.value for r in self.roles],
            "provider": self.provider,
            "channel": self.channel,
            "plane": self.plane,
            "clearance": self.clearance,
            "expires_at": self.expires_at.isoformat(),
        }


def _sign(payload: bytes) -> str:
    return base64.urlsafe_b64encode(
        hmac.new(_key(), payload, hashlib.sha256).digest()
    ).decode("ascii").rstrip("=")


def mint(principal: Principal) -> str:
    """A signed bearer token for one principal."""
    body = json.dumps({
        "sub": principal.subject,
        "nam": principal.name,
        "ttl": principal.title,
        "rol": [r.value for r in principal.roles],
        "prv": principal.provider,
        "chn": principal.channel,
        "pln": principal.plane,
        "iat": principal.issued_at.isoformat(),
        "exp": principal.expires_at.isoformat(),
    }, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    return f"{encoded}.{_sign(body)}"


def verify(token: str | None) -> Principal | None:
    """The principal a token establishes, or `None`.

    Returns `None` for every failure — bad shape, bad signature, expired,
    unparseable, a role that no longer exists — because the caller's only
    correct response to any of them is to treat the request as unauthenticated.
    Distinguishing them for the client would tell a forger which half of the
    token to fix.
    """
    if not token or "." not in token:
        return None
    encoded, _, signature = token.partition(".")
    try:
        body = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    except Exception:
        return None
    if not hmac.compare_digest(_sign(body), signature):
        return None
    try:
        claims = json.loads(body)
        expires = datetime.fromisoformat(claims["exp"])
        roles = tuple(Role(value) for value in claims["rol"])
    except Exception:
        return None
    if utcnow() > expires:
        return None
    return Principal(
        subject=str(claims["sub"]),
        name=str(claims.get("nam", claims["sub"])),
        title=str(claims.get("ttl", "")),
        roles=roles,
        provider=str(claims.get("prv", "directory")),
        channel=str(claims.get("chn", "human")),
        plane=str(claims.get("pln", "offline")),
        issued_at=datetime.fromisoformat(claims["iat"]),
        expires_at=expires,
    )


def _issue(entry: DirectoryEntry, provider: str) -> Principal:
    now = utcnow()
    return Principal(
        subject=entry.person_id,
        name=entry.name,
        title=entry.title,
        roles=(entry.role,),
        provider=provider,
        channel="human",
        plane="offline",
        issued_at=now,
        expires_at=now + SESSION_TTL,
    )


# ---------------------------------------------------------------------------
# The three providers
# ---------------------------------------------------------------------------


def sign_in(person_id: str, code: str) -> Principal:
    """Directory sign-in. Raises rather than returning an anonymous principal."""
    if auth_mode() == "iap":
        raise IdentityError(
            "this deployment takes identity from Identity-Aware Proxy; "
            "there is no code sign-in"
        )
    entry = _entry(person_id)
    expected = access_code(person_id) if entry else ""
    supplied = (code or "").strip().upper()
    # Compared even when the person is unknown, so a wrong id and a wrong code
    # cost the same and the endpoint does not enumerate the directory by timing.
    ok = hmac.compare_digest(expected, supplied) if entry else False
    if not entry or not ok:
        raise IdentityError("that access code does not match anyone in the directory")
    return _issue(entry, "directory")


def judge_sign_in(key: str) -> Principal:
    """The evaluation identity: every authority, and the Gemini plane.

    It holds every signing authority because one evaluator has to be able to
    take a disruption through a two-signature approval alone. That is a real
    weakening of separation of duty, and it is why the identity is named in the
    ledger rather than hidden: every approval it produces is `JUDGE/<role>` on
    channel `judge`, so a reader can see at a glance that one evaluation
    identity signed for two authorities. A directory principal never can — it
    holds exactly the one authority the directory gives it.
    """
    configured = judge_key()
    if not configured:
        raise IdentityError("this deployment has no evaluation key configured")
    if not hmac.compare_digest(configured, (key or "").strip()):
        raise IdentityError("that evaluation key is not valid for this deployment")
    now = utcnow()
    plane, _ = gemini_entitlement()
    return Principal(
        # Derived from the key, so two evaluators on the same link share one
        # identity in the log without the key itself ever appearing in it.
        subject="JUDGE-" + hashlib.sha256(configured.encode()).hexdigest()[:6].upper(),
        name="Hackathon evaluator",
        title="Evaluation identity",
        roles=SIGNING_AUTHORITIES,
        provider="judge",
        channel="judge",
        plane=plane,
        issued_at=now,
        expires_at=now + SESSION_TTL,
    )


def _directory_email_map() -> dict[str, str]:
    """Email to person id, for the proxy provider. `AA_DIRECTORY_EMAILS` JSON."""
    raw = os.environ.get("AA_DIRECTORY_EMAILS", "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return (
        {str(k).strip().lower(): str(v) for k, v in parsed.items()}
        if isinstance(parsed, dict) else {}
    )


def _verified_iap_email(assertion: str) -> str:
    """The email inside a verified IAP assertion, or empty.

    Verification is cryptographic where `google-auth` is present, which it is in
    the deployed image. Where it is not, the assertion is not trusted at all: an
    unverified JWT is a string an attacker also knows how to write.
    """
    audience = os.environ.get("AA_IAP_AUDIENCE", "").strip()
    if not assertion or not audience:
        return ""
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except Exception:
        return ""
    try:
        claims = id_token.verify_token(
            assertion,
            google_requests.Request(),
            audience=audience,
            certs_url="https://www.gstatic.com/iap/verify/public_key",
        )
    except Exception:
        return ""
    return str(claims.get("email", "")).strip().lower()


def iap_principal(headers: Any) -> Principal | None:
    """The principal Identity-Aware Proxy established, if it did.

    Only consulted in `iap` mode. Reading these headers in any other mode would
    turn a request header into an authority claim, which is precisely the defect
    this module exists to remove.
    """
    if auth_mode() != "iap":
        return None
    email = _verified_iap_email(headers.get("x-goog-iap-jwt-assertion", ""))
    if not email and os.environ.get("AA_TRUST_IAP_HEADER", "").strip() == "1":
        # Only safe where ingress is restricted to the load balancer IAP sits
        # behind, because the header is otherwise trivially forged. Off unless a
        # deployment turns it on deliberately.
        raw = headers.get("x-goog-authenticated-user-email", "")
        email = raw.rpartition(":")[2].strip().lower()
    if not email:
        return None
    person_id = _directory_email_map().get(email)
    entry = _entry(person_id) if person_id else None
    if entry is None:
        # Authenticated, and holds no authority on this production. An ordinary
        # outcome rather than an error: they may read.
        now = utcnow()
        return Principal(
            subject=email, name=email, title="Authenticated", roles=(),
            provider="iap", channel="human", plane="offline",
            issued_at=now, expires_at=now + SESSION_TTL,
        )
    return _issue(entry, "iap")


def providers() -> dict[str, Any]:
    """What this deployment accepts, for the sign-in screen and `/api/about`."""
    plane, reason = gemini_entitlement()
    return {
        "mode": auth_mode(),
        "directory_sign_in": auth_mode() != "iap",
        "codes_published": codes_are_published(),
        "judge_key_configured": bool(judge_key()),
        "judge_plane": plane,
        "judge_plane_reason": reason,
        "identity_aware_proxy": auth_mode() == "iap",
        "session_hours": round(SESSION_TTL.total_seconds() / 3600),
    }
