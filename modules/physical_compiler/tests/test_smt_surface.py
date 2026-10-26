"""Independent d3 input semantics and constructive architecture witnesses."""

from dataclasses import replace

import pytest
from experiments.surface_smt.fixtures import (
    constructive_program,
    make_fixture,
    program_to_plan,
)
from experiments.surface_smt.oracle import verify_quantum

from nadit_physical_compiler.atom_ir import CZPulse
from nadit_physical_compiler.replay import replay


@pytest.mark.parametrize("architecture", ["nonzoned", "zoned"])
@pytest.mark.parametrize("motion", ["flexible", "rigid"])
def test_d3_constructive_witness(architecture, motion):
    fixture = make_fixture(architecture, motion)
    program = constructive_program(fixture)
    report = verify_quantum(fixture, program)
    assert report["valid"]
    assert report["cz_count"] == 24
    assert report["measurements"] == 8
    assert report["hook_directions"] == [
        "horizontal",
        "horizontal",
        "vertical",
        "vertical",
    ]
    assert replay(program, fixture.entry_state, fixture.device) == fixture.entry_state
    plan = program_to_plan(fixture, program)
    assert len(plan.states) == len(plan.transitions) + 1
    assert plan.states[0] == plan.states[-1]
    assert sorted(i for group in plan.operations for i in group) == list(
        range(len(fixture.dag.nodes))
    )


def test_four_cases_share_trap_bank_and_remove_only_source_barriers():
    cases = [
        make_fixture(a, m) for a in ("nonzoned", "zoned") for m in ("flexible", "rigid")
    ]
    reference = cases[0]
    for fixture in cases:
        assert fixture.device.slm_sites == reference.device.slm_sites
        assert fixture.entry_state == reference.entry_state
        assert fixture.device.timing == reference.device.timing
        assert fixture.device.cz == reference.device.cz
        assert fixture.device.readout == reference.device.readout
        assert fixture.device.aods[0].max_rows is None
        assert fixture.device.aods[0].max_columns is None
        assert "barrier q;" in fixture.source_qasm
        assert "barrier" not in fixture.scheduling_qasm
        assert (
            fixture.source_qasm.replace("barrier q;\n", "") == fixture.scheduling_qasm
        )
        assert sum(n.name == "cz" for n in fixture.dag.nodes) == 24
        assert sum(n.name == "reset" for n in fixture.dag.nodes) == 8
        assert sum(n.name == "measure" for n in fixture.dag.nodes) == 8


def test_quantum_oracle_uses_actual_illumination():
    fixture = make_fixture("nonzoned", "rigid")
    program = constructive_program(fixture)
    index = next(
        i
        for i, step in enumerate(program.steps)
        if isinstance(step.actions[0], CZPulse)
    )
    step = program.steps[index]
    pulse = replace(step.actions[0], coverage=())
    bad = replace(
        program,
        steps=program.steps[:index]
        + (replace(step, actions=(pulse,)),)
        + program.steps[index + 1 :],
    )
    with pytest.raises(ValueError, match="interactions"):
        verify_quantum(fixture, bad)
