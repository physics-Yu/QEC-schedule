"""Exact tiny optima and unsatisfiable bounds, independently replayed."""

from nadit_physical_compiler.capabilities import (
    CZCapability,
    LocalControl,
)
from nadit_physical_compiler.compilers.contracts import ProgramContext
from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation
from nadit_physical_compiler.state import AODGrid, AtomLayout, AtomState, SLMHolder


def tiny_context(radius=2.1):
    region = Region(0, 0, 10, 0)
    device = Device(
        "tiny-smt",
        (Zone("shared", region, ("cz", "rotate", "reset")),),
        tuple(SLMSite(str(x), Position(x, 0)) for x in (0, 2, 10)),
        (AOD("a", region, 1),),
        Timing(3, 5, 1),
        cz=CZCapability("cz", radius, 0.4),
        local=LocalControl("local", 1, 2),
    )
    entry = AtomLayout(
        (
            AtomState(0, Position(0, 0), SLMHolder("0")),
            AtomState(1, Position(10, 0), SLMHolder("10")),
        ),
        (AODGrid("a"),),
        (0, 1),
    )
    dag = PhysicalDAG(2, 0, (PhysicalOperation(0, "cz", (0, 1), (), ()),), ())
    return ProgramContext(dag, device, "a", None, entry)
