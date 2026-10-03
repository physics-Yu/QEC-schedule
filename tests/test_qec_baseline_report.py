"""Report fixtures are artifact readers, not a substitute physical execution."""
from copy import deepcopy
import json
import re

import pytest

from neutral_atom_experiments.qec_pbc.baseline_report import canonical_memory_report
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical
from neutral_atom_experiments.qec_pbc.neutral_atom import d3_role_bindings


def _save(directory, name, value):
    (directory / name).write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _read(directory, name):
    return json.loads((directory / name).read_text(encoding="utf-8"))


def _payload(page):
    raw = re.search(r'<script type="application/json" id="report-data">(.*?)</script>',
                    page.read_text(encoding="utf-8"), re.S)
    assert raw is not None
    return json.loads(raw.group(1))


@pytest.fixture
def artifacts(tmp_path):
    """Saved data fixture: each six-CZ ideal layer has TWO actual pulse records.

    Times are deliberately supplied fixture data, never computed by the report.
    A persistent random first-round X0 sector proves syndrome 1 need not be a
    failure. The Z-memory detector values remain zero.
    """
    canonical = canonical_memory_program()
    compiled = lower_to_physical(canonical.program, d3_role_bindings(canonical.program))
    encoded = json.loads(json.dumps(compiled.to_dict()))
    phase_map = {gid: p for p in canonical.phases for gid in p.native_gate_ids}
    schedule, operations = [], []
    time = 10.0
    for phase in canonical.phases:
        ids = phase.native_gate_ids
        groups = [ids[:3], ids[3:]] if phase.kind == "cx_cz" else [(gid,) for gid in ids]
        for group in groups:
            if not group:
                continue
            start, end = time, time + (0.36 if phase.kind == "cx_cz" else 1.0)
            for gid in group:
                gate = next(g for g in encoded["gates"] if g["id"] == gid)
                schedule.append({**gate, "start_us": start, "end_us": end, "applied": True})
            if phase.kind == "cx_cz":
                operations.append({"plan_id": "fixture-plan", "operation_id": f"pulse{len(operations)}",
                    "kind": "entangling_pulse", "label": "Explicit fixture interval",
                    "start_us": start, "end_us": end, "gate_ids": list(group)})
            time = end
    raw = {m.raw_gate_id: int(m.result_id.endswith(".X0")) for m in compiled.measurements}
    evidence = {"status": "completed", "basis": "Z", "physical_atom_count": 34,
                "metrics": {"simulation_time_us": time},
                "audit": {"dag_complete": True, "terminal_verified": False,
                    "raw_measurements": raw, "semantic_results": compiled.semantic_results(raw),
                    "classical_outputs": compiled.classical_outputs(raw),
                    "quantum_reference": {"equal": True}}}
    for name, value in (("compiled.json", encoded), ("canonical.json", canonical.to_dict()),
                        ("gate_schedule.json", schedule), ("schedule.json", operations),
                        ("evidence.json", evidence)):
        _save(tmp_path, name, value)
    return tmp_path, canonical, compiled, schedule, evidence


def test_layers_and_actual_pulses_remain_distinct_and_times_are_preserved(artifacts):
    directory, _, _, schedule, _ = artifacts
    original = {p.name: p.read_bytes() for p in directory.glob("*.json")}
    page = canonical_memory_report(directory)
    data = _payload(page)
    assert len(data["layer_counts"]) == 12
    assert all(x["pairs"] == 6 for x in data["layer_counts"])
    assert len(data["pulses"]) == 24
    assert all(len(p["gate_ids"]) == 3 for p in data["pulses"])
    assert data["counts"]["CZ"] == 72
    actual = {g["id"]: (g["start_us"], g["end_us"]) for g in data["gates"]}
    assert actual == {g["id"]: (g["start_us"], g["end_us"]) for g in schedule}
    assert len(data["detectors"]) == 24
    assert {p.name: p.read_bytes() for p in directory.glob("*.json")} == original
    assert "未启用随机噪声" in page.read_text(encoding="utf-8")


def test_random_syndrome_false_machine_check_and_unprovided_fault_audit_not_passed(artifacts):
    directory, _, _, _, _ = artifacts
    data = _payload(canonical_memory_report(directory))
    assert any(m["semantic"] == 1 for m in data["measurements"])
    assert all(d["value"] == 0 for d in data["detectors"])
    boundaries = {d["boundary"] for d in data["detectors"]}
    assert boundaries == {"known_product_preparation", "temporal", "destructive_readout"}
    assert {r["id"]: r["passed"] for r in data["machine_checks"]} == {
        "dag_complete": True, "terminal_verified": False, "quantum_reference.equal": True}
    assert data["fault_audit"] is None
    assert data["fault_checks"] == []
    assert "没有可播放" in " ".join(data["warnings"])


