"""Measured phase gates from the CCLP half-cycle fold, and composed Y preparation.

Source: https://arxiv.org/html/2412.01391v1, Fig. 2 and Fig. S1; reference
Zihan-Chen-PhMA/Dynamical-S-gate-decoding at revision
c3b7a1e2f95d49a5853d5534a4596854317890e9, phase_gadget.py and surface_codes.py.
The author's (u,v) coordinates map to (2-v,u), aligning
its stabilizers with this code. This protocol has its own four N/Z slots;
it does not change the ordinary syndrome extraction circuit.
"""

from dataclasses import dataclass, replace

from nadit_physical_compiler.device import Device, Position

from ..._support.atom_template import AtomComponentTemplate, compile_template
from ...contracts.component import ComponentDescription, CorrectionTerm
from ..definition import CHECK_COORDINATES, CHECKS, DATA_COORDINATES, ROLES
from .circuits import source_qasm as base_source_qasm

PHASE_NAMES = ("logical_s", "logical_sdag", "prepare_y")
FOLD_CZ = ((2, 6), (1, 3), (5, 7), (10, 11))
FOLD_S = (0, 4, 8)
FOLD_SDAG = (14, 15)

# For an encoded input, these name the ideal measured input-sign parities.
# They are protocol equations, not a decoder or runtime frame update.
MEASURED_INPUT_PARITIES = (
    ("X0", ("X0", "Z1")),
    ("X1", ("X1", "Z2")),
    ("X2", ("X2", "Z3")),
    ("X3", ("X3",)),
    *((f"Z{i}", (f"Z{i}",)) for i in range(4)),
)
EXIT_SYNDROME_PARITIES = (
    ("X0", ("phase.X0",)),
    ("X1", ("phase.X1", "phase.Z0")),
    ("X2", ("phase.X2",)),
    ("X3", ("phase.X3",)),
    *((f"Z{i}", (f"phase.Z{i}",)) for i in range(4)),
)


def phase_se_layers() -> tuple[tuple[tuple[int, int], ...], ...]:
    """Return the rotated author's ordering, independent of ordinary SE slots."""
    orders = {
        "X": ((1, -1), (-1, -1), (1, 1), (-1, 1)),
        "Z": ((1, -1), (1, 1), (-1, -1), (-1, 1)),
    }
    positions = {xy: q for q, xy in enumerate(DATA_COORDINATES)}
    layers = []
    for slot in range(4):
        pairs = []
        for i, ((basis, support), (x, y)) in enumerate(
            zip(CHECKS, CHECK_COORDINATES, strict=True)
        ):
            dx, dy = orders[basis][slot]
            data = positions.get((x + dx, y + dy))
            if data is not None:
                if data not in support:
                    raise ValueError("Phase-SE geometry disagrees with stabilizers.")
                pairs.append((9 + i, data) if basis == "X" else (data, 9 + i))
        layers.append(tuple(pairs))
    return tuple(layers)


def _phase_body(adjoint: bool, measurement_offset: int = 0) -> list[str]:
    lines = [f"reset q[{q}];" for q in range(9, 17)]
    lines.extend(f"h q[{q}];" for q in range(9, 13))
    lines.append("barrier q;")
    for index, layer in enumerate(phase_se_layers()):
        lines.extend(f"cx q[{a}], q[{b}];" for a, b in layer)
        lines.append("barrier q;")
        if index == 1:
            lines.extend(f"cz q[{a}], q[{b}];" for a, b in FOLD_CZ)
            lines.extend(f"{'sdg' if adjoint else 's'} q[{q}];" for q in FOLD_S)
            lines.extend(f"{'s' if adjoint else 'sdg'} q[{q}];" for q in FOLD_SDAG)
            lines.append("barrier q;")
    lines.extend(f"h q[{q}];" for q in range(9, 13))
    lines.append("barrier q;")
    lines.extend(f"m[{measurement_offset + i}] = measure q[{9 + i}];" for i in range(8))
    return lines


