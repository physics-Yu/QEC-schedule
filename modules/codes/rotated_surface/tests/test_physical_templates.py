"""Reusable atom contracts at larger distance, including spectator occupancy."""

from dataclasses import replace

import pytest
import stim

from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface import (
    DirectRawTPostselection as RawTPostselection,
)
from modules.codes.rotated_surface import (
    TransversalCNOTComponent,
    definition,
    get_component,
)
from modules.codes.rotated_surface.measurement import read_ideal_observable
from modules.codes.rotated_surface.raw_t_postselection import RawTPostselectionTemplate
from modules.codes.rotated_surface.tests.test_distance_components import (
    circuit,
    pauli,
    prepared,
)
from modules.codes.rotated_surface_d3.components.transversal import (
    TransversalCNOTComponent as D3CNOT,
)
from modules.codes.rotated_surface_d3.tests.quantum_checks import action_stim, unitary


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_transversal_clifford_action(distance):
    code = definition(distance)
    component = TransversalCNOTComponent(distance)
    source = circuit(component.source_qasm)
    unitary = source.to_tableau()
    n = code.atom_count
    for axis, support in (("X", code.logical_x), ("Z", code.logical_z), *code.checks):
        control = stim.PauliString(2 * n)
        target = stim.PauliString(2 * n)
        for q in support:
            control[q] = target[n + q] = axis
        assert unitary(control) == (control * target if axis == "X" else control)
        assert unitary(target) == (control * target if axis == "Z" else target)
    if distance == 3:
        assert component.source_qasm == D3CNOT().source_qasm


@pytest.fixture(scope="module", params=(5, 7))
def world(request):
    return build_world(ExperimentSpec(distance=request.param))


@pytest.mark.parametrize(
    "name",
    (
        "initialize_0",
        "initialize_plus",
        "se_round",
        "logical_s",
        "logical_sdag",
        "prepare_y",
        "raw_t",
        "logical_mx",
        "logical_mz",
    ),
)
def test_single_block_compile_bind_complete_world_and_pending_results(world, name):
    patch = world.patch(0, "W1")
    component = get_component(name, world.spec.distance)
    template = component.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    expanded = template.bind(patch.binding).expand(
        InvocationContext(name, 0, 100, world.device, world.state)
    )
    assert expanded.exit_state == world.state
    assert all(m.value is None for m in expanded.measurements)
    assert len(expanded.measurements) == len(component.description.measurements)
    assert expanded.action_end_us > 0
    assert expanded.validation_checks
    assert expanded.output_syndrome_parities == component.output_syndrome_parities
    if name != "raw_t":
        actual, _ = action_stim(expanded, world.device)
        expected = circuit(component.source_qasm)
        actual.append("I", [definition(world.spec.distance).atom_count - 1])
        assert unitary(actual) == unitary(expected)
    if name in ("logical_mx", "logical_mz"):
        assert (
            read_ideal_observable(
                expanded, distance=world.spec.distance, at_us=expanded.results_ready_us
            ).value
            is None
        )
        values = {
            m.result.measurement_id: int(
                m.port == component.measurement_spec.logical_parity_ports[0]
            )
            for m in expanded.measurements
        }
        received = expanded.with_results(values)
        assert (
            read_ideal_observable(
                received, distance=world.spec.distance, at_us=received.results_ready_us
            ).value
            == 1
        )
        with pytest.raises(ValueError, match="contract"):
            read_ideal_observable(
                received,
                distance=world.spec.distance + 2,
                at_us=received.results_ready_us,
            )


def test_transversal_joint_template_and_participant_exits(world):
    control, target = world.patch(0, "W1"), world.patch(0, "R")
    component = TransversalCNOTComponent(world.spec.distance)
    template = component.compile(
        world.device,
        control_home_sites=control.home_sites,
        target_home_sites=target.home_sites,
        control_origin=control.binding.origin,
        target_origin=target.binding.origin,
        aod_id=control.binding.aod_id,
    )
    expanded = template.bind(control.binding, target.binding).expand(
        InvocationContext("joint", 0, 0, world.device, world.state)
    )
    assert expanded.exit_state == world.state
    assert expanded.exit_binding is None
    assert expanded.exit_participant_bindings == (control.binding, target.binding)
    assert (
        len(expanded.output_syndrome_parities)
        == 2 * definition(world.spec.distance).check_count
    )


