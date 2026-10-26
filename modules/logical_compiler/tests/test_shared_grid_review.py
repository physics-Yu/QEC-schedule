"""Independent negative probes for shared hardware claims and source evidence."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nadit_physical_compiler.atom_ir import Move
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_program
from nadit_physical_compiler.state import AODGrid, AODLine
from test_shared_grid import _wave

from modules.codes.rotated_surface_d3.protocols.parallel_backend import (
    SurfaceParallelCostBackend,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext


def must_not_expand(_context):
    raise AssertionError("An invalid shared hardware claim reached expansion")


@pytest.mark.parametrize(
    "field", ["max_columns", "min_spacing", "readout_channel", "max_readout_atoms"]
)
def test_forged_device_claim_is_rejected_before_expansion(field):
    context, admission, requests = _wave("se_round")
    claim = admission.nodes[0].spec.shared_aod
    if field in ("max_columns", "max_readout_atoms"):
        value = 32 if getattr(claim, field) is None else None
    elif field == "min_spacing":
        value = claim.min_spacing + 0.25
    else:
        value = "not-the-device-readout-channel"
    nodes = tuple(
        replace(
            node,
            spec=replace(
                node.spec, shared_aod=replace(node.spec.shared_aod, **{field: value})
            ),
        )
        for node in admission.nodes
    )
    forged = replace(admission, nodes=nodes)
    requests = tuple(replace(request, bound=must_not_expand) for request in requests)
    before = context.snapshot_id
    with pytest.raises(ValueError, match="SHARED_AOD_DEVICE_CLAIM_MISMATCH"):
        context.invoke_batch(forged, requests)
    assert context.snapshot_id == before
    assert context.invocations == ()
    assert context.next_result_id == 0


def test_even_unoccupied_active_lines_cannot_be_silently_discarded():
    original, admission, requests = _wave("se_round")
    grid = AODGrid(
        original._device.aods[0].id,
        rows=(AODLine(77, 11),),
        columns=(AODLine(88, 11),),
    )
    entry = replace(original.world, aod_grids=(grid,))
    context = PhysicalContext(original._device, entry, original.bindings)
    admission = replace(admission, snapshot_id=context.snapshot_id)
    requests = tuple(replace(request, bound=must_not_expand) for request in requests)
    before = context.snapshot_id
    with pytest.raises(ValueError, match="SHARED_AOD_NONEMPTY_ENTRY_GRID_UNSUPPORTED"):
        context.invoke_batch(admission, requests)
    assert context.snapshot_id == before
    assert context.world == entry


@pytest.fixture(scope="module")
def real_shared_batch():
    context, admission, requests = _wave("se_round")
    entry = context.world
    batch = context.invoke_batch(admission, requests)
    assert len(context._device.aods) == 1
    assert context.finalize().validation["ok"] is True
    return context, entry, batch


def register(context, entry, batch, evidence, *, program=None):
    backend = SurfaceParallelCostBackend(context._device)
    backend.register_parallel_source(
        batch.source(batch.member_parts[0][0]),
        program=batch.program if program is None else program,
        entry_world=entry,
        evidence=evidence,
    )


def test_valid_shared_source_projection_is_accepted(real_shared_batch):
    context, entry, batch = real_shared_batch
    register(context, entry, batch, batch.to_dict())


@pytest.mark.parametrize(
    "tamper",
    [
        "duplicate-local-column",
        "cross-member-column",
        "action-hash",
        "missing-action",
        "row-renaming",
    ],
)
def test_forged_shared_projection_evidence_is_rejected(real_shared_batch, tamper):
    context, entry, batch = real_shared_batch
    evidence = deepcopy(batch.to_dict())
    member = evidence["members"][0]
    mapping = member["shared_aod_mapping"]
    if tamper == "duplicate-local-column":
        mapping["column_id_map"][1][1] = mapping["column_id_map"][0][1]
    elif tamper == "cross-member-column":
        evidence["members"][1]["shared_aod_mapping"]["column_id_map"][0][1] = mapping[
            "column_id_map"
        ][0][1]
    elif tamper == "action-hash":
        member["steps"][0]["action_embeddings"][0]["component_action_sha256"] = "0" * 64
    elif tamper == "missing-action":
        member["steps"][0]["action_embeddings"].pop()
    else:
        mapping["row_ids_unchanged"] = False
    with pytest.raises(ValueError, match="INVALID_PARALLEL_EMBEDDING"):
        register(context, entry, batch, evidence)


def test_rehashing_a_changed_fused_move_cannot_reuse_source_projection(
    real_shared_batch,
):
    context, entry, batch = real_shared_batch
    steps = list(batch.program.steps)
    step_index = next(
        i
        for i, step in enumerate(steps)
        if any(isinstance(a, Move) for a in step.actions)
    )
    actions = list(steps[step_index].actions)
    action_index = next(
        i for i, action in enumerate(actions) if isinstance(action, Move)
    )
    action = actions[action_index]
    columns = list(action.grid.columns)
    columns[0] = replace(columns[0], coordinate=columns[0].coordinate + 0.125)
    actions[action_index] = replace(
        action, grid=replace(action.grid, columns=tuple(columns))
    )
    steps[step_index] = replace(steps[step_index], actions=tuple(actions))
    program = replace(batch.program, steps=tuple(steps))
    evidence = deepcopy(batch.to_dict())
    evidence["program_sha256"] = canonical_hash(encode_program(program))
    with pytest.raises(ValueError, match="INVALID_PARALLEL_EMBEDDING"):
        register(context, entry, batch, evidence, program=program)
