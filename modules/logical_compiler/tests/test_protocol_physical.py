"""Compose real Atom IR with transactional world/time/result ownership."""

import json
from dataclasses import replace
from math import pi

import pytest
from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    Measure,
    Rotation,
    Wait,
)
from nadit_physical_compiler.capabilities import LocalControl, ReadoutCapability
from nadit_physical_compiler.compiler import CompiledOperation
from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.physical_ir import (
    Condition,
    PhysicalDAG,
    PhysicalOperation,
    ResultRef,
)
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentDescription,
    ComponentExpansion,
    MeasurementOutput,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext


@pytest.fixture
def setup_world():
    sites = tuple(SLMSite(f"s{i}", Position(i * 10, 0)) for i in range(3))
    device = Device(
        "physical-context-fixture",
        zones=(Zone("all", Region(-10, -10, 40, 10), ("rotate", "measure")),),
        slm_sites=sites,
        aods=(AOD("aod0", Region(-10, -10, 40, 10), 1),),
        timing=Timing(1, 1, 1),
        local=LocalControl("local", 2, 2),
        readout=ReadoutCapability("readout", 3, latency_us=5),
    )
    world = AtomLayout(
        tuple(
            AtomState(atom, site.position, SLMHolder(site.id))
            for atom, site in zip((7, 11, 99), sites, strict=True)
        ),
        qubit_to_atom=(7, 11, 99),
    )
    bindings = (
        ComponentBinding("A", sites[1].position, (11,), "aod0"),
        ComponentBinding("B", sites[0].position, (7,), "aod0"),
    )
    return device, world, bindings


def _part(context, binding, kind="measure", *, result_id=None, exit_binding=None):
    duration = 3 if kind == "measure" else 2
    reference = ResultRef(context.result_id_base if result_id is None else result_id)
    measurement = kind == "measure"
    action = (
        Measure(
            "readout",
            ((binding.atom_ids[0], reference),),
            True,
            duration_us=duration,
            source_ids=(0,),
        )
        if measurement
        else Rotation(
            "local",
            (binding.atom_ids[0],),
            "X",
            pi / 2,
            duration_us=duration,
            source_ids=(0,),
        )
    )
    description = ComponentDescription(
        "test",
        kind,
        "1",
        tuple(f"r{i}" for i in range(len(binding.atom_ids))),
        ("m",) if measurement else (),
        (),
        (),
    )
    node = PhysicalOperation(
        0,
        "measure" if measurement else "rx",
        (0,),
        (0,) if measurement else (),
        () if measurement else (pi / 2,),
        source_id=reference.measurement_id if measurement else 0,
    )
    return ComponentExpansion(
        description,
        context.invocation_id,
        binding.block_id,
        context.start_us,
        context.world_state,
        context.world_state,
        binding.atom_ids,
        AtomProgram((AtomStep((action,)),)),
        PhysicalDAG(len(binding.atom_ids), int(measurement), (node,), ()),
        (CompiledOperation(0, "emitted", 0, duration),),
        (
            MeasurementOutput(
                context.invocation_id,
                "m",
                reference,
                binding.atom_ids[0],
                context.start_us + 8,
                None,
            ),
        )
        if measurement
        else (),
        (),
        (),
        exit_binding=exit_binding or binding,
        template_content_sha256="f" * 64,
    )


def test_continuous_world_and_global_source_wire_maps_keep_spectators(setup_world):
    device, world, (a, b) = setup_world
    context = PhysicalContext(device, world, (a, b))
    first = context.invoke(lambda c: _part(c, a), "measure-A", 1)
    context.invoke(lambda c: _part(c, b, "rotation"), "rotate-B", 0)
    assert first[0].measurements[0].value is None
    assert context.clock_us == 5
    assert context.next_result_id == 1
    assert context.world == world
    bundle = context.finalize()
    assert bundle.world == world
    assert len(bundle.world.atoms) == 3
    assert [node.qubits for node in bundle.dag.nodes] == [(1,), (0,)]
    assert [
        action.source_ids for step in bundle.program.steps for action in step.actions
    ] == [(0,), (1,)]
    assert [(op.operation_id, op.start_us, op.end_us) for op in bundle.operations] == [
        (0, 0, 3),
        (1, 3, 5),
    ]
    snapshot = bundle.to_dict()
    assert snapshot["validation"]["ok"] is True
    assert snapshot["validation"]["scope"] == "selected_actions_unobserved_measurements"
    assert snapshot["pending_measurements"][0]["value"] is None
    assert snapshot["pending_measurements"][0]["available_at_us"] == 8
    assert snapshot["source_id_map"]["1"]["invocation_id"] == "rotate-B"
    assert snapshot["source_id_map"]["1"]["native_operation_id"] == 0
    trace = bundle.build_trace(title="Pending fixture")
    assert trace["measurements"] == []
    assert trace["pending_measurements"][0]["value"] is None
    assert trace["program_duration_us"] == 5
    assert trace["results_ready_us"] == 8
    assert json.loads(json.dumps(snapshot)) == snapshot


