"""Public d3 measured initialization, single SE round, and physical Pauli gates."""

from dataclasses import dataclass

from nadit_physical_compiler.device import Device, Position

from ..._support.atom_template import AtomComponentTemplate, compile_template
from ...contracts.component import ComponentDescription, CorrectionTerm
from ..definition import ROLES
from .circuits import NAMES, PAULI_STRINGS, source_qasm
from .hadamard import HadamardComponent
from .injection import RawTComponent
from .measurement import MEASUREMENT_NAMES, LogicalMeasurementComponent
from .phase import PHASE_NAMES, PhaseComponent

SINGLE_BLOCK_NAMES = (*NAMES, "logical_h", *PHASE_NAMES, "raw_t", *MEASUREMENT_NAMES)


def _pauli_description(name: str) -> ComponentDescription:
    """Describe a physical logical string without measurement or frame updates."""
    return ComponentDescription(
        "rotated_surface_d3",
        name,
        "1",
        ROLES,
        (),
        (
            "17 atoms at reference SLM homes; complete occupancy supplied",
            "Current nonzoned resource profile; inactive flexible AODs",
            "Encoded data in any stabilizer-sign sector; do not reset data",
            "Ancillas may have any state and are not operated on",
        ),
        (
            "All atoms remain at their entry homes; AODs remain inactive",
            f"Apply physical {name}; preserve stabilizer signs and encoding",
            "Ancillas unchanged; no reset, measurement, or syndrome extraction",
            "No measurement ports, correction relations, or frame updates",
        ),
    )


@dataclass(frozen=True)
class SurfaceD3Component:
    """Concrete protocol, callable through the shared compiled-template contract."""

    name: str

    @property
    def source_qasm(self) -> str:
        """Return the approved initialization, SE, or physical-Pauli circuit."""
        return source_qasm(self.name)

    @property
    def description(self) -> ComponentDescription:
        """Declare entry resources and physical/quantum exit semantics."""
        if self.name in PAULI_STRINGS:
            return _pauli_description(self.name)
        quantum_entry = (
            "Encoded block with any stabilizer-sign sector; do not reset data"
            if self.name == "se_round"
            else "Reset all data, then measure all eight stabilizers"
        )
        quantum_exit = (
            "Measure stabilizers; preserve logical information; apply no correction"
            if self.name == "se_round"
            else (
                f"Prepare {'|0_L>' if self.name == 'initialize_0' else '|+_L>'} "
                "modulo returned Pauli relations; do not apply them"
            )
        )
        return ComponentDescription(
            "rotated_surface_d3",
            self.name,
            "1",
            ROLES,
            ROLES[9:],
            (
                "17 atoms at reference SLM homes; required guest traps empty",
                "Inactive AODs; flexible nonzoned transport; retained readout",
                "Caller supplies complete occupancy and reserved result identities",
                quantum_entry,
            ),
            (
                "All atoms return to the same reference homes; AODs inactive",
                "Ancillas retained in their measured states; no trailing reset",
                "Eight result ports with identity and individual availability time",
                quantum_exit,
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
        """Compile this protocol once for a chosen physical resource profile."""
        expected: tuple[int | None, ...]
        corrections: tuple[CorrectionTerm, ...]
        if self.name == "initialize_0":
            corrections = tuple(
                CorrectionTerm(f"X{i}", ((f"data[{q}]", "Z"),))
                for i, q in enumerate((0, 2, 6, 8))
            )
            expected = (None,) * 4 + (0,) * 4
        elif self.name == "initialize_plus":
            corrections = tuple(
                CorrectionTerm(f"Z{i}", ((f"data[{q}]", "X"),))
                for i, q in enumerate((6, 0, 8, 2))
            )
            expected = (0,) * 4 + (None,) * 4
        elif self.name == "se_round":
            corrections, expected = (), (None,) * 8
        else:
            corrections, expected = (), ()
        return compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=home_sites,
            origin=origin,
            aod_id=aod_id,
            expected_values=expected,
            corrections=corrections,
        )


def get_component(
    name: str,
) -> (
    SurfaceD3Component
    | HadamardComponent
    | RawTComponent
    | PhaseComponent
    | LogicalMeasurementComponent
):
    """Look up approved d3 protocols; reject unimplemented gate substitutions."""
    if name == "logical_h":
        return HadamardComponent()
    if name in MEASUREMENT_NAMES:
        return LogicalMeasurementComponent(name)
    if name == "raw_t":
        return RawTComponent()
    if name in PHASE_NAMES:
        return PhaseComponent(name)
    if name not in NAMES:
        raise ValueError(
            f"Unsupported surface d3 component {name!r}; "
            f"choose from {SINGLE_BLOCK_NAMES}."
        )
    return SurfaceD3Component(name)
