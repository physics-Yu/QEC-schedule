"""Group timing, fail-closed coverage, and no physical compilation in fast runs."""

import pytest

from modules.codes.rotated_surface.fast_factory import acceptance_port
from modules.codes.rotated_surface.joint_factory_profile import (
    JointSurfaceFactoryProfile,
    MissingJointCalibration,
    joint_key,
)
from modules.codes.rotated_surface.joint_factory_source import factory_component_source
from modules.codes.rotated_surface.tests.test_generic_fast_factory import (
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


def test_missing_joint_coverage_raises_without_serial_or_physical_fallback(monkeypatch):
    from nadit_physical_compiler import compiler

    monkeypatch.setattr(
        compiler, "compile_physical", lambda *a, **k: pytest.fail("physical fallback")
    )
    with pytest.raises(MissingJointCalibration):
        run_surface_factory(
            JointSurfaceFactoryProfile(joint_fixture()), seed=0, input_z_error=0
        )


@pytest.mark.parametrize("count", (1, 3, 7))
def test_shared_frontiers_use_joint_time_not_sum_of_singleton_profiles(
    count, monkeypatch
):
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


def test_joint_capacity_is_checked_on_group_peak_before_execution():
    profile = SyntheticJointProfile(joint_fixture(2))
    profile._document["joint_calibration"]["limits"] = {"max_readout_atoms": 1}
    with pytest.raises(ValueError, match="JOINT_CALIBRATION_EXCEEDS_DEVICE_CAPACITY"):
        run_surface_factory(profile, seed=0, input_z_error=0)


@pytest.mark.parametrize("count", (1, 3))
def test_final_mx_frontier_requires_complete_joint_calibration(count, monkeypatch):
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


def test_single_aod_keeps_cohort_grouping_barrier_while_peer_retries():
    class RejectSecondFactory(SyntheticJointProfile):
        def group(self, members):
            group = super().group(members)
            for member in group["raw_ports"]:
                if member.startswith("raw_t_postselection:factory1/"):
                    group["raw_ports"][member] = acceptance_port(
                        0,
                        preparation="raw_t_postselection",
                        evidence={"test_fixture": True},
                        kind="test_fixture",
                    ).to_dict()
            return group

    result = run_surface_factory(
        RejectSecondFactory(joint_fixture(2)), seed=0, input_z_error=0
    )
    calls = result["case"]["execution"]["calls"]
    first_cnot = min(
        c["start_us"]
        for c in calls
        if c["component_id"] == "transversal_cnot"
        and c["participant_blocks"][0].startswith("factory0/")
    )
    last_retry = max(
        c["action_end_us"]
        for c in calls
        if c["component_id"] == "raw_t_postselection"
        and c["participant_blocks"][0].startswith("factory1/")
    )
    assert first_cnot >= last_retry
    assert result["summary"]["outputs"] == 1
    assert result["case"]["coordination_policy"] == "cohort_stage_barriers"


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_joint_sources_keep_injection_and_growth_result_boundaries(distance):
    injection = factory_component_source("raw_t_postselection", distance)
    growth = factory_component_source("raw_t_postselection/canonicalize", distance)
    assert len(injection.wire_indices) == 17 and injection.result_count == 24
    assert growth.result_count == (0 if distance == 3 else distance * (distance**2 - 1))


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_joint_factory_accepts_exact_placement_plan_without_changing_budget(
    distance, monkeypatch
):
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


@pytest.mark.parametrize("change", ("position", "role", "fingerprint"))
def test_joint_factory_rejects_changed_plan_before_calibration_lookup(change):
    from dataclasses import replace

    from nadit_physical_compiler.device import Position

    from experiments.msd.standard import ExperimentSpec, build_world
    from modules.logical_compiler.src.placement import (
        BlockPlacement,
        ExplicitPlacement,
        PlacementRequest,
        place,
    )

    plan = build_world(ExperimentSpec(3, 1)).placement_plan
    document = fixture_profile(3, 1).to_dict()
    for patch in document["patches"]:
        origin = plan.placements[patch["block_id"]].origin
        patch["origin"] = [origin.x, origin.y]
    document["joint_calibration"] = {"family": "synthetic-plan-world", "limits": {}}
    profile = JointSurfaceFactoryProfile(document)
    if change == "fingerprint":
        changed = replace(plan, geometry_fingerprint="forged")
    else:
        blocks, positions = plan.blocks, dict(plan.placements)
        if change == "position":
            positions = {
                name: BlockPlacement(Position(p.origin.x + 10, p.origin.y))
                for name, p in positions.items()
            }
        else:
            blocks = (replace(blocks[0], role="changed"), *blocks[1:])
        changed = place(
            PlacementRequest(blocks, plan.geometries, positions=positions),
            ExplicitPlacement(),
        )
    # Empty group coverage would raise MissingJointCalibration if lookup ran.
    with pytest.raises(ValueError):
        run_surface_factory(profile, seed=0, input_z_error=0, placement_plan=changed)


def test_joint_profile_does_not_silently_adopt_single_component_scoped_cache():
    from modules.logical_compiler.src.estimation.calibration import CalibrationCache
    from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel

    profile = JointSurfaceFactoryProfile(joint_fixture())
    with pytest.raises(ValueError, match="CONTEXTUAL_CALIBRATION_PROVIDER_REQUIRED"):
        ProfileExecutionKernel(
            profile, profile.layout(), calibration_cache=CalibrationCache()
        )


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_static_joint_contracts_need_no_singleton_cost_or_probability(
    distance, monkeypatch
):
    from nadit_physical_compiler import compiler

    from experiments.msd.standard import ExperimentSpec, build_world

    plan = build_world(ExperimentSpec(distance, 2)).placement_plan
    monkeypatch.setattr(
        compiler, "compile_physical", lambda *a, **k: pytest.fail("physical fallback")
    )
    profile = JointSurfaceFactoryProfile.from_placement(
        plan,
        family="static-fixture",
        noise_params={},
    )
    document = profile.to_dict()
    assert document["schema"] == "nadit.joint_surface_factory_profile/1"
    assert "entries" not in document and "raw_ports" not in document
    layout = profile.layout()
    assert layout.placement_plan.to_dict() == plan.to_dict()
    contract = profile.lookup(
        "raw_t_postselection",
        (layout.bindings["factory0/R"],),
        parameters=(("injection_rounds", 3),),
    )
    assert contract.result_count == 24
    assert not hasattr(contract, "phase_durations_us")
    assert not hasattr(contract, "cost_segments")
    with pytest.raises(ValueError, match="JOINT_PREPARATION_REQUIRES_SOURCE_RECEIPT"):
        profile.preparation_port("raw_t_postselection", "factory0/R")
    restored = JointSurfaceFactoryProfile(document)
    with pytest.raises(MissingJointCalibration) as missing:
        run_surface_factory(restored, seed=0, input_z_error=0, placement_plan=plan)
    request = missing.value.to_dict()
    assert request["family"] == "static-fixture"
    assert len(request["members"]) == 10
    assert request["placement_fingerprint"] == plan.geometry_fingerprint
    assert request["member_key"] == joint_key(tuple(request["members"]))


def test_static_joint_contract_source_identity_rejects_tampering():
    from experiments.msd.standard import ExperimentSpec, build_world

    plan = build_world(ExperimentSpec(3, 1)).placement_plan
    profile = JointSurfaceFactoryProfile.from_placement(
        plan,
        family="static-fixture",
        noise_params={},
        additional_calls=(("logical_mz", ("factory0/W1",)),),
    )
    document = profile.to_dict()
    assert "logical_mz:factory0/W1" in document["source_contracts"]
    document["source_contracts"]["logical_mz:factory0/W1"]["result_count"] += 1
    with pytest.raises(ValueError, match="JOINT_STATIC_CONTRACT_CHANGED"):
        JointSurfaceFactoryProfile(document)


def test_static_joint_profile_replays_only_complete_calibrated_group_records(
    monkeypatch,
):
    from nadit_physical_compiler import compiler

    from experiments.msd.standard import ExperimentSpec, build_world

    class StaticFixture(JointSurfaceFactoryProfile):
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
                        member: {
                            "measurement_phases": [(0, 0)]
                            * self.contracts[member].result_count,
                            "cost_segments": [],
                            "primitive_counts": {},
                        }
                        for member in members
                    },
                    "raw_ports": {
                        member: acceptance_port(
                            1,
                            preparation="raw_t_postselection",
                            evidence={"test_fixture": True},
                            kind="test_fixture",
                        ).to_dict()
                        for member in members
                        if member.startswith("raw_t_postselection:")
                    },
                }
            return super().group(members)

    plan = build_world(ExperimentSpec(3, 2)).placement_plan
    monkeypatch.setattr(
        compiler, "compile_physical", lambda *a, **k: pytest.fail("physical fallback")
    )
    profile = StaticFixture.from_placement(
        plan, family="static-fixture", noise_params={}
    )
    first = run_surface_factory(profile, seed=0, input_z_error=0, placement_plan=plan)
    restored = JointSurfaceFactoryProfile(profile.to_dict())
    second = run_surface_factory(restored, seed=0, input_z_error=0, placement_plan=plan)
    assert first["summary"]["makespan_us"] == second["summary"]["makespan_us"]
    assert second["summary"]["outputs"] == 2
    final = [
        call
        for call in second["case"]["execution"]["calls"]
        if "/final/mx/" in call["invocation_id"]
    ]
    assert len(final) == 8
    assert len({call["joint_group_key"] for call in final}) == 1