def test_repeated_raw_t_postselection_identity_and_detector_boundaries(world):
    distance = world.spec.distance
    patch = world.patch(0, "R")
    protocol = RawTPostselection(
        distance, extra_rounds=1, round_policy="explicit_control"
    )
    template = protocol.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    with pytest.raises(ValueError, match="same code"):
        RawTPostselectionTemplate(
            template.raw_t,
            replace(
                template.se_round,
                description=replace(template.se_round.description, code_id="different"),
            ),
        )
    sequence = template.bind(patch.binding).expand(
        InvocationContext("raw-resource", 0, 100, world.device, world.state)
    )
    assert sequence.exit_state == world.state
    assert sequence.acceptance_status == "pending"
    assert not sequence.ready_for_use(sequence.results_ready_us)
    count = definition(distance).check_count
    assert len({m.result.measurement_id for m in sequence.measurements}) == 2 * count
    assert (
        len(sequence.detectors)
        == len(get_component("raw_t_direct_control", distance).acceptance_ports) + count
    )
    # Receive an explicit consistent branch with a nonzero nondeterministic bit.
    values = {m.result.measurement_id: 0 for m in sequence.measurements}
    random_port = next(
        p
        for p in definition(distance).check_roles
        if p not in get_component("raw_t_direct_control", distance).acceptance_ports
    )
    for part in sequence.parts:
        values[
            next(
                m.result.measurement_id
                for m in part.measurements
                if m.port == random_port
            )
        ] = 1
    accepted = sequence.with_results(values)
    assert accepted.acceptance_status == "accepted"
    assert accepted.ready_for_use(accepted.results_ready_us)
    assert not accepted.ready_for_use(accepted.results_ready_us - 1)
    later = next(m for m in sequence.parts[1].measurements if m.port == random_port)
    values[later.result.measurement_id] ^= 1
    assert sequence.with_results(values).acceptance_status == "rejected"


def test_hadamard_real_carrier_rotation_and_logical_action(world):
    code = definition(world.spec.distance)
    patch = world.patch(0, "W1")
    component = get_component("logical_h", world.spec.distance)
    template = component.compile(
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    expanded = template.bind(patch.binding).expand(
        InvocationContext("physical-h", 0, 0, world.device, world.state)
    )
    assert expanded.exit_binding is not None
    assert expanded.exit_binding.atom_ids != patch.binding.atom_ids
    assert expanded.exit_state != world.state
    inverse = template.exit_role_permutation
    for q, old in enumerate(inverse):
        assert expanded.exit_binding.atom_ids[q] == patch.binding.atom_ids[old]
        atom = expanded.exit_state.atom(patch.binding.atom_ids[old])
        assert atom.position == world.device.site(patch.home_sites[q]).position
    actual, _ = action_stim(expanded, world.device)
    actual.append("I", [code.atom_count - 1])
    assert unitary(actual) == unitary(circuit(component.source_qasm))
    for basis, support, output_basis, output_support in (
        ("X", code.logical_x, "Z", code.logical_z),
        ("Z", code.logical_z, "X", code.logical_x),
    ):
        sim = prepared(code, pauli(code, basis, support), (0,) * code.check_count)
        sim.do(actual)
        assert (
            sim.peek_observable_expectation(
                pauli(code, output_basis, tuple(inverse[q] for q in output_support))
            )
            == 1
        )
        for b, qs in code.checks:
            assert (
                sim.peek_observable_expectation(
                    pauli(code, b, tuple(inverse[q] for q in qs))
                )
                == 1
            )
    with pytest.raises(ValueError, match="outside"):
        component.compile(
            world.device,
            home_sites=patch.home_sites,
            origin=patch.binding.origin,
            aod_id=patch.binding.aod_id,
            buffer_site=patch.home_sites[0],
        )
