"""Independent hand-constructed geometry witnesses for offline strict review."""
from dataclasses import replace
from math import sqrt

import pytest

from neutral_atom_kernel.audit import audit_operations
from neutral_atom_kernel.model import GateSpec, Operation


PROFILE = {
    "bounds_um": (-100, -100, 200, 200), "slm_grid_um": 5,
    "aod_rows": 8, "aod_columns": 16, "aod_capacity": 128,
    "cz_zone_um": (-10, -10, 90, 90),
    "measurement_zone_um": (100, 100, 200, 200),
}


def move(oid, targets, displacement):
    return Operation(oid, "MOVE", tuple(targets), 200 * sqrt(displacement / 110), tuple(targets.items()),
                     metadata={"source_line": 42})


def code(report):
    assert report["status"] == "FAIL"
    return report["failures"][0]["code"]


def test_complete_legal_load_transport_store_measure_reset_has_real_time():
    initial = {"q0": (0, 0), "spectator": (50, -50)}
    gates = (GateSpec("h", "H", ("q0",)), GateSpec("m", "MEASURE", ("q0",), ("h",)),
             GateSpec("r", "RESET", ("q0",), ("m",)))
    operations = (Operation("h-op", "GATE", ("q0",), 1, gate_ids=("h",), metadata={"gate_kind": "H"}),
                  Operation("load", "LOAD", ("q0",), 15),
                  move("move", {"q0": (100, 100)}, 100),
                  Operation("store", "STORE", ("q0",), 15),
                  Operation("measure", "MEASURE", ("q0",), 500, gate_ids=("m",), report_ids=("m",)),
                  Operation("reset", "RESET", ("q0",), 100, gate_ids=("r",)))
    report = audit_operations(initial, operations, PROFILE, gates=gates)
    assert report["status"] == "PASS", report
    assert report["checked_operations"] == 6
    assert report["final_reviewed_state"]["holders"]["q0"] == "slm"
    assert report["final_reviewed_state"]["positions"]["q0"] == [100.0, 100.0]
    assert report["final_reviewed_state"]["time_us"] == pytest.approx(631 + 200 * sqrt(100 / 110))
    assert "Cartesian" in report["geometry_contract"]["active_axes"]


def test_load_checks_undeclared_cartesian_capture_not_only_loaded_diagonal():
    initial = {"a": (0, 0), "b": (10, 10), "omitted": (0, 10)}
    report = audit_operations(initial, (Operation("load", "LOAD", ("a", "b"), 15),), PROFILE)
    assert code(report) == "OMITTED_CARTESIAN_CAPTURE"
    assert report["checked_operations"] == 0
    assert report["final_reviewed_state"]["holders"]["a"] == "slm"


def test_empty_cartesian_cell_sweep_catches_collision_that_atoms_miss():
    initial = {"a": (0, 0), "b": (10, 10), "spectator": (10, 20)}
    operations = (Operation("load", "LOAD", ("a", "b"), 15),
                  move("move", {"a": (0, 30), "b": (10, 40)}, 30))
    report = audit_operations(initial, operations, PROFILE)
    assert code(report) == "AOD_STATIC_SWEEP"
    assert report["failures"][0]["op_id"] == "move"
    assert report["failures"][0]["source_line"] == 42
    assert report["checked_operations"] == 1
    assert report["final_reviewed_state"]["positions"]["a"] == [0.0, 0.0]


def test_continuous_loaded_atom_collision_rejects_clear_endpoints():
    initial = {"a": (0, 0), "spectator": (10, 0)}
    operations = (Operation("load", "LOAD", ("a",), 15), move("cross", {"a": (20, 0)}, 20))
    assert code(audit_operations(initial, operations, PROFILE)) == "AOD_STATIC_SWEEP"


def test_shared_axis_must_move_all_its_atoms():
    initial = {"a": (0, 0), "b": (0, 10)}
    operations = (Operation("load", "LOAD", ("a", "b"), 15), move("split", {"a": (10, 0)}, 10))
    assert code(audit_operations(initial, operations, PROFILE)) == "AOD_SHARED_AXIS_SPLIT"


def test_ordered_axes_cannot_exchange_even_when_endpoints_clear():
    initial = {"a": (0, 0), "b": (10, 0)}
    operations = (Operation("load", "LOAD", ("a", "b"), 15), move("cross", {"a": (10, 0), "b": (0, 0)}, 10))
    assert code(audit_operations(initial, operations, PROFILE)) == "AOD_AXIS_CROSSING"


