"""Distance-three logical translation entry; atom components remain pending."""

from .._surface import CLIFFORD_T, SURFACE_COMPONENTS
from ..contracts import CodeEntry


def compilation_entry() -> CodeEntry:
    """Declare the d3 Clifford+T scheme without claiming executable components."""
    return CodeEntry("rotated_surface_d3", "clifford_t", CLIFFORD_T, SURFACE_COMPONENTS)
