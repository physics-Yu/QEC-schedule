"""Offline calibration requires stable, intact, physically checked sources."""

import hashlib
import json

import pytest
from nadit_physical_compiler.activity import ActivityEvent

from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
    _event_owner,
    calibrate_fast_profile,
)


@pytest.mark.parametrize("failure", ("unstable", "hash", "unvalidated", "parallel"))
def test_calibration_rejects_unusable_source_before_replaying(tmp_path, failure):
    source = {
        "physical": {
            "validation": {"ok": failure != "unvalidated"},
            "parallel_batches": [{}] if failure == "parallel" else [],
        },
        "component_schedule": {"policy": {"max_parallel": 1}},
    }
    raw = json.dumps(source).encode()
    (tmp_path / "case.json").write_bytes(raw)
    manifest = {
        "source_stable": failure != "unstable",
        "execution_completed": True,
        "files_sha256": {"case.json": hashlib.sha256(raw).hexdigest()},
    }
    if failure == "hash":
        manifest["files_sha256"]["case.json"] = "0" * 64
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="CALIBRATION"):
        calibrate_fast_profile(tmp_path, tmp_path / "profile.json")
    assert not (tmp_path / "profile.json").exists()


def test_source_free_transport_is_owned_by_verified_serial_call_window():
    event = ActivityEvent("Move", 1, 2, (10,), ((0, 0),), ((1, 0),))
    calls = {
        "first": {"start_us": 0, "end_us": 3},
        "second": {"start_us": 3, "end_us": 6},
    }
    assert _event_owner(event, {}, calls) == "first"
    later = ActivityEvent("Store", 3, 2, (10,), ((1, 0),), ((1, 0),))
    assert _event_owner(later, {}, calls) == "second"
