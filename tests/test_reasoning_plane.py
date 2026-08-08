"""The Gemini plane, driven against a stub client.

No network, no credentials, no credits. What is exercised here is the part that
decides whether a model's answer is allowed to be used: `ungrounded_claims`, the
fallback path, and the record kept of what happened. Those are the controls, and
they are the part that has to be right before a real endpoint is ever pointed at
this system.

The model is stubbed rather than mocked at the SDK boundary, so these tests
describe the contract `GeminiReasoner` relies on — `client.models.generate_content`
returning an object with `.text` — and would fail if that assumption changed.
"""

from __future__ import annotations

import pytest

from productionpulse.agents.core import (
    GeminiReasoner,
    OfflineReasoner,
    build_reasoner,
    ungrounded_claims,
)

FACTS = {
    "constraint_id": "C-ACC-002",
    "requirement_id": "ACC-001",
    "location": "LOC-BOATSHED",
    "threshold_mm": 45,
    "limit_mm": 25,
    "wind_kph": 68,
    "call_time": "18:30",
}

TEMPLATE = "{location} fails {constraint_id}: threshold {threshold_mm} mm over {limit_mm} mm."


class _Response:
    def __init__(self, text: str) -> None:
        self.text = text
        self.usage_metadata = None


class _Models:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    def generate_content(self, **_kwargs):
        self.calls += 1
        return _Response(self._replies.pop(0) if self._replies else "")


class _Client:
    def __init__(self, replies: list[str]) -> None:
        self.models = _Models(replies)


def _reasoner(replies: list[str]) -> GeminiReasoner:
    reasoner = GeminiReasoner()
    reasoner._client = _Client(replies)  # noqa: SLF001
    return reasoner


# ---------------------------------------------------------------------------
# The grounding check
# ---------------------------------------------------------------------------


def test_grounded_text_passes() -> None:
    text = ("LOC-BOATSHED fails C-ACC-002: the threshold is 45 mm against a "
            "25 mm limit.")
    assert ungrounded_claims(text, FACTS) == ()


def test_an_invented_identifier_is_caught() -> None:
    text = "LOC-BOATSHED also breaches C-SAFE-009, which the safety lead owns."
    assert "C-SAFE-009" in ungrounded_claims(text, FACTS)


def test_an_invented_measurement_is_caught() -> None:
    text = "The threshold is 120 mm, well over the limit."
    assert "120 mm" in ungrounded_claims(text, FACTS)


def test_an_invented_time_is_caught() -> None:
    text = "The storm reaches the harbour at 19:45."
    assert "19:45" in ungrounded_claims(text, FACTS)


def test_a_quantity_is_supported_by_its_digits_in_any_form() -> None:
    """`45 kph` and `wind_kph: 45` are the same fact stated two ways."""
    assert ungrounded_claims("Winds reach 68 kph.", FACTS) == ()


def test_prose_without_checkable_tokens_is_not_policed() -> None:
    text = "The boatshed cannot be used and the location manager has been told."
    assert ungrounded_claims(text, FACTS) == ()


# ---------------------------------------------------------------------------
# What the reasoner does with the verdict
# ---------------------------------------------------------------------------


def test_a_grounded_response_is_used() -> None:
    reply = "LOC-BOATSHED fails C-ACC-002 at 45 mm against 25 mm."
    reasoner = _reasoner([reply])
    assert reasoner.narrate("access_agent", "explain", FACTS, TEMPLATE) == reply
    assert reasoner.degraded is False
    assert reasoner.rejected == 0
    assert reasoner.calls()[0].rejected_claims == ()


def test_an_ungrounded_response_is_discarded_for_the_template() -> None:
    reasoner = _reasoner(["The boatshed breaches C-SAFE-009 at 120 mm."])
    result = reasoner.narrate("access_agent", "explain", FACTS, TEMPLATE)

    assert result == TEMPLATE.format(**FACTS)
    # The invented constraint id must not survive into anything a person reads.
    assert "C-SAFE-009" not in result
    assert "120" not in result
    assert reasoner.rejected == 1
    assert reasoner.degraded is True
    call = reasoner.calls()[0]
    assert "C-SAFE-009" in call.rejected_claims
    assert "120 mm" in call.rejected_claims


def test_an_empty_response_falls_back_and_is_recorded() -> None:
    reasoner = _reasoner([""])
    assert reasoner.narrate("access_agent", "explain", FACTS, TEMPLATE) == \
        TEMPLATE.format(**FACTS)
    assert reasoner.degraded is True
    assert reasoner.calls()[0].error


def test_a_failing_call_falls_back_and_is_recorded() -> None:
    class _Exploding:
        models = None

        def __init__(self) -> None:
            self.models = self

        def generate_content(self, **_kwargs):
            raise RuntimeError("permission denied on the endpoint")

    reasoner = GeminiReasoner()
    reasoner._client = _Exploding()  # noqa: SLF001
    assert reasoner.narrate("access_agent", "explain", FACTS, TEMPLATE) == \
        TEMPLATE.format(**FACTS)
    assert reasoner.degraded is True
    assert "permission denied" in (reasoner.calls()[0].error or "")


def test_degradation_is_never_silent() -> None:
    """A run reporting the Gemini plane must not be quietly producing templates."""
    reasoner = _reasoner(["invented C-XXX-001", "LOC-BOATSHED holds at 45 mm"])
    reasoner.narrate("a", "explain", FACTS, TEMPLATE)
    reasoner.narrate("b", "explain", FACTS, TEMPLATE)
    assert reasoner.degraded is True
    assert reasoner.rejected == 1
    assert len(reasoner.calls()) >= 2


# ---------------------------------------------------------------------------
# Plane selection
# ---------------------------------------------------------------------------


def test_offline_is_the_default_plane(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PP_REASONING_MODE", raising=False)
    assert isinstance(build_reasoner(), OfflineReasoner)


def test_gemini_is_selected_explicitly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PP_REASONING_MODE", "gemini")
    reasoner = build_reasoner()
    assert reasoner.plane == "gemini"
    assert isinstance(reasoner, GeminiReasoner)


def test_the_system_instruction_forbids_deciding_and_inventing() -> None:
    instruction = GeminiReasoner.SYSTEM_INSTRUCTION
    assert "never decide whether a plan is feasible" in instruction
    assert "never invent" in instruction
    assert "never speculate about why a person requires an access arrangement" in instruction


def test_the_offline_plane_is_deterministic() -> None:
    a, b = OfflineReasoner(), OfflineReasoner()
    assert a.narrate("x", "p", FACTS, TEMPLATE) == b.narrate("x", "p", FACTS, TEMPLATE)
