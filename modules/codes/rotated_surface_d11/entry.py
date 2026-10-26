"""Distance-11 translation declaration; physical execution needs explicit binding."""

from .._surface import CLIFFORD_T, SURFACE_COMPONENTS
from ..contracts import CodeEntry


def compilation_entry() -> CodeEntry:
    """Declare the shared translation scheme without claiming a full factory backend."""
    return CodeEntry(
        "rotated_surface_d11", "clifford_t", CLIFFORD_T, SURFACE_COMPONENTS
    )
