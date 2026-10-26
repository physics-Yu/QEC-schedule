"""Readback-only comparison, exact startup marks and inspectable SVG output."""

import copy
import json
import re
import xml.etree.ElementTree as ET

import pytest

from modules.logical_compiler.examples.parallel_report import write_parallel_comparison


def test_report_shows_actual_embedded_aod_inventory(tmp_path):
    serial, parallel = _case("serial"), _case("parallel")
    for case in (serial, parallel):
        case["physical"]["device"] = {"aods": [{"id": "transport"}]}
    result = write_parallel_comparison(serial, parallel, tmp_path)
    for mode in ("serial", "parallel"):
        assert result["modes"][mode]["aod_ids"] == ["transport"]
        assert result["modes"][mode]["aod_count"] == 1
    assert "AOD inventory: 1" in (tmp_path / "index.html").read_text("utf-8")


def _case(mode):
    roles = ["W1", "W2", "W3", "W4", "W5"]
    calls, events = [], []
    marks = [{"kind": "batch_started", "batch": 0, "at_us": 0}]

    def attempt(role, number, start, end, accepted, canonical_end=None):
        identity = f"factory/batch[0]/initial/{role}"
        body = f"{identity}/attempt[{number}]"
        component = "initialize_plus" if role == "W1" else "raw_t_postselection"
        calls.append(
            {
                "invocation_id": body + "/body",
                "component_id": component,
                "participant_roles": [role],
                "start_us": start,
                "end_us": end,
            }
        )
        events.append(
            {
                "occurrence": {
                    "case_id": "pair",
                    "invocation_id": identity,
                    "attempt": number,
                    "port_id": "test_fixture.preparation",
                },
                "available_at_us": end + 1,
                "released_at_us": end + 1,
                "outcome_key": "accepted" if accepted else "rejected",
                "values": {"accepted": accepted},
            }
        )
        marks.append(
            {
                "kind": "preparation_decision",
                "preparation": identity,
                "at_us": end + 1,
                "accepted": accepted,
                "attempt": number,
            }
        )
        if accepted:
            canonical_end = end + 2 if canonical_end is None else canonical_end
            calls.append(
                {
                    "invocation_id": body + "/canonicalize",
                    "component_id": component + "/canonicalize",
                    "participant_roles": [role],
                    "start_us": canonical_end - 1,
                    "end_us": canonical_end,
                }
            )
            marks.append(
                {
                    "kind": "preparation_canonicalized",
                    "preparation": identity,
                    "attempt": number,
                    "at_us": canonical_end,
                }
            )

    attempt("W1", 0, 0, 1, True, 3)
    if mode == "serial":
        attempt("W2", 0, 3, 13, True, 15)
        attempt("W3", 0, 15, 25, False)
        attempt("W3", 1, 26, 36, True, 38)
        attempt("W4", 0, 38, 48, True, 50)
        attempt("W5", 0, 50, 60, True, 62)
        ready = 62
    else:
        attempt("W2", 0, 3, 13, True, 15)
        attempt("W3", 0, 3, 13, False)
        attempt("W4", 0, 3, 13, True, 16)
        attempt("W5", 0, 3, 13, True, 17)
        attempt("W3", 1, 17, 27, True, 29)
        ready = 29
    calls.extend(
        [
            {
                "invocation_id": "factory/batch[0]/rotation[0]/s",
                "component_id": "logical_s",
                "participant_roles": ["W1"],
                "start_us": ready + 1,
                "end_us": ready + 2,
            },
            {
                "invocation_id": "algorithm/output-consumption/s",
                "component_id": "logical_s",
                "participant_roles": ["W2"],
                "start_us": ready + 7,
                "end_us": ready + 8,
            },
        ]
    )
    events.append(
        {
            "occurrence": {
                "case_id": "pair",
                "invocation_id": "factory/batch[0]/final/event",
                "attempt": 0,
                "port_id": "test_fixture.proxy",
            },
            "available_at_us": ready + 5,
            "released_at_us": ready + 5,
            "outcome_key": "accepted",
            "values": {"accepted": True},
            "port_sha256": "test_fixture_hash",
        }
    )
    marks.extend(
        [
            {"kind": "initial_preparations_ready", "at_us": ready, "roles": roles},
            {"kind": "factory_output_ready", "at_us": ready + 6},
            {"kind": "algorithm_t_complete", "at_us": ready + 8},
        ]
    )
    return {
        "schema": "nadit.factory_case/1",
        "case_id": "pair",
        "seed": 11,
        "code": "test_fixture",
        "status": "complete",
        "duration_us": ready + 10,
        "recipe": {
            "protocol_id": "test_fixture.factory",
            "version": "1",
            "initial_preparations": [
                {"key": f"initial/{role}", "role": role} for role in roles
            ],
            "final_event": {"key": "final/event"},
        },
        "calls": calls,
        "events": events,
        "milestones": marks,
        "resources": {"tokens": []},
        "component_schedule": {"policy": {"mode": mode}},
        "physical": {"validation": {"ok": True}},
        "reference_parameters": {"profile": "test_fixture"},
        "limits": {"batches": 1},
        "probability_models": {
            "test_fixture_hash": {
                "model": {"kind": "test_fixture"},
                "outcomes": [
                    {"probability": 0.4, "values": {"accepted": True}},
                    {"probability": 0.6, "values": {"accepted": False}},
                ],
            }
        },
    }


