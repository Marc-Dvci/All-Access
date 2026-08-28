"""Deploy the All-Access reasoning plane to Vertex AI Agent Engine.

    python tools/deploy_agent_engine.py --dry-run          # validate, no cloud calls
    python tools/deploy_agent_engine.py --project my-proj --location us-central1
    python tools/deploy_agent_engine.py --list
    python tools/deploy_agent_engine.py --delete <resource-name>

**What this deploys, and what it does not.** Agent Engine hosts the *reasoning*
plane: the fifteen expert agents' interpretation, synthesis and explanation
work, backed by Gemini. It does not host the solver, the constraint registry or
the verification step, and that separation is the product's central claim rather
than a deployment convenience. A managed model runtime cannot be allowed to
decide whether a plan is feasible; feasibility is decided by
`constraints.registry.evaluate` against the twin, in process, and the answer is
reproducible from the committed state hash. Deploying the whole system into an
agent runtime would make the feasibility proof depend on a model call.

So the deployed agent is given tools that *read* and *explain*, never tools that
approve, execute or declare readiness. `_TOOL_ALLOWLIST` below is that boundary
written down, and `--dry-run` checks it: if a tool outside the allowlist is ever
added to the agent definition, this refuses to deploy.

`--dry-run` runs with no credentials and no `google-cloud-aiplatform` installed.
It is what CI runs, and it is the reason this file is not decoration: the
configuration, the allowlist and the packaging manifest are all validated on
every commit, so the deployment path cannot rot silently between the rare
occasions anyone actually deploys.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

#: Tools the hosted agent may be given. Read and explain only.
#:
#: Nothing here can change production state. Approval, command issue and
#: verification stay in the deterministic plane, behind the approval matrix in
#: `constraints.registry.APPROVAL_MATRIX`, where a signed human decision is
#: required and recorded. See docs/THREAT_MODEL.md §4.
#:
#: This list is checked against the functions actually exported by
#: `agents/adk_tools.py` on every dry run, in both directions. An allowlist that
#: names tools the agent does not have is decoration; a tool the agent has that
#: the allowlist does not name is the failure this whole boundary exists to
#: prevent.
_TOOL_ALLOWLIST: frozenset[str] = frozenset({
    "describe_disruption",
    "describe_impact",
    "describe_plan",
    "describe_conflict_set",
    "describe_access_arrangements",
    "summarise_findings",
    "draft_role_communication",
})

#: Tool names that must never appear, checked explicitly rather than left to the
#: allowlist. A deny list next to an allow list is redundant right up until
#: somebody widens the allow list without thinking about it.
_TOOL_DENYLIST: frozenset[str] = frozenset({
    "approve_plan",
    "issue_command",
    "execute_plan",
    "declare_ready",
    "override_constraint",
    "remove_access_arrangement",
})

DEFAULT_LOCATION = "us-central1"
DEFAULT_MODEL = "gemini-3.7-flash"
DISPLAY_NAME = "allaccess-reasoning"


def agent_manifest(project: str, location: str, model: str) -> dict[str, Any]:
    """The deployment descriptor. Pure data, so `--dry-run` can check it."""
    from allaccess.agents.adk_tools import TOOL_NAMES
    from allaccess.agents.core import GeminiReasoner

    return {
        "display_name": DISPLAY_NAME,
        "description": (
            "Interpretation and explanation plane for All-Access. "
            "Explains deterministic decisions; does not make them."
        ),
        "project": project,
        "location": location,
        "model": model,
        "system_instruction": GeminiReasoner.SYSTEM_INSTRUCTION,
        "generation_config": {"temperature": 0.2, "max_output_tokens": 300},
        # What will actually be deployed, read from the implementation rather
        # than restated from the allowlist. `validate()` compares the two; a
        # manifest that copied the allowlist could never disagree with it, which
        # is precisely the check worth having.
        "tools": sorted(TOOL_NAMES),
        "requirements": [
            "google-cloud-aiplatform[agent_engines,adk]>=1.101.0",
            "google-adk>=1.0.0",
            "google-genai>=1.0.0",
            "pydantic>=2.7",
        ],
        "extra_packages": ["src/allaccess"],
        "env_vars": {
            # The hosted agent runs the same code with the same switch. It is
            # given no Confluent credentials: the deployed plane narrates, and
            # publishing is done by the application plane.
            "AA_REASONING_MODE": "gemini",
            "AA_GEMINI_MODEL": model,
        },
        "labels": {
            "component": "reasoning-plane",
            "project": "allaccess",
            "track": "ibm",
        },
    }


def validate(manifest: dict[str, Any]) -> list[str]:
    """Everything that can be checked without a cloud project. Empty means valid."""
    from allaccess.agents import adk_tools

    problems: list[str] = []

    tools = set(manifest["tools"])
    for extra in sorted(tools - _TOOL_ALLOWLIST):
        problems.append(f"tool {extra!r} is not in the allowlist")
    for banned in sorted(tools & _TOOL_DENYLIST):
        problems.append(
            f"tool {banned!r} is on the denylist: the hosted plane may not change "
            "production state"
        )

    # The allowlist and the implemented tool surface must be the same set. This
    # catches the failure where a manifest advertises a careful read-only
    # boundary while the agent is built with a different set of functions —
    # or, as was true here before this check existed, with none at all.
    implemented = set(adk_tools.TOOL_NAMES)
    for missing in sorted(_TOOL_ALLOWLIST - implemented):
        problems.append(
            f"tool {missing!r} is allowlisted but not implemented in "
            "agents/adk_tools.py"
        )
    for unlisted in sorted(implemented - _TOOL_ALLOWLIST):
        problems.append(
            f"tool {unlisted!r} is implemented in agents/adk_tools.py but not "
            "allowlisted; the agent would be given a capability nobody approved"
        )
    for name in sorted(implemented):
        tool = getattr(adk_tools, name)
        # ADK builds the declaration Gemini sees from the docstring and the
        # annotations. Either one missing produces a tool the model misuses.
        if not (tool.__doc__ or "").strip():
            problems.append(f"tool {name!r} has no docstring for ADK to declare")
        if "return" not in getattr(tool, "__annotations__", {}):
            problems.append(f"tool {name!r} has no return annotation")
    if not manifest["system_instruction"].strip():
        problems.append("system instruction is empty")
    if "never decide whether a plan is feasible" not in manifest["system_instruction"]:
        # The instruction is the last line of defence if a tool boundary is ever
        # got wrong, so its content is asserted rather than assumed.
        problems.append(
            "system instruction no longer forbids feasibility judgements; "
            "check GeminiReasoner.SYSTEM_INSTRUCTION"
        )
    for package in manifest["extra_packages"]:
        if not (ROOT / package).exists():
            problems.append(f"extra package {package!r} does not exist")
    if manifest["generation_config"]["temperature"] > 0.4:
        problems.append("temperature above 0.4 for an explanation-only plane")
    if not manifest["project"]:
        problems.append("no project: pass --project or set GOOGLE_CLOUD_PROJECT")
    return problems


def _agent_engines():
    try:
        from vertexai import agent_engines  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - requires the cloud extra
        raise SystemExit(
            "google-cloud-aiplatform is not installed. Either install the cloud "
            'extra (`pip install -e ".[cloud]"`) or run with --dry-run.'
        ) from exc
    return agent_engines


def _init(project: str, location: str) -> None:  # pragma: no cover - needs cloud
    import vertexai  # type: ignore[import-not-found]

    vertexai.init(project=project, location=location)


def deploy(manifest: dict[str, Any]) -> str:  # pragma: no cover - needs cloud
    from allaccess.agents.adk_tools import build_agent

    _init(manifest["project"], manifest["location"])
    agent_engines = _agent_engines()

    # The agent is built from `adk_tools.TOOLS`, which `validate()` has already
    # checked against the allowlist. There is no second place tools are named.
    agent = build_agent(
        manifest["model"], name=manifest["display_name"].replace("-", "_")
    )
    remote = agent_engines.create(
        agent_engine=agent,
        display_name=manifest["display_name"],
        description=manifest["description"],
        requirements=manifest["requirements"],
        extra_packages=manifest["extra_packages"],
        env_vars=manifest["env_vars"],
    )
    return str(remote.resource_name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Deploy the All-Access reasoning plane")
    parser.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--location",
                        default=os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_LOCATION))
    parser.add_argument("--model", default=os.environ.get("AA_GEMINI_MODEL", DEFAULT_MODEL))
    parser.add_argument("--dry-run", action="store_true",
                        help="validate the manifest and exit; no cloud calls")
    parser.add_argument("--list", action="store_true", help="list deployed agent engines")
    parser.add_argument("--delete", metavar="RESOURCE_NAME", help="delete a deployed agent engine")
    parser.add_argument("--json", action="store_true", help="print the manifest as JSON")
    args = parser.parse_args(argv)

    if args.delete:  # pragma: no cover - needs cloud
        _init(args.project, args.location)
        _agent_engines().get(args.delete).delete(force=True)
        print(f"deleted {args.delete}")
        return 0

    if args.list:  # pragma: no cover - needs cloud
        _init(args.project, args.location)
        for engine in _agent_engines().list():
            print(f"{engine.resource_name}\t{engine.display_name}")
        return 0

    manifest = agent_manifest(
        args.project or ("DRY-RUN" if args.dry_run else ""), args.location, args.model
    )
    if args.json:
        print(json.dumps(manifest, indent=2))

    problems = validate(manifest)
    if problems:
        print("manifest is not deployable:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(
            f"manifest valid: {manifest['display_name']} on {manifest['model']} "
            f"in {manifest['location']}\n"
            f"  {len(manifest['tools'])} tools, all read-only\n"
            f"  packages: {', '.join(manifest['extra_packages'])}\n"
            "  no cloud calls made"
        )
        return 0

    resource_name = deploy(manifest)  # pragma: no cover - needs cloud
    print(f"deployed: {resource_name}")  # pragma: no cover
    print(  # pragma: no cover
        "Set AA_AGENT_ENGINE_RESOURCE to this value, and AA_REASONING_MODE=gemini, "
        "to route narration through the hosted plane."
    )
    return 0  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
