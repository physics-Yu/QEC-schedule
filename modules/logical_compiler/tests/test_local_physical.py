"""Real selected Pauli templates composed as local, zero-AOD batches.

These tests enumerate template classes, not sampled syndromes or a quantum
factory yield. Decision/source validation remains owned by canonicalization.
"""

from dataclasses import replace
from math import pi

import pytest
from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Rotation
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_program

from modules.codes._support.atom_template import compile_template
from modules.codes.rotated_surface_d3.components.canonicalization import (
    PreparationCanonicalization,
)
from modules.codes.rotated_surface_d3.definition import ROLES
from modules.codes.rotated_surface_d3.probabilities.preparation import preparation_port
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import make_factory_world
from modules.logical_compiler.src.protocols.parallel_physical import (
    PhysicalBatchRequest,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


@pytest.fixture(scope="module")
def correction_templates():
    world = make_factory_world()
    first = world.patch("W1")
    templates = {
        name: PreparationCanonicalization(name)
        .compile(
            world.device,
            probability_port=preparation_port(name),
            home_sites=first.home_sites,
            origin=first.binding.origin,
            aod_id=first.binding.aod_id,
        )
        .templates
        for name in ("initialize_0", "initialize_plus", "raw_t_postselection")
    }
    return world, SurfaceFactoryBackend(world.device), templates


def _requests(context, backend, templates, selections):
    scheduler = ComponentScheduler()
    requests = []
    for index, (binding, preparation, value) in enumerate(selections):
        identity = f"correction-{index}"
        spec = backend.describe_execution(preparation + "/canonicalize", (binding,))
        assert spec.parallel_mode == "local_parallel"
        assert spec.shared_aod is None and spec.exclusive_resources == ()
        scheduler.add(ComponentNode(identity, spec))
        requests.append(
            PhysicalBatchRequest(
                identity, templates[preparation][value].bind(binding), 0
            )
        )
    admission = scheduler.admit(context.clock_us, snapshot_id=context.snapshot_id)
    assert admission is not None and len(admission.nodes) == len(selections)
    return admission, tuple(requests)


def test_real_mixed_corrections_keep_class_masks_times_phases_and_action_hashes(
    correction_templates,
):
    world, backend, templates = correction_templates
    context = PhysicalContext(world.device, world.world_state, world.bindings.values())
    context.wait_until(7000.125, reason="test_fixture template start")
    selections = (
        (world.bindings["W1"], "raw_t_postselection", 0),
        (world.bindings["W2"], "raw_t_postselection", 1),
        (world.bindings["W3"], "raw_t_postselection", 5),
        (world.bindings["W4"], "initialize_plus", 15),
    )
    admission, requests = _requests(context, backend, templates, selections)
    batch = context.invoke_batch(admission, requests)
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert batch.world == world.world_state
    assert batch.start_us == 7000.125 and batch.action_end_us == 7002.125
    assert [record.action_end_us for record in batch.invocations] == [
        7000.125,
        7001.125,
        7002.125,
        7001.125,
    ]
    assert context.next_result_id == 0 and bundle.pending_measurements == ()
    assert len(batch.program.steps) == 2
    assert sum(len(step.actions) for step in batch.program.steps) == 7
    assert all(
        isinstance(action, Rotation)
        for step in batch.program.steps
        for action in step.actions
    )
    assert batch.program.global_phase == sum(
        parts[0].program.global_phase for _, parts in batch.member_parts
    )
    assert batch.dag.global_phase == sum(
        parts[0].dag.global_phase for _, parts in batch.member_parts
    )
    raw_two = batch.source("correction-2")
    expected = {
        (world.bindings["W3"].atom_ids[ROLES.index("data[2]")], "Z", pi),
        (world.bindings["W3"].atom_ids[ROLES.index("data[0]")], "X", pi),
    }
    assert {
        (atom, action.axis, action.angle)
        for step in raw_two.program.steps
        for action in step.actions
        for atom in action.atoms
    } == expected
    proof = batch.to_dict()
    assert proof["mode"] == "local_parallel"
    assert proof["members"][0]["steps"] == []
    for member, (_, parts) in zip(proof["members"], batch.member_parts, strict=True):
        assert member["aod_ids"] == []
        source = parts[0]
        for record in member["steps"]:
            original = source.program.steps[record["local_step_index"]]
            merged = batch.program.steps[record["batch_step_index"]]
            for mapping in record["action_embeddings"]:
                action = replace(
                    original.actions[mapping["source_action_index"]],
                    source_ids=tuple(mapping["component_source_ids"]),
                )
                assert merged.actions[mapping["batch_action_index"]] == action
                assert mapping["component_action_sha256"] == canonical_hash(
                    encode_program(AtomProgram((AtomStep((action,)),)))
                )


def test_all_identity_batch_keeps_calls_without_breaking_later_dag_dependencies(
    correction_templates,
):
    world, backend, templates = correction_templates
    context = PhysicalContext(world.device, world.world_state, world.bindings.values())
    first_binding = world.bindings["W1"]
    before = context.invoke(
        backend.bind_call("logical_x", (first_binding,)), "before", 0
    )[0]
    at = context.clock_us
    selections = (
        (first_binding, "initialize_0", 0),
        (world.bindings["W2"], "raw_t_postselection", 0),
    )
    admission, requests = _requests(context, backend, templates, selections)
    batch = context.invoke_batch(admission, requests)
    assert batch.program.steps == ()
    assert batch.action_end_us == batch.start_us == context.clock_us == at
    assert len(batch.invocations) == 2
    assert all(
        context.source(request.invocation_id).program.steps == ()
        for request in requests
    )
    after = context.invoke(
        backend.bind_call("logical_z", (first_binding,)), "after", 0
    )[0]
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert len(context.invocations) == 4
    first_nodes = set(range(len(before.dag.nodes)))
    last_nodes = set(
        range(len(before.dag.nodes), len(before.dag.nodes) + len(after.dag.nodes))
    )
    assert first_nodes and last_nodes
    assert {(left, right) for left in first_nodes for right in last_nodes} <= set(
        bundle.dag.edges
    )
    assert len(bundle.program.steps) == len(before.program.steps) + len(
        after.program.steps
    )


def test_claimed_local_correction_cannot_smuggle_reset_and_commit_partial_source(
    correction_templates,
):
    world, backend, templates = correction_templates
    context = PhysicalContext(world.device, world.world_state, world.bindings.values())
    selections = (
        (world.bindings["W1"], "raw_t_postselection", 5),
        (world.bindings["W2"], "initialize_0", 1),
    )
    admission, requests = _requests(context, backend, templates, selections)
    patch = world.patch("W1")
    forged = compile_template(
        replace(
            templates["initialize_0"][0].description,
            component_id="test_fixture.forged_reset",
        ),
        'OPENQASM 3.0; include "stdgates.inc"; qubit[17] q; reset q[0];',
        world.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
        expected_values=(),
        corrections=(),
    )
    requests = (
        requests[0],
        replace(requests[1], bound=forged.bind(world.bindings["W2"])),
    )
    before = context.snapshot_id
    with pytest.raises(ValueError, match="LOCAL_BATCH_UNSUPPORTED_ACTION"):
        context.invoke_batch(admission, requests)
    assert context.snapshot_id == before and context.invocations == ()
    assert context.clock_us == 0 and context.next_result_id == 0
    for request in requests:
        with pytest.raises(KeyError):
            context.source(request.invocation_id)