def mixed_plan(distances=(3, 5)):
    """Explicit code-owned footprints; no physical compilation or world creation."""
    from nadit_physical_compiler.device import Position

    from modules.codes.rotated_surface.fast_factory import ROLES
    from modules.codes.rotated_surface.geometry import geometry
    from modules.logical_compiler.src.placement import (
        BlockPlacement,
        BlockSpec,
        ExplicitPlacement,
        PlacementRequest,
        place,
    )

    blocks = tuple(
        BlockSpec(f"factory{i}/{role}", f"rotated_surface_d{d}", d, f"factory{i}", role)
        for i, d in enumerate(distances)
        for role in ROLES
    )
    return place(
        PlacementRequest(
            blocks,
            {b.code: geometry(b.code, b.distance) for b in blocks},
            positions={
                b.block_id: BlockPlacement(Position(200 * j, -200 * (i + 1)))
                for i in range(len(distances))
                for j, b in enumerate(blocks[6 * i : 6 * (i + 1)])
            },
        ),
        ExplicitPlacement(),
    )


@pytest.mark.parametrize("distance", (5, 7))
def test_mixed_static_members_keep_own_code_source_budget_and_exact_group_gate(
    distance, monkeypatch
):
    from nadit_physical_compiler import compiler

    from modules.codes.rotated_surface.definition import definition
    from modules.logical_compiler.src.scheduling.compatibility import compatible_specs

    monkeypatch.setattr(
        compiler, "compile_physical", lambda *a, **k: pytest.fail("physical fallback")
    )
    plan = mixed_plan((3, distance))
    profile = JointSurfaceFactoryProfile.from_placement(
        plan,
        family="mixed-static-fixture",
        noise_params={},
        additional_calls=tuple(
            ("transversal_cnot", (f"factory{i}/W1", f"factory{i}/W2")) for i in range(2)
        ),
    )
    layout = profile.layout()
    assert layout.budget["atom_count_estimate"] == 6 * (
        definition(3).atom_count + definition(distance).atom_count
    )
    assert layout.budget["aod_count"] == 1
    assert profile.factory_distances == {"factory0": 3, "factory1": distance}
    assert profile.factory_identity("factory1") == (
        f"rotated_surface_d{distance}",
        distance,
    )
    specs = []
    for i, d in enumerate((3, distance)):
        for component, roles, wires, results in (
            ("raw_t_postselection", ("R",), 17, 24),
            ("logical_mx", ("W3",), definition(d).atom_count, d * d),
            ("transversal_cnot", ("W1", "W2"), 2 * definition(d).atom_count, 0),
        ):
            patches = tuple(layout.bindings[f"factory{i}/{role}"] for role in roles)
            parameters = (
                {"injection_rounds": 3} if component == "raw_t_postselection" else {}
            )
            contract = profile.lookup(component, patches, parameters=parameters)
            assert (contract.code_id, contract.distance) == (f"rotated_surface_d{d}", d)
            assert len(contract.wire_indices) == wires
            assert contract.result_count == results
            specs.append(
                profile.describe(
                    component, patches, parameters=parameters, budget=layout.budget
                )
            )
    assert compatible_specs(tuple(specs))
    assert {spec.code_id for spec in specs} == {
        "rotated_surface_d3",
        f"rotated_surface_d{distance}",
    }
    assert all(spec.shared_aod.joint_code_ids == profile.code_ids for spec in specs)
    with pytest.raises(MissingJointCalibration):
        profile.group(tuple(spec.shared_aod.joint_member for spec in specs))
    document = profile.to_dict()
    assert all(
        "code_id" in c and "distance" in c
        for c in document["source_contracts"].values()
    )
    assert JointSurfaceFactoryProfile(document).to_dict() == document
    document["source_contracts"]["logical_mx:factory1/W3"]["distance"] = 3
    with pytest.raises(ValueError, match="JOINT_STATIC_CONTRACT_CHANGED"):
        JointSurfaceFactoryProfile(document)


