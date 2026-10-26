"""Reusable nonzoned component templates with checked world-state admission."""

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from math import isclose
from pathlib import Path

import nadit_physical_compiler.compiler as compiler_module
from nadit_physical_compiler.atom_ir import AtomProgram, Measure, Store
from nadit_physical_compiler.compiler import (
    CompilationResult,
    CompiledOperation,
    MeasurementRecord,
    compile_physical,
)
from nadit_physical_compiler.device import Device, Position, Timing
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG, ResultRef
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import (
    encode_dag,
    encode_device,
    encode_program,
)
from nadit_physical_compiler.state import (
    AtomLayout,
    AtomState,
    SLMHolder,
    validate_layout,
)
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result

from ..contracts.component import (
    ComponentBinding,
    ComponentDescription,
    ComponentExpansion,
    CorrectionRelation,
    CorrectionTerm,
    InvocationContext,
    MeasurementOutput,
)
from .atom_binding import rebind_program, shift_position


class BindingRejected(ValueError):
    """This compiled template cannot execute at the supplied physical binding.

    A caller may choose a different resource binding or explicitly compile a
    template for the new geometry. Replanning is never silently performed here.
    """


def _timing(device: Device) -> tuple[Timing, float, float, float, float, float]:
    if device.local is None or device.cz is None or device.readout is None:
        raise BindingRejected("Components require local, CZ and readout capabilities.")
    return (
        device.timing,
        device.local.rotation_us,
        device.local.reset_us,
        device.cz.duration_us,
        device.readout.duration_us,
        device.readout.latency_us,
    )


def _channels(device: Device) -> dict[str, str]:
    _timing(device)
    assert (
        device.local is not None
        and device.cz is not None
        and device.readout is not None
    )
    return {
        "local": device.local.channel,
        "cz": device.cz.channel,
        "readout": device.readout.channel,
    }


@dataclass(frozen=True)
class AtomComponentTemplate:
    """Immutable local-coordinate actions and metadata, without case outcomes.

    `relative_program` is not directly executable. Atom indices are role indices;
    coordinates are offsets, resource names are placeholders, and result IDs
    are local port indices until bind/expand maps them to a concrete invocation.
    """

    description: ComponentDescription
    source_qasm: str
    relative_program: AtomProgram
    dag: PhysicalDAG
    operations: tuple[CompiledOperation, ...]
    relative_sites: tuple[tuple[str, Position], ...]
    home_sites: tuple[str, ...]
    timing_profile: tuple[Timing, float, float, float, float, float]
    measurement_offsets: tuple[float, ...]
    measurement_atoms: tuple[int, ...]
    expected_ideal_values: tuple[int | None, ...]
    correction_terms: tuple[CorrectionTerm, ...]
    source_sha256: str
    reference_device_sha256: str
    compiler_source_sha256: str
    reference_validation_checks: tuple[str, ...]
    acceptance_ports: tuple[str, ...] = ()
    exit_home_sites: tuple[str, ...] = ()
    exit_role_permutation: tuple[int, ...] = ()
    output_syndrome_parities: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def content_sha256(self) -> str:
        """Identify complete immutable actions and interpretation, including exits.

        Source/compiler hashes alone do not identify component-owned transport
        appended after gate compilation, or changed acceptance/sign metadata.
        """
        return canonical_hash(
            asdict(self)
            | {
                "relative_program": encode_program(self.relative_program),
                "dag": encode_dag(self.dag),
            }
        )

    def __post_init__(self) -> None:
        """Check local predicates and the declared physical exit permutation."""
        if len(set(self.acceptance_ports)) != len(self.acceptance_ports) or not set(
            self.acceptance_ports
        ) <= set(self.description.measurements):
            raise ValueError("Acceptance ports must be distinct measurement ports.")
        count = len(self.description.roles)
        homes = self.exit_home_sites or self.home_sites
        permutation = self.exit_role_permutation or tuple(range(count))
        if len(homes) != count or sorted(permutation) != list(range(count)):
            raise ValueError("Exit must declare one home and input atom per role.")
        if any(
            homes[old] != self.home_sites[new] for new, old in enumerate(permutation)
        ):
            raise ValueError("Exit homes and output role permutation disagree.")

    def bind(self, binding: ComponentBinding) -> "BoundAtomComponent":
        """Bind ordered roles; world-state legality is checked when expanding."""
        ids = binding.atom_ids
        if (
            not binding.block_id
            or not binding.aod_id
            or len(ids) != len(self.description.roles)
            or len(set(ids)) != len(ids)
            or any(type(a) is not int or a < 0 for a in ids)
        ):
            raise BindingRejected(
                "Binding requires a unique nonnegative atom for every role."
            )
        if len(dict(binding.site_ids)) != len(binding.site_ids):
            raise BindingRejected("Repeated site binding key.")
        return BoundAtomComponent(self, binding)


