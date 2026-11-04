"""Component timestamps follow the same floating-point order as atom replay."""

from dataclasses import replace

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Wait
from nadit_physical_compiler.compiler import CompilationResult, MeasurementRecord
from nadit_physical_compiler.validation import validate_result

from modules.codes.rotated_surface_d3.tests.component_fixtures import (
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.component_fixtures import expand
from modules.codes.rotated_surface_d3.tests.component_fixtures import (
    se_template as se_template,  # noqa: PLC0414
)


def test_nonzero_start_records_pass_unchanged_strict_validator(se_template, device):
    start = 105525.57071555762
    part = expand(se_template, device, start=start)
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
