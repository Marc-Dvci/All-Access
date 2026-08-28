"""Test configuration.

Puts `src` on the path so the tests run against the working tree without an
install step. `tools/` and `bench/` are added for the same reason.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT / "src", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))


@pytest.fixture(scope="session")
def twin():
    from allaccess.twin import build_twin

    return build_twin()


@pytest.fixture()
def storm_problem(twin):
    from allaccess.disruptions import STORM_SCENARIO, scenario_problem

    return scenario_problem(STORM_SCENARIO, twin=twin)


@pytest.fixture()
def bus():
    from allaccess.production import world as w
    from allaccess.stream.bus import LocalEventBus
    from allaccess.stream.registry import LocalSchemaRegistry

    return LocalEventBus(LocalSchemaRegistry(), w.PRODUCTION_ID)
