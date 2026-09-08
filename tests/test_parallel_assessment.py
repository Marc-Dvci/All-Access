"""Expert assessment runs the agents concurrently, and the run is unchanged by it.

The claim on the submission is that the expert agents assess in parallel. That
is a claim about behaviour, so these tests measure the behaviour: how many
agents are inside the reasoning plane at once, and whether the resulting event
log differs in any way from the same run taken one agent at a time.

The second half matters more than the first. A concurrent workflow that
produced a slightly different log each time would trade a minute of wall clock
for the replay proof, the committed benchmark and the hash chain — all of which
depend on the same disruption producing the same events.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from allaccess.agents.coordinator import ProductionCoordinator
from allaccess.agents.core import OfflineReasoner, ReasoningCall
from allaccess.agents.experts import EXPERT_AGENTS
from allaccess.contracts import EventType
from allaccess.disruptions import STORM_SCENARIO, build_source_event, scenario_problem
from allaccess.production import world as w
from allaccess.stream.bus import LocalEventBus
from allaccess.stream.registry import LocalSchemaRegistry
from allaccess.systems import build_systems
from allaccess.twin import build_twin


class ConcurrencyProbe(OfflineReasoner):
    """An offline plane that records how many agents narrate at the same time.

    The pause is what makes the measurement possible: without it the offline
    plane returns from `narrate` in microseconds and eleven genuinely parallel
    agents would still rarely be observed inside it together. It stands in for
    the several seconds a Gemini call actually takes.
    """

    def __init__(self, pause: float = 0.02) -> None:
        super().__init__()
        self.pause = pause
        self.peak = 0
        self._live = 0
        self._guard = threading.Lock()

    def narrate(self, agent: str, purpose: str, facts: dict[str, Any],
                template: str) -> str:
        with self._guard:
            self._live += 1
            self.peak = max(self.peak, self._live)
        try:
            time.sleep(self.pause)
            return super().narrate(agent, purpose, facts, template)
        finally:
            with self._guard:
                self._live -= 1


def _run(reasoner: OfflineReasoner) -> tuple[LocalEventBus, Any]:
    bus = LocalEventBus(LocalSchemaRegistry(), w.PRODUCTION_ID)
    coordinator = ProductionCoordinator(
        bus, build_systems(w.PRODUCTION_ID, hold_department="props"), reasoner=reasoner,
    )
    outcome = coordinator.handle(
        scenario_problem(STORM_SCENARIO, twin=build_twin()),
        build_source_event(bus, STORM_SCENARIO),
        title=STORM_SCENARIO.title, scenario_id=STORM_SCENARIO.scenario_id,
        scenarios=40,
    )
    return bus, outcome


def _spine(bus: LocalEventBus) -> list[tuple[str, str, str, str]]:
    """The log up to the approval request, by sequence, type, producer and hash.

    It stops at the approval request on purpose. An approval is issued at a
    moment and expires at another, so its request id and its expiry are
    readings of the clock, and two runs are *supposed* to differ there.
    Everything before it — qualification, the twin traversal, the solve, the
    simulations, every expert finding and every published plan — is a function
    of the disruption alone. That stretch is where running the agents at once
    could perturb the run, so that stretch is what gets compared.
    """
    spine = []
    for event in bus.all_events():
        if event.envelope.event_type is EventType.PLAN_APPROVAL_REQUESTED:
            break
        spine.append((
            event.envelope.event_id,
            event.envelope.event_type.value,
            event.envelope.producer,
            event.envelope.payload_hash,
        ))
    return spine


def test_agents_assess_at_the_same_time() -> None:
    probe = ConcurrencyProbe()
    _run(probe)
    assert probe.peak > 1, (
        "expert assessment ran one agent at a time; the submission says they run "
        "in parallel"
    )


def test_one_worker_serialises_the_same_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """The switch is a switch, not a second implementation."""
    monkeypatch.setenv("AA_ASSESSMENT_WORKERS", "1")
    probe = ConcurrencyProbe()
    _run(probe)
    assert probe.peak == 1


def test_concurrency_does_not_change_the_event_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AA_ASSESSMENT_WORKERS", "1")
    serial_bus, serial = _run(OfflineReasoner())

    monkeypatch.setenv("AA_ASSESSMENT_WORKERS", "11")
    parallel_bus, parallel = _run(OfflineReasoner())

    serial_spine = _spine(serial_bus)
    assert len(serial_spine) > 25, "the compared stretch has to be worth comparing"
    assert _spine(parallel_bus) == serial_spine

    def shape(outcome):
        return [(f.finding_id, f.producer, f.status, f.headline)
                for f in outcome.findings]

    assert shape(parallel) == shape(serial)
    assert parallel.disruption.state is serial.disruption.state
    assert parallel.disruption.selected_plan_id == serial.disruption.selected_plan_id


def test_the_reasoning_ledger_keeps_the_declared_agent_order() -> None:
    """Arrival order is not evidence; declared order is."""
    reasoner = ConcurrencyProbe()
    _run(reasoner)

    declared = [agent.name for agent in EXPERT_AGENTS]
    narrated = [
        call.agent for call in reasoner.calls()
        if call.agent in set(declared)
    ]
    ranks = [declared.index(name) for name in narrated]
    assert ranks == sorted(ranks), narrated


def test_restore_order_is_stable_within_an_agent() -> None:
    reasoner = OfflineReasoner()
    mark = reasoner.mark()
    for agent, purpose in [("z", "second"), ("a", "first"), ("z", "third")]:
        reasoner._calls.append(ReasoningCall(  # noqa: SLF001
            agent=agent, purpose=purpose, plane="offline",
            prompt_chars=0, response_chars=0, latency_ms=0.0,
        ))
    reasoner.restore_order(mark, ["a", "z"])
    assert [(c.agent, c.purpose) for c in reasoner.calls()] == [
        ("a", "first"), ("z", "second"), ("z", "third"),
    ]
