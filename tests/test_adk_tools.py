"""The tool surface handed to the hosted Gemini agent.

A deployment manifest that lists seven careful read-only tools proves nothing if
the agent is built without them, or if the tools return `{}` against a live
application. Both were true here before these tests existed: `deploy()`
constructed the ADK agent with no `tools=` argument at all, so the allowlist
described a boundary that was never applied to anything.

These run against the real FastAPI application over its real HTTP surface,
routed through `TestClient` so no port is needed.
"""

from __future__ import annotations

import json

import pytest

from productionpulse.agents import adk_tools

#: Captured before any fixture routes `_get` at the test application, so the
#: unreachable-application test below exercises the real network path however
#: the module happens to be ordered.
_REAL_GET = adk_tools._get  # noqa: SLF001


@pytest.fixture(scope="module")
def live_tools():
    """Point the tools at the real app instead of a network address."""
    from fastapi.testclient import TestClient

    from productionpulse.api import app

    client = TestClient(app)
    original = adk_tools._get  # noqa: SLF001

    def routed(path: str) -> dict:
        response = client.get(path, headers={"Accept": "application/json"})
        if response.status_code != 200:
            return {"error": f"{path} returned {response.status_code}"}
        return dict(response.json())

    adk_tools._get = routed  # noqa: SLF001
    yield adk_tools
    adk_tools._get = original  # noqa: SLF001


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


def test_tool_surface_matches_the_deployment_allowlist() -> None:
    from tools.deploy_agent_engine import _TOOL_ALLOWLIST

    assert set(adk_tools.TOOL_NAMES) == set(_TOOL_ALLOWLIST)


def test_no_tool_can_change_production_state() -> None:
    from tools.deploy_agent_engine import _TOOL_DENYLIST

    assert not (set(adk_tools.TOOL_NAMES) & set(_TOOL_DENYLIST))
    forbidden = ("approve", "execute", "issue", "override", "delete", "waive",
                 "declare_ready", "remove")
    for name in adk_tools.TOOL_NAMES:
        assert not any(name.startswith(verb) for verb in forbidden), name


def test_every_tool_is_declarable_by_adk() -> None:
    """ADK builds the function declaration from the docstring and annotations."""
    for tool in adk_tools.TOOLS:
        assert (tool.__doc__ or "").strip(), tool.__name__
        assert "return" in tool.__annotations__, tool.__name__


def test_the_manifest_deploys_the_tools_that_exist() -> None:
    from tools.deploy_agent_engine import agent_manifest, validate

    manifest = agent_manifest("DRY-RUN", "us-central1", "gemini-2.5-flash")
    assert validate(manifest) == []
    assert set(manifest["tools"]) == set(adk_tools.TOOL_NAMES)


def test_validate_rejects_a_tool_the_agent_does_not_have() -> None:
    """The check fails when it should, not only when nothing is wrong."""
    from tools.deploy_agent_engine import agent_manifest, validate

    manifest = agent_manifest("DRY-RUN", "us-central1", "gemini-2.5-flash")
    manifest["tools"] = sorted(set(manifest["tools"]) | {"approve_plan"})
    problems = validate(manifest)
    assert any("denylist" in p for p in problems)
    assert any("approve_plan" in p for p in problems)


# ---------------------------------------------------------------------------
# The tools against the real application
# ---------------------------------------------------------------------------


def test_every_tool_returns_substantive_data(live_tools) -> None:
    for tool in live_tools.TOOLS:
        result = tool("department_head") if tool.__name__ == "draft_role_communication" \
            else tool()
        assert "error" not in result, f"{tool.__name__}: {result}"
        assert len(json.dumps(result)) > 120, f"{tool.__name__} returned {result}"


def test_describe_disruption_reports_the_real_workflow_state(live_tools) -> None:
    result = live_tools.describe_disruption()
    assert result["disruption"]["state"] in ("closed", "ready", "verifying")
    assert result["constraints_in_force"] > 0
    assert result["departments"], "no department readiness reached the tool"


