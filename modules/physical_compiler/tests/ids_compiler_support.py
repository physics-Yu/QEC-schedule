"""IDS placement integrates with case compilation and strict atom transport."""

from pathlib import Path
from typing import Literal

import pytest

from nadit_physical_compiler.contracts import Placer
from nadit_physical_compiler.device import Device, load_device
from nadit_physical_compiler.emission import WholeLayerEmitter
from nadit_physical_compiler.placement import (
    GatePairCatalog,
    HeuristicPlacer,
    MultiPairPlacer,
)
from nadit_physical_compiler.reuse import MatchingReuseAnalyzer
from nadit_physical_compiler.scheduling import ReadyScheduler
from nadit_physical_compiler.strategies import SearchSmarterStrategy
from nadit_physical_compiler.transport import StrictTransport

MODULE = Path(__file__).parents[1]

PAIRS = (("gate_0_left", "gate_0_right"), ("gate_1_left", "gate_1_right"))

type Mode = Literal["ids", "fixed", "no_reuse"]


@pytest.fixture
def device() -> Device:
    return load_device(MODULE / "configs/multipair_flexible.json")


def _strategy(
    device: Device, mode: Mode = "ids", capacity: int = 2
) -> SearchSmarterStrategy:
    catalog = GatePairCatalog.from_device(device, "entanglement", PAIRS[:capacity])
    placer: Placer = (
        HeuristicPlacer("transport", catalog)
        if mode == "ids"
        else MultiPairPlacer("transport", catalog)
    )
    return SearchSmarterStrategy(
        ReadyScheduler(capacity),
        placer,
        StrictTransport("transport"),
        WholeLayerEmitter(catalog.coverage),
        reuse_analyzer=MatchingReuseAnalyzer() if mode != "no_reuse" else None,
    )
