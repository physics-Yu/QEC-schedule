"""Semantic report integration and the two saved-result counterexamples."""

from dataclasses import replace

import pytest

from examples.viewer_cases import compile_feedback
from nadit_physical_compiler import (
    AtomStep,
    CZPulse,
    Region,
    Wait,
)
from nadit_physical_compiler.validation import validate_result


def test_empty_cz_illumination_reports_missing_interaction() -> None:
    example = compile_feedback(1)
    steps = tuple(
        AtomStep(
            tuple(
                replace(action, coverage=Region(-100, -100, -90, -90))
                if isinstance(action, CZPulse)
                else action
                for action in step.actions
            )
        )
        for step in example.result.program.steps
    )
    result = replace(
        example.result, program=replace(example.result.program, steps=steps)
    )
    report = validate_result(
        result, entry_state=example.entry, device=example.device, dag=example.dag
    )
    assert report["failure"] is not None
    assert report["failure"]["rule"] == "missing_interaction"
    assert report["failure_count"] >= 3
    assert "timing" in report["checks"]


@pytest.mark.parametrize("bit", [1])
def test_removed_feedback_wait_reports_latency_before_stale_records(bit: int) -> None:
    example = compile_feedback(bit)
    steps = tuple(
        step
        for step in example.result.program.steps
        if not all(isinstance(action, Wait) for action in step.actions)
    )
    assert len(steps) < len(example.result.program.steps)
    result = replace(
        example.result, program=replace(example.result.program, steps=steps)
    )
    report = validate_result(
        result, entry_state=example.entry, device=example.device, dag=example.dag
    )
    assert report["failure"] is not None
    assert report["failure"]["rule"] == "feedback_latency"
    assert "record_mismatch" in {item["rule"] for item in report["failures"]}
