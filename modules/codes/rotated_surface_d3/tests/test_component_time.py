"""Component timestamps follow the same floating-point order as atom replay."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Measure, Wait
from nadit_physical_compiler.compiler import CompilationResult, MeasurementRecord
from nadit_physical_compiler.validation import validate_result

from modules.codes.rotated_surface_d3.tests.test_components import (
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_components import expand
from modules.codes.rotated_surface_d3.tests.test_components import (
    templates as templates,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_raw_t_postselection_quantum import (
    sequence as sequence,  # noqa: PLC0414
)


def walk(program, start, latency):
    """Independent ordinary left-to-right addition, as in physical validation."""
    ready = {}
    cursor = start
    for step in program.steps:
        for action in step.actions:
            if isinstance(action, Measure):
                for _, result in action.results:
                    ready[result.measurement_id] = cursor + action.duration_us + latency
        cursor += step.duration_us
    return cursor, ready


@pytest.mark.parametrize("start", (0.0, 1234.56789, 105525.57071555762))
@pytest.mark.parametrize("name", ("initialize_0", "initialize_plus", "se_round"))
def test_global_action_and_result_clocks_are_exact(templates, device, start, name):
    part = expand(templates[name], device, start=start)
    end, ready = walk(part.program, start, device.readout.latency_us)
    assert part.action_end_us == end
    assert {
        m.result.measurement_id: m.available_at_us for m in part.measurements
    } == ready
    assert all(m.value is None for m in part.measurements)


def test_230_consecutive_calls_match_one_flattened_clock(templates, device):
    cursor = 0.0
    start = 0.0
    entry = None
    identities = set()
    for invocation in range(230):
        part = expand(
            templates["se_round"],
            device,
            invocation=f"round/{invocation}",
            base=800 + 8 * invocation,
            start=start,
            entry=entry,
        )
        assert part.start_us == cursor
        cursor, ready = walk(part.program, cursor, device.readout.latency_us)
        assert part.action_end_us == cursor
        for result in part.measurements:
            assert result.available_at_us == ready[result.result.measurement_id]
            assert result.result.measurement_id not in identities
            identities.add(result.result.measurement_id)
        start, entry = part.action_end_us, part.exit_state
    assert len(identities) == 1840


def test_raw_rounds_follow_one_global_clock(sequence, device):
    cursor = sequence.parts[0].start_us
    for part in sequence.parts:
        assert part.start_us == cursor
        cursor, ready = walk(part.program, cursor, device.readout.latency_us)
        assert part.action_end_us == cursor
        assert all(
            m.available_at_us == ready[m.result.measurement_id]
            for m in part.measurements
        )
    assert sequence.action_end_us == cursor


def test_nonzero_start_records_pass_unchanged_strict_validator(templates, device):
    start = 105525.57071555762
    part = expand(templates["se_round"], device, start=start)
    # A prefixed real wait makes the component's invocation start explicit in
    # one ordinary AtomProgram. Map operation boundaries from the actual walk;
    # measurement records come directly from the production component output.
    boundaries = {0.0: start}
    local, absolute = 0.0, start
    for step in part.program.steps:
        for action in step.actions:
            boundaries[local + action.duration_us] = absolute + action.duration_us
        local += step.duration_us
        absolute += step.duration_us
        boundaries[local] = absolute
    result = CompilationResult(
        AtomProgram(
            (AtomStep((Wait(duration_us=start),)), *part.program.steps),
            part.program.global_phase,
        ),
        part.exit_state,
        tuple(
            replace(op, start_us=boundaries[op.start_us], end_us=boundaries[op.end_us])
            for op in part.operations
        ),
        tuple(
            MeasurementRecord(m.result, 0, m.available_at_us) for m in part.measurements
        ),
        (),
    )
    checked = validate_result(
        result, entry_state=part.entry_state, device=device, dag=part.dag
    )
    assert checked["ok"], checked


def test_empty_action_program_keeps_nonzero_start(templates, device):
    part = expand(templates["se_round"], device, start=1234.56789)
    empty = replace(part, program=AtomProgram(), measurements=())
    assert empty.action_end_us == empty.results_ready_us == part.start_us