def test_conflict_sets_carry_the_measurement_not_a_category(live_tools) -> None:
    """A rejection the model can only paraphrase as "not accessible" is useless."""
    result = live_tools.describe_conflict_set()
    assert result["rejected"], "the storm scenario rejects plans; none reached the tool"
    for plan in result["rejected"]:
        for conflict in plan["conflicts"]:
            assert conflict["constraint_ids"]
            assert len(conflict["production_language"]) > 20
            assert conflict["minimal"] is True


def test_access_arrangements_never_carry_a_reason(live_tools) -> None:
    """The one disclosure this system must not make, checked at the tool boundary."""
    from productionpulse.execution.privacy import check_no_prohibited_fields

    result = live_tools.describe_access_arrangements()
    assert result["arrangements"], "no access arrangements reached the tool"
    assert result["all_preserved"] is True
    assert check_no_prohibited_fields([result]) == []


def test_no_tool_leaks_a_prohibited_field(live_tools) -> None:
    from productionpulse.execution.privacy import check_no_prohibited_fields

    payloads = []
    for tool in live_tools.TOOLS:
        payloads.append(
            tool("crew") if tool.__name__ == "draft_role_communication" else tool()
        )
    assert check_no_prohibited_fields(payloads) == []


def test_the_executive_audience_gets_no_personal_detail(live_tools) -> None:
    result = live_tools.draft_role_communication("executive")
    assert result["audience"] == "aggregate only"
    assert "tasks" not in result and "messages" not in result
    blob = json.dumps(result)
    for personal in ("CAST-", "CREW-", "person_id"):
        assert personal not in blob, f"{personal} reached the executive audience"


# ---------------------------------------------------------------------------
# The ADK agent itself
#
# Skipped unless the `cloud` extra is installed, because the offline evaluation
# path in docs/JUDGE.md must not require it. Run with
# `pip install -e ".[cloud]"` to exercise these.
# ---------------------------------------------------------------------------

adk = pytest.importorskip("google.adk", reason="google-adk is in the `cloud` extra")


def test_the_agent_is_built_with_exactly_the_approved_tools() -> None:
    agent = adk_tools.build_agent()
    assert agent.name == "productionpulse_reasoning"
    assert {t.__name__ for t in agent.tools} == set(adk_tools.TOOL_NAMES)


def test_the_agent_is_instructed_not_to_decide_feasibility() -> None:
    """The last line of defence if a tool boundary is ever got wrong."""
    agent = adk_tools.build_agent()
    assert "never decide whether a plan is feasible" in agent.instruction
    assert "never invent" in agent.instruction


def test_every_tool_declares_cleanly_to_gemini() -> None:
    """ADK has to turn each function into a declaration the model can call.

    A tool whose declaration has no description is one the model invokes on the
    strength of its name alone.
    """
    from google.adk.tools import FunctionTool

    for fn in adk_tools.TOOLS:
        declaration = FunctionTool(func=fn)._get_declaration()  # noqa: SLF001
        assert declaration.name == fn.__name__
        assert len(declaration.description or "") > 100, fn.__name__

    # The one tool that takes an argument must actually declare it, whichever
    # field this ADK version puts the schema in.
    declaration = FunctionTool(func=adk_tools.draft_role_communication)._get_declaration()  # noqa: SLF001
    schema = declaration.parameters_json_schema or {}
    properties = schema.get("properties") or {}
    if not properties and declaration.parameters is not None:
        properties = declaration.parameters.properties or {}
    assert "role" in properties


def test_a_tool_that_cannot_reach_the_application_says_so() -> None:
    """Returning `{}` on failure gives a model a hole it will narrate around."""
    original_base, original_get = adk_tools.API_BASE, adk_tools._get  # noqa: SLF001
    adk_tools.API_BASE = "http://127.0.0.1:1"  # nothing listens here
    adk_tools._get = _REAL_GET  # noqa: SLF001
    try:
        result = adk_tools.describe_disruption()
    finally:
        adk_tools.API_BASE = original_base
        adk_tools._get = original_get  # noqa: SLF001
    assert "error" in result
    assert "could not reach" in result["error"]
    assert result["detail"], "the reason the call failed was dropped"
