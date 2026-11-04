"""Automatic source row order and complete multi-SLM initialization."""

import pytest

from nadit_physical_compiler.device import Position, slm_grid
from nadit_physical_compiler.placement.geometry import PlacementGeometry, SLMArray
from nadit_physical_compiler.placement.initial import make_initial_layout
from nadit_physical_compiler.state import SLMHolder


def _geometry(gate_y: float, storage_count: int = 1) -> PlacementGeometry:
    arrays: list[SLMArray] = []
    for index in range(storage_count):
        sites = slm_grid(f"s{index}", Position(20 * index, 0), 3, 2, Position(5, 5))
        arrays.append(
            SLMArray(
                f"s{index}",
                "storage",
                (sites[:2], sites[2:4], sites[4:]),
                Position(5, 5),
            )
        )
    left = (slm_grid("l", Position(0, gate_y), 1, 2, Position(8, 5)),)
    right = (slm_grid("r", Position(2, gate_y), 1, 2, Position(8, 5)),)
    gates = (
        SLMArray("l", "left", left, Position(8, 5), right),
        SLMArray("r", "right", right, Position(8, 5), left),
    )
    return PlacementGeometry(tuple(arrays), (gates,))


@pytest.mark.parametrize("gate_y", [100])
def test_cross_slm_fill_restarts_same_direction_and_handles_exact_capacity(
    gate_y: float,
) -> None:
    geometry = _geometry(gate_y, storage_count=2)
    layout = make_initial_layout(12, geometry)
    rows = (2, 1, 0) if gate_y > 0 else (0, 1, 2)
    expected = tuple(
        f"s{array}_r{row}_c{column}"
        for array in range(2)
        for row in rows
        for column in range(2)
    )
    assert tuple(atom.holder for atom in layout.atoms) == tuple(
        SLMHolder(site) for site in expected
    )
    assert len({atom.position for atom in layout.atoms}) == 12
