"""Independent edge-case checks for shared-control declaration admission."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.device import Region

from modules.codes.contracts.parallel import (
    ComponentExecutionSpec,
    SharedAODClaim,
    SpaceClaim,
)
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler
from modules.logical_compiler.src.scheduling.compatibility import compatible_specs


def spec(index, *, aod="transport", columns=16, readout=32):
    return ComponentExecutionSpec(
        code_id="review-code",
        component_id="same-component",
        waveform_key="same-local-waveform",
        participant_blocks=(f"P{index}",),
        spaces=(SpaceClaim(Region(index * 100, 0, index * 100 + 70, 115), "patch"),),
        exclusive_resources=(),
        parallel_mode="shared_aod_lockstep",
        result_count=16,
        shared_aod=SharedAODClaim(
            aod,
            "same-absolute-row-path",
            index * 100,
            index * 100 + 62,
            4,
            4,
            4,
            columns,
            "camera",
            8,
            readout,
            1,
        ),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_unbounded_and_finite_shared_capacity_do_not_silently_mix(reverse):
    first, second = spec(0, columns=None), spec(1, columns=16)
    declarations = (second, first) if reverse else (first, second)
    assert not compatible_specs(declarations)


def test_readout_capacity_consistency_applies_even_between_distinct_aods():
    declarations = (spec(0, aod="left", readout=None), spec(1, aod="right", readout=16))
    assert not compatible_specs(declarations)


def test_joint_shared_node_is_valid_but_cannot_mix_participant_arities():
    declaration = replace(spec(0), participant_blocks=("P0", "P1"))
    assert compatible_specs((declaration,))
    assert not compatible_specs((declaration, spec(2)))
    scheduler = ComponentScheduler()
    scheduler.add(
        ComponentNode("joint-shared-node", declaration),
        ComponentNode("single-shared-node", spec(2)),
    )
    assert scheduler.admit(0, snapshot_id="unchanged-world").node_ids == (
        "joint-shared-node",
    )


def test_nonadjacent_failed_patches_can_retry_without_successful_middle_patches():
    scheduler = ComponentScheduler()
    scheduler.add(*(ComponentNode(f"first-{index}", spec(index)) for index in range(4)))
    first = scheduler.admit(0, snapshot_id="first-world")
    scheduler.commit_admission(first)
    for item in first.nodes:
        scheduler.mark_completed(item.id, 10)
    scheduler.release_event("reject-left", 12)
    scheduler.release_event("reject-right", 12)
    scheduler.add(
        ComponentNode("retry-left", spec(0), event_dependencies=("reject-left",)),
        ComponentNode("retry-right", spec(3), event_dependencies=("reject-right",)),
    )
    retry = scheduler.admit(12, snapshot_id="after-first-wave")
    assert retry.node_ids == ("retry-left", "retry-right")
    assert tuple(item.after_calls for item in retry.nodes) == (
        ("first-0",),
        ("first-3",),
    )
    assert tuple(item.spec.shared_aod.column_min for item in retry.nodes) == (0, 300)


def test_incompatible_middle_candidate_does_not_block_a_later_compatible_patch():
    declarations = [spec(index) for index in range(3)]
    declarations[1] = replace(
        declarations[1],
        shared_aod=replace(
            declarations[1].shared_aod, row_trajectory_key="different-path"
        ),
    )
    scheduler = ComponentScheduler()
    scheduler.add(
        *(ComponentNode(f"p{index}", item) for index, item in enumerate(declarations))
    )
    assert scheduler.admit(0, snapshot_id="unchanged-world").node_ids == ("p0", "p2")


def test_readout_peak_is_counted_across_two_shared_aod_groups():
    scheduler = ComponentScheduler()
    scheduler.add(
        *(
            ComponentNode(
                f"p{index}", spec(index, aod=f"aod-{index % 2}", columns=8, readout=24)
            )
            for index in range(4)
        )
    )
    # Each AOD could carry two patches, but the camera can read only three.
    assert scheduler.admit(0, snapshot_id="unchanged-world").node_ids == (
        "p0",
        "p1",
        "p2",
    )
