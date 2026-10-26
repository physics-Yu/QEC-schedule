"""Frozen pilot policy and immutable no-atom trajectory artifact handling."""

import gzip
import json
from copy import deepcopy
from pathlib import Path

import pytest

from experiments.msd import single_fast as runner
from modules.logical_compiler.src.protocols.production import ProductionPolicy

CONFIG = (
    Path(__file__).resolve().parents[3]
    / "experiments/msd/single-level-fast-20261025.json"
)


def test_gzip_identity_is_independent_of_filename_and_has_zero_mtime(tmp_path):
    first, second = tmp_path / "one.gz", tmp_path / "two.gz"
    document = {"seed": 7, "order": [2, 1], "values": {"b": 2, "a": 1}}
    runner._gzip_json(first, document)
    runner._gzip_json(second, document)
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes()[4:8] == bytes(4)
    assert json.loads(gzip.decompress(first.read_bytes())) == document
    with pytest.raises(FileExistsError):
        runner._gzip_json(first, document)


def test_pilot_window_is_frozen_from_separate_two_cycle_time():
    config = runner.load_configuration(CONFIG)
    pilot = {
        "status": "complete",
        "metrics": {
            "case_duration_us": 100.0,
            "requested_window_complete": True,
            "delivered_outputs_total": 4,
        },
    }
    policy = runner.freeze_observation(pilot, config, 2)
    assert policy["warmup_us"] == 50
    assert policy["stop_us"] == 850
    changed = deepcopy(config)
    changed["observation"]["target_cycles"] = 3
    assert runner.freeze_observation(pilot, changed, 2)["stop_us"] == 200
    pilot["status"] = "failed"
    with pytest.raises(ValueError, match="CELL_EXCLUDED"):
        runner.freeze_observation(pilot, config, 2)


@pytest.mark.parametrize(
    "field,value",
    (
        ("cost_basis", None),
        ("physical_compilation_allowed_in_fast_run", True),
        ("pilot_seed", 0),
    ),
)
def test_configuration_rejects_unapproved_or_nonindependent_model(
    tmp_path, field, value
):
    document = json.loads(CONFIG.read_text(encoding="utf-8"))
    document[field] = value
    path = tmp_path / "config.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError):
        runner.load_configuration(path)


def _fake_execution(*args, **kwargs):
    return {
        "case": {"status": "complete", "seed": 0},
        "ledger": {"counts": {"accepted_outputs": 2}},
        "summary": {
            "status": "complete",
            "lines": {},
            "profile_sha256": "fixture",
            "distance": 3,
            "factory_count": 1,
            "seed": 0,
        },
        "metrics": {
            "accepted_outputs": 2,
            "requested_window_complete": True,
            "distance": 3,
            "factory_count": 1,
            "seed": 0,
        },
        "guard": {"passed": True, "intercepted_call_count": 0},
        "profile": {"fixture": True},
    }


def test_resume_reuses_only_hash_verified_complete_artifacts(tmp_path, monkeypatch):
    calls = []

    def execute(*args, **kwargs):
        calls.append(1)
        return _fake_execution()

    monkeypatch.setattr(runner, "_execute", execute)
    monkeypatch.setattr(runner, "source_manifest", lambda: {"sha256": "source"})
    context = {"identity": {"source_sha256": "source"}}
    first = runner._run_once(context, tmp_path, 3, 1, 0, ProductionPolicy(2))
    assert runner._run_once(context, tmp_path, 3, 1, 0, ProductionPolicy(2)) == first
    assert calls == [1]
    case_path = tmp_path / first["attempt"] / "case.json.gz"
    case_path.write_bytes(case_path.read_bytes() + b"corrupt")
    with pytest.raises(ValueError, match="ARTIFACT_HASH_MISMATCH"):
        runner._run_once(context, tmp_path, 3, 1, 0, ProductionPolicy(2))
    assert calls == [1]


