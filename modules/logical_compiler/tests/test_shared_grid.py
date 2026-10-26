"""Shared-AOD lowering preserves complete component trajectories and clocks."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Load, Move, Store
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_program

from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorldConfig,
    make_factory_world,
)
from modules.logical_compiler.src.protocols.parallel_physical import (
    PhysicalBatchRequest,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


def _wave(component_id, *, mixed=False):
    config = FactoryWorldConfig(
        aod_ids=("one", "two") if mixed else ("one",),
        role_aod_ids=(("W4", "two"), ("W5", "two")) if mixed else (),
    )
    world = make_factory_world(config)
    backend = SurfaceFactoryBackend(world.device)
    context = PhysicalContext(world.device, world.world_state, world.bindings.values())
    scheduler = ComponentScheduler(mode="parallel")
    participants = tuple(world.bindings[key] for key in ("W2", "W3", "W4", "W5"))
    scheduler.add(
        *(
            ComponentNode(
                f"member-{i}", backend.describe_execution(component_id, (binding,))
            )
            for i, binding in enumerate(participants)
        )
    )
    admission = scheduler.admit(0, snapshot_id=context.snapshot_id)
    assert admission is not None and len(admission.nodes) == 4
    requests = tuple(
        PhysicalBatchRequest(
            node.id,
            backend.bind_call(component_id, (binding,)),
            node.spec.result_count,
        )
        for node, binding in zip(admission.nodes, participants, strict=True)
    )
    return context, admission, requests


@pytest.mark.parametrize(
    "component_id",
    [
        "se_round",
        "logical_s",
        "raw_t",
        "raw_t_postselection",
        "initialize_0",
        "initialize_plus",
    ],
)
def test_four_real_components_share_one_grid_without_retiming(component_id):
    context, admission, requests = _wave(component_id)
    assert len(context._device.aods) == 1
    entry = context.world
    batch = context.invoke_batch(admission, requests)
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert bundle.world == entry
    assert all(item.value is None for item in bundle.pending_measurements)
    assert len({m.result.measurement_id for m in bundle.pending_measurements}) == sum(
        request.result_count for request in requests
    )
    proof = batch.to_dict()
    assert proof["mode"] == "shared_aod_lockstep"
    global_columns = []
    for member, (_, parts) in zip(proof["members"], batch.member_parts, strict=True):
        mapping = member["shared_aod_mapping"]
        assert mapping["row_ids_unchanged"] is True
        global_columns.extend(global_id for _, global_id in mapping["column_id_map"])
        assert parts[-1].action_end_us == batch.action_end_us
        assert max(part.results_ready_us for part in parts) == batch.results_ready_us
        assert context.source(member["invocation_id"]) is batch.source(
            member["invocation_id"]
        )
        for record in member["steps"]:
            assert record["batch_action_indices"] == sorted(
                {item["batch_action_index"] for item in record["action_embeddings"]}
            )
    assert len(global_columns) == len(set(global_columns))
    assert sorted(global_columns) == list(range(len(global_columns)))
    transports = [
        action
        for step in batch.program.steps
        for action in step.actions
        if isinstance(action, Load | Move | Store)
    ]
    assert max(len(action.grid.rows) for action in transports) == 4
    assert max(len(action.grid.columns) for action in transports) == 16
    for step in batch.program.steps:
        assert (
            sum(isinstance(action, Load | Move | Store) for action in step.actions) <= 1
        )
    if component_id == "se_round":
        assert batch.action_end_us == 658.8174904678644
        assert batch.results_ready_us == 1058.8174904678644
    elif component_id == "logical_s":
        assert batch.action_end_us == 998.291396637524
    elif component_id == "raw_t_postselection":
        assert batch.action_end_us == 1325.6349809357291


def test_shared_mode_can_fuse_two_independent_aod_groups():
    context, admission, requests = _wave("se_round", mixed=True)
    batch = context.invoke_batch(admission, requests)
    assert context.finalize().validation["ok"] is True
    transport_steps = [
        [action for action in step.actions if isinstance(action, Load | Move | Store)]
        for step in batch.program.steps
    ]
    assert max(map(len, transport_steps)) == 2
    assert (
        max(len(action.grid.columns) for step in transport_steps for action in step)
        == 8
    )


def test_actual_row_identity_conflict_is_atomic():
    context, admission, requests = _wave("se_round")
    original = requests[1].bound

    def different_rows(invocation):
        part = original.expand(invocation)
        steps = []
        for step in part.program.steps:
            actions = []
            for action in step.actions:
                if isinstance(action, Load | Move | Store):
                    action = replace(
                        action,
                        grid=replace(
                            action.grid,
                            rows=tuple(
                                replace(row, id=row.id + 50) for row in action.grid.rows
                            ),
                        ),
                    )
                    if isinstance(action, Load):
                        action = replace(
                            action,
                            bindings=tuple(
                                (atom, row + 50, col)
                                for atom, row, col in action.bindings
                            ),
                        )
                actions.append(action)
            steps.append(AtomStep(tuple(actions)))
        program = replace(part.program, steps=tuple(steps))
        return replace(
            part,
            program=program,
            template_content_sha256=canonical_hash(encode_program(program)),
        )

    requests = (requests[0], replace(requests[1], bound=different_rows), *requests[2:])
    before = context.snapshot_id
    with pytest.raises(ValueError, match="SHARED_AOD_ROW"):
        context.invoke_batch(admission, requests)
    assert context.snapshot_id == before
    assert context.invocations == ()
    assert context.next_result_id == 0


def test_shared_action_contribution_hash_uses_original_local_column_ids():
    context, admission, requests = _wave("se_round")
    batch = context.invoke_batch(admission, requests)
    proof = batch.to_dict()
    member = proof["members"][1]
    parts = batch.member_parts[1][1]
    part_by_id = {part.invocation_id: part for part in parts}
    for record in member["steps"]:
        source = part_by_id[record["part_invocation_id"]].program.steps[
            record["local_step_index"]
        ]
        for mapping in record["action_embeddings"]:
            original = replace(
                source.actions[mapping["source_action_index"]],
                source_ids=tuple(mapping["component_source_ids"]),
            )
            assert mapping["component_action_sha256"] == canonical_hash(
                encode_program(AtomProgram((AtomStep((original,)),)))
            )


def test_sparse_member_column_ids_use_a_compact_stable_mapping():
    context, admission, requests = _wave("se_round")
    original = requests[1].bound

    def sparse_columns(invocation):
        part = original.expand(invocation)
        steps = []
        for step in part.program.steps:
            actions = []
            for action in step.actions:
                if isinstance(action, Load | Move | Store):
                    action = replace(
                        action,
                        grid=replace(
                            action.grid,
                            columns=tuple(
                                replace(column, id=1009 + 37 * column.id)
                                for column in action.grid.columns
                            ),
                        ),
                    )
                    if isinstance(action, Load):
                        action = replace(
                            action,
                            bindings=tuple(
                                (atom, row, 1009 + 37 * col)
                                for atom, row, col in action.bindings
                            ),
                        )
                actions.append(action)
            steps.append(AtomStep(tuple(actions)))
        program = replace(part.program, steps=tuple(steps))
        return replace(
            part,
            program=program,
            template_content_sha256=canonical_hash(encode_program(program)),
        )

    requests = (requests[0], replace(requests[1], bound=sparse_columns), *requests[2:])
    batch = context.invoke_batch(admission, requests)
    assert context.finalize().validation["ok"] is True
    mappings = [
        member["shared_aod_mapping"]["column_id_map"]
        for member in batch.to_dict()["members"]
    ]
    assert min(local for local, _ in mappings[1]) >= 1009
    ids = [global_id for mapping in mappings for _, global_id in mapping]
    assert sorted(ids) == list(range(len(ids)))
