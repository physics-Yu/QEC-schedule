"""Compose real Atom IR with transactional world/time/result ownership."""

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


def test_local_validation_preserves_global_ready_and_extra_delay(
    setup_world, monkeypatch
):
    from modules.logical_compiler.src.protocols import assembly

    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    context.wait_until(100000, reason="large global origin")
    extra_delay = 17.25
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
