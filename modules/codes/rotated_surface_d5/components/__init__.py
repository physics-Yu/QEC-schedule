"""Distance-five components using the same compiled-template contract as d3."""

from modules.codes.rotated_surface import HadamardComponent, SurfaceComponent
from modules.codes.rotated_surface import get_component as _get_component


def get_component(name: str) -> SurfaceComponent | HadamardComponent:
    """Return a verified distance-five protocol; unsupported gates raise ValueError."""
    return _get_component(name, 5)
