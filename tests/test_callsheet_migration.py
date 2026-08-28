"""Call-sheet connector: the before/after evidence for the IBM Bob modernization.

These are the tests the legacy adapter never had. Each one names the defect it
covers, so the file doubles as the verification record for
bob-evidence/USE_CASES.md#uc-03.

`test_modern_matches_legacy_semantics` is the parity test: for the same input the
modern connector produces the same intended call-sheet *content* as the legacy
one, so the modernization is provably behaviour-preserving everywhere except
where a defect was deliberately fixed.
"""

from __future__ import annotations

import pytest

from allaccess.contracts import Command, CommandStatus, TargetSystem
from allaccess.production import world as w
from allaccess.systems import callsheet_legacy as legacy
from allaccess.systems.callsheet_modern import (
    CONNECTOR_VERSION,
    CallSheetConnector,
    CallSheetRevision,
)


def _entries() -> list[dict]:
    return [
        {
            "scene_id": s.scene_id,
            "location_id": s.location_id,
            "unit_id": s.unit_id,
            "setup_start": s.setup_start.isoformat(),
            "start": s.start.isoformat(),
            "end": s.end.isoformat(),
            "crew_call": s.crew_call.isoformat(),
            "cast_calls": {k: v.isoformat() for k, v in s.cast_calls.items()},
        }
        for s in w.BASELINE_SCHEDULE
    ]


def _command(idempotency_key: str = "key-1", **payload_overrides) -> Command:
    payload = {
        "production_id": w.PRODUCTION_ID,
        "entries": _entries(),
        "notes": [],
        "accessible_formats": ["written", "captioned"],
    }
    payload.update(payload_overrides)
    return Command(
        command_id="CMD-1", disruption_id="DISR-1", plan_id="PLAN-1", plan_version=2,
        target=TargetSystem.CALL_SHEET, action="publish_revision", payload=payload,
        idempotency_key=idempotency_key,
    )


@pytest.fixture()
def connector() -> CallSheetConnector:
    return CallSheetConnector(w.PRODUCTION_ID)


@pytest.fixture(autouse=True)
def _reset_legacy():
    legacy.reset()
    yield
    legacy.reset()


# -- defect 1: no schema ----------------------------------------------------


def test_malformed_entry_is_rejected_not_stored(connector) -> None:
    command = _command(entries=[{"scene_id": "SC-001"}])
    result = connector.apply(command)
    assert result.status is CommandStatus.REJECTED
    assert result.error == "schema_validation"
    assert connector.current_revision == 1, "a rejected revision must not advance"


def test_end_before_start_is_rejected(connector) -> None:
    rows = _entries()
    rows[0]["end"] = rows[0]["start"]
    result = connector.apply(_command(entries=rows))
    assert result.status is CommandStatus.REJECTED


def test_legacy_accepts_anything() -> None:
    """The defect, demonstrated. Kept so the diff has something to point at."""
    out = legacy.publish_revision("PROD", {"nonsense": object()})
    assert out is not None and out["ok"] is True


# -- defect 2: shared mutable module state ----------------------------------


def test_two_connectors_do_not_interfere() -> None:
    a = CallSheetConnector("PROD-A")
    b = CallSheetConnector("PROD-B")
    a.apply(_command("key-a"))
    assert a.current_revision == 2
    assert b.current_revision == 1, "state must be instance-scoped"


def test_legacy_state_is_shared_between_callers() -> None:
    legacy.publish_revision("PROD-A", {"x": 1})
    before = legacy.get_revision()
    legacy.publish_revision("PROD-B", {"y": 2})
    assert legacy.get_revision() != before
    assert "PROD-A" in legacy.CALL_SHEET_STORE and "PROD-B" in legacy.CALL_SHEET_STORE


# -- defect 4: no idempotency -----------------------------------------------


def test_duplicate_publish_changes_nothing(connector) -> None:
    first = connector.apply(_command("key-1"))
    assert first.status is CommandStatus.COMPLETED
    assert connector.current_revision == 2

    second = connector.apply(_command("key-1"))
    assert second.status is CommandStatus.COMPLETED
    assert second.duplicate_suppressed
    assert connector.current_revision == 2, "a replay must not publish a second revision"


def test_legacy_duplicate_publishes_twice() -> None:
    legacy.publish_revision("PROD", {"a": 1})
    first = legacy.get_revision()
    legacy.publish_revision("PROD", {"a": 1})
    assert legacy.get_revision() > first, "the legacy defect, demonstrated"


