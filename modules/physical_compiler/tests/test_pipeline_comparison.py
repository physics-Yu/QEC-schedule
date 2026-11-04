"""Original complete C++ traces compared with actual production stage handoffs."""

import json
from itertools import combinations
from math import hypot
from pathlib import Path
from typing import Any

import pytest

from nadit_physical_compiler.atom_ir import CZPulse, Load, Move, Store
from nadit_physical_compiler.compiler import (
    CompilationResult,
    compile_physical,
)
from nadit_physical_compiler.coverage import RegionSet
from nadit_physical_compiler.device import Device, Region
from nadit_physical_compiler.motion import check_load, check_move, check_store
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.replay import apply_step, replay
from nadit_physical_compiler.state import validate_layout
from reference import pipeline_candidate
from reference.pipeline_candidate import (
    compare_stages,
    load_cases,
    run_case,
)

HERE = Path(__file__).parents[1] / "reference"

CASES = load_cases()


@pytest.fixture(scope="module")
def source() -> dict[str, Any]:
    return dict(json.loads((HERE / "pipeline_expected.json").read_text())["cases"])


def test_multizone_source_batch_passes_independent_legality_and_final_replay(
    monkeypatch: pytest.MonkeyPatch, source: dict[str, Any]
) -> None:
    audited: list[CompilationResult] = []

    def checked_compile(
        dag: PhysicalDAG, device: Device, **kwargs: Any
    ) -> CompilationResult:
        result = compile_physical(dag, device, **kwargs)
        layout = kwargs["entry_state"]
        for step in result.program.steps:
            for action in step.actions:
                if isinstance(action, Load):
                    checked = check_load(
                        device,
                        layout,
                        action.grid,
                        {atom: (row, column) for atom, row, column in action.bindings},
                    )
                    assert checked.ok, checked.message
                elif isinstance(action, Move):
                    checked = check_move(
                        device, layout, action.grid, dict(action.targets)
                    )
                    assert checked.ok, checked.message
                elif isinstance(action, Store):
                    checked = check_store(
                        device, layout, action.grid, dict(action.bindings)
                    )
                    assert checked.ok, checked.message
                elif isinstance(action, CZPulse):
                    assert isinstance(action.coverage, Region | RegionSet)
                    assert device.cz is not None
                    illuminated = [
                        atom
                        for atom in layout.atoms
                        if action.coverage.contains(atom.position)
                    ]
                    actual = {
                        frozenset((a.id, b.id))
                        for a, b in combinations(illuminated, 2)
                        if hypot(
                            a.position.x - b.position.x, a.position.y - b.position.y
                        )
                        <= device.cz.radius_um
                    }
                    assert actual == {
                        frozenset(
                            layout.qubit_to_atom[q] for q in dag.nodes[index].qubits
                        )
                        for index in action.source_ids
                    }
            layout = apply_step(layout, step, device)
            validate_layout(device, layout)
        assert layout == result.exit_state
        assert layout == replay(result.program, kwargs["entry_state"], device)
        audited.append(result)
        return result

    monkeypatch.setattr(pipeline_candidate, "compile_physical", checked_compile)
    case = next(case for case in CASES if case["name"] == "two_gate_zones")
    result = run_case(case)
    assert len(audited) == 1
    assert result["routings"][0] == [list(range(8))]
    assert compare_stages(source[case["name"]], result)["status"] == "matched"


def test_one_illuminated_region_can_cover_two_entanglement_arrays() -> None:
    case = next(case for case in CASES if case["name"] == "two_gate_zones")
    actual = run_case({**case, "rydberg_range": [[[0, 70], [120, 100]]]})
    pulses = [action for action in actual["actions"] if action["kind"] == "global_cz"]
    assert len(actual["two_layers"][0]) == 4
    assert actual["zones"][0] == {"name": "zone_cz0", "extent": [0, 70, 120, 100]}
    assert len(actual["zones"]) == 2  # One CZ region and the source global-RY region.
    assert pulses and all(action["zones"] == [0] for action in pulses)
