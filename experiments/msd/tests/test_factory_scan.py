"""The saved schedule must contain actual kernel times and resource leases."""

import csv
import json

from experiments.msd.generic_factory import scan
from modules.codes.rotated_surface.tests.test_generic_fast_factory import (
    fixture_profile,
)


def test_scan_exports_execution_schedule_and_hardware_control(tmp_path):
    document = fixture_profile(3, 1).to_dict()
    document.update(
        standard="nadit.msd.standard/2",
        timing={
            "load_us": 10,
            "store_us": 10,
            "measure_us": 100,
            "result_processing_us": 0,
        },
    )
    profiles = tmp_path / "profiles"
    cell = profiles / "d3-n1"
    cell.mkdir(parents=True)
    (cell / "profile.json").write_text(json.dumps(document), encoding="utf-8")
    output = tmp_path / "results"
    report = scan(
        profiles,
        output,
        {
            "standard": "nadit.msd.standard/2",
            "distances": [3],
            "factory_counts": [1],
            "seeds": [0],
            "witness_seed": 0,
            "input_z_error": 0,
            "limits": {"raw_attempts": 2, "batches": 1},
        },
    )
    assert len(report["results"]) == 2
    for row in report["results"]:
        case = json.loads((output / row["witness"]).read_text(encoding="utf-8"))
        calls = case["execution"]["calls"]
        path = output / row["witness"].replace(".case.json", ".schedule.csv")
        with path.open(encoding="utf-8", newline="") as stream:
            records = list(csv.DictReader(stream))
        assert len(records) == len(calls)
        assert len({record["invocation"] for record in records}) == len(records)
        assert any(record["reserved_resources"] for record in records)
        assert row["outputs"] == 1
        for record, call in zip(records, calls, strict=True):
            assert float(record["start_us"]) == call["start_us"]
            assert float(record["action_end_us"]) == call["action_end_us"]
            assert record["blocks"].split(";") == call["participant_blocks"]


def test_existing_scan_dispatches_joint_profiles_to_single_shared_aod(tmp_path):
    from modules.codes.rotated_surface.tests.test_joint_factory_profile import (
        SyntheticJointProfile,
        joint_fixture,
    )
    from modules.logical_compiler.examples.surface_factory_fast import (
        run_surface_factory,
    )

    profile = SyntheticJointProfile(joint_fixture(1))
    run_surface_factory(profile, seed=0, input_z_error=0)
    document = profile.to_dict()
    document.update(
        standard="nadit.msd.standard/2",
        timing={
            "load_us": 10,
            "store_us": 10,
            "measure_us": 100,
            "result_processing_us": 0,
        },
    )
    path = tmp_path / "profiles" / "d5-n1"
    path.mkdir(parents=True)
    (path / "profile.json").write_text(json.dumps(document), encoding="utf-8")
    report = scan(
        path.parent,
        tmp_path / "results",
        {
            "standard": "nadit.msd.standard/2",
            "distances": [5],
            "factory_counts": [1],
            "seeds": [0],
            "witness_seed": 0,
            "input_z_error": 0,
            "limits": {"raw_attempts": 8, "batches": 1},
        },
    )
    assert len(report["results"]) == 1
    assert report["results"][0]["hardware"] == "shared_aod"
    case = json.loads(
        (tmp_path / "results" / report["results"][0]["witness"]).read_text()
    )
    assert all(
        c["parallel_mode"] == "shared_aod_lockstep" for c in case["execution"]["calls"]
    )
    assert "joint" in report["shared_hardware_policy"]
