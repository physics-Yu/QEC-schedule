"""Approved raw T|+> center injection with one complete N/Z extraction round.

Protocol: Ye et al., Phys. Rev. Lett. 131, 210603 (2023); arXiv v2 Fig. 1(a)
and Eq. (1), https://arxiv.org/html/2305.15972v2. Target here is |A^(pi/4)>.
Local branch corrections below use this code's own data-role convention.
"""

from dataclasses import dataclass, replace
from typing import ClassVar

from nadit_physical_compiler.device import Device, Position

from ..._support.atom_template import AtomComponentTemplate, compile_template
from ...contracts.component import ComponentDescription, CorrectionTerm
from ..definition import ROLES
from .circuits import se_layers

ACCEPTANCE_PORTS = ("X0", "X3", "Z0", "Z3")
CORRECTIONS = (
    CorrectionTerm("X1", (("data[2]", "Z"),)),
    CorrectionTerm("X2", (("data[6]", "Z"),)),
    CorrectionTerm("Z1", (("data[0]", "X"),)),
    CorrectionTerm("Z2", (("data[8]", "X"),)),
)


@dataclass(frozen=True)
class RawTComponent:
    """Prepare raw T|+> modulo local correction metadata, with finite acceptance.

    The four boundary ports must equal zero; bulk signs remain arbitrary.
    Rejection marks an unusable output without resetting or retrying it.
    No frame maintenance, physical correction, decoding or distillation occurs.
    """

    name: str = "raw_t"
    acceptance_ports: ClassVar[tuple[str, ...]] = ACCEPTANCE_PORTS

    def __post_init__(self) -> None:
        if self.name != "raw_t":
            raise ValueError(
                "RawTComponent only implements the approved 'raw_t' route."
            )

    @property
    def source_qasm(self) -> str:
        """Return center H/T preparation followed by the unchanged full N/Z round."""
        lines = [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            "qubit[17] q;",
            "bit[8] m;",
        ]
        lines.extend(f"reset q[{q}];" for q in range(9))
        lines.extend(f"h q[{q}];" for q in (0, 1, 4, 7, 8))
        lines.extend(("t q[4];", "barrier q;"))
        lines.extend(f"reset q[{q}];" for q in range(9, 17))
        lines.extend(f"h q[{q}];" for q in range(9, 13))
        lines.append("barrier q;")
        for layer in se_layers():
            lines.extend(f"cx q[{a}], q[{b}];" for a, b in layer)
            lines.append("barrier q;")
        lines.extend(f"h q[{q}];" for q in range(9, 13))
        lines.append("barrier q;")
        lines.extend(f"m[{i}] = measure q[{9 + i}];" for i in range(8))
        return "\n".join(lines) + "\n"

    @property
    def description(self) -> ComponentDescription:
        """Declare discarded input, retained layout, local acceptance and relations."""
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
                "Discard previous data state; prepare center T|+> and product seed",
            ),
            (
                "All atoms return to their entry homes; AODs inactive",
                "Ancillas retained in measured states; eight results may be pending",
                "Accept iff X0=X3=Z0=Z3=0; bulk X1,X2,Z1,Z2 are not rejection tests",
                "Accepted ideal output is encoded T|+> modulo returned Pauli relations",
                "No physical correction, global frame, decoder, retry or distillation",
                "Boundary acceptance does not guarantee absence of logical errors",
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
        """Compile relative atom actions once and retain local interpretation rules."""
        template = compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=home_sites,
            origin=origin,
            aod_id=aod_id,
            expected_values=(0, None, None, 0, 0, None, None, 0),
            corrections=CORRECTIONS,
        )
        return replace(template, acceptance_ports=self.acceptance_ports)
