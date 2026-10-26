"""Readback accounting with explicit, manually specified partial-case evidence."""

import csv
import json
from copy import deepcopy

import pytest

from modules.logical_compiler.src.protocols.experiment_ledger import (
    build_ledger_record,
    write_ledger,
)


def manual_case():
    """One accepted batch followed by a failed algorithm S compilation."""
    return {
        "schema": "nadit.factory_case/1",
        "case_id": "fixed-experiment-case",
        "seed": 7,
        "code": "test_fixture.code",
        "goal": "factory_output_to_t",
        "status": "physical_failure",
        "failure": {"stage": "algorithm/s", "detail": "Explicit fixture failure"},
        "duration_us": 30,
        "recipe": {
            "protocol_id": "test_fixture.factory",
            "version": "1",
            "final_event": {"key": "final/event"},
        },
        "calls": [
            {
                "invocation_id": "factory/batch[0]/raw/attempt[0]/body",
                "component_id": "raw_t_postselection",
            },
            {
                "invocation_id": "factory/batch[0]/raw/attempt[1]/body",
                "component_id": "raw_t_postselection",
            },
            {
                "invocation_id": "factory/batch[0]/raw/attempt[1]/canonicalize",
                "component_id": "raw_t_postselection/canonicalize",
            },
            {
                "invocation_id": "factory/batch[0]/consume/s",
                "component_id": "logical_s",
            },
            {
                "invocation_id": "algorithm/consume/cx",
                "component_id": "transversal_cnot",
            },
        ],
        "events": [
            {
                "occurrence": {"invocation_id": "factory/batch[0]/consume/event"},
                "outcome_key": "m1",
                "values": {"logical_m": 1},
                "port_sha256": "t-model",
            },
            {
                "occurrence": {"invocation_id": "factory/batch[0]/final/event"},
                "outcome_key": "accepted",
                "values": {"accepted": True, "check": 0},
                "port_sha256": "final-model",
                "released_at_us": 20,
            },
            {
                "occurrence": {"invocation_id": "algorithm/consume/event"},
                "outcome_key": "m1",
                "values": {"logical_m": 1},
                "port_sha256": "t-model",
            },
        ],
        "probability_models": {
            "final-model": {
                "model": {"id": "assumed_final", "kind": "pauli_exact"},
                "outcomes": [
                    {
                        "key": "accepted",
                        "probability": 0.75,
                        "values": {"accepted": True},
                    },
                    {
                        "key": "rejected",
                        "probability": 0.25,
                        "values": {"accepted": False},
                    },
                ],
            },
            "t-model": {"model": {"id": "fair_t", "kind": "ideal_exact"}},
            "fixture-model": {
                "model": {"id": "explicit_fixture", "kind": "test_fixture"}
            },
        },
        "milestones": [
            {"kind": "batch_started", "batch": 0, "at_us": 0},
            {"kind": "batch_decision", "batch": 0, "accepted": True, "at_us": 20},
            {"kind": "factory_output_ready", "token_id": "output", "at_us": 21},
        ],
        "resources": {
            "tokens": [
                {
                    "token_id": "raw",
                    "producer": "factory/batch[0]/raw/attempt[1]/canonicalize",
                    "canonicalization": "canonical",
                    "status": "consumed",
                },
                {"token_id": "output", "producer": "factory/batch[0]/final/event"},
            ]
        },
        "output_token_id": "output",
        "algorithm_consumed_token_id": "output",
        "physical": {"validation": {"ok": True, "measurement_values_verified": False}},
    }


def test_counts_distinguish_requested_s_actual_calls_and_raw_tokens():
    record = build_ledger_record(manual_case())
    assert record["schema"] == "nadit.factory_experiment_ledger/2"
    assert record["counts"] == {
        "factory_s_calls": 1,
        "algorithm_s_calls": 0,
        "factory_s_requested": 1,
        "algorithm_s_requested": 1,
        "raw_preparation_attempts": 2,
        "raw_accepted_resources": 1,
        "batches_started": 1,
        "batches_checked": 1,
        "batches_accepted": 1,
        "batches_rejected": 0,
    }
    assert record["factory_final_accepted"] is True
    assert record["factory_output_ready"] is True
    assert record["algorithm_consumed"] is True
    assert record["algorithm_complete"] is False
    assert record["case_status"] == "physical_failure"
    assert record["physical_validation_ok"] is True
    assert record["logical_success"] is None


