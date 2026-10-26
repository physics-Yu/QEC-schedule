"""Saved-trace reports preserve full schedules without running a backend."""

import json
import re
from copy import deepcopy
from pathlib import Path

import pytest

from modules.logical_compiler.examples.factory_schedule import render_schedule


def _saved_case(path: Path, factories: int, duration: float) -> None:
    calls = [
        {
            "invocation_id": f"factory{i}/read",
            "factory_id": f"factory{i}",
            "component_id": "logical_mz",
            "participant_roles": ["R"],
            "end_us": duration,
        }
        for i in range(factories)
    ]
    ids = [c["invocation_id"] for c in calls]
    wave = {
        "start_us": 0,
        "end_us": duration,
        "invocations": ids,
        "resource_busy_us": {"aod:transport": duration},
        "stage_schedule": [
            {
                "start_us": 0,
                "end_us": duration,
                "phase": "readout",
                "category": "measurement",
                "resources": ["aod:transport", "camera"],
                "members": ids,
            }
        ],
        "stage_waits": [],
    }
    case = {
        "status": "complete",
        "duration_us": duration,
        "calls": calls,
        "execution": {"waves": [wave]},
        "factories": {
            f"factory{i}": {
                "production_cycles": [{"delivery": {"deliverable_at_us": duration}}],
                "milestones": [],
            }
            for i in range(factories)
        },
    }
    summary = {
        "distance": 3,
        "factories": factories,
        "seed": 7,
        "cycles_per_factory": 1,
        "accepted_outputs": factories,
        "allocated_atoms": 102 * factories,
        "raw_rejections": 0,
        "factory_rejections": 0,
        "raw_acceptance_parameter": 0.75,
        "makespan_us": duration,
    }
    path.write_text(json.dumps({"case": case, "summary": summary}))


@pytest.mark.parametrize("factories", [1, 2, 3])
def test_complete_report_uses_saved_dynamic_counts_and_full_trace(tmp_path, factories):
    source, target = tmp_path / "case.json", tmp_path / "schedule.html"
    _saved_case(source, factories, 123456)
    result = render_schedule(source, target)
    page = target.read_text(encoding="utf-8")
    payload = json.loads(
        re.search(
            r'<script id="schedule-data" type="application/json">(.*?)</script>',
            page,
            re.DOTALL,
        )[1]
    )
    assert result["windows"] == 3
    assert result["calls"] == factories
    assert result["phases"] == 1
    assert result["outputs"] == factories
    assert payload["waves"][0][1] == 123456
    assert len(payload["waves"][0][3]) == factories
    assert "123.456 ms" in page
    assert f"N = {factories}" in page and "seed = 7" in page
    assert "0.75" in page
    assert "334.841" not in page and "324 个波次" not in page
    assert "<html" in page and "</html>" in page
    assert not re.search(r'<(?:script|link)[^>]+(?:src|href)="https?://', page)
    assert "fetch(" not in page and "window.openai" not in page
    assert "__SCHEDULE__" not in page
    for index in range(factories):
        assert f"工厂 {index} 码块" in page
        assert f"仅工厂 {index}" in page


def test_sync_epoch_wait_after_delivery_is_not_reported_as_finished(tmp_path):
    source, target = tmp_path / "case.json", tmp_path / "schedule.html"
    _saved_case(source, 2, 40)
    run = json.loads(source.read_text())
    run["summary"]["strategy"] = {"name": "synchronous"}
    case = run["case"]
    base = case["execution"]["waves"][0]
    waves = []
    for i in range(2):
        wave = deepcopy(base)
        wave["start_us"], wave["end_us"] = i * 20, (i + 1) * 20
        wave["invocations"] = [f"factory{i}/read"]
        wave["stage_schedule"][0].update(
            members=wave["invocations"], start_us=0, end_us=20
        )
        waves.append(wave)
        case["calls"][i]["end_us"] = (i + 1) * 20
        factory = case["factories"][f"factory{i}"]
        factory["production_cycles"][0]["delivery"]["deliverable_at_us"] = (i + 1) * 20
        factory["completed_at_us"] = 40
    case["execution"]["waves"] = waves
    case["factories"]["factory0"]["milestones"] = [
        {"kind": "line_state_changed", "state": "waiting_peers", "at_us": 20}
    ]
    source.write_text(json.dumps(run))
    result = render_schedule(source, target)
    page = target.read_text(encoding="utf-8")
    assert 'data-state="barrier"' in page
    assert 'data-state="done"' not in page
    assert result["factory_time_us"][0]["barrier"] == 20
    assert "同步策略" in page