def test_readback_counts_retries_hold_and_real_overlap_without_mutating_inputs(
    tmp_path,
):
    serial, parallel = _case("serial"), _case("parallel")
    before = copy.deepcopy((serial, parallel))
    evaluation = {
        "case_id": "pair",
        "seed": 11,
        "status": "evaluated",
        "proxy_success": False,
        "logical_success": None,
    }
    result = write_parallel_comparison(
        serial, parallel, tmp_path, parallel_evaluation=evaluation
    )
    assert (serial, parallel) == before
    a, b = result["modes"]["serial"], result["modes"]["parallel"]
    assert (a["duration_us"], b["duration_us"]) == (72, 39)
    assert (a["startup_ready_us"], b["startup_ready_us"]) == (62, 29)
    assert a["raw_attempts"] == b["raw_attempts"] == 5
    assert a["raw_rejections"] == b["raw_rejections"] == 1
    assert a["factory_s_calls"] == b["algorithm_s_calls"] == 1
    assert a["startups"][0]["peak_raw_concurrency"] == 1
    assert b["startups"][0]["peak_raw_concurrency"] == 4
    assert {hold["role"] for hold in b["startups"][0]["holds"]} == {
        "W1",
        "W2",
        "W4",
        "W5",
    }
    assert b["terminal_evaluation"] == evaluation
    assert a["terminal_evaluation"] is None
    assert result["logical_success"] is None
    assert b["batch_decisions"][0]["acceptance_probability"] == 0.4
    assert json.loads((tmp_path / "comparison.json").read_text("utf-8")) == result
    page = (tmp_path / "index.html").read_text("utf-8")
    assert 'href="serial/index.html"' in page and 'href="parallel/index.html"' in page
    assert "raw retry 1" in page and "Logical success: unknown" in page
    for svg in re.findall(r"<svg\b.*?</svg>", page, flags=re.DOTALL):
        ET.fromstring(svg)
    assert len(re.findall(r"<svg\b", page)) == 2
    assert len(re.findall(r"data-call-id=", page)) == 22
    assert len(result["inputs"]["serial_case_sha256"]) == 64


@pytest.mark.parametrize(
    "key,value",
    [("seed", 12), ("case_id", "different"), ("code", "other"), ("recipe", {})],
)
def test_identity_mismatch_fails_before_output(tmp_path, key, value):
    serial, parallel = _case("serial"), _case("parallel")
    parallel[key] = value
    with pytest.raises(ValueError, match="IDENTITY_MISMATCH"):
        write_parallel_comparison(serial, parallel, tmp_path / "new")
    assert not (tmp_path / "new").exists()


def test_modes_evaluation_identity_and_nonfinite_times_are_rejected(tmp_path):
    with pytest.raises(ValueError):
        write_parallel_comparison(_case("serial"), _case("serial"), tmp_path)
    with pytest.raises(ValueError, match="EVALUATION_IDENTITY"):
        write_parallel_comparison(
            _case("serial"),
            _case("parallel"),
            tmp_path,
            serial_evaluation={"case_id": "pair", "seed": 12},
        )
    bad = _case("parallel")
    bad["calls"][0]["start_us"] = float("nan")
    with pytest.raises(ValueError):
        write_parallel_comparison(_case("serial"), bad, tmp_path)


def test_existing_viewers_are_preserved_and_existing_report_is_not_overwritten(
    tmp_path,
):
    (tmp_path / "serial").mkdir()
    (tmp_path / "serial/index.html").write_text("original viewer")
    write_parallel_comparison(_case("serial"), _case("parallel"), tmp_path)
    before = (tmp_path / "comparison.json").read_bytes()
    with pytest.raises(FileExistsError):
        write_parallel_comparison(_case("serial"), _case("parallel"), tmp_path)
    assert (tmp_path / "comparison.json").read_bytes() == before
    assert (tmp_path / "serial/index.html").read_text() == "original viewer"


def test_incomplete_startup_never_invents_ready_and_html_escapes_input(tmp_path):
    serial, parallel = _case("serial"), _case("parallel")
    for case in (serial, parallel):
        case["case_id"] = "<script>alert(1)</script>"
        case["status"] = "input_supply_exhausted"
        case["milestones"] = [
            mark
            for mark in case["milestones"]
            if not (
                mark["kind"] == "preparation_canonicalized"
                and mark.get("preparation", "").endswith("W5")
            )
        ]
    result = write_parallel_comparison(serial, parallel, tmp_path)
    assert result["modes"]["serial"]["startup_ready_us"] is None
    assert result["modes"]["parallel"]["startup_ready_us"] is None
    page = (tmp_path / "index.html").read_text("utf-8")
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