def test_final_probability_preserves_the_original_joint_port_and_observation():
    case = manual_case()
    record = build_ledger_record(case)
    batch = record["batches"][0]
    assert batch["batch"] == 0
    assert batch["accepted"] is True
    assert batch["acceptance_probability"] == 0.75
    assert batch["final_event"] == case["events"][1]
    assert batch["probability_port"] == case["probability_models"]["final-model"]
    assert batch["port_sha256"] == "final-model"
    batch["probability_port"]["outcomes"][0]["probability"] = 0
    assert (
        case["probability_models"]["final-model"]["outcomes"][0]["probability"] == 0.75
    )


def test_failure_before_first_check_is_unknown_not_rejected():
    case = manual_case()
    case.update(
        events=[],
        calls=[],
        output_token_id=None,
        algorithm_consumed_token_id=None,
        physical=None,
    )
    case["milestones"] = [{"kind": "batch_started", "batch": 0, "at_us": 0}]
    case["resources"] = {"tokens": []}
    record = build_ledger_record(case)
    assert record["factory_final_accepted"] is None
    assert record["batches"][0]["accepted"] is None
    assert record["batches"][0]["acceptance_probability"] is None
    assert record["counts"]["batches_checked"] == 0
    assert record["counts"]["batches_rejected"] == 0
    assert record["factory_output_ready"] is False
    assert record["physical_validation_ok"] is None


def test_rejected_batch_followed_by_incomplete_retry_has_no_false_final_result():
    case = manual_case()
    final = case["events"][1]
    final.update(outcome_key="rejected", values={"accepted": False, "check": 1})
    case["events"] = [final]
    case["milestones"] = [
        {"kind": "batch_started", "batch": 0, "at_us": 0},
        {"kind": "batch_decision", "batch": 0, "accepted": False, "at_us": 20},
        {"kind": "batch_started", "batch": 1, "at_us": 21},
    ]
    record = build_ledger_record(case)
    assert [batch["accepted"] for batch in record["batches"]] == [False, None]
    assert record["factory_final_accepted"] is None
    assert record["counts"]["batches_started"] == 2
    assert record["counts"]["batches_checked"] == 1
    assert record["counts"]["batches_rejected"] == 1


def test_rejected_then_accepted_batches_are_retained_separately():
    case = manual_case()
    first = deepcopy(case["events"][1])
    first.update(outcome_key="rejected", values={"accepted": False, "check": 1})
    second = deepcopy(case["events"][1])
    second["occurrence"]["invocation_id"] = "factory/batch[1]/final/event"
    case["events"] = [first, second]
    case["milestones"].append({"kind": "batch_started", "batch": 1, "at_us": 22})
    record = build_ledger_record(case)
    assert [batch["accepted"] for batch in record["batches"]] == [False, True]
    assert record["factory_final_accepted"] is True
    assert record["counts"]["batches_accepted"] == 1
    assert record["counts"]["batches_rejected"] == 1


def test_algorithm_milestone_does_not_override_final_physical_failure():
    case = manual_case()
    case["milestones"].append({"kind": "algorithm_t_complete", "at_us": 30})
    case["physical"] = None
    record = build_ledger_record(case)
    assert record["algorithm_complete"] is True
    assert record["case_status"] == "physical_failure"
    assert record["physical_validation_ok"] is None
    assert record["logical_success"] is None