def test_mixed_single_cnot_and_inconsistent_factory_roles_are_rejected():
    from dataclasses import replace

    from modules.codes.rotated_surface.joint_factory_contracts import static_contracts
    from modules.logical_compiler.src.placement import (
        ExplicitPlacement,
        PlacementRequest,
        place,
    )

    plan = mixed_plan()
    with pytest.raises(ValueError, match="JOINT_STATIC_PARTICIPANT_CODE_MISMATCH"):
        static_contracts(plan, (("transversal_cnot", ("factory0/W1", "factory1/W1")),))
    profile = JointSurfaceFactoryProfile.from_placement(
        plan, family="mixed-fixture", noise_params={}
    )
    bindings = profile.layout().bindings
    with pytest.raises(
        ValueError, match="UNCALIBRATED_GENERIC_PARTICIPANT_CODE_MISMATCH"
    ):
        profile.lookup(
            "transversal_cnot", (bindings["factory0/W1"], bindings["factory1/W1"])
        )
    with pytest.raises(ValueError, match="INCOMPLETE_PROFILE_FACTORY_ROLES"):
        profile.factory_identity("factory2")
    blocks = (
        replace(plan.blocks[0], code="rotated_surface_d5", distance=5),
        *plan.blocks[1:],
    )
    inconsistent = place(
        PlacementRequest(blocks, plan.geometries, positions=plan.placements),
        ExplicitPlacement(),
    )
    with pytest.raises(ValueError, match="JOINT_STATIC_FACTORY_ROLES_MISMATCH"):
        static_contracts(inconsistent)


