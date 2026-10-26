"""Export accounting from an existing partial case without compiling components."""

import hashlib
import json

import pytest

from modules.logical_compiler.examples.factory_to_t import _export
from modules.logical_compiler.src.protocols.factory import FactoryCase


def partial_case():
    """Construct the serialized envelope of an interrupted, unchecked batch."""
    return FactoryCase(
        json.dumps(
            {
                "schema": "nadit.factory_case/1",
                "case_id": "fixed-export-fixture",
                "seed": 17,
                "code": "test_fixture.code",
                "goal": "factory_output_to_t",
                "status": "input_supply_exhausted",
                "failure": {"stage": "raw", "detail": "Fixture supply exhausted"},
                "duration_us": 12,
                "recipe": {
                    "protocol_id": "test_fixture.factory",
                    "version": "1",
                    "final_event": {"key": "final/event"},
                },
                "calls": [],
                "events": [],
                "probability_models": {},
                "milestones": [{"kind": "batch_started", "batch": 0, "at_us": 0}],
                "resources": {"tokens": []},
                "output_token_id": None,
                "algorithm_consumed_token_id": None,
            }
        ),
        None,
    )


def test_export_automatically_writes_ledger_and_exact_case_hash(tmp_path):
    case = partial_case()
    before = case.to_json()
    manifest = {
        "scenario": "test_fixture",
        "source_files_sha256": {"fixture.py": "known-source-digest"},
        "scopes": {"physical_failure_fixture": False},
        "files_sha256": {},
    }
    output = tmp_path / "run"
    _export(case, manifest, output)
    record = json.loads((output / "experiment.json").read_text(encoding="utf-8"))
    exported_manifest = json.loads(
        (output / "manifest.json").read_text(encoding="utf-8")
    )
    case_hash = hashlib.sha256((output / "case.json").read_bytes()).hexdigest()
    assert case.to_json() == before
    assert (output / "case.json").read_text(encoding="utf-8") == before
    assert record["schema"] == "nadit.factory_experiment_ledger/2"
    assert record["case_status"] == "input_supply_exhausted"
    assert record["factory_final_accepted"] is None
    assert record["logical_success"] is None
    assert record["source_provenance"]["artifact_files_sha256"] == {
        "case.json": case_hash
    }
    assert record["source_provenance"]["source_files_sha256"] == {
        "fixture.py": "known-source-digest"
    }
    assert record["metadata"]["files_sha256"] == {"case.json": case_hash}
    assert set(exported_manifest["files_sha256"]) == {"case.json", "experiment.json"}
    for name, expected in exported_manifest["files_sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    assert manifest == exported_manifest


def test_export_does_not_overwrite_an_existing_experiment(tmp_path):
    case = partial_case()
    manifest = {"scenario": "test_fixture", "files_sha256": {}}
    output = tmp_path / "run"
    _export(case, manifest, output)
    before = {path.name: path.read_bytes() for path in output.iterdir()}
    with pytest.raises(FileExistsError):
        _export(case, manifest, output)
    assert {path.name: path.read_bytes() for path in output.iterdir()} == before