def test_cartesian_capacity_counts_empty_intersections():
    initial = {"a": (0, 0), "b": (10, 10), "c": (20, 20)}
    profile = dict(PROFILE, aod_capacity=8)
    assert code(audit_operations(initial, (Operation("load", "LOAD", tuple(initial), 15),), profile)) == "AOD_CAPACITY"


def test_selective_store_closes_unused_axis_and_can_be_legal():
    initial = {"a": (0, 0), "b": (10, 10)}
    operations = (Operation("load", "LOAD", tuple(initial), 15), Operation("store-a", "STORE", ("a",), 15))
    report = audit_operations(initial, operations, PROFILE)
    assert report["passed"], report
    assert report["final_reviewed_state"]["holders"] == {"a": "slm", "b": "AOD_0"}


def test_selective_store_rejects_new_static_atom_on_still_active_empty_cell():
    initial = {"a": (0, 0), "b": (0, 10), "c": (10, 0)}
    operations = (Operation("load", "LOAD", tuple(initial), 15), Operation("store-a", "STORE", ("a",), 15))
    assert code(audit_operations(initial, operations, PROFILE)) == "EMPTY_TRAP_STATIC_OVERLAP"


def test_store_requires_actual_legal_slm_lattice_position():
    initial = {"a": (0, 0)}
    operations = (Operation("load", "LOAD", ("a",), 15), move("move", {"a": (3, 10)}, 10),
                  Operation("store", "STORE", ("a",), 15))
    assert code(audit_operations(initial, operations, PROFILE)) == "INVALID_SLM_SITE"


def test_valid_parallel_cz_includes_zone_spectators_and_exact_requested_pairs():
    initial = {"a": (0, 0), "b": (5, 0), "c": (20, 0), "d": (25, 0), "outside": (100, 0)}
    gates = (GateSpec("cz0", "CZ", ("a", "b")), GateSpec("cz1", "CZ", ("c", "d")))
    op = Operation("pulse", "CZ", ("a", "b", "c", "d"), .36, gate_ids=("cz0", "cz1"),
                   metadata={"pairs": (("a", "b"), ("c", "d"))})
    assert audit_operations(initial, (op,), PROFILE, gates=gates)["passed"]


def test_cz_reports_unrequested_spectator_pair():
    initial = {"a": (0, 0), "b": (5, 0), "spectator": (10, 0)}
    op = Operation("pulse", "CZ", ("a", "b"), .36, gate_ids=("cz",), metadata={"pairs": (("a", "b"),)})
    assert code(audit_operations(initial, (op,), PROFILE)) == "CZ_ACTUAL_PAIRS"


def test_cz_nonpartner_clearance_rejects_pair_not_in_finite_range():
    initial = {"a": (0, 0), "b": (5, 0), "spectator": (10, 5)}
    op = Operation("pulse", "CZ", ("a", "b"), .36, gate_ids=("cz",), metadata={"pairs": (("a", "b"),)})
    assert code(audit_operations(initial, (op,), PROFILE)) == "CZ_NONPARTNER_CLEARANCE"


def test_zone_metadata_is_reviewed_not_gate_target_subset():
    initial = {"a": (0, 0), "b": (5, 0), "c": (20, 0), "d": (25, 0)}
    op = Operation("pulse", "CZ", ("a", "b"), .36, gate_ids=("cz",),
                   metadata={"pairs": (("a", "b"),), "zone_ids": ("left",),
                             "zone_bounds": {"left": ((-5, -5), (10, 5)), "right": ((15, -5), (30, 5))}})
    profile = dict(PROFILE, cz_zones_um={"left": ((-5, -5), (10, 5)), "right": ((15, -5), (30, 5))})
    assert code(audit_operations(initial, (op,), profile)) == "CZ_ZONE_BINDING"
    full = replace(op, metadata=dict(op.metadata, zone_bounds={"left": ((-100, -5), (200, 5))}))
    assert code(audit_operations(initial, (full,), profile)) == "CZ_ACTUAL_PAIRS"
    assert code(audit_operations(initial, (op,), PROFILE)) == "CZ_ZONE_BINDING"


def test_raman_checks_addressed_atom_against_every_spectator():
    initial = {"a": (0, 0), "spectator": (0, 5)}
    op = Operation("h", "GATE", ("a",), 1, gate_ids=("h",), metadata={"gate_kind": "H"})
    assert audit_operations(initial, (op,), PROFILE)["passed"]
    assert code(audit_operations(initial, (op,), dict(PROFILE, raman_separation_um=6))) == "RAMAN_SEPARATION"