def test_real_wait_and_reason_survive_assembly(setup_world):
    device, world, (a, b) = setup_world
    context = PhysicalContext(device, world, {"A": a, "B": b})
    context.invoke(lambda c: _part(c, a), "measurement", 1)
    context.wait_until(8, reason="wait for selected protocol result")
    context.invoke(lambda c: _part(c, b, "rotation"), "feedback", 0)
    bundle = context.finalize()
    assert isinstance(bundle.program.steps[1].actions[0], Wait)
    assert bundle.program.steps[1].duration_us == 5
    assert bundle.program.duration_us == context.clock_us == 10
    assert bundle.to_dict()["waits"] == [
        {"start_us": 3, "end_us": 8, "reason": "wait for selected protocol result"}
    ]
    assert bundle.operations[-1].start_us == 8


def test_not_before_wait_and_measurement_ranges_are_global(setup_world):
    device, world, bindings = setup_world
    a = bindings[0]
    context = PhysicalContext(device, world, bindings)
    context.invoke(lambda c: _part(c, a), "one", 1, not_before_us=4)
    context.invoke(lambda c: _part(c, a), "two", 1)
    bundle = context.finalize()
    assert isinstance(bundle.program.steps[0].actions[0], Wait)
    assert context.next_result_id == 2
    assert [m.result.measurement_id for m in bundle.pending_measurements] == [0, 1]
    assert [m.available_at_us for m in bundle.pending_measurements] == [12, 15]
    assert context.clock_us == 10