def test_uniform_static_document_and_claim_omit_mixed_identity_extension():
    profile = JointSurfaceFactoryProfile.from_placement(
        mixed_plan((3, 3)), family="uniform-fixture", noise_params={}
    )
    layout = profile.layout()
    assert profile.factory_identity("factory1") == ("rotated_surface_d3", 3)
    assert profile.factory_distances == {"factory0": 3, "factory1": 3}
    assert all(
        "code_id" not in c and "distance" not in c
        for c in profile.to_dict()["source_contracts"].values()
    )
    spec = profile.describe(
        "logical_mx", (layout.bindings["factory0/W3"],), budget=layout.budget
    )
    assert "joint_code_ids" not in spec.shared_aod.to_dict()


def test_mixed_static_geometry_requires_every_exact_code_owned_footprint():
    from dataclasses import replace

    from modules.codes.rotated_surface.joint_factory_contracts import static_contracts
    from modules.logical_compiler.src.placement import (
        ExplicitPlacement,
        PlacementRequest,
        place,
    )

    plan = mixed_plan()
    geometries = dict(plan.geometries)
    code = "rotated_surface_d5"
    geometries[code] = replace(geometries[code], version="caller-forged-geometry")
    changed = place(
        PlacementRequest(plan.blocks, geometries, positions=plan.placements),
        ExplicitPlacement(),
    )
    with pytest.raises(ValueError, match="JOINT_STATIC_CODE_GEOMETRY_MISMATCH"):
        static_contracts(changed)
    profile = JointSurfaceFactoryProfile.from_placement(
        plan, family="mixed-fixture", noise_params={}
    )
    with pytest.raises(ValueError, match="UNCALIBRATED_GENERIC_PLACEMENT"):
        profile.layout(placement_plan=changed)


