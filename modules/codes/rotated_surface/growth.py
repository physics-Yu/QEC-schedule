"""Rotated-code deformation from a fixed d=3 injection patch.

The small patch touches the upper physical edge and the left logical boundary.
New rows are |+>; new columns alongside the old patch are |0>. Measuring the
target checks preserves the extended middle-column X and middle-row Z of the
seed patch. No target check is a postselection predicate.
"""

from dataclasses import dataclass
from functools import cached_property

from nadit_physical_compiler.device import Device, Position

from modules.codes._support.atom_template import AtomComponentTemplate, compile_template
from modules.codes.contracts.component import ComponentDescription, CorrectionTerm

from .algebra import mask
from .circuits import extraction_body
from .components import _correction
from .definition import definition


def injection_indices(distance: int) -> tuple[int, ...]:
    """Map all 17 small-patch roles into target roles without moving data."""
    code = definition(distance)
    positions = {xy: q for q, xy in enumerate(code.reference_coordinates)}
    return tuple(
        positions[x, y + 2 * (distance - 3)]
        for x, y in definition(3).reference_coordinates
    )


@dataclass(frozen=True)
class GrowthComponent:
    """Initialize only new data and perform the first full target-code SE.

    Args:
        distance: Odd target distance greater than three.
    Raises:
        ValueError: If there is no enlargement or the distance is invalid.
    """

    distance: int

    def __post_init__(self) -> None:
        definition(self.distance)
        if self.distance == 3:
            raise ValueError("Distance three needs no growth component.")

    @property
    def source_qasm(self) -> str:
        """Return actual preparation and measured extraction, with no seed reset."""
        code = definition(self.distance)
        kept = set(injection_indices(self.distance)[:9])
        new = [q for q in range(code.data_count) if q not in kept]
        lines = [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            f"qubit[{code.atom_count}] q;",
            f"bit[{code.check_count}] m;",
            *(f"reset q[{q}];" for q in new),
            *(f"h q[{q}];" for q in new if q // self.distance < self.distance - 3),
            "barrier q;",
            *extraction_body(code),
        ]
        return "\n".join(lines) + "\n"

    @property
    def acceptance_ports(self) -> tuple[str, ...]:
        """Growth always uses syndrome decoding, never postselection."""
        return ()

    @cached_property
    def correction_terms(self) -> tuple[CorrectionTerm, ...]:
        """Ideal branch gauge correction preserving both transported seed axes.

        These are not a noisy decoder. Repeated noisy measurements are handled
        separately by GrowthDecoder before evaluating this linear frame map.
        """
        code = definition(self.distance)
        n, d = code.data_count, self.distance
        preserve = (mask(range(1, n, d)), mask(range((d - 2) * d, (d - 1) * d)) << n)
        return tuple(
            CorrectionTerm(
                port,
                _correction(code, tuple(int(i == j) for i in range(n - 1)), preserve),
            )
            for j, port in enumerate(code.check_roles)
        )

    @property
    def description(self) -> ComponentDescription:
        """Describe deformation and its explicit frame handoff."""
        code = definition(self.distance)
        return ComponentDescription(
            f"rotated_surface_d{self.distance}",
            "grow_from_d3",
            "1",
            code.roles,
            code.check_roles,
            ("Live d3 seed at injection_indices; unprepared outer data",),
            (
                "One full target SE; no postselection",
                "Frame and noisy decoding required before logical use",
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
        """Compile actual deformation using the caller's unchanged device/world."""
        return compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=home_sites,
            origin=origin,
            aod_id=aod_id,
            expected_values=(None,) * definition(self.distance).check_count,
            corrections=self.correction_terms,
        )