def _site_map(
    template: AtomComponentTemplate, binding: ComponentBinding, device: Device
) -> dict[str, str]:
    supplied = dict(binding.site_ids)
    if supplied and supplied.keys() != dict(template.relative_sites).keys():
        raise BindingRejected(
            "Explicit site map must cover exactly the template site keys."
        )
    result = {}
    for key, offset in template.relative_sites:
        point = shift_position(offset, binding.origin)
        matches = [
            s.id
            for s in device.slm_sites
            if isclose(s.position.x, point.x, abs_tol=1e-9, rel_tol=0)
            and isclose(s.position.y, point.y, abs_tol=1e-9, rel_tol=0)
            and (not supplied or s.id == supplied[key])
        ]
        if len(matches) != 1:
            raise BindingRejected(
                f"Site {key!r} needs a unique trap at {point}; "
                "bind or recompile explicitly."
            )
        result[key] = matches[0]
    return result


@dataclass(frozen=True)
class BoundAtomComponent:
    """Participant-bound template; no mutable case or measurement cache."""

    template: AtomComponentTemplate
    binding: ComponentBinding

    def expand(self, context: InvocationContext) -> ComponentExpansion:
        """Expand without compilation and validate against the complete world.

        Raises BindingRejected for geometry, resources, occupancy or timing that
        invalidate reuse. Outputs are pending; results can be attached afterward.
        """
        template, binding, device = self.template, self.binding, context.device
        if _timing(device) != template.timing_profile:
            raise BindingRejected(
                "Timing profile changed; explicitly recompile this component."
            )
        try:
            aod = device.aod(binding.aod_id)
        except KeyError as error:
            raise BindingRejected(
                f"Unknown AOD resource {binding.aod_id!r}."
            ) from error
        if context.world_state.aod_grids or aod.motion != "flexible":
            raise BindingRejected(
                "This nonzoned template requires inactive AODs and flexible transport."
            )
        sites = _site_map(template, binding, device)
        try:
            for atom_id, home in zip(
                binding.atom_ids, template.home_sites, strict=True
            ):
                atom = context.world_state.atom(atom_id)
                if (
                    atom.holder != SLMHolder(sites[home])
                    or atom.position != device.site(sites[home]).position
                ):
                    raise BindingRejected(
                        f"Atom {atom_id} is not at its required entry home."
                    )
        except KeyError as error:
            raise BindingRejected(f"Missing entry atom or site: {error}") from error
        entry = replace(context.world_state, qubit_to_atom=binding.atom_ids)
        try:
            validate_layout(device, entry)
        except ValueError as error:
            raise BindingRejected(f"Invalid complete-world entry: {error}") from error
        ids = {
            i: context.result_id_base + i
            for i in range(len(template.measurement_offsets))
        }
        program = rebind_program(
            template.relative_program,
            shift=binding.origin,
            atoms=dict(enumerate(binding.atom_ids)),
            sites=sites,
            channels=_channels(device),
            aod_id=binding.aod_id,
            results=ids,
        )
        dag = replace(
            template.dag,
            nodes=tuple(
                replace(n, source_id=ids[n.result.measurement_id])
                if n.result is not None
                else n
                for n in template.dag.nodes
            ),
        )
        exit_state = replay(program, entry, device)
        # Validator needs bit-valued records. These structural stand-ins are
        # discarded, never exposed as observations, and cannot select branches.
        records = tuple(
            MeasurementRecord(ResultRef(ids[i]), 0, t)
            for i, t in enumerate(template.measurement_offsets)
        )
        check_result = CompilationResult(
            program, exit_state, template.operations, records, ()
        )
        checked = validate_result(
            check_result, entry_state=entry, device=device, dag=dag
        )
        destinations = {
            atom: sites[home]
            for atom, home in zip(
                binding.atom_ids,
                template.exit_home_sites or template.home_sites,
                strict=True,
            )
        }
        expected_exit = replace(
            entry,
            atoms=tuple(
                replace(
                    atom,
                    position=device.site(destinations[atom.id]).position,
                    holder=SLMHolder(destinations[atom.id]),
                )
                if atom.id in destinations
                else atom
                for atom in entry.atoms
            ),
        )
        if not checked["ok"]:
            raise BindingRejected(f"Bound atom actions rejected: {checked}")
        if exit_state != expected_exit:
            raise BindingRejected(
                "Atom actions do not reach the declared physical exit."
            )
        # Derive global delivery times from actual action boundaries. Adding a
        # pre-summed local offset to start_us rounds differently from replaying
        # a long concatenated program and can violate strict timing checks.
        cursor = context.start_us
        available: dict[int, float] = {}
        for step in program.steps:
            for action in step.actions:
                if isinstance(action, Measure):
                    if device.readout is None:
                        raise BindingRejected(
                            "Measurement actions require readout capability."
                        )
                    ready = cursor + action.duration_us + device.readout.latency_us
                    available.update(
                        (result.measurement_id, ready) for _, result in action.results
                    )
            cursor += step.duration_us
        outputs = tuple(
            MeasurementOutput(
                context.invocation_id,
                port,
                ResultRef(ids[i]),
                binding.atom_ids[template.measurement_atoms[i]],
                available[ids[i]],
                template.expected_ideal_values[i],
            )
            for i, port in enumerate(template.description.measurements)
        )
        role_atoms = dict(
            zip(template.description.roles, binding.atom_ids, strict=True)
        )
        ports = {r.port: r.result for r in outputs}
        relations = tuple(
            CorrectionRelation(
                binding.block_id,
                ports[t.measurement_port],
                tuple((role_atoms[role], basis) for role, basis in t.pauli_roles),
            )
            for t in template.correction_terms
        )
        return ComponentExpansion(
            template.description,
            context.invocation_id,
            binding.block_id,
            context.start_us,
            context.world_state,
            replace(exit_state, qubit_to_atom=context.world_state.qubit_to_atom),
            binding.atom_ids,
            program,
            dag,
            template.operations,
            outputs,
            relations,
            tuple(checked.get("checks", ())),
            replace(
                binding,
                atom_ids=tuple(
                    binding.atom_ids[i] for i in template.exit_role_permutation
                )
                if template.exit_role_permutation
                else binding.atom_ids,
            ),
            tuple((ports[port], 0) for port in template.acceptance_ports),
            template.output_syndrome_parities,
            template_content_sha256=template.content_sha256,
        )