def test_metadata_provenance_and_unknown_evaluation_are_copied_without_mutation():
    case = manual_case()
    metadata = {
        "experiment_id": "frozen-one",
        "run_id": "seed-7",
        "source_files_sha256": {"producer.py": "source-digest"},
        "source_revision": "abc123",
        "cost_profile": {"name": "declared-cost", "raw_acceptance": 0.75},
        "scopes": {"physical_failure_fixture": True},
    }
    originals = deepcopy((case, metadata))
    record = build_ledger_record(case, metadata)
    assert (case, metadata) == originals
    assert record["case_id"] == "fixed-experiment-case"
    assert record["seed"] == 7
    assert record["event_fixture"] is True
    assert record["physical_failure_fixture"] is True
    assert record["source_provenance"]["source_files_sha256"] == {
        "producer.py": "source-digest"
    }
    assert record["cost_profile"] == metadata["cost_profile"]
    assert record["algorithm_evaluation"] is None
    assert record["logical_success"] is None
    assert record["probability_model_hashes"] == [
        "final-model",
        "fixture-model",
        "t-model",
    ]
    record["cost_profile"]["name"] = "changed"
    assert metadata["cost_profile"]["name"] == "declared-cost"


def test_write_ledger_roundtrips_jsonl_and_csv_without_overwriting(tmp_path):
    record = build_ledger_record(manual_case(), {"run_id": "one"})
    destination = tmp_path / "new-ledger"
    paths = write_ledger([record], destination)
    assert set(paths) == {"jsonl", "csv"}
    with open(paths["jsonl"], encoding="utf-8") as stream:
        assert [json.loads(line) for line in stream] == [record]
    with open(paths["csv"], encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows[0]["factory_s_calls"] == "1"
    assert rows[0]["algorithm_s_calls"] == "0"
    assert rows[0]["logical_success"] == ""
    assert rows[0]["factory_final_accepted"] == "true"
    assert json.loads(rows[0]["batches_json"])[0]["acceptance_probability"] == 0.75
    before = (destination / "ledger.jsonl").read_bytes()
    with pytest.raises(FileExistsError):
        write_ledger([record], destination)
    assert (destination / "ledger.jsonl").read_bytes() == before


@pytest.mark.parametrize(
    "invalid",
    [
        {"schema": "other"},
        {"schema": "nadit.factory_experiment_ledger/2", "value": float("nan")},
    ],
)
def test_invalid_export_records_do_not_create_a_directory(tmp_path, invalid):
    destination = tmp_path / "must-not-exist"
    with pytest.raises(ValueError):
        write_ledger([invalid], destination)
    assert not destination.exists()


def test_wrong_case_schema_and_nonfinite_metadata_are_rejected():
    with pytest.raises(ValueError):
        build_ledger_record({"schema": "nadit.abstract_case/1"})
    with pytest.raises(ValueError):
        build_ledger_record(manual_case(), {"cost_profile": {"duration": float("nan")}})


def test_missing_final_model_retains_observed_acceptance_but_unknown_probability():
    case = manual_case()
    del case["probability_models"]["final-model"]
    record = build_ledger_record(case)
    assert record["factory_final_accepted"] is True
    assert record["batches"][0]["acceptance_probability"] is None
    assert record["batches"][0]["probability_port"] is None


def test_duplicate_final_events_are_rejected_instead_of_silently_replaced():
    case = manual_case()
    case["events"].append(deepcopy(case["events"][1]))
    with pytest.raises(ValueError, match="duplicate final event"):
        build_ledger_record(case)


def test_incomplete_ledger_record_is_rejected_before_directory_creation(tmp_path):
    destination = tmp_path / "missing-fields"
    with pytest.raises(ValueError, match="incomplete ledger"):
        write_ledger([{"schema": "nadit.factory_experiment_ledger/2"}], destination)
    assert not destination.exists()


def test_historical_v1_records_cannot_be_mixed_into_the_v2_ledger(tmp_path):
    record = build_ledger_record(manual_case())
    record["schema"] = "nadit.factory_experiment_ledger/1"
    with pytest.raises(ValueError, match="expected nadit.factory_experiment_ledger/2"):
        write_ledger([record], tmp_path / "mixed-versions")
    assert not (tmp_path / "mixed-versions").exists()
