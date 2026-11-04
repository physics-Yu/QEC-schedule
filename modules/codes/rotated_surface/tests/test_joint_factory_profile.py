"""Group timing, fail-closed coverage, and no physical compilation in fast runs."""

import pytest

from modules.codes.rotated_surface.fast_factory import acceptance_port
from modules.codes.rotated_surface.joint_factory_profile import (
    JointSurfaceFactoryProfile,
    MissingJointCalibration,
    joint_key,
)
from modules.codes.rotated_surface.tests.factory_fixtures import (
    fixture_profile,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory


class SyntheticJointProfile(JointSurfaceFactoryProfile):
    """Unit-control costs only; never physical calibration evidence."""

    def group(self, members):
        key = joint_key(members)
        if key not in self.groups:
            self.groups[key] = {
                "family": self.joint_family,
                "validation_ok": True,
                "trace_sha256": "0" * 64,
                "phase_durations_us": [7.0],
                "peak_rows": 4,
                "peak_columns": 4,
                "peak_readout_atoms": 8 * len(members),
                "members": {
                    m: {
                        "measurement_phases": [(0, 0)]
                        * self.entries[m].claim["result_count"],
                        "cost_segments": [],
                        "primitive_counts": {},
                    }
                    for m in members
                },
                "raw_ports": {
                    m: acceptance_port(
                        1,
                        preparation="raw_t_postselection",
                        evidence={"test_fixture": True},
                        kind="test_fixture",
                    ).to_dict()
                    for m in members
                    if m.startswith("raw_t_postselection:")
                },
            }
        return super().group(members)


def joint_fixture(count=3):
    doc = fixture_profile(5, count).to_dict()
    doc["joint_calibration"] = {"family": "synthetic-joint-world", "limits": {}}
    return doc


def test_shared_frontiers_use_joint_time_not_sum_of_singleton_profiles(monkeypatch):
    count = 3
    profile = SyntheticJointProfile(joint_fixture(count))
    run_surface_factory(profile, seed=0, input_z_error=0)
    frozen = JointSurfaceFactoryProfile(profile.to_dict())
    from nadit_physical_compiler import compiler

    monkeypatch.setattr(
        compiler, "compile_physical", lambda *a, **k: pytest.fail("physical fallback")
    )
    result = run_surface_factory(frozen, seed=0, input_z_error=0)
    assert result["summary"]["outputs"] == count
    assert result["summary"]["hardware"]["aod_count"] == 1
    calls = result["case"]["execution"]["calls"]
    initial = [c for c in calls if c["start_us"] == 0]
    assert len(initial) == 5 * count
    assert {c["action_end_us"] for c in initial} == {7.0}
    assert all(
        c["reserved_resources"] == [] and c["shared_resources"] == ["aod:transport"]
        for c in calls
    )
    assert all(c["parallel_mode"] == "shared_aod_lockstep" for c in calls)


def test_final_mx_frontier_requires_complete_joint_calibration(monkeypatch):
    count = 3
    from nadit_physical_compiler import compiler

    monkeypatch.setattr(
        compiler, "compile_physical", lambda *a, **k: pytest.fail("physical fallback")
    )
    profile = SyntheticJointProfile(joint_fixture(count))
    result = run_surface_factory(profile, seed=0, input_z_error=0)
    final_calls = [
        call
        for call in result["case"]["execution"]["calls"]
        if "/final/mx/" in call["invocation_id"]
    ]
    members = tuple(
        f"logical_mx:factory{factory}/W{role}"
        for factory in range(count)
        for role in range(2, 6)
    )
    key = joint_key(members)
    assert len(final_calls) == 4 * count
    assert {call["profile_key"] for call in final_calls} == set(members)
    assert {call["joint_group_key"] for call in final_calls} == {key}
    assert len({call["batch_id"] for call in final_calls}) == 1
    assert len({call["start_us"] for call in final_calls}) == 1
    assert len({call["action_end_us"] for call in final_calls}) == 1
    assert all(call["action_end_us"] - call["start_us"] == 7.0 for call in final_calls)

    # Older profiles may cover each role across factories, but not all final MXs.
    for role in range(2, 6):
        profile.group(tuple(f"logical_mx:factory{f}/W{role}" for f in range(count)))
    document = profile.to_dict()
    del document["joint_groups"][key]
    with pytest.raises(MissingJointCalibration) as missing:
        run_surface_factory(
            JointSurfaceFactoryProfile(document), seed=0, input_z_error=0
        )
    assert set(missing.value.members) == set(members)


def test_joint_factory_accepts_exact_placement_plan_without_changing_budget(
    monkeypatch,
):
    distance = 3
    from nadit_physical_compiler import compiler

    from experiments.msd.standard import ExperimentSpec, build_world

    monkeypatch.setattr(
        compiler, "compile_physical", lambda *a, **k: pytest.fail("physical fallback")
    )
    world = build_world(ExperimentSpec(distance, 3))
    plan = world.placement_plan
    document = fixture_profile(distance, 3).to_dict()
    for patch in document["patches"]:
        origin = plan.placements[patch["block_id"]].origin
        patch["origin"] = [origin.x, origin.y]
    document["joint_calibration"] = {"family": "synthetic-plan-world", "limits": {}}
    profile = SyntheticJointProfile(document)
    layout = profile.layout(placement_plan=plan)
    assert layout.placement_plan is plan
    assert layout.budget["aod_count"] == 1
    assert all(
        layout.budget[key] is None
        for key in ("aod_max_rows", "aod_max_columns", "max_readout_atoms")
    )
    assert all(
        layout.bindings[patch.binding.block_id].origin == patch.binding.origin
        for patch in world.patches
    )
    run_surface_factory(profile, seed=0, input_z_error=0, placement_plan=plan)
    frozen = JointSurfaceFactoryProfile(profile.to_dict())
    result = run_surface_factory(frozen, seed=0, input_z_error=0, placement_plan=plan)
    assert result["summary"]["outputs"] == 3
    assert result["summary"]["placement_fingerprint"] == plan.geometry_fingerprint
    assert all(
        call["provenance"]["joint_trace_sha256"] == call["joint_trace_sha256"]
        and call["provenance"]["joint_group_key"] == call["joint_group_key"]
        for call in result["case"]["execution"]["calls"]
    )