@pytest.mark.parametrize("kind,duration", [("MEASURE", 500), ("RESET", 100)])
def test_readout_and_reset_require_stable_mz_support(kind, duration):
    gate = GateSpec("effect", kind, ("a",))
    op = Operation("read", kind, ("a",), duration, gate_ids=("effect",))
    assert code(audit_operations({"a": (0, 0)}, (op,), PROFILE, gates=(gate,))) == "READOUT_ZONE_SUPPORT"
    assert code(audit_operations({"a": (100, 100)}, (op,), PROFILE, initial_holders={"a": "AOD_0"}, gates=(gate,))) == "READOUT_ZONE_SUPPORT"
    assert audit_operations({"a": (100, 100)}, (op,), PROFILE, gates=(gate,))["passed"]


def test_duration_is_checked_against_hardware_not_trusted_metadata():
    op = Operation("load", "LOAD", ("a",), 0, metadata={"source_line": 7})
    report = audit_operations({"a": (0, 0)}, (op,), PROFILE)
    assert code(report) == "DURATION_MISMATCH"
    assert report["failures"][0]["source_line"] == 7


def test_duplicate_missing_or_wrong_identity_effects_are_rejected():
    initial = {"a": (0, 0), "b": (20, 0)}
    gate = GateSpec("h", "H", ("a",))
    op = Operation("h", "GATE", ("a",), 1, gate_ids=("h",), metadata={"gate_kind": "H"})
    assert code(audit_operations(initial, (op, replace(op, id="again")), PROFILE, gates=(gate,))) == "DUPLICATE_GATE_EFFECT"
    assert code(audit_operations(initial, (), PROFILE, gates=(gate,))) == "MISSING_GATE_EFFECT"
    assert code(audit_operations(initial, (replace(op, atoms=("b",)),), PROFILE, gates=(gate,))) == "GATE_ATOM_MAPPING"
    assert code(audit_operations(initial, (replace(op, atoms=("a", "b")),), PROFILE, gates=(gate,))) == "GATE_ATOM_MAPPING"
    duplicate_target = (gate, GateSpec("other", "H", ("a",)))
    assert code(audit_operations(initial, (replace(op, gate_ids=("h", "other")),), PROFILE, gates=duplicate_target)) == "GATE_ATOM_MAPPING"


def test_transfer_cannot_teleport_and_native_second_aod_is_not_qualified():
    initial = {"a": (0, 0)}
    op = Operation("load", "LOAD", ("a",), 15, positions=(("a", (10, 0)),))
    assert code(audit_operations(initial, (op,), PROFILE)) == "TRANSFER_TELEPORTATION"
    op = Operation("load", "LOAD", ("a",), 15, aod_id="AOD_1")
    assert code(audit_operations(initial, (op,), PROFILE)) == "UNSUPPORTED_AOD_PROFILE"


def test_bounds_are_required_and_review_does_not_mutate_inputs():
    initial = {"a": [0, 0]}
    profile = dict(PROFILE)
    report = audit_operations(initial, (), {})
    assert code(report) == "PROFILE_REQUIRED"
    assert audit_operations(initial, (), profile)["passed"]
    assert initial == {"a": [0, 0]} and profile == PROFILE


@pytest.mark.parametrize("key,value", [("cz_radius_um", 100), ("raman_separation_um", 1),
                                      ("transport_clearance_um", .1), ("cz_nonpartner_um", 1),
                                      ("slm_grid_um", 1), ("aod_axis_spacing_um", .1)])
def test_profile_cannot_weaken_physical_thresholds(key, value):
    assert code(audit_operations({"a": (0, 0)}, (), dict(PROFILE, **{key: value}))) == "PROFILE_PHYSICAL_THRESHOLD"


def test_profile_cannot_make_hidden_transport_or_readout_free():
    assert code(audit_operations({"a": (0, 0)}, (), dict(PROFILE, load_duration_us=1))) == "PROFILE_HARDWARE_TIMING"


FULL_PROFILE = dict(PROFILE, aod_rows=2, aod_columns=2, aod_capacity=4)
AXES = {"columns": (0, 20), "rows": (0, 20)}


def full_meta(source, target, xs=(), ys=()):
    return {"source_axes": source, "target_axes": target, "active_columns": xs, "active_rows": ys}


