"""Independent accounting checks with simultaneous transports and idle tails."""

from pathlib import Path

import pytest
from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    Load,
    Measure,
    Move,
    Store,
    Wait,
)
from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
    Zone,
)
from nadit_physical_compiler.physical_ir import ResultRef
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import (
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.state import (
    AODGrid,
    AODLine,
    AtomLayout,
    AtomState,
    SLMHolder,
)

from experiments.msd import calibrate as calibration
from experiments.msd.calibrate import source_snapshot, summarize
from experiments.msd.standard import REFERENCE_PATH, ExperimentSpec


def _accounting_fixture():
    """Hand-built replay fixture; intentionally not a compiler validation result.

    Two atoms travel simultaneously on distinct AODs; a third stays idle. Their
    transport lasts seven elapsed microseconds but thirteen action microseconds.
    A later measurement and feedback tail extend total completion to twelve.
    """
    bounds = Region(-1, -1, 21, 5)
    device = Device(
        "analytic-accounting-fixture",
        (Zone("region", bounds, ()),),
        tuple(
            SLMSite(name, Position(x, y))
            for name, x, y in (
                ("s0", 0, 0),
                ("s1", 10, 0),
                ("s2", 20, 0),
                ("t0", 0, 3),
                ("t1", 10, 4),
            )
        ),
        (AOD("a", bounds, 1), AOD("b", bounds, 1)),
        Timing(2, 1, 1),
    )
    entry = AtomLayout(
        tuple(AtomState(i, Position(10 * i, 0), SLMHolder(f"s{i}")) for i in range(3)),
        qubit_to_atom=(0, 1, 2),
    )
    a = AODGrid("a", (AODLine(0, 0),), (AODLine(0, 0),))
    b = AODGrid("b", (AODLine(0, 0),), (AODLine(0, 10),))
    ta = AODGrid("a", (AODLine(0, 3),), a.columns)
    tb = AODGrid("b", (AODLine(0, 4),), b.columns)
    program = AtomProgram(
        (
            AtomStep(
                (
                    Load(a, ((0, 0, 0),), duration_us=2),
                    Load(b, ((1, 0, 0),), duration_us=2),
                )
            ),
            AtomStep(
                (
                    Move(ta, ((0, Position(0, 3)),), duration_us=3),
                    Move(tb, ((1, Position(10, 4)),), duration_us=4),
                )
            ),
            AtomStep(
                (
                    Store(AODGrid("a"), ((0, "t0"),), duration_us=1),
                    Store(AODGrid("b"), ((1, "t1"),), duration_us=1),
                )
            ),
            AtomStep((Wait(duration_us=2),)),
            AtomStep((Measure("camera", ((0, ResultRef(0)),), True, duration_us=1),)),
        )
    )
    return {
        "schema": "nadit.result/2",
        "device": encode_device(device),
        "entry_state": encode_layout(entry),
        "exit_state": encode_layout(replay(program, entry, device)),
        "program": encode_program(program),
        "measurements": [{"available_at_us": 12}],
        "dag": {"nodes": []},
        "validation": {
            "ok": False,
            "scope": "analytic fixture, not validated lowering",
        },
    }


def test_concurrent_transport_and_feedback_accounting():
    result = summarize(_accounting_fixture())
    assert result["execution_duration_us"] == 12
    assert result["transport_elapsed_us"] == 7
    assert result["transport_action_sum_us"] == 13
    assert result["movement_distance_atom_um"] == 7
    assert result["atom_count"] == 3
    assert result["atom_time_us"] == 36
    assert result["atom_busy_us"] == 14
    assert result["atom_idle_us"] == 22
    assert result["exposure_by_action"]["Move"] == {
        "action_count": 2,
        "atom_events": 2,
        "atom_us": 7,
    }
    assert result["exposure_by_action"]["Measure"]["atom_us"] == 1
    assert result["physical_validation_ok"] is False
    assert result["accepted_outputs"] is None
    assert result["accepted_output_throughput_per_s"] is None
    assert result["logical_error_probability"] is None


def test_trajectory_footprint_includes_spectators_and_excludes_unused_window():
    document = _accounting_fixture()
    result = summarize(document)
    assert result["trajectory_bbox_um"] == [0, 0, 20, 4]
    assert result["trajectory_bbox_area_um2"] == 80
    # Enlarging a computational window alone does not change actual atom support.
    for zone in document["device"]["zones"]:
        zone["bounds"] = {"x_min": -100, "y_min": -100, "x_max": 100, "y_max": 100}
    assert summarize(document) == result


def test_source_snapshot_changes_when_reference_json_changes(monkeypatch):
    original = source_snapshot()
    read_bytes = Path.read_bytes

    def changed_reference(path):
        contents = read_bytes(path)
        return contents + b"\n" if path == REFERENCE_PATH else contents

    monkeypatch.setattr(Path, "read_bytes", changed_reference)
    changed = source_snapshot()
    changed_keys = {key for key in original if original[key] != changed[key]}
    assert changed_keys == {
        "modules/codes/rotated_surface_d3/configs/nonzoned_cnot_reference.json"
    }


def test_source_snapshot_rejects_compiler_from_another_checkout(monkeypatch):
    monkeypatch.setattr(calibration, "compile_physical", lambda *args: None)
    with pytest.raises(ValueError, match="imported from this experiment checkout"):
        source_snapshot()


@pytest.mark.parametrize("operation", ("logical_h", "unregistered_operation"))
def test_source_only_calibration_rejects_missing_physical_protocol(
    monkeypatch, operation
):
    def forbidden_source_access(*args, **kwargs):
        raise AssertionError(
            "Unsupported protocol reached source or world construction."
        )

    monkeypatch.setattr(calibration, "get_component", forbidden_source_access)
    monkeypatch.setattr(calibration, "build_world", forbidden_source_access)
    expected = (
        "physical permutation template path"
        if operation == "logical_h"
        else "Unsupported"
    )
    with pytest.raises(ValueError, match=expected):
        calibration.calibrate(ExperimentSpec(), operation)