def test_invalid_expander_preserves_context(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    with pytest.raises(TypeError, match="INVALID_PHYSICAL_EXPANDER"):
        context.invoke(object(), "invalid", 0)
    assert context.world == world
    assert context.clock_us == 0
    assert context.next_result_id == 0
    assert context.invocations == ()


@pytest.mark.parametrize(
    "fault",
    [
        "stale_entry",
        "missing_spectator",
        "wrong_result",
        "wrong_count",
        "wrong_output_atom",
        "bad_time",
        "bad_duration",
        "observed",
    ],
)
def test_failed_invocation_is_atomic(setup_world, fault):
    device, world, bindings = setup_world
    a = bindings[0]
    context = PhysicalContext(device, world, bindings)
    context.invoke(lambda c: _part(c, a, "rotation"), "before", 0)
    before = context.finalize().to_dict()

    def broken(c):
        part = _part(c, a, result_id=99 if fault == "wrong_result" else None)
        if fault == "stale_entry":
            part = replace(
                part, entry_state=replace(c.world_state, qubit_to_atom=(11, 7, 99))
            )
        elif fault == "missing_spectator":
            part = replace(
                part,
                exit_state=AtomLayout(c.world_state.atoms[:2], qubit_to_atom=(7, 11)),
            )
        elif fault == "bad_time":
            part = replace(part, start_us=c.start_us - 1)
        elif fault == "bad_duration":
            action = replace(part.program.steps[0].actions[0], duration_us=1)
            part = replace(part, program=AtomProgram((AtomStep((action,)),)))
        elif fault == "observed":
            part = replace(part, measurements=(replace(part.measurements[0], value=0),))
        elif fault == "wrong_output_atom":
            part = replace(
                part, measurements=(replace(part.measurements[0], atom_id=99),)
            )
        return part

    with pytest.raises(ValueError):
        context.invoke(
            broken, "broken", 2 if fault == "wrong_count" else 1, not_before_us=10
        )
    assert context.clock_us == 2 and context.next_result_id == 0
    assert context.world == world
    assert context.finalize().to_dict() == before
    with pytest.raises(KeyError):
        context.source("broken")


def test_tuple_and_parts_adapters_use_latest_bindings_and_unique_results(setup_world):
    device, world, (a, _b) = setup_world
    joint = replace(a, atom_ids=(11, 7))
    context = PhysicalContext(device, world, (joint,))

    class Adapter:
        def expand(self, c):
            first = _part(replace(c, invocation_id=f"{c.invocation_id}/0"), joint)
            second_context = replace(
                c,
                invocation_id=f"{c.invocation_id}/1",
                start_us=c.start_us + 3,
                result_id_base=c.result_id_base + 1,
            )
            second = _part(
                second_context, joint, exit_binding=replace(joint, atom_ids=(7, 11))
            )
            return type("Sequence", (), {"parts": (first, second)})()

    parts = context.invoke(Adapter(), "batch")
    assert len(parts) == 2
    assert context.source("batch").parts == parts
    assert context.bindings["A"].atom_ids == (7, 11)
    assert context.next_result_id == 2
    assert context.clock_us == 6
    context.invoke(lambda c: (_part(c, context.bindings["A"], "rotation"),), "tuple", 0)
    assert context.finalize().dag.nodes[-1].qubits == (0,)


def test_duplicate_invocations_and_physical_conditions_are_rejected(setup_world):
    device, world, bindings = setup_world
    a = bindings[0]
    context = PhysicalContext(device, world, bindings)
    context.invoke(lambda c: _part(c, a), "one", 1)
    with pytest.raises(ValueError, match="invocation"):
        context.invoke(lambda c: _part(c, a), "one", 1)

    def conditional(c):
        part = _part(c, a)
        rotation = PhysicalOperation(
            1, "rx", (0,), (), (pi / 2,), Condition(part.measurements[0].result)
        )
        return replace(
            part,
            dag=replace(part.dag, nodes=part.dag.nodes + (rotation,), edges=((0, 1),)),
        )

    with pytest.raises(ValueError, match="[Cc]ondition"):
        context.invoke(conditional, "conditional", 1)
    assert context.next_result_id == 1


def test_world_wire_metadata_is_completed_without_losing_spectators(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, replace(world, qubit_to_atom=(11,)), bindings)
    assert context.world.qubit_to_atom == (11, 7, 99)
    assert context.world.atoms == world.atoms
    context.invoke(lambda c: _part(c, bindings[1], "rotation"), "one", 0)
    assert context.finalize().dag.nodes[0].qubits == (1,)
    assert context.finalize().to_dict()["normalized_entry_wire_map"] == [11, 7, 99]
    assert context.finalize().to_dict()["input_entry_wire_map"] == [11]


def test_single_expansion_adapter_keeps_original_runtime_object(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)

    def canonicalize(c):
        expansion = _part(c, bindings[0], "rotation")
        return type("Correction", (), {"expansion": expansion, "decision": "fixture"})()

    parts = context.invoke(canonicalize, "canonicalize")
    original = context.source("canonicalize")
    assert original.expansion is parts[0]
    assert original.decision == "fixture"
    assert context.next_result_id == 0
    assert "decision" not in context.finalize().to_json()


def test_derived_result_count_rejects_duplicate_ids_atomically(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)

    def duplicate(c):
        first = _part(replace(c, invocation_id="attempt/0"), bindings[0])
        second = _part(replace(c, invocation_id="attempt/1", start_us=3), bindings[0])
        return first, second

    with pytest.raises(ValueError, match="RESULT_RANGE"):
        context.invoke(duplicate, "attempt")
    assert context.clock_us == context.next_result_id == 0
    assert context.invocations == ()


def test_assembly_preserves_program_phase_and_pending_acceptance_relation(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)

    def prepare(c):
        part = _part(c, bindings[0])
        return replace(
            part,
            program=replace(part.program, global_phase=0.25),
            dag=replace(part.dag, global_phase=0.25),
            acceptance_conditions=((part.measurements[0].result, 0),),
        )

    context.invoke(prepare, "prepare")
    context.invoke(prepare, "repeat")
    bundle = context.finalize()
    assert bundle.program.global_phase == bundle.dag.global_phase == 0.5
    assert bundle.to_dict()["parts"][1]["acceptance_conditions"] == [
        [{"measurement_id": 1}, 0]
    ]
    assert all(output.value is None for output in bundle.pending_measurements)


def _long_fractional_part(context, binding, kind="rotation", *, wait_duration=0.1):
    part = _part(context, binding, kind)
    program = AtomProgram(
        (AtomStep((Wait(duration_us=wait_duration),)),) * 1024 + part.program.steps
    )
    start, step = program.timeline()[-1]
    end = start + step.duration_us
    measurements = tuple(
        replace(output, available_at_us=context.start_us + (end + 5))
        for output in part.measurements
    )
    return replace(
        part,
        program=program,
        operations=(CompiledOperation(0, "emitted", start, end),),
        measurements=measurements,
    )


def test_long_flattened_timeline_defines_operation_record_intervals(setup_world):
    """Grouping valid local times must not disagree with actual AtomStep sums."""
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    context.wait_until(100000, reason="long-running physical prefix")
    context.invoke(lambda c: _long_fractional_part(c, bindings[0]), "late-rotation", 0)
    bundle = context.finalize()
    start, step = bundle.program.timeline()[-1]
    operation = bundle.operations[0]
    assert (operation.start_us, operation.end_us) == (
        start,
        start + step.actions[0].duration_us,
    )
    assert bundle.validation["ok"] is True


def test_long_timeline_summary_and_viewer_use_the_same_committed_clock(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    context.wait_until(100000, reason="long-running physical prefix")
    context.invoke(lambda c: _long_fractional_part(c, bindings[0]), "late-rotation", 0)
    bundle = context.finalize()
    last_start, last_step = bundle.program.timeline()[-1]
    end = last_start + last_step.duration_us
    assert bundle.to_dict()["clock_us"] == context.clock_us == end
    trace = bundle.build_trace(title="clock regression")
    assert trace["duration_us"] == trace["program_duration_us"] == end


def test_flattened_record_includes_all_source_actions_but_not_parallel_padding(
    setup_world,
):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)

    def expanded(c):
        part = _part(c, bindings[0], "rotation")
        rotation = part.program.steps[0].actions[0]
        program = AtomProgram(
            (
                AtomStep((Wait(duration_us=0.25, source_ids=(0,)),)),
                AtomStep((rotation, Wait(duration_us=4))),
            )
        )
        return replace(
            part,
            program=program,
            operations=(CompiledOperation(0, "emitted", 0, 2.25),),
        )

    context.invoke(expanded, "source-envelope", 0)
    bundle = context.finalize()
    assert bundle.program.duration_us == 4.25
    assert (bundle.operations[0].start_us, bundle.operations[0].end_us) == (0, 2.25)


def test_flattening_does_not_repair_invalid_component_record(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)

    def invalid(c):
        part = _part(c, bindings[0], "rotation")
        return replace(part, operations=(CompiledOperation(0, "emitted", 0, 1),))

    with pytest.raises(ValueError, match="record_mismatch"):
        context.invoke(invalid, "invalid-local-record", 0)
    assert context.clock_us == 0
    assert context.invocations == ()


def _canonical_global_measurement(context, binding, *, extra_delay=0):
    part = _long_fractional_part(context, binding, "measure", wait_duration=0.2)
    global_start = context.start_us
    for step in part.program.steps:
        for action in step.actions:
            if isinstance(action, Measure):
                global_end = global_start + action.duration_us
        global_start += step.duration_us
    return replace(
        part,
        measurements=(
            replace(part.measurements[0], available_at_us=global_end + 5 + extra_delay),
        ),
    )


@pytest.mark.parametrize("extra_delay", [0, 17.25])
def test_local_validation_preserves_global_ready_and_extra_delay(
    setup_world, monkeypatch, extra_delay
):
    from modules.logical_compiler.src.protocols import assembly

    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    context.wait_until(100000, reason="large global origin")
    actual_validate = assembly.validate_result
    local_records = []

    def observed_validate(result, **kwargs):
        local_records.append(result.measurements)
        return actual_validate(result, **kwargs)

    monkeypatch.setattr(assembly, "validate_result", observed_validate)
    parts = context.invoke(
        lambda c: _canonical_global_measurement(
            c, bindings[0], extra_delay=extra_delay
        ),
        "globally-timed-readout",
        1,
    )
    original = parts[0].measurements[0]
    local_start, local_step = parts[0].program.timeline()[-1]
    local_ready = local_start + local_step.actions[0].duration_us + 5 + extra_delay
    assert local_records[0][0].available_at_us == local_ready
    bundle = context.finalize()
    assert bundle.pending_measurements[0] == original
    assert bundle.pending_measurements[0].value is None
    global_start, global_step = bundle.program.timeline()[-1]
    assert original.available_at_us == (
        global_start + global_step.actions[0].duration_us + 5 + extra_delay
    )
    assert bundle.validation["ok"] is True


def test_local_validation_rejects_early_global_readiness_without_clamping(setup_world):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    context.wait_until(100000, reason="large global origin")
    with pytest.raises(ValueError, match="readout"):
        context.invoke(
            lambda c: _canonical_global_measurement(c, bindings[0], extra_delay=-0.01),
            "early-global-readout",
            1,
        )
    assert context.clock_us == 100000
    assert context.next_result_id == 0
    assert context.invocations == ()