def test_round_report_supports_zero_outputs_and_rejects_quota_comparison(tmp_path):
    source, baseline = tmp_path / "round.json", tmp_path / "quota.json"
    _saved_case(source, 1, 50000)
    _saved_case(baseline, 1, 50000)
    run = json.loads(source.read_text())
    run["summary"].update(
        production_basis="production_rounds", accepted_outputs=0, factory_rejections=1
    )
    factory = run["case"]["factories"]["factory0"]
    factory["production_cycles"] = []
    factory["completed_at_us"] = 50000
    factory["production_rounds"] = [
        {"round": 0, "accepted": False, "started_at_us": 0, "completed_at_us": 50000}
    ]
    factory["milestones"] = [
        {"kind": "batch_decision", "accepted": False, "at_us": 50000}
    ]
    source.write_text(json.dumps(run))
    target = tmp_path / "schedule.html"
    result = render_schedule(source, target)
    assert result["outputs"] == 0
    page = target.read_text(encoding="utf-8")
    assert "最终拒绝，本轮无输出" in page
    assert "不等待补齐成功输出数" in page
    with pytest.raises(ValueError, match="BASELINE_PRODUCTION_BASIS_MISMATCH"):
        render_schedule(source, tmp_path / "comparison.html", baseline_case=baseline)


def test_report_draws_only_saved_block_footprints(tmp_path):
    source, target = tmp_path / "case.json", tmp_path / "layout.html"
    _saved_case(source, 1, 10000)
    run = json.loads(source.read_text())
    run["layout"] = {
        "budget": {
            "storage_bounds_um": [0, -60, 560, 0],
            "atom_count_estimate": 102,
            "code_geometry": {
                "relative_bounds": {"x_min": 0, "y_min": 0, "x_max": 60, "y_max": 60}
            },
            "factory_placement": {"kind": "horizontal", "columns": 1, "rows": 1},
        },
        "patches": [
            {
                "factory_id": "factory0",
                "block_id": f"factory0/{role}",
                "role": role,
                "origin": {"x": 100 * j, "y": -60},
            }
            for j, role in enumerate(("W1", "W2", "W3", "W4", "W5", "R"))
        ],
    }
    source.write_text(json.dumps(run))
    render_schedule(source, target)
    page = target.read_text(encoding="utf-8")
    assert page.count('data-block="factory0/') == 6
    assert "560 × 60 μm" in page and "33600 μm²" in page
    assert "左右排列" in page and "当前模型不限制设备横向宽度" in page
    assert "__LAYOUT__" not in page


@pytest.mark.parametrize("count", [0, True, False, -1, 1.5])
def test_factory_count_must_be_a_positive_integer(tmp_path, count):
    source = tmp_path / "case.json"
    _saved_case(source, 1, 50000)
    run = json.loads(source.read_text())
    run["summary"]["factories"] = count
    source.write_text(json.dumps(run))
    with pytest.raises(ValueError, match="POSITIVE_INTEGER_FACTORY_COUNT"):
        render_schedule(source, tmp_path / "schedule.html")


def test_many_factory_owners_and_member_indices_do_not_wrap(tmp_path):
    source, target = tmp_path / "case.json", tmp_path / "schedule.html"
    _saved_case(source, 33, 50000)
    result = render_schedule(source, target)
    page = target.read_text(encoding="utf-8")
    payload = json.loads(
        re.search(
            r'<script id="schedule-data" type="application/json">(.*?)</script>',
            page,
            re.DOTALL,
        )[1]
    )
    assert payload["waves"][0][4][0][5] == list(range(33))
    assert "AOD · " + "+".join(f"F{i}" for i in range(33)) + " ·" in page
    assert 'fill="var(--ab)"' in page
    assert "多厂共用同一命令" in page
    assert result["windows"] == 1
    assert page.count('<svg class="timeline"') == 1


