"""Calibration reuse depends on local applicability, never just factory count."""

import pytest
from nadit_physical_compiler.device import Position, Region

from modules.codes.contracts.geometry import BlockGeometry
from modules.logical_compiler.src.estimation.calibration import (
    CalibrationCache,
    CalibrationKey,
    CalibrationMiss,
    CalibrationRecord,
    MissingCalibration,
    calibration_context,
)
from modules.logical_compiler.src.placement import (
    BlockPlacement,
    BlockSpec,
    ExplicitPlacement,
    PlacementRequest,
    place,
)

DEVICE = {
    "control": {"pulse_us": 1, "version": "control-v1"},
    "transport": {"min_spacing_um": 5, "version": "transport-v1"},
    "readout": {"bounds": [-10, 90, 300, 130], "latency_us": 2},
}
DECLARATION = {"provider": "test_code.se", "version": "local-envelope-v1"}


def plan(positions=None, *, code="test_code", distance=3, version="geometry-v1"):
    positions = positions or {"a": (0, 0), "near": (100, 0)}
    geometry = BlockGeometry(
        code,
        distance,
        Region(0, 0, 60, 60),
        allowed_orientations=("standard", "rot180"),
        version=version,
    )
    request = PlacementRequest(
        blocks=tuple(BlockSpec(key, code, distance) for key in positions),
        geometries={code: geometry},
        positions={
            key: BlockPlacement(Position(*point)) for key, point in positions.items()
        },
    )
    return place(request, ExplicitPlacement())


def context(layout=None, **overrides):
    options = {
        "component_id": "se",
        "component_version": "1",
        "component_fingerprint": "source-content-v1",
        "device_context": DEVICE,
        "scope": "local",
        "influence_bounds": Region(-10, -10, 170, 70),
        "scope_evidence": DECLARATION,
    }
    options.update(overrides)
    return calibration_context(plan() if layout is None else layout, ("a",), **options)


def test_remote_new_factory_reuses_local_record_without_reusing_plan_identity():
    first = context()
    expanded = context(plan({"a": (0, 0), "near": (100, 0), "far": (1000, -300)}))
    assert first.geometry_fingerprint != expanded.geometry_fingerprint
    assert first.key == expanded.key
    cache = CalibrationCache()
    record = CalibrationRecord(first, {"duration_us": 5}, {"source": "verified-wave"})
    cache.put(record)
    assert cache.lookup(expanded) is record
    assert record.context.geometry_fingerprint == first.geometry_fingerprint


def test_world_scope_conservatively_invalidates_when_remote_world_changes():
    first = context(scope="world", influence_bounds=None)
    expanded = context(
        plan({"a": (0, 0), "near": (100, 0), "far": (1000, -300)}),
        scope="world",
        influence_bounds=None,
    )
    assert first.key != expanded.key


def test_nearby_spectator_change_is_a_miss_even_when_participant_is_unchanged():
    cache = CalibrationCache()
    cache.put(CalibrationRecord(context(), {"duration_us": 5}, {"source": "one"}))
    changed = context(plan({"a": (0, 0), "near": (105, 0)}))
    result = cache.lookup(changed)
    assert isinstance(result, CalibrationMiss)
    assert result.reason == "not_calibrated"
    assert result.key == changed.key
    assert result.geometry_fingerprint == changed.geometry_fingerprint
    with pytest.raises(MissingCalibration, match="MISSING_CALIBRATION") as error:
        cache.require(changed)
    assert error.value.missing == result


@pytest.mark.parametrize(
    "overrides",
    [
        {"component_id": "different_component"},
        {"component_version": "2"},
        {"component_fingerprint": "changed-source"},
        {"parameters": {"rounds": 4}},
        {"selection": {"byproduct_class": 1}},
        {"scope_evidence": {"provider": "test_code.se", "version": "v2"}},
        {"device_context": {**DEVICE, "readout": {"bounds": [-10, 100, 300, 140]}}},
        {"device_context": {**DEVICE, "control": {"pulse_us": 2}}},
        {"device_context": {**DEVICE, "transport": {"min_spacing_um": 6}}},
    ],
)
def test_changed_component_parameter_or_device_context_cannot_hit(overrides):
    assert context().key != context(**overrides).key


def test_code_distance_geometry_revision_and_orientation_are_part_of_identity():
    original = context(influence_bounds=Region(-70, -70, 170, 70))
    for changed in (
        plan(code="other_code"),
        plan(distance=5),
        plan(version="geometry-v2"),
    ):
        assert (
            context(changed, influence_bounds=Region(-70, -70, 170, 70)).key
            != original.key
        )
    layout = plan()
    alternate = place(
        PlacementRequest(
            blocks=layout.blocks,
            geometries=layout.geometries,
            positions={
                **layout.placements,
                "a": BlockPlacement(Position(0, 0), "rot180"),
            },
        ),
        ExplicitPlacement(),
    )
    assert (
        context(alternate, influence_bounds=Region(-70, -70, 170, 70)).key
        != original.key
    )