def test_explicit_empty_configuration_is_timed_and_full_coordinates_retained():
    target = {"columns": (10, 30), "rows": (10, 30)}
    op = Operation("configure", "CONFIGURE", duration_us=200 * sqrt(10 / 110), metadata=full_meta(AXES, target))
    report = audit_operations({"a": (0, 0)}, (op,), FULL_PROFILE, initial_axes=AXES)
    assert report["passed"], report
    assert report["final_reviewed_state"]["axes"] == {"columns": [10.0, 30.0], "rows": [10.0, 30.0]}
    assert report["geometry_contract"]["name"] == "experimental_native_full_rf_ordered_axes/2"
    assert "disabled RF axes" in report["geometry_contract"]["dormant_axes"]


def test_full_rf_movement_time_includes_disabled_spare_axis_travel():
    target = {"columns": (10, 100), "rows": (10, 20)}
    load = Operation("load", "LOAD", ("a",), 15, metadata=full_meta(AXES, AXES, (0,), (0,)))
    movement = Operation("move", "MOVE", ("a",), 200 * sqrt(80 / 110), positions=(("a", (10, 10)),),
                         metadata=full_meta(AXES, target, (10,), (10,)))
    report = audit_operations({"a": (0, 0)}, (load, movement), FULL_PROFILE, initial_axes=AXES)
    assert report["passed"], report
    wrong_duration = replace(movement, duration_us=200 * sqrt(10 / 110))
    assert code(audit_operations({"a": (0, 0)}, (load, wrong_duration), FULL_PROFILE, initial_axes=AXES)) == "DURATION_MISMATCH"


def test_disabled_rf_coordinates_cannot_escape_bounds_or_cross():
    assert code(audit_operations({"a": (0, 0)}, (), FULL_PROFILE,
                                initial_axes={"columns": (0, 300), "rows": (0, 20)})) == "AOD_AXIS_BOUNDS"
    assert code(audit_operations({"a": (0, 0)}, (), FULL_PROFILE,
                                initial_axes={"columns": (20, 0), "rows": (0, 20)})) == "AOD_AXIS_SPACING"


def test_full_rf_metadata_binds_origin_and_atom_axis_identity():
    load = Operation("load", "LOAD", ("a",), 15, metadata=full_meta(AXES, AXES, (0,), (0,)))
    wrong_source = {"columns": (5, 20), "rows": (0, 20)}
    assert code(audit_operations({"a": (0, 0)}, (replace(load, metadata=full_meta(wrong_source, AXES)),),
                                FULL_PROFILE, initial_axes=AXES)) == "AOD_AXIS_BINDING"
    target = {"columns": (5, 20), "rows": (0, 20)}
    movement = Operation("move", "MOVE", ("a",), 200 * sqrt(5 / 110), positions=(("a", (10, 0)),),
                         metadata=full_meta(AXES, target, (10,), (0,)))
    assert code(audit_operations({"a": (0, 0)}, (load, movement), FULL_PROFILE, initial_axes=AXES)) == "AOD_AXIS_SUPPORT"


def test_configuration_cannot_move_loaded_atoms_or_teleport_for_free():
    load = Operation("load", "LOAD", ("a",), 15, metadata=full_meta(AXES, AXES, (0,), (0,)))
    target = {"columns": (10, 30), "rows": (10, 30)}
    cfg = Operation("cfg", "CONFIGURE", duration_us=200 * sqrt(10 / 110), metadata=full_meta(AXES, target))
    assert code(audit_operations({"a": (0, 0)}, (load, cfg), FULL_PROFILE, initial_axes=AXES)) == "CONFIGURE_LOADED_DEVICE"
    assert code(audit_operations({"a": (0, 0)}, (replace(cfg, duration_us=0),), FULL_PROFILE, initial_axes=AXES)) == "DURATION_MISMATCH"


def test_active_mask_cannot_hide_loaded_support_or_enable_undeclared_line():
    op = Operation("load", "LOAD", ("a",), 15, metadata=full_meta(AXES, AXES, (0, 20), (0,)))
    assert code(audit_operations({"a": (0, 0)}, (op,), FULL_PROFILE, initial_axes=AXES)) == "AOD_ACTIVE_MASK_BINDING"


def test_full_rf_stream_requires_declared_initial_rf_coordinates():
    op = Operation("load", "LOAD", ("a",), 15, metadata=full_meta(AXES, AXES, (0,), (0,)))
    assert code(audit_operations({"a": (0, 0)}, (op,), FULL_PROFILE)) == "INITIAL_AXES_REQUIRED"


