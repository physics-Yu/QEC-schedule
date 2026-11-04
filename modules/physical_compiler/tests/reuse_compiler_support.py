"""Matching reuse through strict transport, feedback, and independent replay."""

from pathlib import Path

import pytest

from nadit_physical_compiler import (
    Device,
    PhysicalDAG,
    load_device,
    loads_qasm,
)
from nadit_physical_compiler.emission import WholeLayerEmitter
from nadit_physical_compiler.placement import GatePairCatalog, MultiPairPlacer
from nadit_physical_compiler.reuse import MatchingReuseAnalyzer
from nadit_physical_compiler.scheduling import ReadyScheduler
from nadit_physical_compiler.strategies import SearchSmarterStrategy
from nadit_physical_compiler.transport import StrictTransport

MODULE = Path(__file__).parents[1]

PAIRS = (("gate_0_left", "gate_0_right"), ("gate_1_left", "gate_1_right"))


@pytest.fixture
def device() -> Device:
    return load_device(MODULE / "configs/multipair_flexible.json")


def _dag(body: str, count: int = 4) -> PhysicalDAG:
    return loads_qasm(
        f'OPENQASM 3.0; include "stdgates.inc"; qubit[{count}] q; bit c; {body}'
    )


def _strategy(
    device: Device, *, reuse: bool = True, capacity: int = 2
) -> SearchSmarterStrategy:
    catalog = GatePairCatalog.from_device(device, "entanglement", PAIRS[:capacity])
    return SearchSmarterStrategy(
        ReadyScheduler(capacity),
        MultiPairPlacer("transport", catalog),
        StrictTransport("transport"),
        WholeLayerEmitter(catalog.coverage),
        reuse_analyzer=MatchingReuseAnalyzer() if reuse else None,
    )