def test_translated_geometry_reuses_only_with_equivalent_relative_device_context():
    shifted = plan({"a": (500, -300), "near": (600, -300)})
    equivalent = context(shifted, influence_bounds=Region(490, -310, 670, -230))
    assert equivalent.key == context().key
    absolute_readout = {
        **DEVICE,
        "readout": {"bounds": [-510, 390, -200, 430], "latency_us": 2},
    }
    changed = context(
        shifted,
        influence_bounds=Region(490, -310, 670, -230),
        device_context=absolute_readout,
    )
    assert changed.key != equivalent.key


def test_rotated_spectator_footprint_entering_envelope_invalidates_reuse():
    straight = plan({"a": (0, 0), "turn": (200, 0)})
    rotated = place(
        PlacementRequest(
            blocks=straight.blocks,
            geometries=straight.geometries,
            positions={
                **straight.placements,
                "turn": BlockPlacement(Position(200, 0), "rot180"),
            },
        ),
        ExplicitPlacement(),
    )
    first = context(straight, influence_bounds=Region(-10, -70, 170, 70))
    second = context(rotated, influence_bounds=Region(-10, -70, 170, 70))
    assert first.key.to_dict()["spectators"] == []
    assert len(second.key.to_dict()["spectators"]) == 1
    assert first.key != second.key


@pytest.mark.parametrize(
    "overrides",
    [
        {"scope_evidence": None},
        {"scope_evidence": {"provider": "code"}},
        {"influence_bounds": None},
        {"influence_bounds": Region(0, 0, 20, 20)},
        {"global_operation": True},
        {"scope": "unknown"},
        {"device_context": {"control": {}, "transport": {}}},
        {"parameters": {"noise": float("nan")}},
        {"component_fingerprint": ""},
    ],
)
def test_incomplete_or_nonfinite_applicability_is_rejected(overrides):
    with pytest.raises((TypeError, ValueError)):
        context(**overrides)


def test_global_operation_can_only_use_world_scope():
    declared = context(scope="world", influence_bounds=None, global_operation=True)
    assert declared.key.to_dict()["global_operation"] is True


def test_records_and_context_are_immutable_copies_and_conflicts_fail():
    payload = {"duration_us": 5, "counts": {"measure": 8}}
    evidence = {"source": {"fingerprint": "a"}}
    record = CalibrationRecord(context(), payload, evidence)
    cache = CalibrationCache()
    cache.put(record)
    payload["counts"]["measure"] = 999
    evidence["source"]["fingerprint"] = "changed"
    exported = record.payload
    exported["counts"]["measure"] = 77
    assert cache.require(context()).payload["counts"]["measure"] == 8
    assert record.evidence["source"]["fingerprint"] == "a"
    with pytest.raises(ValueError, match="CONFLICTING_CALIBRATION"):
        cache.put(CalibrationRecord(context(), {"duration_us": 6}, {}))
    cache.put(CalibrationRecord(context(), record.payload, {"source": "second-proof"}))
    assert cache.require(context()) is record


def test_cache_roundtrip_and_tampered_fingerprints(tmp_path):
    cache = CalibrationCache()
    expected = CalibrationRecord(
        context(), {"duration_us": 5}, {"validation": "recorded"}
    )
    cache.put(expected)
    path = tmp_path / "nested/cache.json"
    cache.save(path)
    loaded = CalibrationCache.load(path)
    assert loaded.require(context()).to_dict() == expected.to_dict()
    assert loaded.to_dict() == cache.to_dict()
    tampered = cache.to_dict()
    tampered["records"][0]["context"]["key"]["component"]["version"] = "changed"
    with pytest.raises(ValueError, match="FINGERPRINT"):
        CalibrationCache.from_dict(tampered)


def test_parameter_order_and_signed_zero_do_not_create_new_geometric_keys():
    one = context(parameters={"rounds": 3, "mode": "full"})
    two = context(parameters=(("mode", "full"), ("rounds", 3)))
    assert one.key == two.key
    changed = one.key.to_dict()
    changed["participants"][0]["origin"] = [-0.0, 0.0]
    assert CalibrationKey.from_dict(changed) == one.key


def test_unknown_or_repeated_participants_never_create_a_cache_key():
    for participants in ((), ("missing",), ("a", "a")):
        with pytest.raises(ValueError):
            calibration_context(
                plan(),
                participants,
                component_id="se",
                component_version="1",
                component_fingerprint="code",
                device_context=DEVICE,
            )
