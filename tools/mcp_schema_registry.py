"""Development-time MCP server over the event data contracts.

    python -m tools.mcp_schema_registry

Registered in `.bob/mcp.json` as `schema-registry-dev`. It gives IBM Bob three
read-only tools -- `list_subjects`, `get_schema`, `check_compatibility` -- so
that a session editing an event contract can read the contract that is actually
registered instead of guessing at it from a docstring.

**Read-only by construction, not by convention.** There is no `register`, no
`set_compatibility` and no `delete`. Bob writes contracts by editing
`src/productionpulse/stream/schemas.py`, which goes through review like any
other code; it does not mutate a registry directly. `check_compatibility` is the
one that earns its place: it runs the project's own compatibility rules over a
proposed schema and reports what would break, which is precisely the check that
is easy to skip and expensive to skip.

Which registry it reads depends on the environment, and it says which one in
every response:

* `PP_SCHEMA_REGISTRY_URL` set -> the hosted Confluent development registry,
  through the same `ConfluentSchemaRegistry` client the runtime uses.
* unset -> the in-process contracts from `schemas.py`.

The `.bob/mcp.json` entry points the URL at a **development** registry. Nothing
here should ever be given production credentials: a tool that can read
production subjects during an agent session is a tool that will eventually paste
one into a diff.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from productionpulse.stream import schemas as sch  # noqa: E402
from productionpulse.stream.registry import build_registry  # noqa: E402
from tools.mcp_common import MCPServer  # noqa: E402

server = MCPServer(
    name="productionpulse-schema-registry",
    instructions=(
        "Read-only access to the ProductionPulse event data contracts. Use "
        "check_compatibility before proposing a change to any schema in "
        "src/productionpulse/stream/schemas.py -- it reports the same verdict "
        "the runtime registry enforces on publish."
    ),
)


def _registry_kind() -> str:
    return "confluent" if os.getenv("PP_SCHEMA_REGISTRY_URL") else "local"


@server.tool(
    "list_subjects",
    "Every registered subject, with its version, owner, compatibility mode, "
    "data classification and event type.",
)
def list_subjects(_args: dict[str, Any]) -> dict[str, Any]:
    registry = build_registry()
    return {
        "registry": _registry_kind(),
        "subjects": [
            {
                "subject": c.subject,
                "version": c.version,
                "event_type": c.event_type.value,
                "owner": c.owner.value,
                "compatibility": c.compatibility,
                "classification": c.classification.value,
                "deprecated": c.deprecated,
                "description": c.description,
            }
            for c in sch.CONTRACTS
        ],
        "registered_subjects": registry.subjects(),
    }


@server.tool(
    "get_schema",
    "The full JSON Schema for one subject, with its domain validation rules. "
    "Rules are checked in addition to structural typing and are the reason a "
    "structurally valid payload can still be rejected.",
    {
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Subject name, e.g. 'production.decision.plan.generated-value'.",
            }
        },
        "required": ["subject"],
    },
)
def get_schema(args: dict[str, Any]) -> dict[str, Any]:
    subject = str(args["subject"])
    contract = next((c for c in sch.CONTRACTS if c.subject == subject), None)
    if contract is None:
        raise KeyError(
            f"no subject {subject!r}; call list_subjects for the {len(sch.CONTRACTS)} available"
        )
    return {
        "registry": _registry_kind(),
        "subject": contract.subject,
        "version": contract.version,
        "event_type": contract.event_type.value,
        "owner": contract.owner.value,
        "compatibility": contract.compatibility,
        "classification": contract.classification.value,
        "tags": list(contract.tags),
        "rules": [{"name": n, "expression": e} for n, e in contract.rules],
        "schema": contract.schema,
        "envelope_schema_note": (
            "Every event also carries the shared envelope; see ENVELOPE_SCHEMA in "
            "src/productionpulse/stream/schemas.py."
        ),
    }


@server.tool(
    "check_compatibility",
    "Check a proposed schema against the registered one under the subject's "
    "compatibility mode. Returns the breaking changes, if any, so the change "
    "can be assessed before it is written.",
    {
        "type": "object",
        "properties": {
            "subject": {"type": "string"},
            "schema": {
                "type": "object",
                "description": "The proposed JSON Schema, in full.",
            },
        },
        "required": ["subject", "schema"],
    },
)
def check_compatibility(args: dict[str, Any]) -> dict[str, Any]:
    subject = str(args["subject"])
    proposed = args["schema"]
    if not isinstance(proposed, dict):
        raise TypeError("`schema` must be a JSON Schema object")
    contract = next((c for c in sch.CONTRACTS if c.subject == subject), None)
    if contract is None:
        raise KeyError(f"no subject {subject!r}")
    result = sch.check_compatibility(contract.schema, proposed, contract.compatibility)
    return {
        "subject": subject,
        "compatibility": result.mode,
        "compatible": result.compatible,
        "breaking_changes": result.problems,
        "current_version": contract.version,
        "next_version_if_accepted": contract.version + 1,
    }


if __name__ == "__main__":
    server.run()