def test_metadata_object_and_result_fallback_are_supported(artifacts):
    directory, canonical, _, _, evidence = artifacts
    (directory / "canonical.json").unlink()
    (directory / "evidence.json").unlink()
    _save(directory, "result.json", evidence)
    data = _payload(canonical_memory_report(directory, metadata=canonical))
    assert data["sources"]["evidence"] == "result.json"
    assert data["canonical"]["source"]["commit"] == canonical.source_commit


def test_missing_schedule_entries_do_not_gain_invented_times(artifacts):
    directory, _, _, schedule, _ = artifacts
    omitted = schedule.pop(0)
    _save(directory, "gate_schedule.json", schedule)
    data = _payload(canonical_memory_report(directory))
    row = next(g for g in data["gates"] if g["id"] == omitted["id"])
    assert row["start_us"] is row["end_us"] is row["applied"] is None
    assert any("部分门尚无执行记录" in x for x in data["warnings"])


def test_json_embedding_resists_script_injection_and_roundtrips_unicode(artifacts):
    directory, _, _, _, evidence = artifacts
    injected = "</script><script>window.INJECTED=true</script>&中文\u2028"
    evidence["scope"] = injected
    _save(directory, "evidence.json", evidence)
    page = canonical_memory_report(directory)
    assert _payload(page)["evidence"]["scope"] == injected
    assert "<script>window.INJECTED" not in page.read_text(encoding="utf-8")


@pytest.mark.parametrize("damage, message", [
    ("unknown_gate", "Unknown or duplicate gate schedule"),
    ("duplicate_gate", "Unknown or duplicate gate schedule"),
    ("gate_targets", "changes compiled qubit_ids"),
    ("negative_time", "Invalid actual operation interval"),
    ("reverse_time", "Invalid actual operation interval"),
    ("boolean_time", "Invalid actual operation interval"),
    ("unknown_applied", "applied status must be boolean"),
    ("pulse_time", "CZ pulse interval disagrees"),
    ("pulse_duplicate", "multiple pulses"),
    ("wrong_coupling", "coupling disagrees"),
    ("semantic_mismatch", "Raw and semantic measurements disagree"),
    ("detector_mismatch", "Reported detectors disagree"),
])
def test_conflicting_artifact_evidence_fails_closed(artifacts, damage, message):
    directory, _, _, schedule, evidence = artifacts
    if damage == "unknown_gate":
        schedule[0]["id"] = "unknown"
    elif damage == "duplicate_gate":
        schedule.append(deepcopy(schedule[0]))
    elif damage == "gate_targets":
        schedule[0]["qubit_ids"] = ["Q033"]
    elif damage == "negative_time":
        schedule[0]["start_us"] = -1
    elif damage == "reverse_time":
        schedule[0]["end_us"] = schedule[0]["start_us"] - 1
    elif damage == "boolean_time":
        schedule[0]["start_us"] = True
    elif damage == "unknown_applied":
        schedule[0]["applied"] = "yes"
    elif damage in ("pulse_time", "pulse_duplicate"):
        operations = _read(directory, "schedule.json")
        if damage == "pulse_time":
            operations[0]["start_us"] += 0.1
        else:
            operations.append(deepcopy(operations[0]))
        _save(directory, "schedule.json", operations)
    elif damage == "wrong_coupling":
        canonical = _read(directory, "canonical.json")
        canonical["couplings"][0]["data_role"] = "A.d8"
        _save(directory, "canonical.json", canonical)
    elif damage == "semantic_mismatch":
        key = next(iter(evidence["audit"]["semantic_results"]))
        evidence["audit"]["semantic_results"][key] ^= 1
        _save(directory, "evidence.json", evidence)
    elif damage == "detector_mismatch":
        key = next(iter(evidence["audit"]["classical_outputs"]["detectors"]))
        evidence["audit"]["classical_outputs"]["detectors"][key] ^= 1
        _save(directory, "evidence.json", evidence)
    _save(directory, "gate_schedule.json", schedule)
    with pytest.raises(ValueError, match=message):
        canonical_memory_report(directory)
    failed = (directory / "index.html").read_text(encoding="utf-8")
    assert "报告尚未通过生成校验" in failed
    assert "report-data" not in failed


def test_failed_regeneration_clears_old_success_page(artifacts):
    directory, _, _, schedule, _ = artifacts
    (directory / "index.html").write_text("OLD_SUCCESS_PAGE", encoding="utf-8")
    schedule[0]["id"] = "unknown"
    _save(directory, "gate_schedule.json", schedule)
    with pytest.raises(ValueError):
        canonical_memory_report(directory)
    assert "OLD_SUCCESS_PAGE" not in (directory / "index.html").read_text(encoding="utf-8")


