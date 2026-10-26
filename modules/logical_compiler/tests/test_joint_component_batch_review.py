"""Independent public-interface checks for joint and measurement component waves.

These tests validate actual component composition and unobserved measurement
identities. They do not simulate logical quantum states or estimate fidelity.
"""

from dataclasses import replace

import pytest
import test_local_physical as local_tests
from nadit_physical_compiler.atom_ir import Load, Move, Store

from modules.codes.rotated_surface_d3.protocols.factory_array import make_factory_array
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.logical_compiler.src.protocols.parallel_physical import (
    PhysicalBatchRequest,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler

correction_templates = local_tests.correction_templates


@pytest.fixture(scope="module")
def array_backend():
    array = make_factory_array()
    return array, SurfaceFactoryBackend(array.device)


def _context(array):
    return PhysicalContext(array.device, array.world_state, array.bindings.values())


def _wave(array_backend, name, *, context=None, role="W1"):
    array, backend = array_backend
    context = context or _context(array)
    participants = tuple(
        tuple(
            context.bindings[placement.bindings[key].block_id]
            for key in (("W1", "W2") if name == "transversal_cnot" else (role,))
        )
        for placement in array.factories
    )
    scheduler = ComponentScheduler()
    scheduler.add(
        *(
            ComponentNode(
                f"review/{name}/{index}", backend.describe_execution(name, bindings)
            )
            for index, bindings in enumerate(participants)
        )
    )
    admission = scheduler.admit(context.clock_us, snapshot_id=context.snapshot_id)
    assert admission is not None and len(admission.nodes) == 2
    requests = tuple(
        PhysicalBatchRequest(
            node.id, backend.bind_call(name, bindings), node.spec.result_count
        )
        for node, bindings in zip(admission.nodes, participants, strict=True)
    )
    return context, admission, requests, participants


def test_real_corresponding_cnot_pairs_share_one_aod_and_preserve_both_exits(
    array_backend,
):
    array, _ = array_backend
    context, admission, requests, participants = _wave(
        array_backend, "transversal_cnot"
    )
    assert len(array.device.aods) == 1
    assert all(len(node.spec.participant_blocks) == 2 for node in admission.nodes)
    before = dict(context.bindings)
    batch = context.invoke_batch(admission, requests)
    bundle = context.finalize()

    assert bundle.validation["ok"] is True
    assert bundle.world == array.world_state
    assert dict(context.bindings) == before
    assert context.next_result_id == 0 and bundle.pending_measurements == ()
    proof = batch.to_dict()
    assert proof["mode"] == "shared_aod_lockstep"
    all_claimed = set()
    for member, (identity, parts), bindings in zip(
        proof["members"], batch.member_parts, participants, strict=True
    ):
        expected_atoms = {atom for binding in bindings for atom in binding.atom_ids}
        assert len(expected_atoms) == 34
        assert not all_claimed.intersection(expected_atoms)
        all_claimed.update(expected_atoms)
        assert set(member["participant_atoms"]) == expected_atoms
        assert member["invocation_id"] == identity
        assert parts[0].participant_bindings == bindings
        assert parts[-1].exit_participant_bindings == bindings
        assert parts[0].start_us == batch.start_us
        assert parts[-1].action_end_us == batch.action_end_us
        assert member["shared_aod_mapping"]["row_ids_unchanged"] is True
    assert len(all_claimed) == 68
    transports = [
        action
        for step in batch.program.steps
        for action in step.actions
        if isinstance(action, Load | Move | Store)
    ]
    assert transports
    assert {action.grid.aod_id for action in transports} == {array.device.aods[0].id}
    assert all(
        sum(isinstance(action, Load | Move | Store) for action in step.actions) <= 1
        for step in batch.program.steps
    )


@pytest.mark.parametrize(
    "malformation", ["missing_exit", "foreign_exit", "missing_entry", "foreign_entry"]
)
def test_malformed_second_joint_member_rolls_back_the_whole_wave(
    array_backend, malformation
):
    array, _ = array_backend
    context, admission, requests, _ = _wave(array_backend, "transversal_cnot")
    original = requests[1].bound
    foreign = array.factories[1].bindings["R"]

    def malformed(invocation):
        part = original.expand(invocation)
        if malformation == "missing_exit":
            return replace(
                part, exit_participant_bindings=part.exit_participant_bindings[:1]
            )
        if malformation == "foreign_exit":
            return replace(
                part,
                exit_participant_bindings=(*part.exit_participant_bindings, foreign),
            )
        if malformation == "missing_entry":
            return replace(part, participant_bindings=part.participant_bindings[:1])
        return replace(part, participant_bindings=(*part.participant_bindings, foreign))

    changed = (requests[0], replace(requests[1], bound=malformed))
    before = context.snapshot_id
    with pytest.raises(ValueError):
        context.invoke_batch(admission, changed)
    assert context.snapshot_id == before
    assert context.invocations == ()
    assert context.next_result_id == 0
    assert context.world == array.world_state


@pytest.mark.parametrize("name", ["logical_mx", "logical_mz"])
def test_real_measurement_wave_has_disjoint_unobserved_result_ranges(
    array_backend, name
):
    context, admission, requests, participants = _wave(array_backend, name)
    assert [node.spec.result_count for node in admission.nodes] == [9, 9]
    batch = context.invoke_batch(admission, requests)
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert context.next_result_id == 18
    assert len(bundle.pending_measurements) == 18
    assert {item.result.measurement_id for item in bundle.pending_measurements} == set(
        range(18)
    )
    assert all(item.value is None for item in bundle.pending_measurements)
    for index, ((identity, parts), bindings) in enumerate(
        zip(batch.member_parts, participants, strict=True)
    ):
        measurements = [
            measurement for part in parts for measurement in part.measurements
        ]
        assert len(measurements) == 9
        assert {m.result.measurement_id for m in measurements} == set(
            range(9 * index, 9 * (index + 1))
        )
        assert all(m.value is None for m in measurements)
        assert all(part.block_id == bindings[0].block_id for part in parts)
        assert parts[-1].exit_binding == bindings[0]
        assert max(m.available_at_us for m in measurements) == batch.results_ready_us
        assert context.source(identity) is batch.source(identity)
    assert batch.results_ready_us > batch.action_end_us


def test_real_successive_measurement_waves_do_not_reuse_global_result_ids(
    array_backend,
):
    context, admission, requests, _ = _wave(array_backend, "logical_mx")
    first = context.invoke_batch(admission, requests)
    context, admission, requests, _ = _wave(
        array_backend, "logical_mz", context=context, role="W2"
    )
    second = context.invoke_batch(admission, requests)
    assert second.start_us >= first.action_end_us
    assert context.next_result_id == 36
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert {m.result.measurement_id for m in bundle.pending_measurements} == set(
        range(36)
    )
    second_ids = {
        m.result.measurement_id
        for _, parts in second.member_parts
        for part in parts
        for m in part.measurements
    }
    assert second_ids == set(range(18, 36))
    assert all(m.value is None for m in bundle.pending_measurements)


def test_mixed_measurement_basis_is_not_one_declared_wave(array_backend):
    array, backend = array_backend
    scheduler = ComponentScheduler()
    scheduler.add(
        ComponentNode(
            "x",
            backend.describe_execution(
                "logical_mx", (array.factory(0).bindings["W1"],)
            ),
        ),
        ComponentNode(
            "z",
            backend.describe_execution(
                "logical_mz", (array.factory(1).bindings["W1"],)
            ),
        ),
    )
    admission = scheduler.admit(0, snapshot_id="declaration-only")
    assert admission.node_ids == ("x",)


def test_local_wave_cannot_redirect_a_valid_correction_to_an_undeclared_patch(
    correction_templates,
):
    world, backend, templates = correction_templates
    context = PhysicalContext(world.device, world.world_state, world.bindings.values())
    selections = (
        (world.bindings["W1"], "raw_t_postselection", 5),
        (world.bindings["W2"], "initialize_plus", 1),
    )
    admission, requests = local_tests._requests(context, backend, templates, selections)
    # The pulse template and foreign binding are individually valid. The failure
    # must come from ownership of this already admitted wave, not malformed gates.
    foreign = templates["initialize_plus"][1].bind(world.bindings["W3"])
    changed = (requests[0], replace(requests[1], bound=foreign))
    before = context.snapshot_id
    with pytest.raises(ValueError):
        context.invoke_batch(admission, changed)
    assert context.snapshot_id == before
    assert context.world == world.world_state
    assert context.invocations == () and context.next_result_id == 0
    for request in requests:
        with pytest.raises(KeyError):
            context.source(request.invocation_id)