def scheduled(initial, operations, profile=PROFILE, **kwargs):
    return audit_operations(initial, operations, profile, execution_mode="scheduled", **kwargs)


def test_global_ez_band_cannot_hide_remote_x_spectator_pair():
    initial = {"a": (0, 0), "b": (5, 0), "remote-c": (150, 0), "remote-d": (155, 0)}
    op = Operation("cz", "CZ", ("a", "b"), .36, gate_ids=("cz",),
                   metadata={"pairs": (("a", "b"),), "zone_bounds": {"ez": ((-100, -10), (200, 90))},
                             "zone_ids": ("ez",), "illumination_scope": "global-world-x-y-band/v1"})
    assert code(audit_operations(initial, (op,), PROFILE)) == "CZ_ACTUAL_PAIRS"
    outside = {**initial, "remote-c": (150, 100), "remote-d": (155, 100)}
    assert audit_operations(outside, (op,), PROFILE)["passed"]


def test_global_ez_band_checks_remote_spectator_nonpartners():
    initial = {"a": (0, 0), "b": (5, 0), "remote-c": (150, 0), "remote-d": (155, 5)}
    op = Operation("cz", "CZ", ("a", "b"), .36, gate_ids=("cz",), metadata={"pairs": (("a", "b"),)})
    assert code(audit_operations(initial, (op,), PROFILE)) == "CZ_NONPARTNER_CLEARANCE"


def test_independent_same_kind_slm_pulses_overlap_and_time_is_makespan():
    gates = (GateSpec("ha", "H", ("a",)), GateSpec("hb", "H", ("b",)))
    ops = tuple(Operation(g.id, "GATE", g.atoms, 1, gate_ids=(g.id,), start_us=0,
                          metadata={"gate_kind": "H"}) for g in gates)
    report = scheduled({"a": (0, 0), "b": (20, 0)}, ops, gates=gates)
    assert report["passed"], report
    assert report["final_reviewed_state"]["time_us"] == 1
    assert report["checked_operations"] == 2


def test_completion_precedes_equal_time_start_and_dependencies_are_real():
    gates = (GateSpec("h", "H", ("a",)), GateSpec("x", "X", ("a",), ("h",)))
    ops = (Operation("h", "GATE", ("a",), 1, gate_ids=("h",), start_us=0, metadata={"gate_kind": "H"}),
           Operation("x", "GATE", ("a",), 1, gate_ids=("x",), start_us=1, depends_on=("h",), metadata={"gate_kind": "X"}))
    assert scheduled({"a": (0, 0)}, ops, gates=gates)["passed"]
    assert code(scheduled({"a": (0, 0)}, (ops[0], replace(ops[1], start_us=.5)), gates=gates)) == "OPERATION_DEPENDENCY"


def test_scheduled_stream_cannot_omit_explicit_start():
    assert code(scheduled({"a": (0, 0)}, (Operation("wait", "WAIT", duration_us=1),))) == "OPERATION_START"


def test_extra_resource_cannot_remove_core_atom_or_device_exclusions():
    ops = (Operation("load-a", "LOAD", ("a",), 15, start_us=0, resources=("extra-a",)),
           Operation("load-b", "LOAD", ("b",), 15, start_us=0, resources=("extra-b",)))
    assert code(scheduled({"a": (0, 0), "b": (20, 0)}, ops)) == "RESOURCE_OVERLAP"
    gate = Operation("h", "GATE", ("a",), 1, gate_ids=("h",), start_us=0, metadata={"gate_kind": "H"})
    assert code(scheduled({"a": (0, 0)}, (gate, replace(gate, id="other", gate_ids=("other",))))) == "RESOURCE_OVERLAP"


def test_different_light_modes_are_excluded_even_on_distinct_atoms():
    ops = (Operation("h", "GATE", ("a",), 1, gate_ids=("h",), start_us=0, metadata={"gate_kind": "H"}),
           Operation("x", "GATE", ("b",), 1, gate_ids=("x",), start_us=.5, metadata={"gate_kind": "X"}))
    assert code(scheduled({"a": (0, 0), "b": (20, 0)}, ops)) == "LIGHT_TYPE_OVERLAP"


