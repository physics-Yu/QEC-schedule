"""Distance-parameterized components using the established atom-template ABI."""

from dataclasses import dataclass, replace
from functools import cache, cached_property

from nadit_physical_compiler.device import Device, Position

from modules.codes._support.atom_template import AtomComponentTemplate, compile_template
from modules.codes.contracts.component import ComponentDescription, CorrectionTerm

from .algebra import combination, conjugate, mask, solve
from .circuits import (
    MEASUREMENT_NAMES,
    PHASE_NAMES,
    SINGLE_BLOCK_NAMES,
    phase_unitary,
    raw_plus_qubits,
    source_qasm,
)
from .definition import SurfaceCodeDefinition, definition
from .hadamard import HadamardComponent
from .measurement import LogicalMeasurementSpec, measurement_spec


def _stabilizer_vectors(code: SurfaceCodeDefinition) -> tuple[int, ...]:
    return tuple(
        mask(qs) << (0 if b == "X" else code.data_count) for b, qs in code.checks
    )


@cache
def phase_sign_matrices(distance: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Derive input-to-measurement and input-to-exit parity matrices exactly.

    Pull every measured Z and output check backwards through the actual S-SE
    Clifford. Initial ancilla Z stabilizers have positive signs. The remaining
    data operator must be a positive product of input checks; failure rejects
    the protocol instead of silently asserting a sign relation.
    """
    code = definition(distance)
    n = code.data_count
    data_mask = (1 << n) - 1
    checks = _stabilizer_vectors(code)
    gates = phase_unitary(code)

    def pull(x: int, z: int) -> int:
        x, z, phase = conjugate((x, z, 0), gates, inverse=True)
        if x >> n or phase:
            raise ValueError(
                "Phase check is not a positive deterministic input parity."
            )
        return combination(checks, x | ((z & data_mask) << n), 2 * n)

    measured = tuple(pull(0, 1 << (n + i)) for i in range(code.check_count))
    exited = tuple(pull(v & data_mask, v >> n) for v in checks)
    return measured, exited


def _correction(
    code: SurfaceCodeDefinition, values: tuple[int, ...], preserve: tuple[int, ...]
) -> tuple[tuple[str, str], ...]:
    n = code.data_count
    data_mask = (1 << n) - 1
    vectors = (*_stabilizer_vectors(code), *preserve)
    # Symplectic commutation with (x,z) is dot((z,x), correction).
    equations = tuple((v >> n) | ((v & data_mask) << n) for v in vectors)
    solution = solve(equations, (*values, *(0 for _ in preserve)), 2 * n)
    x, z = solution & data_mask, solution >> n
    return tuple(
        (f"data[{q}]", "Y" if x & z & (1 << q) else "X" if x & (1 << q) else "Z")
        for q in range(n)
        if (x | z) & (1 << q)
    )


@dataclass(frozen=True)
class SurfaceComponent:
    """One concrete single-block protocol at an odd code distance.

    Args:
        name: A supported protocol name; H is deliberately not substituted.
        distance: Odd integer at least three.
    Raises:
        ValueError: If either protocol name or code distance is unsupported.
    """

    name: str
    distance: int

    def __post_init__(self) -> None:
        definition(self.distance)
        if self.name not in SINGLE_BLOCK_NAMES:
            raise ValueError(
                f"Unsupported surface component {self.name!r}; "
                f"choose from {SINGLE_BLOCK_NAMES}."
            )

    @property
    def code(self) -> SurfaceCodeDefinition:
        """Return this component's immutable patch definition."""
        return definition(self.distance)

    @property
    def source_qasm(self) -> str:
        """Return the full concrete circuit including reset and measured SE."""
        return source_qasm(self.name, self.code)

    @property
    def measurement_spec(self) -> LogicalMeasurementSpec:
        """Return destructive-readout parity metadata; reject other components."""
        return measurement_spec(self.name, self.code)

    @cached_property
    def measured_input_parities(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Local ideal S-SE measurement equations, without runtime frame state."""
        if self.name not in PHASE_NAMES:
            return ()
        measured, _ = phase_sign_matrices(self.distance)
        roles = self.code.check_roles
        return tuple(
            (f"phase.{role}", tuple(p for j, p in enumerate(roles) if row & (1 << j)))
            for role, row in zip(roles, measured, strict=True)
        )

    @cached_property
    def output_syndrome_parities(self) -> tuple[tuple[str, tuple[str, ...]], ...]:
        """Express each output check sign using this call's phase-result ports."""
        if self.name not in PHASE_NAMES:
            return ()
        measured, exited = phase_sign_matrices(self.distance)
        roles = self.code.check_roles
        rows = tuple(
            combination(measured, row, self.code.check_count) for row in exited
        )
        return tuple(
            (role, tuple(f"phase.{p}" for j, p in enumerate(roles) if row & (1 << j)))
            for role, row in zip(roles, rows, strict=True)
        )

    @cached_property
    def acceptance_ports(self) -> tuple[str, ...]:
        """Raw-seed deterministic initial checks only; temporal checks are separate."""
        if self.name != "raw_t":
            return ()
        plus = set(raw_plus_qubits(self.code))
        center = self.code.data_count // 2
        return tuple(
            role
            for role, (basis, support) in zip(
                self.code.check_roles, self.code.checks, strict=True
            )
            if center not in support
            and (
                (basis == "X" and set(support) <= plus)
                or (basis == "Z" and not set(support) & plus)
            )
        )

    @cached_property
    def correction_terms(self) -> tuple[CorrectionTerm, ...]:
        """Return exact ideal branch canonicalization; never apply it implicitly."""
        code, name = self.code, self.name
        n, count = code.data_count, code.check_count
        if name not in ("initialize_0", "initialize_plus", "prepare_y", "raw_t"):
            return ()
        x, z = mask(code.logical_x), mask(code.logical_z) << n
        preserve: tuple[int, ...] = (z,) if name == "initialize_0" else (x,)
        if name == "prepare_y":
            preserve = (x | z,)
        elif name == "raw_t":
            center = code.distance // 2
            preserve = (
                mask(range(center, n, code.distance)),
                mask(range(center * code.distance, (center + 1) * code.distance)) << n,
            )
        exited = phase_sign_matrices(code.distance)[1] if name == "prepare_y" else ()
        terms = []
        for j, (port, (basis, _)) in enumerate(
            zip(code.check_roles, code.checks, strict=True)
        ):
            if name == "raw_t" and port in self.acceptance_ports:
                continue
            if name != "raw_t" and basis != ("X" if name == "initialize_0" else "Z"):
                continue
            values = (
                tuple((row >> j) & 1 for row in exited)
                if exited
                else tuple(int(i == j) for i in range(count))
            )
            terms.append(
                CorrectionTerm(
                    ("prepare." if name == "prepare_y" else "") + port,
                    _correction(code, values, preserve),
                )
            )
        return tuple(terms)

    @property
    def description(self) -> ComponentDescription:
        """Describe physical entry/exit and explicitly bounded quantum evidence."""
        code, name = self.code, self.name
        if name in MEASUREMENT_NAMES:
            ports = code.roles[: code.data_count]
            effect = (
                "Destructive data readout; ideal parity metadata is not noisy decoding"
            )
        elif name in PHASE_NAMES:
            ports = tuple(f"phase.{p}" for p in code.check_roles)
            if name == "prepare_y":
                ports = tuple(f"prepare.{p}" for p in code.check_roles) + ports
            effect = (
                "Real half-cycle fold S-SE; retain result and output-sign equations"
            )
        elif name.startswith("logical_"):
            ports = ()
            effect = "Physical logical Pauli string; no implicit syndrome extraction"
        else:
            ports = code.check_roles
            effect = (
                "One complete measured N/Z extraction; ideal corrections are metadata"
            )
        return ComponentDescription(
            f"rotated_surface_d{code.distance}",
            name,
            "1",
            code.roles,
            ports,
            (
                f"{code.atom_count} atoms at SLM homes; complete world supplied",
                "Inactive flexible AOD; nonzoned transport and retained-atom readout",
                "Preparation discards input; other protocols preserve it until readout",
            ),
            (
                "All atoms return home; AOD inactive; no trailing reset",
                effect,
                "No global frame, decoder, retries, or logical error-rate claim",
                "Raw-T use requires the separate repeated-SE postselection protocol",
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
        """Compile through the existing physical backend and immutable template.

        Args:
            device: Complete device, including caller-selected timing and layout.
            home_sites: One SLM home per role in definition order.
            origin: Translation origin of the local template.
            aod_id: Flexible AOD selected by the caller.
        Returns:
            A validated relative atom template with no outcomes or clock state.
        Raises:
            ValueError: If homes/readout or the physical profile are unsupported.
        """
        if len(home_sites) != self.code.atom_count:
            raise ValueError(
                f"Distance {self.distance} needs {self.code.atom_count} homes."
            )
        if device.readout is None or not device.readout.retain_atoms:
            raise ValueError("Surface components require retained-atom readout.")
        code = self.code
        expected: tuple[int | None, ...] = (None,) * len(self.description.measurements)
        if self.name in ("initialize_0", "initialize_plus"):
            deterministic = "Z" if self.name == "initialize_0" else "X"
            expected = tuple(0 if b == deterministic else None for b, _ in code.checks)
        elif self.name == "raw_t":
            expected = tuple(
                0 if port in self.acceptance_ports else None
                for port in code.check_roles
            )
        if self.name == "prepare_y":
            measured, _ = phase_sign_matrices(self.distance)
            expected = tuple(0 if b == "X" else None for b, _ in code.checks)
            expected += tuple(
                None if row >> (code.check_count // 2) else 0 for row in measured
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
        return replace(
            template,
            acceptance_ports=self.acceptance_ports,
            output_syndrome_parities=self.output_syndrome_parities,
        )


def get_component(name: str, distance: int) -> SurfaceComponent | HadamardComponent:
    """Select a verified concrete protocol without silently replacing a gate."""
    if name == "raw_t_direct_control":
        return SurfaceComponent("raw_t", distance)
    if name == "raw_t" and distance != 3:
        from .small_raw_t import SmallInjectionRawT

        return SmallInjectionRawT(name, distance)
    if name == "logical_h":
        return HadamardComponent(distance)
    return SurfaceComponent(name, distance)