def test_additional_factory_single_owner_color_is_defined(tmp_path):
    source, target = tmp_path / "case.json", tmp_path / "schedule.html"
    _saved_case(source, 3, 50000)
    run = json.loads(source.read_text())
    run["case"]["execution"]["waves"][0]["stage_schedule"][0]["members"] = [
        "factory2/read"
    ]
    source.write_text(json.dumps(run))
    render_schedule(source, target)
    page = target.read_text(encoding="utf-8")
    assert "--a2:" in page
    assert 'fill="var(--a2)"' in page
    assert "AOD · F2 ·" in page


@pytest.mark.parametrize("duration,windows", [(50000, 1), (100000, 2), (100000.25, 3)])
def test_exact_window_boundary_does_not_add_an_empty_strip(tmp_path, duration, windows):
    source, target = tmp_path / "case.json", tmp_path / "schedule.html"
    _saved_case(source, 1, duration)
    result = render_schedule(source, target)
    assert result["windows"] == windows
    assert target.read_text(encoding="utf-8").count('<svg class="timeline"') == windows


def test_baseline_comparison_and_fresh_output_are_enforced(tmp_path):
    source, baseline = tmp_path / "new.json", tmp_path / "old.json"
    target = tmp_path / "schedule.html"
    _saved_case(source, 2, 75000)
    _saved_case(baseline, 2, 100000)
    result = render_schedule(source, target, baseline_case=baseline)
    assert result["comparison"]["reduction_percent"] == 25
    assert "100.000 ms" in target.read_text(encoding="utf-8")
    assert "25.00%" in target.read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        render_schedule(source, target)


@pytest.mark.parametrize("distance,growth_rounds", [(3, 0), (5, 5), (7, 7)])
def test_accepted_only_growth_has_distinct_labels_and_color(
    tmp_path, distance, growth_rounds
):
    source, target = tmp_path / "case.json", tmp_path / "schedule.html"
    _saved_case(source, 1, 10000)
    run = json.loads(source.read_text())
    run["summary"]["distance"] = distance
    run["summary"]["growth_rounds_per_accepted_input"] = growth_rounds
    component = "raw_t_postselection/canonicalize"
    run["case"]["calls"][0]["component_id"] = component
    source.write_text(json.dumps(run))
    render_schedule(source, target)
    page = target.read_text(encoding="utf-8")
    payload = json.loads(
        re.search(
            r'<script id="schedule-data" type="application/json">(.*?)</script>',
            page,
            re.DOTALL,
        )[1]
    )
    if distance == 3:
        assert "Corr T" in page
        assert 'fill="var(--correct)"' in page
        assert '<i style="--c:var(--growth)">' not in page
    else:
        label = f"通过后扩码至 d{distance} + {growth_rounds} 轮普通 SE + 修正"
        assert label in page
        assert payload["component_labels"][component] == label
        assert 'fill="var(--growth)"' in page
        assert '<i style="--c:var(--growth)">' in page
        assert "Corr T" not in page


def test_incompatible_baseline_and_incomplete_trace_are_rejected(tmp_path):
    source, baseline = tmp_path / "new.json", tmp_path / "old.json"
    _saved_case(source, 2, 75000)
    _saved_case(baseline, 1, 100000)
    with pytest.raises(ValueError, match="BASELINE"):
        render_schedule(source, tmp_path / "schedule.html", baseline_case=baseline)
    run = json.loads(source.read_text())
    run["case"]["status"] = "timeout"
    source.write_text(json.dumps(run))
    with pytest.raises(ValueError, match="COMPLETE"):
        render_schedule(source, tmp_path / "schedule.html")