def test_cubic_motion_is_checked_over_raman_overlap_not_linear_or_endpoints():
    duration = 200 * sqrt(20 / 110)
    load = Operation("load", "LOAD", ("a",), 15, start_us=0)
    movement = replace(move("move", {"a": (20, 0)}, 20), start_us=15, depends_on=("load",))
    # At u=.1 cubic x≈.56, whereas linear x=2. The latter would falsely fail.
    pulse = Operation("h", "GATE", ("b",), 1, gate_ids=("h",), start_us=15 + .1 * duration,
                      metadata={"gate_kind": "H"})
    profile = dict(PROFILE, raman_separation_um=6)
    report = scheduled({"a": (0, 0), "b": (5, 5)}, (load, movement, pulse), profile)
    assert report["passed"], report
    close_pulse = replace(pulse, start_us=15 + .17 * duration)
    assert code(scheduled({"a": (0, 0), "b": (5, 5)}, (load, movement, close_pulse), profile)) == "RAMAN_INTERVAL_SEPARATION"
    assert code(scheduled({"a": (0, 0), "b": (5, 5)}, (load, replace(movement, motion_profile="rigid"), pulse), profile)) == "RAMAN_SEPARATION"
    # The committed MOVE source can be near a target while its actual pulse-time pose is safe.
    far_pulse = replace(pulse, start_us=15 + .5 * duration)
    assert scheduled({"a": (0, 0), "b": (0, 5)}, (load, movement, far_pulse), profile)["passed"]


def test_moving_atom_cannot_enter_global_ez_during_static_cz_pulse():
    initial = {"moving": (150, -20), "a": (0, 0), "b": (5, 0)}
    load = Operation("load", "LOAD", ("moving",), 15, start_us=0)
    movement = replace(move("move", {"moving": (150, 20)}, 40), start_us=15, depends_on=("load",))
    pulse = Operation("cz", "CZ", ("a", "b"), .36, gate_ids=("cz",),
                      start_us=15 + .325 * movement.duration_us, metadata={"pairs": (("a", "b"),)})
    # At pulse submission the committed endpoint is outside the band; cubic path enters it.
    assert code(scheduled(initial, (load, movement, pulse))) == "CZ_MOVING_ILLUMINATION"


def test_readout_reports_commit_at_completion_after_safe_overlap():
    initial = {"a": (100, 100), "b": (0, 0)}
    gates = (GateSpec("m", "MEASURE", ("a",)), GateSpec("h", "H", ("b",)))
    ops = (Operation("read", "MEASURE", ("a",), 500, gate_ids=("m",), report_ids=("result",), start_us=0),
           Operation("h", "GATE", ("b",), 1, gate_ids=("h",), start_us=200, metadata={"gate_kind": "H"}))
    report = scheduled(initial, ops, gates=gates)
    assert report["passed"], report
    assert report["final_reviewed_state"]["measurement_completion_times_us"] == {"result": 500}
    assert report["final_reviewed_state"]["report_source_cursor"] == 1


def test_zero_duration_boundary_preserves_parent_first_causality():
    ops = (Operation("first", "WAIT", start_us=0), Operation("next", "WAIT", duration_us=1, start_us=0, depends_on=("first",)))
    assert scheduled({"a": (0, 0)}, ops)["passed"]
    assert code(scheduled({"a": (0, 0)}, ops[::-1])) == "OPERATION_DEPENDENCY"


def test_explicit_slm_inventory_and_regions_override_implicit_world_lattice():
    profile = dict(PROFILE, declared_slm_sites_um=((0, 0), (20, 0)), slm_site_regions_um=((-10, -10, 30, 10),))
    assert code(audit_operations({"a": (10, 0)}, (), profile)) == "UNDECLARED_SLM_SITE"
    ops = (Operation("load", "LOAD", ("a",), 15), move("move", {"a": (10, 0)}, 10), Operation("store", "STORE", ("a",), 15))
    assert code(audit_operations({"a": (0, 0)}, ops, profile)) == "UNDECLARED_SLM_SITE"
    assert code(audit_operations({"a": (20, 0)}, (), dict(PROFILE, slm_site_regions_um=((-5, -5, 5, 5),)))) == "UNDECLARED_SLM_SITE"
    # AOD corridors may use off-lattice coordinates, but cannot STORE there.
    corridor = (Operation("load", "LOAD", ("a",), 15), move("move", {"a": (2.5, 2.5)}, 2.5))
    assert audit_operations({"a": (0, 0)}, corridor, profile)["passed"]
    assert code(audit_operations({"a": (0, 0)}, (*corridor, Operation("store", "STORE", ("a",), 15)), profile)) == "INVALID_SLM_SITE"
