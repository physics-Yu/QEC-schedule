import json
from math import hypot
from pathlib import Path

import pytest

from neutral_atom_experiments.qec_pbc.modular_aod_demo import (
    build_profile, repository_root, run,
)
from neutral_atom_app.modular_aod_report import export_report


def test_admitted_home_geometry_support_inventory_and_unencoded_resource_roles():
    initial, profile, roles, descriptions = build_profile()
    proposal = json.loads((repository_root() / profile["placement_provenance"]["proposal_path"]).read_text())
    assert len(initial) == 34 and len(profile["declared_slm_sites_um"]) == 68
    for role, atom in roles.items():
        if role.startswith("data."):
            assert initial[atom] == tuple(proposal["coordinates_um"]["A." + role.split(".")[1]])
        else:
            assert role.startswith("resource.r")
    assert sum(".X" in role or ".Z" in role for role in roles) == 8
    for device, item in descriptions.items():
        axes = profile["initial_axes"][device]
        assert len(axes["rows"]) * len(axes["columns"]) == 25
        assert len(item["atoms"]) == 17  # Eight active empty Cartesian traps during full capture.
    points = list(initial.values())
    assert min(hypot(a[0] - b[0], a[1] - b[1]) for i, a in enumerate(points) for b in points[i+1:]) == 10
    assert not profile["native_compilation_invoked"] and not profile["syndrome_executed"]


def test_real_dual_movement_recovery_serial_control_and_shared_export(tmp_path):
    from tools.audit_modular_aod import audit_modular_operations
    output = tmp_path / "actual-fixture"
    result, evidence = run(output, geometry_guard=audit_modular_operations)
    assert result["offline_physical_status"] == "PASS"
    assert result["actual_execution_verified"]
    assert result["loaded_move_overlap_us"] > 0
    assert result["resource_complete_data_still_moving"]
    assert result["checkpoint_two_moves_inflight"]["exact_final_and_journal_equal"]
    assert result["checkpoint_after_resource_completed"]["exact_final_and_journal_equal"]
    assert result["recording_off_on_semantic_equal"]
    assert result["same_profile_serial_control"]["same_physical_primitives"]
    assert result["same_profile_serial_control"]["same_final_state_except_time"]
    assert result["same_profile_serial_control"]["physical_time_us"] > result["physical_time_us"]
    assert result["same_profile_serial_control"]["actual_execution_verified"]
    assert result["same_profile_serial_control"]["offline_physical_status"] == "PASS"
    assert result["same_profile_serial_control"]["time_reduction_percent"] > 0
    serial_audit = json.loads((output / "serial-offline-audit.json").read_text())
    assert serial_audit["status"] == "PASS" and serial_audit["actual_execution_verified"]
    assert result["gates"] == result["reports"] == 0
    exported = export_report(result, evidence, output)
    payload = json.loads(Path(exported["recording"]).read_text(encoding="utf-8"))
    from neutral_atom_app.native_kernel_view import build_native_kernel_payload
    baseline = json.loads(json.dumps(build_native_kernel_payload(evidence)))
    assert payload["scheduling_report_source"] is None
    assert "pure transport" in payload["evidence_scope"]
    assert all("独立 row / column" in label and "native" not in label
               for label in payload["scene"]["aod_labels"].values())
    # The adapter changes only the three presentation provenance fields.
    baseline["scheduling_report_source"] = payload["scheduling_report_source"]
    baseline["evidence_scope"] = payload["evidence_scope"]
    baseline["scene"]["aod_labels"] = payload["scene"]["aod_labels"]
    assert payload == baseline
    assert any(set(frame["movements"]) == {"AOD_0", "AOD_MAGIC"} for frame in payload["frames"])
    assert {"AOD_0", "AOD_MAGIC"} <= set(payload["summary"]["resource_busy_us"])
    assert len([v for v in payload["scene"]["atom_roles"].values()
                if v["patch"] == "resource" and v["kind"] == "protocol_auxiliary"]) == 17
    assert not payload["measurement_completion_times_us"]
    page = (output / "index.html").read_text(encoding="utf-8")
    assert "资源回家，数据仍在运输" in page and "window.modularAodViewer" in page
    assert "同 profile 串行" in page and "完成时间减少" in page
    assert "modelCaption" not in page


def test_rejected_guard_leaves_failure_evidence_and_attempt_cannot_be_overwritten(tmp_path):
    from tools.audit_modular_aod import audit_modular_operations
    output = tmp_path / "refused-fixture"
    def mismatched_guard(*args, **kwargs):
        report = audit_modular_operations(*args, **kwargs)
        return {**report, "input_sha256": "0" * 64}
    with pytest.raises(ValueError):
        run(output, geometry_guard=mismatched_guard)
    failure = json.loads((output / "failure.json").read_text())
    assert failure["runtime_status"] == "rejected"
    assert (output / "initial.json").is_file() and (output / "operations.json").is_file()
    assert (output / "pre-execution-audit.json").is_file()
    assert not (output / "journal.json").exists()
    with pytest.raises(FileExistsError):
        run(output, geometry_guard=audit_modular_operations)
