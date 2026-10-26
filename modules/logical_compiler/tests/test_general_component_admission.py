"""Multi-patch control and local correction groups are declared before lowering."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.device import Region

from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler
from modules.logical_compiler.src.scheduling.compatibility import compatible_specs
from modules.logical_compiler.tests.test_shared_aod_scheduler import declaration


def joint(index):
    spec = declaration(index)
    return replace(
        spec,
        component_id="transversal_cnot",
        waveform_key="translated-cnot/dx100",
        participant_blocks=(f"C{index}", f"T{index}"),
        result_count=0,
        shared_aod=replace(spec.shared_aod, peak_readout_atoms=0),
    )


def local(index, component="raw_t_postselection/canonicalize"):
    return ComponentExecutionSpec(
        "code",
        component,
        "addressed-paulis/timing-v1",
        (f"P{index}",),
        (SpaceClaim(Region(index * 100, 0, index * 100 + 60, 60), "local"),),
        (),
        "local_parallel",
        0,
    )


def select(*specs):
    scheduler = ComponentScheduler()
    scheduler.add(*(ComponentNode(str(i), spec) for i, spec in enumerate(specs)))
    return scheduler, scheduler.admit(0, snapshot_id="world")


def test_disjoint_declared_cnot_pairs_join_one_global_frontier():
    first, second = joint(0), joint(1)
    assert compatible_specs((first, second))
    scheduler, wave = select(first, second)
    assert wave.node_ids == ("0", "1")
    assert wave.nodes[0].spec.participant_blocks == ("C0", "T0")
    scheduler.commit_admission(wave)
    for node in wave.nodes:
        scheduler.mark_completed(node.id, 10)
    followup = scheduler.add(ComponentNode("target-next", local(2)))[0]
    assert followup.after_calls == ()
    target = replace(local(3), participant_blocks=("T1",))
    assert scheduler.add(ComponentNode("T1-next", target))[0].after_calls == ("1",)


@pytest.mark.parametrize("change", ["direction", "arity", "rows", "space"])
def test_joint_claim_incompatibility_prevents_grouping(change):
    first, second = joint(0), joint(1)
    if change == "direction":
        second = replace(second, waveform_key="translated-cnot/dx-minus100")
    elif change == "arity":
        second = replace(second, participant_blocks=("C1",))
    elif change == "rows":
        second = replace(
            second, shared_aod=replace(second.shared_aod, row_trajectory_key="other")
        )
    else:
        second = replace(second, spaces=first.spaces)
    assert not compatible_specs((first, second))
    assert select(first, second)[1].node_ids == ("0",)


def test_shared_target_creates_a_dependency_and_cannot_be_double_admitted():
    first, second = joint(0), replace(joint(1), participant_blocks=("C1", "T0"))
    scheduler, wave = select(first, second)
    assert wave.node_ids == ("0",)
    assert scheduler.snapshot()["nodes"][1]["after_calls"] == ["0"]


def test_local_correction_families_batch_without_transport_or_equal_class():
    specs = (
        local(0),
        local(1, "initialize_plus/canonicalize"),
        local(2, "logical_x"),
        local(3, "logical_z"),
    )
    assert compatible_specs(specs)
    assert select(*specs)[1].node_ids == ("0", "1", "2", "3")


@pytest.mark.parametrize(
    "changes",
    [
        {"result_count": 1},
        {"participant_blocks": ("P", "Q")},
        {"exclusive_resources": ("aod:transport",)},
    ],
)
def test_local_mode_cannot_hide_measurement_or_transport_claims(changes):
    with pytest.raises(ValueError, match="Local"):
        replace(local(0), **changes)


def test_local_mode_keeps_waveform_code_space_and_feedback_checks():
    first = local(0)
    for second in (
        replace(local(1), waveform_key="other-timing"),
        replace(local(1), code_id="other-code"),
        replace(local(1), spaces=first.spaces),
    ):
        assert not compatible_specs((first, second))
    scheduler = ComponentScheduler()
    scheduler.add(
        ComponentNode("correction0", first, event_dependencies=("decision0",)),
        ComponentNode("correction1", local(1), event_dependencies=("decision1",)),
    )
    scheduler.release_event("decision0", 10)
    scheduler.release_event("decision1", 12)
    assert scheduler.admit(10, snapshot_id="world").node_ids == ("correction0",)
    assert scheduler.admit(12, snapshot_id="world").node_ids == (
        "correction0",
        "correction1",
    )


def test_zero_readout_demand_does_not_relax_transport_capacity():
    first, second = joint(0), joint(1)
    specs = tuple(
        replace(spec, shared_aod=replace(spec.shared_aod, max_columns=4))
        for spec in (first, second)
    )
    assert not compatible_specs(specs)
    assert select(*specs)[1].node_ids == ("0",)
