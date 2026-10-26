"""Retained-atom destructive readout and ideal logical-observable metadata."""

from dataclasses import dataclass
from math import isfinite
from typing import Literal

from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.physical_ir import ResultRef

from ..._support.atom_template import AtomComponentTemplate, compile_template
from ...contracts.component import ComponentDescription, ComponentExpansion
from ..definition import CHECKS, LOGICAL_X, LOGICAL_Z, ROLES

MEASUREMENT_NAMES = ("logical_mz", "logical_mx")


@dataclass(frozen=True)
class LogicalMeasurementSpec:
    """Describe physical readout and ideal parities, without implementing decoding.

    ``same_basis_check_parities`` supplies local check equations for a future
    decoder. Their signs are not assumed positive. ``logical_parity_ports``
    names the chosen logical representative, including its existing input sign.
    """

    basis: Literal["X", "Z"]
    physical_ports: tuple[str, ...]
    logical_parity_ports: tuple[str, ...]
    same_basis_check_parities: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class IdealLogicalObservable:
    """One ideal parity result with invocation identity and classical availability.

    ``value=None`` means a required bit or its delivery time is still pending.
    A supplied value is the physical-bit XOR, not a noisy decoded logical bit.
    The caller separately respects the component's physical exit before reuse.
    """

    invocation_id: str
    block_id: str
    basis: Literal["X", "Z"]
    result_refs: tuple[ResultRef, ...]
    available_at_us: float
    value: int | None
    evidence: Literal["ideal_parity"] = "ideal_parity"


@dataclass(frozen=True)
class LogicalMeasurementComponent:
    """Read all nine data atoms, consuming encoding while retaining all 17 atoms.

    Args:
        name: ``logical_mz`` or ``logical_mx``.

    Raises:
        ValueError: If the requested measurement basis is unsupported.
    """

    name: str

    def __post_init__(self) -> None:
        if self.name not in MEASUREMENT_NAMES:
            raise ValueError(f"Unsupported d3 logical measurement {self.name!r}.")

    @property
    def measurement_spec(self) -> LogicalMeasurementSpec:
        """Return ideal observable and same-basis check equations for readout."""
        basis: Literal["X", "Z"] = "X" if self.name == "logical_mx" else "Z"
        support = LOGICAL_X if basis == "X" else LOGICAL_Z
        return LogicalMeasurementSpec(
            basis,
            ROLES[:9],
            tuple(f"data[{q}]" for q in support),
            tuple(
                (f"{b}{i % 4}", tuple(f"data[{q}]" for q in check))
                for i, (b, check) in enumerate(CHECKS)
                if b == basis
            ),
        )

    @property
    def source_qasm(self) -> str:
        """Return destructive X/Z readout; MX uses H9 with no patch permutation."""
        lines = [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            "qubit[17] q;",
            "bit[9] m;",
        ]
        if self.name == "logical_mx":
            lines.extend(f"h q[{q}];" for q in range(9))
            lines.append("barrier q;")
        lines.extend(f"m[{q}] = measure q[{q}];" for q in range(9))
        return "\n".join(lines) + "\n"

    @property
    def description(self) -> ComponentDescription:
        """Declare consumed encoding, retained physical carriers, and raw ports."""
        return ComponentDescription(
            "rotated_surface_d3",
            self.name,
            "1",
            ROLES,
            ROLES[:9],
            (
                "17 atoms at reference SLM homes; complete occupancy supplied",
                "Inactive flexible AODs and retained-atom readout capability",
                "Encoded data in any stabilizer-sign sector; input signs are retained",
                "Ancillas may have any state and are not operated on",
            ),
            (
                "Logical quantum information is consumed by nine data measurements",
                "All 17 atoms return to their entry homes; AODs inactive",
                "Measured data atoms are retained in Z eigenstates; no trailing reset",
                "Nine raw result ports retain identity and individual availability",
                "Ideal logical parity is metadata; no decoder or frame update",
                "No syndrome extraction, logical-H permutation, or postselection",
            ),
        )

    def compile(
        self,
        device: Device,
        *,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
    ) -> AtomComponentTemplate:
        """Compile readout using the supplied finite or unbounded exposure capacity.

        Raises:
            ValueError: If readout cannot retain the component's physical atoms,
                or if the physical compiler rejects the reference configuration.
        """
        if device.readout is None or not device.readout.retain_atoms:
            raise ValueError("Logical measurement requires retained-atom readout.")
        return compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=home_sites,
            origin=origin,
            aod_id=aod_id,
            expected_values=(None,) * 9,
            corrections=(),
        )


def read_ideal_observable(
    expansion: ComponentExpansion, *, at_us: float
) -> IdealLogicalObservable:
    """Interpret delivered physical bits as an ideal parity, never as decoding.

    Args:
        expansion: A d3 logical-MX or logical-MZ expansion, possibly with bits.
        at_us: Caller-owned current time; early or missing bits remain pending.

    Returns:
        Observable identity, required result references, availability and value.

    Raises:
        ValueError: If time is invalid or the expansion has incompatible ports.
    """
    if not isfinite(at_us) or at_us < 0:
        raise ValueError("Observable time must be finite and nonnegative.")
    description = expansion.description
    if (
        description.code_id != "rotated_surface_d3"
        or description.component_id not in MEASUREMENT_NAMES
        or description.version != "1"
        or description.roles != ROLES
        or description.measurements != ROLES[:9]
        or tuple(m.port for m in expansion.measurements) != ROLES[:9]
    ):
        raise ValueError("Expected a d3 logical measurement with nine data ports.")
    spec = LogicalMeasurementComponent(description.component_id).measurement_spec
    outputs = {m.port: m for m in expansion.measurements}
    selected = tuple(outputs[port] for port in spec.logical_parity_ports)
    available = max(m.available_at_us for m in selected)
    value = None
    if at_us >= available and all(m.value is not None for m in selected):
        value = sum(m.value for m in selected if m.value is not None) % 2
    return IdealLogicalObservable(
        expansion.invocation_id,
        expansion.block_id,
        spec.basis,
        tuple(m.result for m in selected),
        available,
        value,
    )
