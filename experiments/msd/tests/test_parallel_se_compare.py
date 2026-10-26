"""Exact signed SE comparison accounting with matched complete-world controls."""

from copy import deepcopy

import pytest

from experiments.msd.parallel_se_compare import compare_cases
from experiments.msd.standard import STANDARD_ID


def _row(mode, indices, phases):
    return {
        "schema": "nadit.msd.parallel_se/1",
        "standard": STANDARD_ID,
        "parameters": {"distance": 3, "pipelines": 2, "window_padding_um": 20.0},
        "mode": mode,
        "factory_indices": indices,
        "active_patch_role": "W1",
        "se_instances": len(indices),
        "expected_measurements": 8 * len(indices),
        "metrics": {"execution_duration_us": sum(phases.values())},
        "scheduler": {"time_partition_us": phases},
        "device_sha256": "same-device",
        "source_tree_sha256": "same-source-tree",
        "scope": "joint SE round; not a complete distillation production cycle",
    }


def _controls():
    top = _row("solo", (0,), {"gate": 8.0, "readout": 2.0})
    slowest = _row("solo", (1,), {"gate": 2.0, "readout": 10.0})
    joint = _row("joint", (0, 1), {"gate": 4.0, "readout": 6.0})
    serial = _row("serial", (0, 1), {"gate": 10.0, "readout": 12.0})
    return joint, serial, (top, slowest)


def test_signed_joint_effect_uses_one_slowest_factory_for_every_phase():
    cases = _controls()
    unchanged = deepcopy(cases)
    result = compare_cases(*cases)
    assert cases == unchanged
    assert result["joint_round_us"] == 10.0
    assert result["serial_round_us"] == 22.0
    assert result["top_solo_us"] == 10.0
    assert result["slowest_solo_us"] == 12.0
    assert result["slowest_factory"] == 1
    assert result["position_effect_us"] == 2.0
    assert result["net_joint_effect_us"] == -2.0
    assert result["serial_speedup"] == pytest.approx(2.2)
    assert result["rounds_per_second"] == 200000.0
    # Taking a separate slowest/fastest factory per phase would not telescope.
    assert result["position_by_phase_us"] == {"gate": -6.0, "readout": 8.0}
    assert result["joint_by_phase_us"] == {"gate": 2.0, "readout": -4.0}
    assert sum(result["position_by_phase_us"].values()) == result["position_effect_us"]
    assert sum(result["joint_by_phase_us"].values()) == result["net_joint_effect_us"]
    assert "not pure AOD contention" in result["attribution_note"]
    assert "physical bound" in result["attribution_note"]
    assert "SE rounds" in result["throughput_unit"]


def test_missing_phase_categories_are_zero_and_ties_choose_lowest_index():
    joint, serial, solos = _controls()
    solos[1]["scheduler"]["time_partition_us"] = {"readout": 10.0}
    solos[1]["metrics"]["execution_duration_us"] = 10.0
    joint["scheduler"]["time_partition_us"] = {"gate": 4.0, "readout": 5.0, "wait": 1.0}
    result = compare_cases(joint, serial, tuple(reversed(solos)))
    assert result["slowest_factory"] == 0
    assert result["position_effect_us"] == 0
    assert result["net_joint_effect_us"] == 0
    assert result["joint_by_phase_us"] == {"gate": -4.0, "readout": 3.0, "wait": 1.0}


@pytest.mark.parametrize(
    "mutation",
    (
        lambda j, s, solos: j.update(mode="solo"),
        lambda j, s, solos: s.update(mode="joint"),
        lambda j, s, solos: solos[0].update(mode="joint"),
        lambda j, s, solos: j.update(factory_indices=(0,)),
        lambda j, s, solos: s.update(factory_indices=(0, 0)),
        lambda j, s, solos: solos[1].update(factory_indices=(0,)),
        lambda j, s, solos: solos[1].update(factory_indices=(True,)),
        lambda j, s, solos: solos[1].update(active_patch_role="W2"),
        lambda j, s, solos: solos[1].update(se_instances=2),
        lambda j, s, solos: solos[1].update(expected_measurements=9),
        lambda j, s, solos: solos[1].update(scope="complete factory production"),
        lambda j, s, solos: solos[1].update(device_sha256="different"),
        lambda j, s, solos: solos[1].update(source_tree_sha256="different"),
        lambda j, s, solos: solos[1]["parameters"].update(window_padding_um=40),
        lambda j, s, solos: solos[1]["metrics"].update(execution_duration_us=11),
        lambda j, s, solos: j["metrics"].update(execution_duration_us=0),
        lambda j, s, solos: j["metrics"].update(execution_duration_us=float("nan")),
        lambda j, s, solos: j["scheduler"]["time_partition_us"].update(gate=-4),
        lambda j, s, solos: j["scheduler"]["time_partition_us"].update(
            gate=float("inf")
        ),
    ),
)
def test_incompatible_or_invalid_controls_rejected(mutation):
    joint, serial, solos = _controls()
    mutation(joint, serial, solos)
    with pytest.raises(ValueError):
        compare_cases(joint, serial, solos)


def test_missing_solo_and_missing_required_metadata_rejected():
    joint, serial, solos = _controls()
    with pytest.raises(ValueError, match="solo"):
        compare_cases(joint, serial, solos[:1])
    del joint["source_tree_sha256"]
    with pytest.raises(ValueError, match="source_tree_sha256"):
        compare_cases(joint, serial, solos)
