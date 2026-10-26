"""Array playback reveals decisions and token ownership only at their audit times."""

import json
import re
from copy import deepcopy

import pytest

from modules.logical_compiler.examples.array_report import (
    _chart_data,
    report_state_at,
    write_array_report,
)
from modules.logical_compiler.src.protocols.array_ledger import build_array_ledger
from modules.logical_compiler.tests.test_array_ledger import example


@pytest.fixture
def ledger():
    result = build_array_ledger(example())
    result["duration_us"] = 8
    first = result["lines"]["factory0"]
    first["completed_at_us"] = 8
    first["state_intervals"][-1].update(state="running", start_us=5, end_us=8)
    first["state_intervals"].append(
        {"start_us": 8, "end_us": 8, "state": "complete", "reason": "terminal"}
    )
    first["algorithm_consumed_token_id"] = first["output_token_id"]
    first["output_status"] = "consumed"
    result["resources"]["audit"].extend(
        [
            {
                "action": "reserve",
                "at_us": 6,
                "token_id": first["output_token_id"],
                "consumer": "algorithm",
            },
            {
                "action": "consume",
                "at_us": 6.5,
                "token_id": first["output_token_id"],
                "usage_kind": "consume",
                "safe_exit_at_us": 8,
            },
        ]
    )
    raw = "factory0/batch[0]/raw"
    result["calls"] = [
        {
            "factory_id": "factory0",
            "invocation_id": raw + "/attempt[0]/body",
            "component_id": "raw_t_postselection",
            "participant_roles": ["W1"],
            "start_us": 0,
            "end_us": 1,
        },
        {
            "factory_id": "factory0",
            "invocation_id": raw + "/attempt[1]/body",
            "component_id": "raw_t_postselection",
            "participant_roles": ["W1"],
            "start_us": 2,
            "end_us": 3,
        },
        {
            "factory_id": "factory0",
            "invocation_id": "factory0/S",
            "component_id": "logical_s",
            "participant_roles": ["W1"],
            "start_us": 4,
            "end_us": 4.5,
        },
    ]
    result["events"] = [
        {
            "occurrence": {"invocation_id": raw, "attempt": 0},
            "released_at_us": 1.5,
            "available_at_us": 1,
            "values": {"accepted": False},
            "branch_id": "retry",
        },
        {
            "occurrence": {"invocation_id": raw, "attempt": 1},
            "released_at_us": 4,
            "available_at_us": 3,
            "values": {"accepted": True, "m": 1},
            "branch_id": "accept",
        },
    ]
    return result


def test_early_playback_hides_future_output_failure_and_decisions(ledger):
    early = report_state_at(ledger, 2)
    assert early["resources"]["tokens"] == []
    assert early["lines"]["factory0"]["output"] is None
    assert early["lines"]["factory1"]["failure"] is None
    assert early["lines"]["factory1"]["terminal_status"] is None
    assert early["lines"]["factory0"]["factory_accepted"] is None
    assert early["lines"]["factory0"]["raw_rejections"] == 1
    assert early["lines"]["factory0"]["raw_accepted"] == 0
    assert early["lines"]["factory0"]["s_calls"] == 0
    assert early["lines"]["factory0"]["state"] == "waiting_peers"
    assert early["lines"]["factory0"]["stage_key"] == "initial"


def test_output_offered_reserved_and_consumed_are_distinct_time_states(ledger):
    assert report_state_at(ledger, 4.9)["lines"]["factory0"]["output"] is None
    assert (
        report_state_at(ledger, 5)["lines"]["factory0"]["output"]["status"] == "offered"
    )
    assert (
        report_state_at(ledger, 6)["lines"]["factory0"]["output"]["status"]
        == "reserved"
    )
    final = report_state_at(ledger, 8)
    assert final["lines"]["factory0"]["output"]["status"] == "consumed"
    assert final["lines"]["factory0"]["algorithm_consumed"] is True
    assert final["lines"]["factory1"]["failure"]["code"] == "distillation_rejected"


def test_feedback_uses_release_time_and_s_correction_is_not_early(ledger):
    assert report_state_at(ledger, 3.9)["lines"]["factory0"]["raw_accepted"] == 0
    now = report_state_at(ledger, 4)["lines"]["factory0"]
    assert now["raw_accepted"] == 1 and now["s_calls"] == 1
    assert now["raw_attempts"] == 2


def test_chart_data_is_stable_and_snapshots_follow_boundaries(ledger):
    before = deepcopy(ledger)
    data = _chart_data(ledger, {"aod_max_rows": 4})
    assert data == _chart_data(deepcopy(ledger), {"aod_max_rows": 4})
    assert ledger == before
    assert data["times"] == sorted(set(data["times"]))
    assert {0, 1.5, 2, 4, 5, 6, 6.5, 8} <= set(data["times"])
    assert data["frames"][0]["resources"]["tokens"] == []
    assert data["frames"][-1]["lines"]["factory0"]["output"]["status"] == "consumed"
    # Older audits timestamp offer at the start of its physical correction.
    earlier_offer = deepcopy(ledger)
    next(e for e in earlier_offer["resources"]["audit"] if e["action"] == "offer")[
        "at_us"
    ] = 4
    corrected = _chart_data(earlier_offer, {})
    assert (
        next(f for f in corrected["frames"] if f["at_us"] == 4)["resources"]["tokens"]
        == []
    )
    assert (
        next(f for f in corrected["frames"] if f["at_us"] == 5)["lines"]["factory0"][
            "output"
        ]["status"]
        == "offered"
    )


def test_exports_self_contained_links_readable_report_and_safe_embedded_data(
    ledger, tmp_path
):
    ledger["case_id"] = "<script>alert('fixture')</script>"
    write_array_report(ledger, tmp_path, budget={"aod_max_columns": 48})
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    for link in (
        "atom-replay.html",
        "case.json",
        "array-ledger.json",
        "resource-events.jsonl",
    ):
        assert f'href="{link}"' in page
    assert 'id="time"' in page and 'value="0"' in page
    assert "waiting_peers" in page and "Stage barrier" in page
    assert "<script>alert('fixture')</script>" not in page
    payload = re.search(
        r'<script id="report-data" type="application/json">(.*?)</script>',
        page,
        re.DOTALL,
    )
    data = json.loads(payload.group(1))
    assert data["case_id"] == ledger["case_id"]
    assert "Final case summary" in text and "not logical success" in text
    assert "offered" in text and "consumed" in text


def test_invalid_time_or_schema_is_rejected_before_writing(ledger, tmp_path):
    with pytest.raises(ValueError):
        report_state_at(ledger, 9)
    ledger["schema"] = "wrong"
    with pytest.raises(ValueError, match="SCHEMA"):
        write_array_report(ledger, tmp_path / "invalid", budget={})
    assert not (tmp_path / "invalid").exists()


def test_theory_report_separates_joint_checks_quality_and_cost(ledger, tmp_path):
    ledger["factory_acceptance_kind"] = "theoretical_iid_z"
    ledger["experiment_model"] = {
        "mode": "theory",
        "input_z_error": 0.01,
        "theoretical_acceptance_probability": 0.860090333670424,
        "conditional_output_z_error": 3.6087683965e-5,
    }
    write_array_report(ledger, tmp_path, budget={})
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (
        "Joint theoretical MX checks" in page and "Joint theoretical MX checks" in text
    )
    assert "p = 0.01" in page and "p = 0.01" in text
    assert "Physical no-fault cost does not control acceptance" in page
    assert "raw physical loss" in text
    assert 'href="physical-costs.json"' in page
    assert "Factory acceptance is a physical no-fault proxy" not in text
