"""Four-logical-qubit GHZ experiment.

The package deliberately contains only experiment construction, verification,
and reporting.  Compilation, placement, batching, and execution are delegated
to the public qec_schedule layers.
"""

from .logical_program import FourLogicalSurfaceCode, build_logical_program, build_physical_circuit
from .config import build_block_placements, logical_block_visualization

__all__ = [
    "FourLogicalSurfaceCode",
    "build_logical_program",
    "build_physical_circuit",
    "build_block_placements",
    "logical_block_visualization",
]
