"""Nearest-array candidates, source windows, and orientation score metadata."""

from nadit_physical_compiler.placement.scoring import PlacementConfig
from nadit_physical_compiler.placement.windows import candidate_indices


def test_occupied_center_expands_and_entire_array_exhaustion_terminates() -> None:
    indices = candidate_indices(
        1,
        5,
        (0, 2),
        frozenset(((0, 0),)),
        8,
        PlacementConfig(window_min_width=1),
        stage="gate",
    )

    assert indices == ((0, 0),)