def test_mixed_members_use_one_existing_scheduler_wave_and_exact_receipt_counts():
    """Synthetic shared timing tests admission/accounting, not physical feasibility."""
    from modules.codes.contracts.factory_recipe import ComponentCall
    from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
    from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
    from modules.logical_compiler.src.scheduling import (
        ComponentNode,
        ComponentScheduler,
    )

    profile = JointSurfaceFactoryProfile.from_placement(
        mixed_plan(),
        family="synthetic-mixed-wave",
        noise_params={},
        additional_calls=(("transversal_cnot", ("factory1/W1", "factory1/W2")),),
    )
    execution = ProfileExecutionKernel(profile, profile.layout())
    requests = (
        ExecutionRequest(
            "read3",
            None,
            ComponentCall("read3", "logical_mx", ("W3",)),
            ("factory0/W3",),
        ),
        ExecutionRequest(
            "read5",
            None,
            ComponentCall("read5", "logical_mx", ("W3",)),
            ("factory1/W3",),
        ),
        ExecutionRequest(
            "cnot5",
            None,
            ComponentCall("cnot5", "transversal_cnot", ("W1", "W2")),
            ("factory1/W1", "factory1/W2"),
        ),
    )
    scheduler = ComponentScheduler()
    scheduler.add(
        *(
            ComponentNode(
                r.invocation_id, execution.describe(None, r.call, r.participant_blocks)
            )
            for r in requests
        )
    )
    admission = scheduler.admit(0, snapshot_id=execution.snapshot_id)
    assert len(admission.nodes) == 3
    requests_by_id = {r.invocation_id: r for r in requests}
    requests = tuple(requests_by_id[name] for name in admission.node_ids)
    with pytest.raises(MissingJointCalibration):
        execution.execute(admission, requests)
    assert execution.clock_us == 0 and not execution.used
    members = tuple(
        f"{r.call.component_id}:{','.join(r.participant_blocks)}" for r in requests
    )
    profile.groups[joint_key(members)] = {
        "family": profile.joint_family,
        "validation_ok": True,
        "trace_sha256": "0" * 64,
        "phase_durations_us": [7.0],
        "peak_rows": 4,
        "peak_columns": 4,
        "peak_readout_atoms": 34,
        "members": {
            member: {
                "measurement_phases": [(0, 0)] * profile.contracts[member].result_count,
                "cost_segments": [],
                "primitive_counts": {},
            }
            for member in members
        },
    }
    receipts = execution.execute(admission, requests)
    assert execution.clock_us == 7
    assert len(execution.snapshot()["waves"]) == 1
    assert {
        name: len(value[0].result_availability) for name, value in receipts.items()
    } == {"read3": 9, "read5": 25, "cnot5": 0}
    assert (
        len(
            {
                index
                for rows in receipts.values()
                for index, _ in rows[0].result_availability
            }
        )
        == 34
    )
