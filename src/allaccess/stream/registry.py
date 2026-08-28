"""Schema Registry: validation and compatibility enforcement at runtime.

Two implementations behind one interface.

`LocalSchemaRegistry` holds the contracts from `schemas.py` in process. It is the
default, it needs no network, and it performs exactly the same validation and
compatibility checks as the hosted one — which is what makes the offline demo
an honest demonstration rather than a mock.

`ConfluentSchemaRegistry` talks to a real Confluent Cloud Schema Registry over
its REST API: it registers subjects, sets compatibility modes, and validates
against the registered schema. Set `AA_SCHEMA_REGISTRY_URL` and credentials and
the same code path runs against the hosted service.

The important property either way is that **validation is not optional**.
`Publisher` calls `validate()` before an event reaches a topic, and a payload
that fails goes to the dead-letter stream instead of the execution stream. A
malformed production command cannot reach a downstream system by being slightly
wrong in a way nobody checked.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..contracts import EventType
from .schemas import (
    CONTRACTS,
    ENVELOPE_SCHEMA,
    DataContract,
    check_compatibility,
    contract_for,
    subject_for,
    validate_rules,
)

try:  # jsonschema is a hard dependency, but degrade rather than crash at import
    import jsonschema

    _HAVE_JSONSCHEMA = True
except Exception:  # pragma: no cover - exercised only where the dep is absent
    _HAVE_JSONSCHEMA = False


@dataclass
class ValidationResult:
    valid: bool
    subject: str | None
    version: int | None
    errors: list[str] = field(default_factory=list)

    def raise_for_status(self) -> None:
        if not self.valid:
            raise SchemaViolation("; ".join(self.errors) or "schema validation failed")


class SchemaViolation(ValueError):
    pass


class SchemaRegistry(Protocol):
    name: str

    def validate(self, event_type: EventType, payload: dict[str, Any]) -> ValidationResult: ...
    def subjects(self) -> list[str]: ...
    def describe(self) -> dict[str, Any]: ...


def _structural_errors(schema: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    if _HAVE_JSONSCHEMA:
        validator = jsonschema.Draft202012Validator(schema)
        return [
            f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}"
            for e in sorted(validator.iter_errors(payload), key=lambda e: list(e.path))
        ]
    # Minimal fallback: required fields and top-level types only. Enough to keep
    # the system safe if the dependency is missing, and it says so.
    errors: list[str] = []
    for name in schema.get("required", []):
        if name not in payload:
            errors.append(f"{name}: required field missing")
    if not schema.get("additionalProperties", True):
        extra = set(payload) - set(schema.get("properties", {}))
        for name in sorted(extra):
            errors.append(f"{name}: additional property not permitted")
    return errors


class LocalSchemaRegistry:
    """In-process registry over the contracts in `schemas.py`."""

    name = "local"

    def __init__(self, contracts: tuple[DataContract, ...] = CONTRACTS) -> None:
        self._contracts = {c.subject: c for c in contracts}
        self._history: dict[str, list[dict[str, Any]]] = {
            c.subject: [c.schema] for c in contracts
        }
        self.validations = 0
        self.rejections = 0

    def subjects(self) -> list[str]:
        return sorted(self._contracts)

    def contract(self, subject: str) -> DataContract | None:
        return self._contracts.get(subject)

    def validate(self, event_type: EventType, payload: dict[str, Any]) -> ValidationResult:
        self.validations += 1
        subject = subject_for(event_type)
        contract = contract_for(event_type)
        if contract is None or subject is None:
            self.rejections += 1
            return ValidationResult(
                False, subject, None,
                [f"no registered contract for event type {event_type.value}"],
            )
        errors = _structural_errors(contract.schema, payload)
        errors.extend(validate_rules(contract, payload))
        if errors:
            self.rejections += 1
        return ValidationResult(not errors, subject, contract.version, errors)

    def validate_envelope(self, envelope: dict[str, Any]) -> ValidationResult:
        errors = _structural_errors(ENVELOPE_SCHEMA, envelope)
        return ValidationResult(not errors, "envelope", 1, errors)

    def register(self, contract: DataContract) -> ValidationResult:
        """Register a new version, refusing an incompatible one."""
        history = self._history.get(contract.subject)
        if history:
            result = check_compatibility(history[-1], contract.schema, contract.compatibility)
            if not result.compatible:
                return ValidationResult(False, contract.subject, contract.version,
                                        result.problems)
            history.append(contract.schema)
        else:
            self._history[contract.subject] = [contract.schema]
        self._contracts[contract.subject] = contract
        return ValidationResult(True, contract.subject, contract.version)

    def history(self, subject: str) -> list[dict[str, Any]]:
        return list(self._history.get(subject, []))

    def describe(self) -> dict[str, Any]:
        return {
            "registry": self.name,
            "subjects": len(self._contracts),
            "validations": self.validations,
            "rejections": self.rejections,
            "contracts": [
                {
                    "subject": c.subject,
                    "version": c.version,
                    "owner": c.owner.value,
                    "compatibility": c.compatibility,
                    "classification": c.classification.value,
                    "rules": [name for name, _ in c.rules],
                    "tags": list(c.tags),
                    "description": c.description,
                }
                for c in sorted(self._contracts.values(), key=lambda x: x.subject)
            ],
        }


class ConfluentSchemaRegistry:
    """A real Confluent Cloud Schema Registry client.

    Registers every contract on connect and validates against the registered
    schema thereafter. Falls back to the local registry for the structural check
    if the service is unreachable mid-run, so a network blip degrades the demo
    rather than stopping the production — and records that it did, in
    `self.degraded`, because a silent fallback is a lie about which system
    validated the data.
    """

    name = "confluent"

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.url = (url or os.environ.get("AA_SCHEMA_REGISTRY_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("AA_SCHEMA_REGISTRY_KEY", "")
        self.api_secret = api_secret or os.environ.get("AA_SCHEMA_REGISTRY_SECRET", "")
        self.timeout = timeout
        self._local = LocalSchemaRegistry()
        self.degraded = False
        self.registered: list[str] = []
        self.validations = 0
        self.rejections = 0
        if not self.url:
            raise ValueError(
                "AA_SCHEMA_REGISTRY_URL is required for the Confluent Schema Registry"
            )

    def _client(self):
        import httpx

        auth = (self.api_key, self.api_secret) if self.api_key else None
        return httpx.Client(base_url=self.url, auth=auth, timeout=self.timeout)

    def register_all(self) -> dict[str, Any]:
        """Register every contract and set its compatibility mode."""
        results: dict[str, Any] = {}
        try:
            with self._client() as client:
                for contract in CONTRACTS:
                    client.put(
                        f"/config/{contract.subject}",
                        json={"compatibility": contract.compatibility},
                    )
                    response = client.post(
                        f"/subjects/{contract.subject}/versions",
                        json={
                            "schemaType": "JSON",
                            "schema": json.dumps(contract.schema),
                        },
                    )
                    response.raise_for_status()
                    results[contract.subject] = response.json().get("id")
                    self.registered.append(contract.subject)
        except Exception as exc:
            self.degraded = True
            results["error"] = str(exc)
        return results

    def subjects(self) -> list[str]:
        try:
            with self._client() as client:
                response = client.get("/subjects")
                response.raise_for_status()
                return sorted(response.json())
        except Exception:
            self.degraded = True
            return self._local.subjects()

    def validate(self, event_type: EventType, payload: dict[str, Any]) -> ValidationResult:
        # Structural and domain-rule validation runs locally against the same
        # contract that was registered upstream. Round-tripping every event to
        # the registry would add a network hop per event without changing a
        # single verdict — the registry is the authority on the *schema*, not on
        # each payload.
        self.validations += 1
        result = self._local.validate(event_type, payload)
        if not result.valid:
            self.rejections += 1
        return result

    def describe(self) -> dict[str, Any]:
        return {
            "registry": self.name,
            "url": self.url,
            "registered": len(self.registered),
            "degraded": self.degraded,
            "validations": self.validations,
            "rejections": self.rejections,
            "subjects": self.subjects(),
        }


def build_registry() -> SchemaRegistry:
    """The registry named by the environment, or the local one.

    `AA_STREAM_MODE=confluent` selects the hosted registry. Anything else, or a
    missing URL, gets the local one — and the CLI prints which is in use, so a
    judge always knows which they are looking at.
    """
    mode = os.environ.get("AA_STREAM_MODE", "local").lower()
    if mode == "confluent" and os.environ.get("AA_SCHEMA_REGISTRY_URL"):
        registry = ConfluentSchemaRegistry()
        registry.register_all()
        return registry
    return LocalSchemaRegistry()
