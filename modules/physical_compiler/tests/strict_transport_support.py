"""Strict transport batching checked against the independent action validators."""

from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
)
from nadit_physical_compiler.state import (
    AtomLayout,
    AtomState,
    SLMHolder,
)


def _case(
    sources: tuple[tuple[float, float], ...],
    targets: tuple[tuple[float, float], ...],
    *,
    stationary: tuple[tuple[float, float], ...] = (),
    rows: int | None = None,
    columns: int | None = None,
) -> tuple[Device, AtomLayout, AtomLayout]:
    source_sites = tuple(
        SLMSite(f"s{index}", Position(*point)) for index, point in enumerate(sources)
    )
    target_sites = tuple(
        SLMSite(f"t{index}", Position(*point)) for index, point in enumerate(targets)
    )
    static_sites = tuple(
        SLMSite(f"p{index}", Position(*point)) for index, point in enumerate(stationary)
    )
    device = Device(
        "strict",
        (),
        source_sites + target_sites + static_sites,
        (AOD("a", Region(-50, -50, 100, 250), 1, rows, columns),),
        Timing(3, 4, 2),
    )
    static_atoms = tuple(
        AtomState(100 + index, site.position, SLMHolder(site.id))
        for index, site in enumerate(static_sites)
    )
    ids = tuple(range(len(sources)))
    entry = AtomLayout(
        tuple(
            AtomState(index, site.position, SLMHolder(site.id))
            for index, site in enumerate(source_sites)
        )
        + static_atoms,
        qubit_to_atom=ids,
    )
    target = AtomLayout(
        tuple(
            AtomState(index, site.position, SLMHolder(site.id))
            for index, site in enumerate(target_sites)
        )
        + static_atoms,
        qubit_to_atom=ids,
    )
    return device, entry, target