def test_recording_is_copied_exactly_and_shared_viewer_export_is_used(artifacts):
    directory, _, _, _, _ = artifacts
    # Inert recorder fixture proves exact data ownership; browser/runtime
    # validity and native movement are verified separately on real artifacts.
    recording = {"format": "neutral-atom-view/2", "scene": {"fixture": True},
                 "frames": [{"time": 0, "atom_updates": []}, {"time": 1234.5, "atom_updates": []}],
                 "operations": [], "start_time": 0, "duration": 1234.5}
    _save(directory, "recording.json", recording)
    _save(directory, "fault_audit.json", {"scope": "offline Pauli faults", "passed": False,
                                           "single_faults": 128, "logical_failures": 2})
    page = canonical_memory_report(directory)
    text = page.read_text(encoding="utf-8")
    raw = re.search(r'<script type="application/json" id="recording-data">(.*?)</script>', text, re.S)
    assert json.loads(raw.group(1)) == recording
    assert (directory / "atom-viewer.js").exists()
    assert "NeutralAtomViewer.mount" in text
    data = _payload(page)
    assert data["duration_us"] == 1234.5
    assert data["fault_checks"] == [{"id": "passed", "passed": False}]
    assert data["fault_audit"]["logical_failures"] == 2


def test_recording_operations_can_supply_actual_pulses_without_schedule_file(artifacts):
    directory, _, _, _, _ = artifacts
    ops = _read(directory, "schedule.json")
    (directory / "schedule.json").unlink()
    _save(directory, "recording.json", {"frames": [], "start_time": 0, "duration": 1000,
        "operations": [{**op, "start": op["start_us"], "end": op["end_us"]} for op in ops]})
    data = _payload(canonical_memory_report(directory))
    assert data["sources"]["operations"] == "recording.json.operations"
    assert len(data["pulses"]) == 24
    assert data["pulses"][0]["start_us"] == ops[0]["start_us"]


@pytest.mark.parametrize("evidence_mode, metadata_mode, expected_mode, expected_source", [
    ("prearranged", None, "prearranged", "evidence.json"),
    ("storage", None, "storage", "evidence.json"),
    (None, "prearranged", "prearranged", "run_metadata.json"),
    (None, "storage", "storage", "run_metadata.json"),
    ("prearranged", "prearranged", "prearranged", "evidence.json"),
    ("storage", "storage", "storage", "evidence.json"),
    (None, None, None, None),
    ("historical_undefined", None, None, "evidence.json"),
])
def test_initial_placement_boundary_uses_declared_metadata_only(
        artifacts, evidence_mode, metadata_mode, expected_mode, expected_source):
    directory, _, _, _, evidence = artifacts
    if evidence_mode is not None:
        evidence["initial_placement"] = evidence_mode
    if metadata_mode is not None:
        _save(directory, "run_metadata.json", {"initial_placement": metadata_mode})
    _save(directory, "evidence.json", evidence)
    page = canonical_memory_report(directory)
    data = _payload(page)
    initial = data["initial_placement"]
    assert initial["mode"] == expected_mode
    assert initial["source"] == expected_source
    if expected_mode == "prearranged":
        assert "已重排 EZ 工作布局起步" in initial["description"]
        assert "上游重排/加载准备时间未计入本次运行" in initial["description"]
        assert "量子 RESET/测量仍真实执行" in initial["description"]
    elif expected_mode == "storage":
        assert "SZ 初始布局起步" in initial["description"]
        assert "包含逐原子 staging/归还" in initial["description"]
    else:
        assert "初始布局模式未声明" in initial["description"]
        assert "不推断" in initial["description"]
    assert 'id="initial-placement"' in page.read_text(encoding="utf-8")


def test_conflicting_initial_placement_boundaries_do_not_display_old_success(artifacts):
    directory, _, _, _, evidence = artifacts
    evidence["initial_placement"] = "prearranged"
    _save(directory, "evidence.json", evidence)
    _save(directory, "run_metadata.json", {"initial_placement": "storage"})
    (directory / "index.html").write_text("OLD_SUCCESS_PAGE", encoding="utf-8")
    with pytest.raises(ValueError, match="Initial placement metadata disagree"):
        canonical_memory_report(directory)
    text = (directory / "index.html").read_text(encoding="utf-8")
    assert "OLD_SUCCESS_PAGE" not in text
    assert "报告尚未通过生成校验" in text