def test_incomplete_attempt_is_preserved_on_resume(tmp_path, monkeypatch):
    old = tmp_path / "attempt-0001"
    old.mkdir()
    (old / "interrupted.txt").write_text("original", encoding="utf-8")
    monkeypatch.setattr(runner, "_execute", _fake_execution)
    monkeypatch.setattr(runner, "source_manifest", lambda: {"sha256": "source"})
    result = runner._run_once(
        {"identity": {"source_sha256": "source"}},
        tmp_path,
        3,
        1,
        0,
        ProductionPolicy(2),
    )
    assert result["attempt"] == "attempt-0002"
    assert (old / "interrupted.txt").read_text(encoding="utf-8") == "original"


def test_source_drift_preserves_failure_without_publishing_completion(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "_execute", _fake_execution)
    monkeypatch.setattr(runner, "source_manifest", lambda: {"sha256": "changed"})
    with pytest.raises(ValueError, match="SOURCE_CHANGED"):
        runner._run_once(
            {"identity": {"source_sha256": "source"}},
            tmp_path,
            3,
            1,
            0,
            ProductionPolicy(2),
        )
    assert not (tmp_path / "completion.json").exists()
    assert (
        json.loads((tmp_path / "attempt-0001/error.json").read_text())["error_type"]
        == "ValueError"
    )


def test_existing_manifest_rejects_changed_configuration(tmp_path, monkeypatch):
    monkeypatch.setattr(
        runner, "source_manifest", lambda: {"sha256": "source", "files": {}}
    )
    output = tmp_path / "output"
    runner._initialize(CONFIG, output)
    document = runner.load_configuration(CONFIG)
    document["s"]["duration_us"] = 2.0
    changed = tmp_path / "changed.json"
    changed.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="RESUME_IDENTITY_MISMATCH"):
        runner._initialize(changed, output)


def _smoke_fixture():
    calls = [
        {
            "component_id": "raw_t_postselection",
            "invocation_id": f"factory0/cycle[0]/batch[0]/initial/{role}/attempt[0]/body",
        }
        for role in ("W2", "W3", "W4", "W5")
    ]
    return {
        "status": "complete",
        "physical": None,
        "execution_representation": "logical_estimate",
        "calls": calls,
        "execution": {
            "calls": calls,
            "waves": [
                {"batch_id": "wave", "invocations": [c["invocation_id"] for c in calls]}
            ],
        },
        "factories": {
            "factory0": {"outputs": [{"token_id": "output0"}], "milestones": []}
        },
        "resources": {"audit": [{"action": "consume", "token_id": "output0"}]},
    }


def test_smoke_checks_real_wave_membership_and_unique_output_consumption():
    config = runner.load_configuration(CONFIG)
    config["ec"] = {"mode": "preparation_only", "rounds": 0}
    case = _smoke_fixture()
    ledger = {"counts": {"raw_rejections": 1}}
    assert runner.smoke_invariants(case, ledger, config, 3)["passed"]
    case["resources"]["audit"].append({"action": "consume", "token_id": "output0"})
    with pytest.raises(ValueError, match="CONSUMPTION_NOT_UNIQUE"):
        runner.smoke_invariants(case, ledger, config, 3)


def test_smoke_rejects_serial_initial_raw_even_with_same_seed():
    config = runner.load_configuration(CONFIG)
    case = _smoke_fixture()
    case["execution"]["waves"] = [
        {"batch_id": f"wave{i}", "invocations": [c["invocation_id"]]}
        for i, c in enumerate(case["calls"])
    ]
    with pytest.raises(ValueError, match="INITIAL_RAW_NOT_PARALLEL"):
        runner.smoke_invariants(case, {"counts": {"raw_rejections": 1}}, config, 3)


def test_smoke_reads_kernel_receipt_times_for_assumed_s():
    config = runner.load_configuration(CONFIG)
    config["ec"] = {"mode": "preparation_only", "rounds": 0}
    case = _smoke_fixture()
    correction = {
        "component_id": "assumed_transversal_s",
        "invocation_id": "correction",
        "start_us": 10.0,
        "action_end_us": 10.0 + config["s"]["duration_us"],
    }
    case["calls"].append(correction)
    ledger = {"counts": {"raw_rejections": 1}}
    assert runner.smoke_invariants(case, ledger, config, 3)["passed"]
    correction["action_end_us"] += 1
    with pytest.raises(ValueError, match="S_DURATION_DIFFERS"):
        runner.smoke_invariants(case, ledger, config, 3)


