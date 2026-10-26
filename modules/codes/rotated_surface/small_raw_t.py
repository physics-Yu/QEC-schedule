"""Unpostselected raw-T: one d3 injection SE, followed by ordinary code growth."""

import re
from dataclasses import replace
from functools import cached_property

from nadit_physical_compiler.device import Device, Position

from modules.codes._support.atom_template import AtomComponentTemplate, compile_template
from modules.codes.contracts.component import ComponentDescription, CorrectionTerm

from .circuits import extraction_body
from .components import SurfaceComponent
from .definition import definition
from .growth import GrowthComponent, injection_indices


class SmallInjectionRawT(SurfaceComponent):
    """Raw primitive with fixed d3 injection and d ordinary target rounds.

    It never promises acceptance. Use the staged RawTPostselection to stop on
    rejected injection results before growth. Measurement histories, including
    nonzero growth syndromes, must be handed to the ordinary growth decoder.
    """

    @property
    def source_qasm(self) -> str:
        """Emit a single seed T and resets only when each data region is introduced."""
        mapping = injection_indices(self.distance)
        small = SurfaceComponent("raw_t", 3).source_qasm.splitlines()[4:]
        small = [
            re.sub(r"q\[(\d+)\]", lambda m: f"q[{mapping[int(m[1])]}]", line)
            for line in small
        ]
        growth = GrowthComponent(self.distance).source_qasm.splitlines()[4:]
        growth = [
            re.sub(r"m\[(\d+)\]", lambda m: f"m[{8 + int(m[1])}]", line)
            for line in growth
        ]
        code = definition(self.distance)
        lines = [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            f"qubit[{code.atom_count}] q;",
            f"bit[{8 + self.distance * code.check_count}] m;",
            *small,
            "barrier q;",
            *growth,
        ]
        for r in range(1, self.distance):
            lines += [
                "barrier q;",
                *extraction_body(code, offset=8 + r * code.check_count),
            ]
        return "\n".join(lines) + "\n"

    @property
    def description(self) -> ComponentDescription:
        """Version the changed raw source and distinguish both result namespaces."""
        code = definition(self.distance)
        return ComponentDescription(
            f"rotated_surface_d{self.distance}",
            "raw_t",
            "3",
            code.roles,
            tuple(f"injection.{p}" for p in definition(3).check_roles)
            + tuple(
                f"growth[{r}].{p}"
                for r in range(self.distance)
                for p in code.check_roles
            ),
            ("Unprepared target patch; only d3 is injected",),
            (
                "One seed T; ordinary target SE after growth",
                "No growth postselection; explicit decoding/frame handoff required",
                "No accepted-output logical error-rate claim",
            ),
        )

    @cached_property
    def acceptance_ports(self) -> tuple[str, ...]:
        """Expose only initial d3 predicates; these do not qualify noisy raw use."""
        return tuple(
            f"injection.{p}" for p in SurfaceComponent("raw_t", 3).acceptance_ports
        )

    @cached_property
    def correction_terms(self) -> tuple[CorrectionTerm, ...]:
        """Ideal final branch relations; noisy use needs the entire SE history."""
        return tuple(
            replace(
                t, measurement_port=f"growth[{self.distance - 1}].{t.measurement_port}"
            )
            for t in GrowthComponent(self.distance).correction_terms
        )

    def compile(
        self,
        device: Device,
        *,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
    ) -> AtomComponentTemplate:
        """Compile actual d3 injection plus target growth using the current device."""
        expected = tuple(
            0 if p in self.acceptance_ports else None
            for p in self.description.measurements
        )
        template = compile_template(
            self.description,
            self.source_qasm,
            device,
            home_sites=home_sites,
            origin=origin,
            aod_id=aod_id,
            expected_values=expected,
            corrections=self.correction_terms,
        )
        return replace(template, acceptance_ports=self.acceptance_ports)
