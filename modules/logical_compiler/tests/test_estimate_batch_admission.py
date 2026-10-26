"""Estimated synchronized batches retain explicit model-only evidence."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.device import Region

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.execution_kernel import (
    ExecutionRequest,
    PhysicalExecutionKernel,
)
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler
from modules.logical_compiler.src.scheduling.compatibility import compatible_specs


def spec(block, key="model:se", *, component="se_round", participants=None):
    return ComponentExecutionSpec(
        "toy",
        component,
        "estimated-macro",
        participants or (block,),
        (),
        (),
        "profile_parallel",
        1,
        estimate_batch_key=key,
    )


@pytest.mark.parametrize("key", ("", " ", 1))
def test_estimate_key_requires_nonempty_text(key):
    with pytest.raises(ValueError, match="estimate|Estimate"):
        spec("a", key)


def test_estimate_key_is_only_an_estimation_declaration():
    with pytest.raises(ValueError, match="profile_parallel"):
        replace(spec("a"), parallel_mode="independent_aods_lockstep")
    assert "estimate_batch_key" not in spec("a", None).to_dict()
    assert spec("a").to_dict()["estimate_batch_key"] == "model:se"


def test_homogeneous_estimates_preserve_patch_space_and_resource_constraints():
    a, b = spec("a"), spec("b")
    assert compatible_specs((a, b))
    assert not compatible_specs((a, a))
    assert not compatible_specs((a, replace(b, estimate_batch_key=None)))
    assert not compatible_specs((a, replace(b, estimate_batch_key="model:mx")))
    assert not compatible_specs(
        tuple(replace(s, exclusive_resources=("camera",)) for s in (a, b))
    )
    region = SpaceClaim(Region(0, 0, 10, 10), "fixture")
    assert not compatible_specs(tuple(replace(s, spaces=(region,)) for s in (a, b)))
    # Legacy estimates keep independently declared resource/duration behavior.
    assert compatible_specs((spec("a", None), spec("b", None, component="other")))


def test_ordered_cnot_geometry_keys_select_distinct_frontiers():
    left = spec("a", "cx:100,0", component="cx", participants=("a", "b"))
    same = spec("c", "cx:100,0", component="cx", participants=("c", "d"))
    reverse = replace(same, estimate_batch_key="cx:-100,0")
    assert compatible_specs((left, same))
    assert not compatible_specs((left, reverse))


class BatchProfile:
    profile_sha256 = "a" * 64

    def __init__(self, damage=None):
        self.damage = damage
        self.batch_calls = 0

    def describe(self, component_id, participants, parameters=(), **kwargs):
        return spec(participants[0].block_id, component=component_id)

    def lookup(self, *args, **kwargs):
        pytest.fail("Keyed estimates must query the complete proposed batch")

    def lookup_batch(self, requests):
        self.batch_calls += 1
        if self.damage == "missing":
            raise ValueError("MISSING_ESTIMATE_BATCH")
        result = tuple(
            SimpleNamespace(
                key=request.call.component_id,
                phase_durations_us=(2.0, 3.0),
                measurement_phases=((0, 4.0),),
                cost_segments=(
                    {
                        "start_offset_us": 0.0,
                        "end_offset_us": 2.0,
                        "category": "measurement",
                        "resource": "camera",
                    },
                ),
                primitive_counts={"Measure": 1},
                claim={
                    "estimate_model_sha256": "b" * 64,
                    "estimate_segments": [
                        {
                            "start_offset_us": 0.0,
                            "end_offset_us": 2.0,
                            "category": "measurement",
                            "resource": "camera",
                            "atom_count": 2,
                            "busy_atom_us": 3.0,
                            "movement_distance_atom_um": 0.0,
                            "primitive_counts": {"Measure": 2},
                            "basis": "explicit fixture estimate",
                        }
                    ],
                },
            )
            for request in requests
        )
        if self.damage == "count":
            return result[:-1]
        if self.damage == "phases":
            result[-1].phase_durations_us = (2.0, 4.0)
        if self.damage == "results":
            result[-1].measurement_phases = ()
        if self.damage == "model":
            result[-1].claim["estimate_model_sha256"] = "not-a-hash"
        if self.damage == "segment_time":
            result[-1].claim["estimate_segments"][0]["end_offset_us"] = 7
        if self.damage == "segment_atoms":
            result[-1].claim["estimate_segments"][0]["atom_count"] = -1
        if self.damage == "segment_movement":
            result[-1].claim["estimate_segments"][0]["movement_distance_atom_um"] = (
                float("nan")
            )
        if self.damage in (
            "busy_negative",
            "busy_excess",
            "busy_type",
            "busy_infinite",
        ):
            result[-1].claim["estimate_segments"][0]["busy_atom_us"] = {
                "busy_negative": -1,
                "busy_excess": 5,
                "busy_type": True,
                "busy_infinite": float("inf"),
            }[self.damage]
        self.entries = result
        return result


class LocalProfile(BatchProfile):
    def describe(self, component_id, participants, parameters=(), **kwargs):
        return replace(
            spec(participants[0].block_id, None, component=component_id),
            parallel_mode="local_parallel",
            result_count=0,
        )

    def lookup_batch(self, requests):
        pytest.fail("Local model overlays do not require synchronized group lookup")

    def lookup(self, component_id, participants, selection=None, parameters=()):
        return SimpleNamespace(
            key=component_id,
            phase_durations_us=(3.0,),
            measurement_phases=(),
            cost_segments=(),
            primitive_counts={"S": 9},
            claim={
                "estimate_model_sha256": "c" * 64,
                "estimate_segments": [
                    {
                        "start_offset_us": 0.0,
                        "end_offset_us": 3.0,
                        "category": "gate",
                        "resource": "local_control",
                        "atom_count": 9,
                        "movement_distance_atom_um": 0,
                        "primitive_counts": {"S": 9},
                        "basis": "assumed local overlay",
                    }
                ],
            },
        )


def proposed(profile):
    execution = ProfileExecutionKernel(
        profile,
        SimpleNamespace(
            bindings={name: SimpleNamespace(block_id=name) for name in ("a", "b")},
            budget={},
        ),
    )
    scheduler = ComponentScheduler()
    call = ComponentCall("read", "se_round", ("work",))
    scheduler.add(
        *(
            ComponentNode(name, execution.describe(None, call, (name,)))
            for name in ("a", "b")
        )
    )
    admission = scheduler.admit(0, snapshot_id=execution.snapshot_id)
    requests = tuple(ExecutionRequest(name, None, call, (name,)) for name in ("a", "b"))
    return execution, admission, requests


def test_keyed_batch_retains_model_provenance_without_native_trace_claims():
    profile = BatchProfile()
    execution, admission, requests = proposed(profile)
    receipts = execution.execute(admission, requests)
    assert profile.batch_calls == 1
    assert execution.clock_us == 5
    assert [receipts[name][0].results_ready_us for name in ("a", "b")] == [6, 6]
    assert [receipts[name][0].result_availability[0][0] for name in ("a", "b")] == [
        0,
        1,
    ]
    for receipt in (receipts[name][0] for name in ("a", "b")):
        assert receipt.provenance["estimate_batch_key"] == "model:se"
        assert receipt.provenance["estimate_model_sha256"] == "b" * 64
        assert not any(key.startswith("joint_") for key in receipt.provenance)
    for call in execution.calls:
        assert call["estimate_batch_key"] == "model:se"
        assert call["estimate_model_sha256"] == "b" * 64
        assert not any(key.startswith("joint_") for key in call)
        assert call["estimate_segments"][0]["atom_count"] == 2
        assert call["estimate_segments"][0]["busy_atom_us"] == 3
        assert "estimate_segments" not in call["provenance"]
    profile.entries[0].claim["estimate_segments"][0]["atom_count"] = 100
    assert execution.calls[0]["estimate_segments"][0]["atom_count"] == 2
    assert execution.finalize() is None


def test_local_overlay_retains_explicit_estimate_segments_without_batch_claim():
    execution, admission, requests = proposed(LocalProfile())
    receipts = execution.execute(admission, requests)
    assert execution.clock_us == 3
    for call in execution.calls:
        assert call["estimate_model_sha256"] == "c" * 64
        assert call["estimate_segments"][0]["atom_count"] == 9
        assert "estimate_batch_key" not in call
        assert "estimate_batch_key" not in call["provenance"]
    assert all(
        receipt[0].provenance["estimate_model_sha256"] == "c" * 64
        for receipt in receipts.values()
    )


@pytest.mark.parametrize(
    "damage",
    (
        "missing",
        "count",
        "phases",
        "results",
        "model",
        "segment_time",
        "segment_atoms",
        "segment_movement",
        "busy_negative",
        "busy_excess",
        "busy_type",
        "busy_infinite",
    ),
)
def test_invalid_estimate_batch_leaves_kernel_state_unchanged(damage):
    execution, admission, requests = proposed(BatchProfile(damage))
    before = execution.snapshot()
    with pytest.raises(ValueError):
        execution.execute(admission, requests)
    assert execution.snapshot() == before
    assert execution.clock_us == 0
    assert not execution.used


def test_physical_kernel_rejects_keyed_estimates_before_native_binding():
    _, admission, requests = proposed(BatchProfile())
    execution = PhysicalExecutionKernel(SimpleNamespace())
    with pytest.raises(ValueError, match="PROFILE_ONLY_ADMISSION_CANNOT_EXECUTE_ATOMS"):
        execution.execute(admission, requests)
    assert execution._parts == {}
