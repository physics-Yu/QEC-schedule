"""Global rotation placement matches the configured illuminated atom set."""

import pytest

from nadit_physical_compiler import (
    AOD,
    AtomLayout,
    AtomState,
    CZCapability,
    Device,
    GlobalControl,
    GlobalRY,
    Position,
    Region,
    SLMHolder,
    SLMSite,
    Timing,
    Zone,
    compile_physical,
)
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.placement import PairPlacer
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.scheduling import ReadyScheduler
from nadit_physical_compiler.strategies import SearchSmarterStrategy
from nadit_physical_compiler.transport import PairTransport, SequentialTransport
from nadit_physical_compiler.validation import validate_result


def _device() -> Device:
    return Device(
        "global-rotation-placement",
        (
            Zone("storage", Region(-1, -1, 16, 1), ("rotate",)),
            Zone("gate", Region(-1, 99, 11, 101), ("cz", "rotate")),
        ),
        tuple(SLMSite(f"s{index}", Position(5 * index, 0)) for index in range(4))
        + (
            SLMSite("g0", Position(0, 100)),
            SLMSite("g1", Position(2, 100)),
            SLMSite("outside", Position(10, 100)),
        ),
        (AOD("transport", Region(-5, -5, 30, 110), 1),),
        Timing(15, 15, 1),
        cz=CZCapability("cz", 4.6, 0.4),
        global_control=GlobalControl("global", 2, region=(-1, -1, 16, 1)),
    )


def _layout(device: Device, *sites: str) -> AtomLayout:
    ids = tuple(7 + 3 * index for index in range(len(sites)))
    return AtomLayout(
        tuple(
            AtomState(atom, device.site(site).position, SLMHolder(site))
            for atom, site in zip(ids, sites, strict=True)
        ),
        qubit_to_atom=ids,
    )


@pytest.mark.parametrize("transport", [PairTransport("transport")])
def test_cz_retention_then_storage_global_rotation_has_complete_semantics(
    transport: PairTransport | SequentialTransport,
) -> None:
    device = _device()
    entry = _layout(device, "s0", "s1")
    dag = PhysicalDAG(
        2,
        0,
        (
            PhysicalOperation(0, "cz", (0, 1), (), ()),
            PhysicalOperation(1, "global_ry", (0, 1), (), (0.25,)),
        ),
        ((0, 1),),
    )

    result = compile_physical(
        dag,
        device,
        entry_state=entry,
        strategy=SearchSmarterStrategy(
            ReadyScheduler(), PairPlacer("transport"), transport
        ),
    )

    report = validate_result(result, dag=dag, device=device, entry_state=entry)
    assert report["ok"], report
    current = entry
    for step in result.program.steps:
        for action in step.actions:
            if isinstance(action, GlobalRY):
                assert action.coverage == Region(-1, -1, 16, 1)
                assert all(
                    action.coverage.contains(atom.position) for atom in current.atoms
                )
        current = apply_step(current, step, device)
    assert current == result.exit_state