@pytest.mark.parametrize(
    "last_window,status,recorded",
    (
        (True, "complete", True),
        (False, "partial_failure", True),
        (None, "incomplete", False),
    ),
)
def test_report_distinguishes_recorded_failure_from_complete_windows(
    tmp_path, monkeypatch, last_window, status, recorded
):
    config = {"distances": [3], "factory_counts": [1], "production_seeds": [0, 1]}
    monkeypatch.setattr(
        runner,
        "_initialize",
        lambda *args: {"config": config, "identity": {"fixture": "source"}},
    )

    def completion(path, identity):
        complete = True if path.name == "seed-0000" else last_window
        return (
            None
            if complete is None
            else {
                "distance": 3,
                "factory_count": 1,
                "seed": int(path.name[-4:]),
                "metrics": {
                    "requested_window_complete": complete,
                    "distance": 3,
                    "factory_count": 1,
                    "seed": int(path.name[-4:]),
                },
            }
        )

    monkeypatch.setattr(runner, "_verified_completion", completion)
    monkeypatch.setattr(
        runner,
        "summarize_center_samples",
        lambda rows: {
            "complete_seed_count": sum(
                row["requested_window_complete"] for row in rows
            ),
            "statistics": {},
        },
    )
    result = runner.summarize_campaign(CONFIG, tmp_path)
    assert result["cells"][0]["status"] == status
    assert result["all_trajectories_recorded"] is recorded
    assert result["all_observation_windows_complete"] is (status == "complete")


def test_completion_metrics_cannot_override_hash_checked_metrics_file(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner, "_execute", _fake_execution)
    monkeypatch.setattr(runner, "source_manifest", lambda: {"sha256": "source"})
    context = {"identity": {"source_sha256": "source"}}
    runner._run_once(context, tmp_path, 3, 1, 0, ProductionPolicy(2))
    path = tmp_path / "completion.json"
    record = json.loads(path.read_text())
    record["metrics"]["accepted_outputs"] = 999
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(ValueError, match="COMPLETION_CONTENT_MISMATCH"):
        runner._verified_completion(tmp_path, context["identity"])


@pytest.mark.parametrize("seed,cycles", ((1, 2), (0, 3)))
def test_existing_result_rejects_foreign_seed_or_cycle_policy(
    tmp_path, monkeypatch, seed, cycles
):
    monkeypatch.setattr(runner, "_execute", _fake_execution)
    monkeypatch.setattr(runner, "source_manifest", lambda: {"sha256": "source"})
    context = {"identity": {"source_sha256": "source"}}
    runner._run_once(context, tmp_path, 3, 1, 0, ProductionPolicy(2))
    with pytest.raises(ValueError, match="TASK_IDENTITY_MISMATCH"):
        runner._run_once(context, tmp_path, 3, 1, seed, ProductionPolicy(cycles))


def test_report_recovers_missing_csv_without_overwriting_json(tmp_path, monkeypatch):
    config = {"distances": [3], "factory_counts": [1], "production_seeds": [0]}
    monkeypatch.setattr(
        runner,
        "_initialize",
        lambda *args: {"config": config, "identity": {"fixture": "source"}},
    )
    monkeypatch.setattr(runner, "_verified_completion", lambda *args: None)
    first = runner.summarize_campaign(CONFIG, tmp_path)
    folder = Path(first["report_directory"])
    json_bytes = (folder / "summary.json").read_bytes()
    csv_bytes = (folder / "summary.csv").read_bytes()
    (folder / "summary.csv").unlink()
    second = runner.summarize_campaign(CONFIG, tmp_path)
    assert second == first
    assert (folder / "summary.json").read_bytes() == json_bytes
    assert (folder / "summary.csv").read_bytes() == csv_bytes
