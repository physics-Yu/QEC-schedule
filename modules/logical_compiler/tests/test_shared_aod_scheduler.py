"""Admission counts shared grid capacity before binding or atom expansion."""

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


def declaration(index, *, aod="transport", columns=None, readout=None):
    return ComponentExecutionSpec(
        code_id="test-code",
        component_id="se",
        waveform_key="same-implementation",
        participant_blocks=(f"P{index}",),
        spaces=(SpaceClaim(Region(index * 100, 0, index * 100 + 70, 115), "patch"),),
        exclusive_resources=(),
        parallel_mode="shared_aod_lockstep",
        result_count=8,
        shared_aod=SharedAODClaim(
            aod_id=aod,
            row_trajectory_key="rows-y0",
            column_min=index * 100,
            column_max=index * 100 + 62,
            peak_rows=4,
            peak_columns=4,
            max_rows=4,
            max_columns=columns,
            readout_channel="camera",
            peak_readout_atoms=8,
            max_readout_atoms=readout,
            min_spacing=1,
        ),
    )


def admit(specs):
    scheduler = ComponentScheduler()
    scheduler.add(*(ComponentNode(f"p{i}", spec) for i, spec in enumerate(specs)))
    return scheduler.admit(0, snapshot_id="unchanged-world")


def test_four_same_components_share_one_aod_at_declaration_level():
    specs = tuple(declaration(i, columns=16, readout=32) for i in range(4))
    assert compatible_specs(specs)
    assert admit(specs).node_ids == ("p0", "p1", "p2", "p3")


@pytest.mark.parametrize(
    "columns,readout,expected", [(8, 32, 2), (16, 16, 2), (12, 32, 3)]
)
def test_group_capacity_is_aggregate_not_pairwise(columns, readout, expected):
    specs = tuple(declaration(i, columns=columns, readout=readout) for i in range(4))
    assert not compatible_specs(specs)
    assert len(admit(specs).nodes) == expected


def test_readout_capacity_applies_across_different_aods():
    specs = tuple(
        declaration(i, aod=f"aod{i}", columns=4, readout=16) for i in range(4)
    )
    assert len(admit(specs).nodes) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"row_trajectory_key": "other-row-path"},
        {"column_min": 50, "column_max": 112},
        {"column_min": 62.5, "column_max": 124.5},
        {"max_columns": 20},
        {"max_readout_atoms": 16},
    ],
)
def test_incompatible_shared_control_claims_do_not_batch(changes):
    first, second = (declaration(i, columns=16, readout=32) for i in range(2))
    second = replace(second, shared_aod=replace(second.shared_aod, **changes))
    assert not compatible_specs((first, second))
    assert len(admit((first, second)).nodes) == 1


def test_exact_component_and_participant_shape_rule_still_applies():
    first, second = (declaration(i) for i in range(2))
    for other in (
        replace(second, component_id="other-component"),
        replace(second, waveform_key="different-implementation"),
        replace(second, participant_blocks=("P1", "P2")),
        replace(second, participant_blocks=first.participant_blocks),
        replace(second, spaces=first.spaces),
    ):
        assert not compatible_specs((first, other))


def test_exclusive_claim_cannot_hide_a_conflict_with_shared_transport():
    first = declaration(0)
    second = replace(
        declaration(1, aod="other"), exclusive_resources=("aod:transport",)
    )
    assert not compatible_specs((first, second))


def test_retry_on_a_subset_does_not_need_successful_patch_columns():
    scheduler = ComponentScheduler()
    scheduler.add(*(ComponentNode(f"p{i}", declaration(i)) for i in range(4)))
    wave = scheduler.admit(0, snapshot_id="entry")
    scheduler.commit_admission(wave)
    for node in wave.nodes:
        scheduler.mark_completed(node.id, 10)
    scheduler.add(
        ComponentNode("retry0", declaration(0)), ComponentNode("retry1", declaration(1))
    )
    retry = scheduler.admit(10, snapshot_id="after-first-wave")
    assert retry.node_ids == ("retry0", "retry1")
    assert {node.spec.shared_aod.column_min for node in retry.nodes} == {0, 100}
