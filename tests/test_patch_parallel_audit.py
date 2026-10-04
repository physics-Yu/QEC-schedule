"""Independent rejection cases for protocol-preserving intra-patch execution."""
from copy import deepcopy
from dataclasses import asdict
import importlib.util
import json
from pathlib import Path

import pytest

from neutral_atom_experiments.qec_pbc.parallel_prefix import load_native_parallel_prefix
from neutral_atom_experiments.qec_pbc.patch_layout import create_enola_environment, create_interleaved_environment
from neutral_atom_env.visualization import VisualRecorder


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("patch_parallel_audit",
    ROOT / "tools/audit_patch_parallel_layout.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


@pytest.fixture
def prefix():
    return load_native_parallel_prefix(ROOT / "references/qec_pbc_validation/shor15_native_prefix_seed0_2026_10_04",
                                      patch_count=1)


def _protocol(prefix):
    return audit.verify_canonical_protocol(prefix.source, [asdict(g) for g in prefix.circuit.gates])


def _effects(protocol, mode="layer"):
    patch = protocol["patches"][0]
    pulses = [{"kind": "entangling_pulse", "gate_ids": [gid]}
              for gid in protocol["css_cz"][patch]]
    entries = protocol["canonical_cz"][patch]
    if mode == "role":
        pulses.extend({"kind": "entangling_pulse", "gate_ids": [gid]} for gid, _, _ in entries)
    else:
        for layer in range(1, 5):
            groups = (None,) if layer in (1, 4) else ("X", "Z")
            for kind in groups:
                selected = [gid for gid, l, k in entries if l == layer and (kind is None or k == kind)]
                subsets = (selected,) if kind is None else (selected[:2], selected[2:])
                pulses.extend({"kind": "entangling_pulse", "gate_ids": group} for group in subsets)
    return pulses


def test_fixed_source_has_six_pair_layers_and_declared_ten_closed_capture_pulses(prefix):
    protocol = _protocol(prefix)
    layer = audit.verify_cz_batches(protocol, _effects(protocol), "layer")
    role = audit.verify_cz_batches(protocol, _effects(protocol, "role"), "role")
    assert layer["total_cz_pulses"] == 54
    assert role["total_cz_pulses"] == 68
    assert layer["cz_native_effects"] == role["cz_native_effects"] == 68
    assert layer["per_patch"]["phase0"] == {
        "maximum_pairs_in_one_canonical_pulse": 6, "round_pulses": 10,
        "pairs_per_pulse_histogram": {6: 2, 2: 4, 1: 4}, "pulses_per_layer": {1: 1, 2: 4, 3: 4, 4: 1}}


def test_same_final_pairs_cannot_hide_wrong_canonical_hook_order(prefix):
    gates = [asdict(g) for g in prefix.circuit.gates]
    left = next(g for g in gates if g["id"].endswith("r1.layer1.cz.0"))
    right = next(g for g in gates if g["id"].endswith("r1.layer2.cz.0"))
    left["qubit_ids"], right["qubit_ids"] = right["qubit_ids"], left["qubit_ids"]
    with pytest.raises(ValueError, match="coupling"):
        audit.verify_canonical_protocol(prefix.source, gates)


def test_disjoint_gate_barrier_is_not_replaced_by_own_wire_only(prefix):
    gates = [asdict(g) for g in prefix.circuit.gates]
    gate = next(g for g in gates if g["id"].endswith("r1.layer2.cz.0"))
    gate["depends_on"] = gate["depends_on"][:1]
    with pytest.raises(ValueError, match="phase barrier"):
        audit.verify_canonical_protocol(prefix.source, gates)


def test_encoder_disjoint_wire_frontier_cannot_silently_change_declared_contract(prefix):
    gates = [asdict(g) for g in prefix.circuit.gates]
    gate = next(g for g in gates if g["id"].endswith("encode.plus2"))
    gate["depends_on"] = ()
    with pytest.raises(ValueError, match="CSS encoder serial chain"):
        audit.verify_canonical_protocol(prefix.source, gates)


def test_six_pair_pulse_cannot_cross_canonical_layers(prefix):
    protocol = _protocol(prefix)
    effects = _effects(protocol)
    effects[44]["gate_ids"][0], effects[45]["gate_ids"][0] = (
        effects[45]["gate_ids"][0], effects[44]["gate_ids"][0])
    with pytest.raises(ValueError, match="crossed a canonical layer"):
        audit.verify_cz_batches(protocol, effects, "layer")


def test_equal_size_pulse_cannot_mix_opposite_displacement_families(prefix):
    protocol = _protocol(prefix)
    effects = _effects(protocol)
    effects[45]["gate_ids"][0], effects[47]["gate_ids"][0] = (
        effects[47]["gate_ids"][0], effects[45]["gate_ids"][0])
    with pytest.raises(ValueError, match="Opposite X/Z"):
        audit.verify_cz_batches(protocol, effects, "layer")


def _move_fixture(tmp_path):
    source = {"x_um": [0, 10], "y_um": [0, 10]}
    target = {"x_um": [5, 20], "y_um": [0, 10]}
    holder = {"holder_type": "mobile", "holder_id": {"aod_id": "AOD_0", "row": 0, "column": 1}}
    atom = {"id": "a", "holder": holder, "position": {"x_um": 10, "y_um": 0}}
    final_atom = deepcopy(atom)
    final_atom["position"]["x_um"] = 20
    masks = {"enabled_rows": [True, False], "enabled_columns": [True, True]}
    op = {"kind": "aod_move", "plan_id": "p", "aod_id": "AOD_0", "start": 0, "end": 30,
          "source_axes": source, "target_axes": target, "moving_atom_ids": ["a"], **masks}
    recording = {"operations": [op], "frames": [
        {"time": 0, "version": 1, "atom_updates": [atom], "axes_by_aod": {"AOD_0": source}, "aods": {"AOD_0": masks}},
        {"time": 30, "version": 2, "atom_updates": [final_atom], "axes_by_aod": {"AOD_0": target}, "aods": {"AOD_0": masks}}]}
    rows = [{"operation_type": "aod_move", "aod_id": "AOD_0", "motion_profile": "cubic",
             "state_version": 1, "source_configuration": source, "target_configuration": target, "moving_atom_ids": ["a"],
             "event": {"event_type": "operation_started", "time_us": 0, "plan_id": "p", "operation_id": "m"}},
            {"operation_type": "aod_move", "aod_id": "AOD_0", "state_version": 2, "event": {
                "event_type": "operation_completed", "time_us": 30, "plan_id": "p", "operation_id": "m"}}]
    path = tmp_path / "trace.jsonl"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    initial = {"hardware": {"backend": "row_column", "minimum_axis_spacing_um": 2, "speed_um_per_us": 1,
                           "max_acceleration_um_per_us2": 1, "max_jerk_um_per_us3": 1}}
    return recording, path, initial


def test_true_row_column_deformation_uses_committed_axes_and_cells(tmp_path):
    recording, path, initial = _move_fixture(tmp_path)
    result = audit.verify_move_evidence(recording, path, initial)
    assert result["committed_moves_checked"] == 1
    assert result["carrier_endpoint_checks"] == 2
    assert result["deforming_axis_move_count"] == 1


def test_rendered_deformation_cannot_override_committed_target_configuration(tmp_path):
    recording, path, initial = _move_fixture(tmp_path)
    recording["operations"][0]["target_axes"] = {"x_um": [5, 25], "y_um": [0, 10]}
    with pytest.raises(ValueError, match="differ from committed"):
        audit.verify_move_evidence(recording, path, initial)


def test_endpoint_atom_is_bound_to_actual_aod_cell(tmp_path):
    recording, path, initial = _move_fixture(tmp_path)
    recording["frames"][-1]["atom_updates"][0]["position"]["x_um"] = 19
    with pytest.raises(ValueError, match="carrier endpoint"):
        audit.verify_move_evidence(recording, path, initial)


def test_mobile_spectator_cannot_be_omitted_from_move_evidence(tmp_path):
    recording, path, initial = _move_fixture(tmp_path)
    other = deepcopy(recording["frames"][0]["atom_updates"][0])
    other["id"] = "spectator"
    other["holder"]["holder_id"]["column"] = 0
    other["position"]["x_um"] = 0
    recording["frames"][0]["atom_updates"].append(other)
    with pytest.raises(ValueError, match="mobile spectator"):
        audit.verify_move_evidence(recording, path, initial)


def test_rigid_trace_cannot_hide_an_independently_moved_column(tmp_path):
    recording, path, initial = _move_fixture(tmp_path)
    initial["hardware"]["backend"] = "rigid"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["motion_profile"] = "linear"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    with pytest.raises(ValueError, match="rigid MOVE changed"):
        audit.verify_move_evidence(recording, path, initial)


def test_ten_um_nonpair_rule_is_stricter_than_finite_cz_legality():
    recording = {"frames": [{"time": 0, "atom_updates": [
        {"id": "a", "position": {"x_um": 0, "y_um": 0}},
        {"id": "b", "position": {"x_um": -3, "y_um": 0}},
        {"id": "spectator", "position": {"x_um": 0, "y_um": 8}}]}],
        "operations": [{"kind": "entangling_pulse", "start": 0, "gate_ids": ["cz"]}]}
    gates = [{"id": "cz", "qubit_ids": ["a", "b"]}]
    initial = {"atoms": {atom: {} for atom in ("a", "b", "spectator")}}
    with pytest.raises(ValueError, match="10 um CZ design"):
        audit.verify_nonpair_spacing(recording, gates, initial)


def test_rigid_cartesian_move_uses_trace_endpoints_without_fictitious_deformation(tmp_path):
    recording, path, initial = _move_fixture(tmp_path)
    initial["hardware"]["backend"] = "rigid"
    target = {"x_um": [5, 15], "y_um": [0, 10]}
    recording["operations"][0]["target_axes"] = target
    recording["frames"][-1]["axes_by_aod"]["AOD_0"] = target
    recording["frames"][-1]["atom_updates"][0]["position"]["x_um"] = 15
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[0]["target_configuration"] = target
    rows[0]["motion_profile"] = "linear"
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    result = audit.verify_move_evidence(recording, path, initial)
    assert result["backend"] == "rigid" and result["deforming_axis_move_count"] == 0


def test_standard_home_layout_keeps_fixed_slm_grid_and_declared_local_aod_capacity(prefix):
    env, _, _, _ = create_interleaved_environment(prefix)
    initial = json.loads(env.snapshot())
    result = audit.verify_home_layout(initial, _protocol(prefix))
    assert result["minimum_occupied_home_distance_um"] == pytest.approx(2 ** 0.5 * 10)
    assert result["algorithm_aod_capacity"] == 9
    assert result["finite_cz_distance_um"] == 6


def test_layout_audit_rejects_widening_cz_radius_to_bypass_pairing(prefix):
    env, _, _, _ = create_interleaved_environment(prefix)
    initial = json.loads(env.snapshot())
    initial["hardware"]["interaction_distance_um"] = 12
    with pytest.raises(ValueError, match="finite 6 um CZ"):
        audit.verify_home_layout(initial, _protocol(prefix))


@pytest.mark.parametrize("partitions", (1, 2))
def test_enola_mode_counts_actual_canonical_subsets_without_imposing_predicted_pulse_count(prefix, partitions):
    protocol = _protocol(prefix)
    patch = protocol["patches"][0]
    effects = [{"kind": "entangling_pulse", "gate_ids": [gid]} for gid in protocol["css_cz"][patch]]
    for layer in range(1, 5):
        ids = [gid for gid, l, _ in protocol["canonical_cz"][patch] if l == layer]
        effects.extend({"kind": "entangling_pulse", "gate_ids": ids[index::partitions]}
                       for index in range(partitions))
    result = audit.verify_cz_batches(protocol, effects, "enola")
    assert result["canonical_round_cz_pulses"] == 4 * partitions
    assert result["cz_native_effects"] == 68


def test_enola_mode_cannot_count_dropped_coupling_as_a_smaller_parallel_circuit(prefix):
    protocol = _protocol(prefix)
    effects = _effects(protocol)
    effects[-1]["gate_ids"].pop()
    with pytest.raises(ValueError, match="exactly once"):
        audit.verify_cz_batches(protocol, effects, "enola")


@pytest.fixture
def proposal():
    return ROOT / "references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json"


def test_frozen_enola_proposal_authenticates_exact_bytes_and_independent_role_mapping(proposal):
    result = audit.verify_enola_proposal(proposal)
    assert result["proposal_raw_sha256"] == "b04b39ba29e6345c26404d289b6d3b441e1f3a92d9fb7ab249cd1b9b2d1b68ae"
    assert result["placement_mapping_sha256"] == "49a2c2d531af2bad5e77d8d368c6809dd8386ffe19c3fe166c7e23882b44337c"
    assert result["coordinates_um"]["d0"] == (40, 20)
    assert result["coordinates_um"]["X0"] == (30, 20)


def test_changed_proposal_bytes_cannot_relabel_geometry_as_author_output(proposal, tmp_path):
    changed = tmp_path / "changed.json"
    changed.write_bytes(proposal.read_bytes() + b" ")
    with pytest.raises(ValueError, match="raw bytes"):
        audit.verify_enola_proposal(changed)


def test_enola_initial_and_observer_coordinates_bind_to_same_actual_roles(prefix, proposal):
    env, _, _, metadata = create_enola_environment(prefix, proposal)
    recording = VisualRecorder(env.state, scene_metadata={key: value for key, value in metadata.items()
        if key != "layout_contract"}).payload()
    result = audit.verify_home_layout(json.loads(env.snapshot()), _protocol(prefix),
                                     proposal=proposal, recording=recording)
    assert result["minimum_occupied_home_distance_um"] == 10
    assert result["enola_proposal"]["placement_mapping_sha256"] == audit.ENOLA_MAPPING_SHA256


def test_enola_display_cannot_swap_data_and_syndrome_roles(prefix, proposal):
    env, _, _, metadata = create_enola_environment(prefix, proposal)
    recording = VisualRecorder(env.state, scene_metadata={key: value for key, value in metadata.items()
        if key != "layout_contract"}).payload()
    atom = dict(prefix.bindings)["phase0.d0"]
    recording["scene"]["atom_roles"][atom]["role"] = "phase0.X0"
    with pytest.raises(ValueError, match="role/coordinate binding"):
        audit.verify_home_layout(json.loads(env.snapshot()), _protocol(prefix),
                                 proposal=proposal, recording=recording)


def test_equal_time_equal_axes_uses_committed_version_after_capture(tmp_path):
    recording, path, initial = _move_fixture(tmp_path)
    earlier = deepcopy(recording["frames"][0])
    earlier["version"] = 0
    earlier["atom_updates"][0]["holder"] = {"holder_type": "static", "holder_id": "SLM_a"}
    recording["frames"].insert(0, earlier)
    result = audit.verify_move_evidence(recording, path, initial)
    assert result["carrier_endpoint_checks"] == 2
