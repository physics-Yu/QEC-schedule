"""Saved component artifacts retain physical exits and unobserved outcomes."""

import json

import pytest
from nadit_physical_compiler.cost import prepare

from experiments.msd.build_components import build_distance


@pytest.mark.fast
@pytest.mark.parametrize("operations", ((), ("se_round", "se_round"), ("logical_t",)))
def test_invalid_catalog_selection_fails_before_creating_artifacts(
    tmp_path, operations
):
    with pytest.raises(ValueError, match="distinct supported"):
        build_distance(9, tmp_path / "output", operations=operations)
    assert not (tmp_path / "output").exists()


def test_saved_h_cnot_and_phase_components_revalidate_in_full_world(tmp_path):
    output = tmp_path / "output"
    manifest = build_distance(
        5, output, operations=("logical_h", "transversal_cnot", "logical_s")
    )
    assert manifest["world_atoms"] == 294
    for name, row in manifest["operations"].items():
        doc = json.loads((output / name / "result.json").read_text(encoding="utf-8"))
        activity = prepare(doc)
        assert activity.duration_us == pytest.approx(
            row["metrics"]["execution_duration_us"]
        )
        expansion = json.loads(
            (output / name / "expansion.json").read_text(encoding="utf-8")
        )
        assert all(m["value"] is None for m in expansion["measurements"])
        if name == "logical_h":
            assert expansion["exit_state"] != expansion["entry_state"]
            assert row["exit_binding"] is not None
        if name == "transversal_cnot":
            assert len(row["exit_participant_bindings"]) == 2
            assert row["participant_atoms"] == 98
