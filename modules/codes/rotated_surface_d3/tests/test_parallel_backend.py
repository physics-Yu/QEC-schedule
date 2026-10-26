"""Verify actual merged raw lanes without importing the logical compiler."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    Load,
    Measure,
    Move,
    Rotation,
    Store,
)
from nadit_physical_compiler.compiler import CompilationResult, MeasurementRecord
from nadit_physical_compiler.physical_ir import PhysicalDAG, ResultRef
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.serialization import (
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.validation import validate_result

from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface_d3.protocols.cost_proxy import (
    SurfaceCostProxyBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorldConfig,
    make_factory_world,
)
from modules.codes.rotated_surface_d3.protocols.parallel_backend import (
    SurfaceParallelCostBackend,
)


def projection(world, atoms, aods):
    return {
        "atoms": [asdict(world.atom(a)) for a in sorted(atoms)],
        "aod_grids": [asdict(world.grid(a)) for a in sorted(aods)],
    }


def _fused_step(lane_steps, maps):
    actions, embeddings, transport = [], [], {}
    for step, mapping in zip(lane_steps, maps, strict=True):
        records = []
        for local, original in enumerate(step.actions):
            action = original
            if isinstance(action, Load | Move | Store):
                grid = replace(
                    action.grid,
                    columns=tuple(
                        replace(line, id=mapping[line.id])
                        for line in action.grid.columns
                    ),
                )
                action = replace(action, grid=grid)
                if isinstance(action, Load):
                    action = replace(
                        action,
                        bindings=tuple(
                            (atom, row, mapping[column])
                            for atom, row, column in action.bindings
                        ),
                    )
                key = (type(action), action.grid.aod_id)
                if key in transport:
                    index = transport[key]
                    before = actions[index]
                    assert before.grid.rows == action.grid.rows
                    grid = replace(
                        before.grid, columns=before.grid.columns + action.grid.columns
                    )
                    updates = {
                        "grid": grid,
                        "source_ids": before.source_ids + action.source_ids,
                    }
                    updates["targets" if isinstance(action, Move) else "bindings"] = (
                        before.targets + action.targets
                        if isinstance(action, Move)
                        else before.bindings + action.bindings
                    )
                    actions[index] = replace(before, **updates)
                else:
                    index = len(actions)
                    transport[key] = index
                    actions.append(action)
            else:
                index = len(actions)
                actions.append(action)
            records.append(
                {
                    "source_action_index": local,
                    "batch_action_index": index,
                    "component_source_ids": list(original.source_ids),
                    "component_action_sha256": canonical_hash(
                        encode_program(AtomProgram((AtomStep((original,)),)))
                    ),
                }
            )
        embeddings.append(records)
    return AtomStep(tuple(actions)), embeddings


def build_batch_fixture(*, shared=False):
    """Compose two real sources and independently validate their merged Atom IR."""
    factory = make_factory_world(
        FactoryWorldConfig(
            aod_ids=("a", "b"), role_aod_ids=() if shared else (("W3", "b"),)
        )
    )
    backend = SurfaceParallelCostBackend(factory.device)
    sources = tuple(
        backend.bind_call("raw_t_postselection", (factory.bindings[role],)).expand(
            InvocationContext(
                f"fixture/{role}",
                1000,
                index * 100,
                factory.device,
                factory.world_state,
            )
        )
        for index, role in enumerate(("W2", "W3"))
    )
    # Normal d3 postselection contains raw-T's SE plus two additional rounds.
    # This fixture exercises the production policy, not the historical R=2 control.
    assert all(
        source.total_rounds == 3
        and source.round_policy == "distance"
        and len(source.measurements) == 24
        and len(source.detectors) == 20
        for source in sources
    )
    nodes, edges, operations, lanes, origins = [], [], [], [], []
    clbit_base = 0
    for source in sources:
        lane, provenance = [], []
        for part in source.parts:
            base = len(nodes)
            nodes.extend(
                replace(
                    node,
                    id=node.id + base,
                    qubits=tuple(
                        factory.world_state.qubit_to_atom.index(part.wire_atoms[q])
                        for q in node.qubits
                    ),
                    clbits=tuple(c + clbit_base for c in node.clbits),
                )
                for node in part.dag.nodes
            )
            edges.extend((a + base, b + base) for a, b in part.dag.edges)
            operations.extend(
                replace(
                    op,
                    operation_id=op.operation_id + base,
                    start_us=op.start_us + part.start_us - 1000,
                    end_us=op.end_us + part.start_us - 1000,
                )
                for op in part.operations
            )
            lane.extend(
                replace(
                    step,
                    actions=tuple(
                        replace(
                            action,
                            source_ids=tuple(i + base for i in action.source_ids),
                        )
                        for action in step.actions
                    ),
                )
                for step in part.program.steps
            )
            provenance.extend(
                (part.invocation_id, i) for i in range(len(part.program.steps))
            )
            clbit_base += part.dag.num_clbits
        lanes.append(lane)
        origins.append(provenance)
    world, clock, steps = factory.world_state, 1000.0, []
    embeddings = [[], []]
    maps = [
        {
            column: column + 100 * index
            for column in sorted(
                {
                    line.id
                    for step in lane
                    for action in step.actions
                    if isinstance(action, Load | Move | Store)
                    for line in action.grid.columns
                }
            )
        }
        for index, lane in enumerate(lanes)
    ]
    standalone = [world, world]
    for step_index, lane_steps in enumerate(zip(*lanes, strict=True)):
        merged = AtomStep(
            tuple(action for step in lane_steps for action in step.actions)
        )
        action_embeddings = None
        if shared:
            merged, action_embeddings = _fused_step(lane_steps, maps)
        after = apply_step(world, merged, factory.device)
        offset = 0
        for index, (source, step) in enumerate(zip(sources, lane_steps, strict=True)):
            atoms, aods = source.parts[0].wire_atoms, (source.exit_binding.aod_id,)
            part_id, local_step = origins[index][step_index]
            embeddings[index].append(
                {
                    "batch_step_index": step_index,
                    "part_invocation_id": part_id,
                    "local_step_index": local_step,
                    "start_us": clock,
                    "end_us": clock + step.duration_us,
                    "batch_action_indices": list(
                        range(offset, offset + len(step.actions))
                    ),
                    "participant_entry_sha256": canonical_hash(
                        projection(standalone[index] if shared else world, atoms, aods)
                    ),
                    "participant_exit_sha256": canonical_hash(
                        projection(
                            apply_step(standalone[index], step, factory.device)
                            if shared
                            else after,
                            atoms,
                            aods,
                        )
                    ),
                }
            )
            if shared:
                embeddings[index][-1]["action_embeddings"] = action_embeddings[index]
                embeddings[index][-1]["batch_action_indices"] = sorted(
                    {
                        record["batch_action_index"]
                        for record in action_embeddings[index]
                    }
                )
                standalone[index] = apply_step(standalone[index], step, factory.device)
            offset += len(step.actions)
        steps.append(merged)
        world, clock = after, clock + merged.duration_us
    program = AtomProgram(
        tuple(steps), sum(p.program.global_phase for s in sources for p in s.parts)
    )
    dag = PhysicalDAG(
        len(factory.world_state.atoms),
        clbit_base,
        tuple(nodes),
        tuple(edges),
        global_phase=program.global_phase,
    )
    validation = validate_result(
        CompilationResult(
            program,
            world,
            tuple(operations),
            tuple(
                MeasurementRecord(m.result, 0, m.available_at_us - 1000)
                for s in sources
                for m in s.measurements
            ),
            (),
        ),
        entry_state=factory.world_state,
        device=factory.device,
        dag=dag,
    )
    assert validation["ok"], validation
    evidence = {
        "schema": "nadit.physical_lockstep_batch/1",
        "batch_id": "fixture-wave",
        "entry_world_sha256": canonical_hash(encode_layout(factory.world_state)),
        "exit_world_sha256": canonical_hash(encode_layout(world)),
        "device_sha256": canonical_hash(encode_device(factory.device)),
        "start_us": 1000.0,
        "action_end_us": clock,
        "mode": "shared_aod_lockstep" if shared else "independent_aods_lockstep",
        "time_basis": "ordered_global_atom_steps",
        "program_sha256": canonical_hash(encode_program(program)),
        "participant_trajectory_projection_verified": True,
        "declared_space_envelopes_verified": True,
        "cross_patch_interaction_check": "physical_pulse_and_addressing_validation",
        "noise_factorization_claimed": False,
        "global_noise_coverage_claimed": False,
        "validation": validation,
        "members": [],
    }
    for index, (source, role) in enumerate(zip(sources, ("W2", "W3"), strict=True)):
        evidence["members"].append(
            {
                "invocation_id": f"fixture/{role}",
                "participant_atoms": sorted(source.parts[0].wire_atoms),
                "aod_ids": [source.exit_binding.aod_id],
                "result_id_base": index * 100,
                "result_count": 24,
                "execution_spec": backend.describe_execution(
                    "raw_t_postselection", (factory.bindings[role],)
                ).to_dict(),
                "steps": embeddings[index],
                "pending_measurements": [asdict(m) for m in source.measurements],
                "source_parts": [
                    {
                        "invocation_id": p.invocation_id,
                        "template_content_sha256": p.template_content_sha256,
                        "program_sha256": canonical_hash(encode_program(p.program)),
                        "standalone_entry_world_sha256": canonical_hash(
                            encode_layout(p.entry_state)
                        ),
                        "standalone_exit_world_sha256": canonical_hash(
                            encode_layout(p.exit_state)
                        ),
                        "start_us": p.start_us,
                        "action_end_us": p.action_end_us,
                        "results_ready_us": p.results_ready_us,
                    }
                    for p in source.parts
                ],
            }
        )
        member = evidence["members"][-1]
        if shared:
            member["shared_aod_mapping"] = {
                "aod_id": source.exit_binding.aod_id,
                "row_ids_unchanged": True,
                "column_id_map": [list(pair) for pair in maps[index].items()],
            }
        else:
            member["execution_spec"].update(
                parallel_mode="independent_aods_lockstep",
                shared_aod=None,
                exclusive_resources=[f"aod:{source.exit_binding.aod_id}"],
            )
    evidence["waveform_key"] = evidence["members"][0]["execution_spec"]["waveform_key"]
    return factory, backend, sources, program, evidence


@pytest.fixture(scope="module")
def batch_fixture():
    return build_batch_fixture()


@pytest.fixture(scope="module")
def shared_batch_fixture():
    return build_batch_fixture(shared=True)


def test_shared_actual_fusion_preserves_each_joint_marginal(shared_batch_fixture):
    factory, backend, sources, program, evidence = shared_batch_fixture
    params = {
        "noise_model": "noise/v1",
        "noise_params": {"readout_flip": 0.03, "exposure": {"aod_t2_us": 1e6}},
    }
    for source in sources:
        reference = SurfaceCostProxyBackend.preparation_event(
            backend, "raw_t_postselection", source, params
        )
        backend.register_parallel_source(
            source, program=program, entry_world=factory.world_state, evidence=evidence
        )
        actual = backend.preparation_event("raw_t_postselection", source, params)
        assert actual.to_dict()["outcomes"] == reference.to_dict()["outcomes"]
        proof = actual.to_dict()["model"]["evidence"]["parallel_schedule_embedding"]
        assert proof["mode"] == "shared_aod_lockstep"
        assert proof["fused_transport_components_verified"] is True


@pytest.mark.parametrize(
    "fault",
    [
        "column_collision",
        "column_wrong",
        "row_map",
        "component_hash",
        "component_ids",
        "missing_component",
        "actual_binding",
    ],
)
def test_shared_embedding_tampering_is_rejected(shared_batch_fixture, fault):
    factory, _, sources, program, original = shared_batch_fixture
    evidence = deepcopy(original)
    first = evidence["members"][0]
    if fault == "column_collision":
        evidence["members"][1]["shared_aod_mapping"]["column_id_map"][0][1] = first[
            "shared_aod_mapping"
        ]["column_id_map"][0][1]
    elif fault == "column_wrong":
        first["shared_aod_mapping"]["column_id_map"][0][1] = 999
    elif fault == "row_map":
        first["shared_aod_mapping"]["row_ids_unchanged"] = False
    elif fault == "component_hash":
        first["steps"][0]["action_embeddings"][0]["component_action_sha256"] = "f" * 64
    elif fault == "component_ids":
        first["steps"][0]["action_embeddings"][0]["component_source_ids"] = [9999]
    elif fault == "missing_component":
        first["steps"][0]["action_embeddings"].pop()
    else:
        steps = list(program.steps)
        i, j = next(
            (i, j)
            for i, step in enumerate(steps)
            for j, action in enumerate(step.actions)
            if isinstance(action, Load)
        )
        actions = list(steps[i].actions)
        load = actions[j]
        bindings = list(load.bindings)
        atom, row, _column = bindings[0]
        bindings[0] = (atom, row, 999)
        actions[j] = replace(load, bindings=tuple(bindings))
        steps[i] = replace(steps[i], actions=tuple(actions))
        program = replace(program, steps=tuple(steps))
        evidence["program_sha256"] = canonical_hash(encode_program(program))
    with pytest.raises(ValueError, match="PARALLEL"):
        SurfaceParallelCostBackend(factory.device).register_parallel_source(
            sources[0],
            program=program,
            entry_world=factory.world_state,
            evidence=evidence,
        )


def test_registered_source_keeps_joint_probabilities_and_quality_consistency(
    batch_fixture,
):
    factory, backend, sources, program, evidence = batch_fixture
    source = sources[0]
    params = {
        "noise_model": "noise/v1",
        "noise_params": {
            "readout_flip": 0.03,
            "transport": {"slm_loss_per_us": 0.00001},
        },
    }
    original = SurfaceCostProxyBackend.preparation_event(
        backend, "raw_t_postselection", source, params
    )
    backend.register_parallel_source(
        source, program=program, entry_world=factory.world_state, evidence=evidence
    )
    port = backend.preparation_event("raw_t_postselection", source, params)
    assert port.port_id == original.port_id
    assert port.to_dict()["outcomes"] == original.to_dict()["outcomes"]
    proof = port.to_dict()["model"]["evidence"]["parallel_schedule_embedding"]
    assert proof["actual_program_sha256"] == evidence["program_sha256"]
    assert proof["source_actions_and_times_verified"] is True
    assert proof["cross_patch_interactions_absent"] is True
    assert proof["global_noise_coverage_claimed"] is False
    loss = port.to_dict()["model"]["evidence"]["physical_loss"]
    assert loss["scope"] == "isolated_participant_projection_reference"
    assert {row["atom"] for row in loss["per_atom"]} == set(source.parts[0].wire_atoms)
    quality = backend.preparation_quality_from_event(
        "raw_t_postselection",
        source,
        port,
        dict(port.outcome("accepted_1").values),
        params,
    )
    assert quality["actual_quality"]["status"] == "unsupported"
    assert quality["actual_quality"]["source_port_sha256"] == port.content_sha256
    assert all(m.value is None for m in source.measurements)
    backend.register_parallel_source(
        source,
        program=program,
        entry_world=factory.world_state,
        evidence=deepcopy(evidence),
    )
    assert backend.preparation_event("raw_t_postselection", source, params) == port


@pytest.mark.parametrize(
    "fault",
    [
        "missing_steps",
        "time",
        "result",
        "angle",
        "trajectory",
        "unowned_action",
        "cross_patch_cz",
        "program_hash",
    ],
)
def test_inconsistent_actual_embedding_is_rejected(batch_fixture, fault):
    factory, _, sources, program, original = batch_fixture
    backend = SurfaceParallelCostBackend(factory.device)
    evidence = deepcopy(original)
    if fault == "missing_steps":
        evidence["members"][0]["steps"].pop()
    elif fault == "time":
        evidence["members"][0]["steps"][0]["start_us"] += 1
    elif fault == "trajectory":
        evidence["members"][0]["steps"][0]["participant_exit_sha256"] = "f" * 64
    elif fault == "program_hash":
        evidence["program_sha256"] = "f" * 64
    elif fault == "unowned_action":
        evidence["members"][1]["steps"][0]["batch_action_indices"] = []
    else:
        from nadit_physical_compiler.atom_ir import CZPulse
        from nadit_physical_compiler.device import Region

        kind = (
            Measure if fault == "result" else Rotation if fault == "angle" else CZPulse
        )
        steps = list(program.steps)
        step_index, action_index = next(
            (i, j)
            for i, step in enumerate(steps)
            for j, action in enumerate(step.actions)
            if isinstance(action, kind)
        )
        actions = list(steps[step_index].actions)
        action = actions[action_index]
        if fault == "result":
            actions[action_index] = replace(
                action,
                results=((action.results[0][0], ResultRef(9000)), *action.results[1:]),
            )
        elif fault == "angle":
            actions[action_index] = replace(action, angle=action.angle + 0.1)
        else:
            actions[action_index] = replace(action, coverage=Region(-5, -5, 565, 65))
        steps[step_index] = replace(steps[step_index], actions=tuple(actions))
        program = replace(program, steps=tuple(steps))
        evidence["program_sha256"] = canonical_hash(encode_program(program))
    with pytest.raises(ValueError, match="PARALLEL"):
        backend.register_parallel_source(
            sources[0],
            program=program,
            entry_world=factory.world_state,
            evidence=evidence,
        )


def test_nonzero_spectator_pauli_refuses_parallel_factorization(batch_fixture):
    factory, _, sources, program, evidence = batch_fixture
    backend = SurfaceParallelCostBackend(factory.device)
    backend.register_parallel_source(
        sources[0], program=program, entry_world=factory.world_state, evidence=evidence
    )
    with pytest.raises(ValueError, match="spectator"):
        backend.preparation_event(
            "raw_t_postselection",
            sources[0],
            {
                "noise_model": "noise/v1",
                "noise_params": {"spectator_pauli": [0.01, 0, 0]},
            },
        )


def test_registration_freezes_evidence_and_rejects_conflicting_rebinding(batch_fixture):
    factory, _, sources, program, original = batch_fixture
    backend = SurfaceParallelCostBackend(factory.device)
    evidence = deepcopy(original)
    backend.register_parallel_source(
        sources[0], program=program, entry_world=factory.world_state, evidence=evidence
    )
    evidence["batch_id"] = "different-wave"
    with pytest.raises(ValueError, match="CONFLICTING_PARALLEL_SOURCE"):
        backend.register_parallel_source(
            sources[0],
            program=program,
            entry_world=factory.world_state,
            evidence=evidence,
        )
    port = backend.preparation_event(
        "raw_t_postselection",
        sources[0],
        {"noise_model": "noise/v1", "noise_params": {}},
    )
    assert (
        port.to_dict()["model"]["evidence"]["parallel_schedule_embedding"]["batch_id"]
        == "fixture-wave"
    )


@pytest.mark.parametrize(
    "field",
    [
        "entry_world_sha256",
        "exit_world_sha256",
        "device_sha256",
        "validation",
        "members",
    ],
)
def test_incomplete_batch_evidence_fails_closed(batch_fixture, field):
    factory, _, sources, program, original = batch_fixture
    evidence = deepcopy(original)
    del evidence[field]
    with pytest.raises(ValueError, match="PARALLEL"):
        SurfaceParallelCostBackend(factory.device).register_parallel_source(
            sources[0],
            program=program,
            entry_world=factory.world_state,
            evidence=evidence,
        )


def test_parallel_adapter_leaves_unregistered_serial_source_explicitly_isolated(
    batch_fixture,
):
    factory, _, sources, _, _ = batch_fixture
    backend = SurfaceParallelCostBackend(factory.device)
    params = {"noise_model": "noise/v1", "noise_params": {}}
    port = backend.preparation_event("raw_t_postselection", sources[0], params)
    assert "parallel_schedule_embedding" not in port.to_dict()["model"]["evidence"]
    assert port == SurfaceCostProxyBackend.preparation_event(
        backend, "raw_t_postselection", sources[0], params
    )
