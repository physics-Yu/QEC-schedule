"""Distance-independent destructive readout interpretation; no noisy decoder."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from nadit_physical_compiler.physical_ir import ResultRef

from modules.codes.contracts.component import ComponentExpansion

from .definition import SurfaceCodeDefinition, definition


@dataclass(frozen=True)
class LogicalMeasurementSpec:
    """Physical ports and ideal logical/check parities with input signs retained."""

    basis: Literal["X", "Z"]
    physical_ports: tuple[str, ...]
    logical_parity_ports: tuple[str, ...]
    same_basis_check_parities: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class IdealLogicalObservable:
    """Delivered physical parity, explicitly distinct from a decoded noisy bit."""

    invocation_id: str
    block_id: str
    basis: Literal["X", "Z"]
    result_refs: tuple[ResultRef, ...]
    available_at_us: float
    value: int | None
    evidence: Literal["ideal_parity"] = "ideal_parity"


def measurement_spec(name: str, code: SurfaceCodeDefinition) -> LogicalMeasurementSpec:
    """Describe a supported destructive X/Z readout; reject other components."""
    if name not in ("logical_mx", "logical_mz"):
        raise ValueError("Measurement metadata requires logical_mx or logical_mz.")
    basis: Literal["X", "Z"] = "X" if name == "logical_mx" else "Z"
    support = code.logical_x if basis == "X" else code.logical_z
    return LogicalMeasurementSpec(
        basis,
        code.roles[: code.data_count],
        tuple(f"data[{q}]" for q in support),
        tuple(
            (role, tuple(f"data[{q}]" for q in qs))
            for role, (b, qs) in zip(code.check_roles, code.checks, strict=True)
            if b == basis
        ),
    )


def read_ideal_observable(
    expansion: ComponentExpansion, *, distance: int, at_us: float
) -> IdealLogicalObservable:
    """Interpret delivered data bits; missing or early inputs remain pending.

    Args:
        expansion: A destructive logical-MX/MZ invocation at the specified code.
        distance: Odd distance of the expected code contract.
        at_us: Caller-owned current time, in microseconds.
    Returns:
        An ideal parity value and its source identities/availability.
    Raises:
        ValueError: If time or the component's identity/ports are incompatible.
    """
    if not isfinite(at_us) or at_us < 0:
        raise ValueError("Observable time must be finite and nonnegative.")
    code, description = definition(distance), expansion.description
    spec = measurement_spec(description.component_id, code)
    if (
        description.code_id != f"rotated_surface_d{distance}"
        or description.version != "1"
        or description.roles != code.roles
        or description.measurements != spec.physical_ports
        or tuple(m.port for m in expansion.measurements) != spec.physical_ports
    ):
        raise ValueError(
            "Logical measurement does not match the expected code/port contract."
        )
    outputs = {m.port: m for m in expansion.measurements}
    selected = tuple(outputs[p] for p in spec.logical_parity_ports)
    ready = max(m.available_at_us for m in selected)
    value = None
    if at_us >= ready and all(m.value is not None for m in selected):
        value = sum(m.value for m in selected if m.value is not None) % 2
    return IdealLogicalObservable(
        expansion.invocation_id,
        expansion.block_id,
        spec.basis,
        tuple(m.result for m in selected),
        ready,
        value,
    )