@dataclass(frozen=True)
class PhaseComponent:
    """A local phase protocol with immutable measurement/correction metadata."""

    name: str

    def __post_init__(self) -> None:
        if self.name not in PHASE_NAMES:
            raise ValueError(f"Unsupported d3 phase component: {self.name!r}.")

    @property
    def source_qasm(self) -> str:
        """Return an S-SE round or approved initialization followed by S-SE."""
        if self.name == "prepare_y":
            lines = (
                base_source_qasm("initialize_plus")
                .replace("bit[8] m;", "bit[16] m;")
                .splitlines()
            )
            lines.append("barrier q;")
            lines.extend(_phase_body(False, 8))
        else:
            lines = [
                "OPENQASM 3.0;",
                'include "stdgates.inc";',
                "qubit[17] q;",
                "bit[8] m;",
            ]
            lines.extend(_phase_body(self.name == "logical_sdag"))
        return "\n".join(lines) + "\n"

    @property
    def correction_terms(self) -> tuple[CorrectionTerm, ...]:
        """Select canonical Y using only this preparation's recorded bits.

        Each term repairs the output stabilizer signs caused by one initial
        Z-check outcome, and commutes with logical Y. These relations neither
        interpret noisy syndromes nor accumulate a frame across invocations.
        S/Sdag alone preserve logical information and expose sector equations,
        without claiming to canonicalize arbitrary encoded input sectors.
        """
        if self.name != "prepare_y":
            return ()
        return (
            CorrectionTerm("prepare.Z0", (("data[6]", "X"), ("data[2]", "Z"))),
            CorrectionTerm("prepare.Z1", (("data[0]", "Y"),)),
            CorrectionTerm("prepare.Z2", (("data[8]", "X"), ("data[2]", "Z"))),
            CorrectionTerm("prepare.Z3", (("data[2]", "X"), ("data[6]", "Z"))),
        )

    @property
    def description(self) -> ComponentDescription:
        """Declare reference-layout entry, measurements, and phase-gate exit."""
        ports = tuple(f"phase.{role}" for role in ROLES[9:])
        if self.name == "prepare_y":
            ports = tuple(f"prepare.{role}" for role in ROLES[9:]) + ports
        return ComponentDescription(
            "rotated_surface_d3",
            self.name,
            "1",
            ROLES,
            ports,
            (
                "17 atoms at reference SLM homes; complete occupancy supplied",
                "Inactive flexible AODs; nonzoned transport and retained readout",
                (
                    "Discard input data; run initialize_plus then a separate S-SE round"
                    if self.name == "prepare_y"
                    else "Encoded input in any stabilizer-sign sector; preserve data"
                ),
            ),
            (
                "All atoms return to the same reference homes; AODs inactive",
                "Ancillas retained in measured states; results may remain pending",
                "Measurement identities and local Pauli relations only; no global frame",
                (
                    "Prepare +Y_L modulo returned correction terms; apply no correction"
                    if self.name == "prepare_y"
                    else (
                        "Logical conjugation X_L -> -Y_L, Y_L -> X_L, Z_L -> Z_L"
                        if self.name == "logical_sdag"
                        else "Logical conjugation X_L -> Y_L, Y_L -> -X_L, Z_L -> Z_L"
                    )
                ),
                "Ideal phase ports: mX=(x0^z1,x1^z2,x2^z3,x3); mZ=(z0,z1,z2,z3)",
                "Exit signs: X=(mX0,mX1^mZ0,mX2,mX3); Z=(mZ0,mZ1,mZ2,mZ3)",
                "These local sign equations assume ideal encoded input; no noisy decoding",
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
        """Compile once into the existing relative-coordinate atom contract."""
        template = compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=home_sites,
            origin=origin,
            aod_id=aod_id,
            expected_values=(
                (0,) * 4 + (None,) * 4 + (None,) * 3 + (0,) + (None,) * 4
                if self.name == "prepare_y"
                else (None,) * 8
            ),
            corrections=self.correction_terms,
        )
        return replace(template, output_syndrome_parities=EXIT_SYNDROME_PARITIES)
