"""Transactional lockstep batches built from real component AtomPrograms."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Wait
from nadit_physical_compiler.capabilities import LocalControl, ReadoutCapability
from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import Admission, ComponentNode
from modules.logical_compiler.tests.test_protocol_physical import _part


@pytest.fixture
def parallel_world():
    sites = tuple(SLMSite(f"s{i}", Position(i * 20, 0)) for i in range(5))
    device = Device(
        "parallel-context-fixture",
        zones=(Zone("all", Region(-10, -10, 100, 10), ("rotate", "measure")),),
        slm_sites=sites,
        aods=tuple(AOD(f"aod{i}", Region(-10, -10, 100, 10), 1) for i in range(4)),
        timing=Timing(1, 1, 1),
        local=LocalControl("local", 2, 2),
        readout=ReadoutCapability("readout", 3, latency_us=5, max_atoms=None),
    )
    world = AtomLayout(
        tuple(
            AtomState(i, site.position, SLMHolder(site.id))
            for i, site in enumerate(sites)
        ),
        qubit_to_atom=(4, 3, 2, 1, 0),
    )
    bindings = tuple(
        ComponentBinding(f"P{i}", sites[i].position, (i,), f"aod{i}") for i in range(4)
    )
    return device, world, bindings


def _admission(context, bindings, *, start=None):
    return Admission(
        batch_id="wave-0",
        snapshot_id=context.snapshot_id,
        start_us=context.clock_us if start is None else start,
        nodes=tuple(
            ComponentNode(
                id=f"member-{i}",
                spec=ComponentExecutionSpec(
                    code_id="test",
                    component_id="measure",
                    waveform_key="measure.v1",
                    participant_blocks=(binding.block_id,),
                    spaces=(
                        SpaceClaim(Region(i * 20 - 5, -5, i * 20 + 5, 5), "fixture"),
                    ),
                    exclusive_resources=(f"aod:{binding.aod_id}",),
                    parallel_mode="independent_aods_lockstep",
                    result_count=1,
                ),
            )
            for i, binding in enumerate(bindings)
        ),
    )


def _requests(bindings, factory=None):
    from modules.logical_compiler.src.protocols.parallel_physical import (
        PhysicalBatchRequest,
    )

    return tuple(
        PhysicalBatchRequest(
            f"member-{i}",
            (lambda c, b=binding: _part(c, b)) if factory is None else factory(binding),
            1,
        )
        for i, binding in enumerate(bindings)
    )


def test_four_members_share_actual_clock_without_serial_dag_edges(parallel_world):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)
    batch = context.invoke_batch(_admission(context, bindings), _requests(bindings))
    assert context.clock_us == 3
    assert context.next_result_id == 4
    assert batch.start_us == 0 and batch.action_end_us == 3
    assert batch.results_ready_us == 8
    for member, parts in batch.member_parts:
        assert context.source(member) is batch.source(member)
        assert context.batch_for(member) is batch
        assert context.batch_for(parts[0].invocation_id) is batch
        assert parts[0].measurements[0].value is None
    assert context.batch_for("missing") is None
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert len(bundle.program.steps) == 1 and len(bundle.program.steps[0].actions) == 4
    assert bundle.dag.edges == ()
    assert [node.qubits for node in bundle.dag.nodes] == [(4,), (3,), (2,), (1,)]
    assert {m.result.measurement_id for m in bundle.pending_measurements} == set(
        range(4)
    )
    assert bundle.world == world
    proof = bundle.to_dict()["parallel_batches"][0]
    assert proof["batch_id"] == "wave-0"
    assert proof["noise_factorization_claimed"] is False
    assert proof["participant_trajectory_projection_verified"] is True
    context.invoke(lambda c: _part(c, bindings[0], "rotation"), "after", 0)
    assert context.finalize().operations[-1].start_us == 3


def test_multiple_parts_keep_original_sources_and_global_result_readiness(
    parallel_world,
):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)
    context.wait_until(100000.125, reason="large-origin fixture")

    def factory(binding):
        def expand(c):
            first = _part(replace(c, invocation_id=c.invocation_id + "/0"), binding)
            second = _part(
                replace(
                    c,
                    invocation_id=c.invocation_id + "/1",
                    start_us=first.action_end_us,
                ),
                binding,
                "rotation",
            )
            return SimpleNamespace(parts=(first, second))

        return expand

    batch = context.invoke_batch(
        _admission(context, bindings), _requests(bindings, factory)
    )
    assert batch.action_end_us == 100005.125
    assert batch.results_ready_us == 100008.125
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert len(bundle.to_dict()["parts"]) == 8
    assert len(bundle.dag.edges) == 4
    assert all(m.available_at_us == 100008.125 for m in bundle.pending_measurements)
    assert context.batch_for("member-0/1") is batch


@pytest.mark.parametrize("fault", ["stale", "shape", "same_aod"])
def test_admission_failures_do_not_expand(parallel_world, fault):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)
    admission = _admission(context, bindings)
    if fault == "stale":
        admission = replace(admission, snapshot_id="old")
    elif fault == "shape":
        node = replace(
            admission.nodes[0],
            spec=replace(
                admission.nodes[0].spec, waveform_key=None, parallel_mode="exclusive"
            ),
        )
        admission = replace(admission, nodes=(node, *admission.nodes[1:]))
    else:
        node = replace(
            admission.nodes[1],
            spec=replace(admission.nodes[1].spec, exclusive_resources=("aod:aod0",)),
        )
        admission = replace(
            admission, nodes=(admission.nodes[0], node, *admission.nodes[2:])
        )

    def forbidden(binding):
        def expand(c):
            raise AssertionError("Admission must be checked before any expansion")

        return expand

    before = context.snapshot_id
    with pytest.raises(ValueError):
        context.invoke_batch(admission, _requests(bindings, forbidden))
    assert context.snapshot_id == before


def test_lowering_shape_mismatch_is_atomic_without_padding(parallel_world):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)

    def factory(binding):
        def expand(c):
            part = _part(c, binding)
            if binding.block_id == "P1":
                return replace(
                    part,
                    program=AtomProgram(
                        part.program.steps + (AtomStep((Wait(duration_us=0.5),)),)
                    ),
                )
            return part

        return expand

    before = context.snapshot_id
    with pytest.raises(ValueError, match="LOCKSTEP"):
        context.invoke_batch(
            _admission(context, bindings), _requests(bindings, factory)
        )
    assert context.snapshot_id == before
    assert context.invocations == ()


def test_declared_member_space_is_checked_even_before_an_empty_expansion(
    parallel_world,
):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)
    admission = _admission(context, bindings)
    first = admission.nodes[0]
    first = replace(
        first,
        spec=replace(
            first.spec,
            spaces=(SpaceClaim(Region(-9, -9, -8, -8), "incorrect-home"),),
        ),
    )
    admission = replace(admission, nodes=(first, *admission.nodes[1:]))

    def forbidden(binding):
        def expand(invocation):
            raise AssertionError("Space eligibility must precede even empty bodies")

        return expand

    before = context.snapshot_id
    with pytest.raises(ValueError, match="OUTSIDE_DECLARED_SPACE"):
        context.invoke_batch(admission, _requests(bindings, forbidden))
    assert context.snapshot_id == before


def test_joint_resource_failure_rolls_back_entire_batch(parallel_world):
    device, world, bindings = parallel_world
    device = replace(device, readout=replace(device.readout, max_atoms=1))
    context = PhysicalContext(device, world, bindings)
    before = context.snapshot_id
    with pytest.raises(ValueError, match="readout_capacity"):
        context.invoke_batch(_admission(context, bindings), _requests(bindings))
    assert context.snapshot_id == before
    assert context.next_result_id == 0


def test_local_components_can_share_default_aod_without_claiming_transport(
    parallel_world,
):
    device, world, bindings = parallel_world
    bindings = tuple(replace(binding, aod_id="aod0") for binding in bindings)
    context = PhysicalContext(device, world, bindings)
    admission = _admission(context, bindings)
    admission = replace(
        admission,
        nodes=tuple(
            replace(node, spec=replace(node.spec, exclusive_resources=()))
            for node in admission.nodes
        ),
    )
    context.invoke_batch(admission, _requests(bindings))
    assert context.finalize().validation["ok"] is True


def test_batch_after_serial_call_keeps_global_ids_and_actual_offsets(parallel_world):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)
    context.invoke(lambda c: _part(c, bindings[0]), "prefix", 1)
    batch = context.invoke_batch(
        _admission(context, bindings, start=11), _requests(bindings)
    )
    assert batch.start_us == 11 and context.clock_us == 14
    assert context.next_result_id == 5
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert [item.result.measurement_id for item in bundle.pending_measurements] == list(
        range(5)
    )
    assert all(
        item.start_us == 11 and item.end_us == 14 for item in bundle.operations[1:]
    )
    assert bundle.dag.edges == ((0, 1), (0, 2), (0, 3), (0, 4))
    assert bundle.to_dict()["waits"] == [
        {"start_us": 3, "end_us": 11, "reason": "batch_not_before:wave-0"}
    ]
    assert (
        bundle.build_trace(title="Parallel fixture")["parallel_batches"][0][
            "global_operation_base"
        ]
        == 1
    )


def test_member_cannot_execute_another_patchs_component(parallel_world):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)
    before = context.snapshot_id
    with pytest.raises(ValueError, match="OWNERSHIP"):
        context.invoke_batch(
            _admission(context, bindings),
            _requests(bindings, lambda binding: lambda c: _part(c, bindings[1])),
        )
    assert context.snapshot_id == before


@pytest.mark.parametrize("fault", ["cross_patch", "different_component", "overlap"])
def test_forged_admission_is_rejected_before_expansion(parallel_world, fault):
    device, world, bindings = parallel_world
    context = PhysicalContext(device, world, bindings)
    admission = _admission(context, bindings)
    spec = admission.nodes[0].spec
    if fault == "cross_patch":
        spec = replace(spec, participant_blocks=("P0", "P1"))
    elif fault == "different_component":
        spec = replace(spec, component_id="different")
    else:
        spec = replace(spec, spaces=admission.nodes[1].spec.spaces)
    admission = replace(
        admission, nodes=(replace(admission.nodes[0], spec=spec), *admission.nodes[1:])
    )

    def forbidden(binding):
        def expand(c):
            raise AssertionError("Forged admission cannot execute")

        return expand

    with pytest.raises(ValueError):
        context.invoke_batch(admission, _requests(bindings, forbidden))


@pytest.mark.parametrize(
    "component_id,shared_default_aod",
    [
        ("raw_t_postselection", False),
        ("se_round", False),
        ("logical_s", False),
        ("logical_x", True),
        ("logical_z", True),
        ("initialize_0", False),
        ("initialize_plus", False),
    ],
)
def test_real_single_patch_components_embed_in_one_validated_world(
    component_id, shared_default_aod
):
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
    from modules.logical_compiler.src.scheduling import ComponentScheduler

    world = make_factory_world(
        FactoryWorldConfig(
            aod_ids=("one", "two", "three", "four"),
            role_aod_ids=()
            if shared_default_aod
            else (
                ("W2", "one"),
                ("W3", "two"),
                ("W4", "three"),
                ("W5", "four"),
            ),
        )
    )
    backend = SurfaceFactoryBackend(world.device)
    context = PhysicalContext(world.device, world.world_state, world.bindings.values())
    scheduler = ComponentScheduler(mode="parallel")
    participants = [world.bindings[role] for role in ("W2", "W3", "W4", "W5")]
    # Retain the original independent-resource lowering regression even when
    # this code's canonical declarations also permit shared-grid composition.
    specs = tuple(
        backend.describe_execution(component_id, (binding,)) for binding in participants
    )
    specs = tuple(
        replace(
            spec,
            parallel_mode="independent_aods_lockstep",
            shared_aod=None,
            exclusive_resources=()
            if shared_default_aod
            else (f"aod:{binding.aod_id}",),
        )
        for spec, binding in zip(specs, participants, strict=True)
    )
    scheduler.add(*(ComponentNode(f"raw-{i}", spec) for i, spec in enumerate(specs)))
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
    batch = context.invoke_batch(admission, requests)
    bundle = context.finalize()
    assert bundle.validation["ok"] is True
    assert len(bundle.world.atoms) == 102
    assert len(bundle.pending_measurements) == sum(
        node.spec.result_count for node in admission.nodes
    )
    assert all(item.value is None for item in bundle.pending_measurements)
    assert len(bundle.to_dict()["parts"]) == (
        8 if component_id == "raw_t_postselection" else 4
    )
    assert batch.action_end_us == batch.source("raw-0").action_end_us
    assert all(
        batch.source(node.id).action_end_us == batch.action_end_us
        for node in admission.nodes
    )
    assert batch.to_dict()["noise_factorization_claimed"] is False
    if shared_default_aod:
        assert all(not node.spec.exclusive_resources for node in admission.nodes)
    if component_id == "raw_t_postselection":
        fresh = PhysicalContext(
            world.device, world.world_state, world.bindings.values()
        )
        undeclared = replace(
            admission,
            nodes=tuple(
                replace(node, spec=replace(node.spec, exclusive_resources=()))
                for node in admission.nodes
            ),
        )
        before = fresh.snapshot_id
        with pytest.raises(ValueError, match="AOD_CLAIM"):
            fresh.invoke_batch(undeclared, requests)
        assert fresh.snapshot_id == before
