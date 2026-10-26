"""Complete concrete surface component catalog, independent of code distance."""

from .circuits import SINGLE_BLOCK_NAMES
from .components import SurfaceComponent, get_component
from .growth import GrowthComponent
from .hadamard import HadamardComponent
from .staged_raw_t import RawTPostselection
from .transversal import TransversalCNOTComponent

COMPONENT_NAMES = (
    *SINGLE_BLOCK_NAMES,
    "logical_h",
    "transversal_cnot",
    "grow_from_d3",
    "raw_t_postselection",
)
type SurfaceProtocol = (
    SurfaceComponent
    | HadamardComponent
    | TransversalCNOTComponent
    | GrowthComponent
    | RawTPostselection
)


def get_protocol(name: str, distance: int) -> SurfaceProtocol:
    """Return one existing concrete protocol without inventing a gate realization.

    Single blocks bind one patch, CNOT binds two patches, and postselection owns
    an explicit injection/growth boundary. Their compile APIs remain distinct.
    """
    if name == "transversal_cnot":
        return TransversalCNOTComponent(distance)
    if name == "grow_from_d3":
        return GrowthComponent(distance)
    if name == "raw_t_postselection":
        return RawTPostselection(distance)
    if name in (*SINGLE_BLOCK_NAMES, "logical_h"):
        return get_component(name, distance)
    raise ValueError(
        f"Unsupported surface protocol {name!r}; choose from {COMPONENT_NAMES}."
    )
