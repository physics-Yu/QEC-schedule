"""Complete distance-11 component lookup using the shared implementation."""

from modules.codes.rotated_surface.catalog import (
    COMPONENT_NAMES,
    SurfaceProtocol,
    get_protocol,
)

__all__ = ["COMPONENT_NAMES", "get_component"]


def get_component(name: str) -> SurfaceProtocol:
    """Return a concrete d11 protocol; unknown names raise ValueError."""
    return get_protocol(name, 11)