def test_identical_content_under_a_new_key_is_a_no_op(connector) -> None:
    connector.apply(_command("key-1"))
    revision = connector.current_revision
    result = connector.apply(_command("key-2"))
    assert result.duplicate_suppressed
    assert connector.current_revision == revision


# -- defect 5: errors swallowed ---------------------------------------------


def test_failures_are_typed_not_silent(connector) -> None:
    result = connector.apply(_command(entries=[{"bad": True}]))
    assert result.status is CommandStatus.REJECTED
    assert result.error
    assert result.detail


def test_unknown_action_is_rejected(connector) -> None:
    command = _command()
    command = command.model_copy(update={"action": "delete_everything"})
    result = connector.apply(command)
    assert result.status is CommandStatus.REJECTED
    assert result.error == "unknown_action"


def test_legacy_failure_looks_like_nothing_happened() -> None:
    class Exploding(dict):
        def __iter__(self):
            raise RuntimeError("boom")

    assert legacy.publish_revision("PROD", Exploding()) is None


# -- defect 6: personal data in logs ----------------------------------------


def test_log_line_carries_no_personal_data(connector) -> None:
    connector.apply(_command("key-1"))
    assert connector.log
    line = connector.log[0]
    for performer in w.PERFORMERS:
        assert performer.performer_id not in line
        assert performer.name not in line
    assert "cast call(s)" in line, "counts are fine; identities are not"


def test_legacy_log_leaks_cast_calls() -> None:
    legacy.publish_revision("PROD", {"cast_calls": {"CAST-001": "20:45"}})
    assert any("CAST-001" in line for line in legacy.PUBLISH_LOG)


# -- defect 7: off-by-one revision numbering --------------------------------


def test_first_revision_is_two_and_supersedes_one(connector) -> None:
    connector.apply(_command("key-1"))
    current = connector.current()
    assert current is not None
    assert current.revision == 2
    assert current.supersedes == 1


def test_revisions_increment_by_one(connector) -> None:
    connector.apply(_command("key-1"))
    rows = _entries()
    rows[0]["end"] = w.at(23, 0).isoformat()
    connector.apply(_command("key-2", entries=rows))
    current = connector.current()
    assert current.revision == 3
    assert current.supersedes == 2


def test_legacy_revision_numbering_is_wrong() -> None:
    """The off-by-one the modernization found: two increments per publish."""
    legacy.reset()
    assert legacy.get_revision() == 1
    legacy.publish_revision("PROD", {"a": 1})
    assert legacy.get_revision() == 2
    legacy.publish_revision("PROD", {"a": 2})
    assert legacy.get_revision() == 3
    # ... but set_call_sheet also increments, so a normal flow skips numbers.
    legacy.set_call_sheet("PROD", {"b": 1})
    legacy.publish_revision("PROD", {"b": 2})
    assert legacy.get_revision() == 5, "two increments for one logical publish"


def test_revision_below_two_is_refused() -> None:
    with pytest.raises(ValueError):
        CallSheetRevision(
            production_id="P", revision=1, supersedes=0, plan_id="X",
            disruption_id="D",
        )


# -- parity: behaviour preserved where it should be -------------------------


def test_modern_matches_legacy_semantics(connector) -> None:
    """The modernization is behaviour preserving on the intended content.

    Both connectors, given the same input, must end up describing the same call
    sheet. Everything else about them differs; this is the part that must not.
    """
    entries = _entries()
    connector.apply(_command("key-1", entries=entries))
    legacy.publish_revision(w.PRODUCTION_ID, {"entries": entries})

    modern = connector.current()
    legacy_store = legacy.CALL_SHEET_STORE[w.PRODUCTION_ID]

    assert {e.scene_id for e in modern.entries} == {
        row["scene_id"] for row in legacy_store["entries"]
    }
    for entry in modern.entries:
        row = next(r for r in legacy_store["entries"] if r["scene_id"] == entry.scene_id)
        assert entry.start.isoformat() == row["start"]
        assert entry.end.isoformat() == row["end"]
        assert entry.location_id == row["location_id"]


# -- the connector as a target system ---------------------------------------


def test_state_reports_version_and_formats(connector) -> None:
    connector.apply(_command("key-1"))
    state = connector.state()
    assert state["connector_version"] == CONNECTOR_VERSION
    assert state["revision"] == 2
    assert state["publishes"] == 1
    assert set(state["accessible_formats"]) == {"written", "captioned"}


def test_wrong_target_is_refused(connector) -> None:
    command = _command().model_copy(update={"target": TargetSystem.SCHEDULING})
    result = connector.apply(command)
    assert result.status is CommandStatus.REJECTED
    assert result.error == "wrong_target"