def compile_template(
    description: ComponentDescription,
    source: str,
    device: Device,
    *,
    home_sites: tuple[str, ...],
    origin: Position,
    aod_id: str,
    expected_values: tuple[int | None, ...],
    corrections: tuple[CorrectionTerm, ...],
    spectator_home_sites: tuple[str, ...] = (),
) -> AtomComponentTemplate:
    """Compile an unconditional reference once, discard outcomes, relativize it.

    Optional stationary spectator homes constrain reference transport planning.
    Every later expansion checks the caller's complete world, including spectators.
    """
    if len(home_sites) != len(description.roles) or len(set(home_sites)) != len(
        home_sites
    ):
        raise ValueError("Reference homes must supply one distinct site per role.")
    timing = _timing(device)
    occupied_homes = home_sites + spectator_home_sites
    if len(set(occupied_homes)) != len(occupied_homes):
        raise ValueError("Reference spectator homes must be distinct and unoccupied.")
    dag = loads_qasm(source)
    if any(n.condition is not None for n in dag.nodes):
        raise ValueError("This adapter supports unconditional action templates only.")
    entry = AtomLayout(
        tuple(
            AtomState(i, device.site(s).position, SLMHolder(s))
            for i, s in enumerate(occupied_homes)
        ),
        qubit_to_atom=tuple(range(len(home_sites))),
    )
    assert device.readout is not None
    strategy = NonZonedStrategy(
        aod_id,
        GatePairCatalog.from_pair_arrays(device),
        max_measurements=device.readout.max_atoms,
    )
    result = compile_physical(dag, device, strategy=strategy, entry_state=entry)
    checked = validate_result(result, entry_state=entry, device=device, dag=dag)
    if not checked["ok"] or result.exit_state != entry:
        raise ValueError(f"Reference compilation failed: {checked}")
    measurements = sorted(
        (n for n in dag.nodes if n.result is not None), key=lambda n: n.clbits
    )
    if len(measurements) != len(description.measurements) or len(
        expected_values
    ) != len(measurements):
        raise ValueError("Source measurements disagree with component ports.")
    ids = {
        n.result.measurement_id: i
        for i, n in enumerate(measurements)
        if n.result is not None
    }
    available = {
        m.result.measurement_id: m.available_at_us for m in result.measurements
    }
    used_sites = set(home_sites)
    for step in result.program.steps:
        for action in step.actions:
            if isinstance(action, Store):
                used_sites.update(s for _, s in action.bindings)
    shift = Position(-origin.x, -origin.y)
    relative = rebind_program(
        result.program,
        shift=shift,
        atoms={i: i for i in range(len(home_sites))},
        sites={s: s for s in used_sites},
        channels={"local": "local", "cz": "cz", "readout": "readout"},
        aod_id="component_aod",
        results=ids,
    )
    local_dag = replace(
        dag,
        nodes=tuple(
            replace(n, source_id=ids[n.result.measurement_id])
            if n.result is not None
            else n
            for n in dag.nodes
        ),
    )
    assert compiler_module.__file__ is not None
    compiler_root = Path(compiler_module.__file__).parent
    compiler_hash = canonical_hash(
        {
            str(p.relative_to(compiler_root)): sha256(p.read_bytes()).hexdigest()
            for p in sorted(compiler_root.rglob("*.py"))
        }
    )
    return AtomComponentTemplate(
        description,
        source,
        relative,
        local_dag,
        result.operations,
        tuple(
            (s, shift_position(device.site(s).position, shift))
            for s in sorted(used_sites)
        ),
        home_sites,
        timing,
        tuple(
            available[n.result.measurement_id]
            for n in measurements
            if n.result is not None
        ),
        tuple(n.qubits[0] for n in measurements),
        expected_values,
        corrections,
        sha256(source.encode()).hexdigest(),
        canonical_hash(encode_device(device)),
        compiler_hash,
        tuple(checked.get("checks", ())),
    )
