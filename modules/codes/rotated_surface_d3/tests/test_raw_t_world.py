"""Raw preparation noise on the actual occupied world and bounded time segment."""

import json
from pathlib import Path

import pytest
from nadit_physical_compiler.atom_ir import Measure
from nadit_physical_compiler.cost import prepare
from nadit_physical_compiler.serialization import decode_program

from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface_d3.probabilities.raw_t import (
    _joint_document,
    raw_t_pauli_port,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorldConfig,
    make_factory_world,
)
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)


@pytest.fixture(scope="module")
def raw_world():
    factory = make_factory_world(FactoryWorldConfig(atom_id_base=300))
    patch = factory.patch("W3")
    template = RawTPostselection(
        extra_rounds=1, round_policy="explicit_control"
    ).compile(
        factory.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    source = template.bind(patch.binding).expand(
        InvocationContext("world/raw", 2500, 800, factory.device, factory.world_state)
    )
    return factory, template, source


def _noise_params():
    path = (
        Path(__file__).parents[3]
        / "physical_compiler/cost_params/noise_illustrative.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_noise_report_retains_all_102_atoms_and_actual_segment(raw_world):
    factory, _, source = raw_world
    port = raw_t_pauli_port(source, factory.device, noise_params=_noise_params())
    evidence = port.to_dict()["model"]["evidence"]
    assert 0 < port.outcome("accepted").probability < 1
    assert evidence["world_atom_ids"] == list(range(300, 402))
    assert evidence["participant_atom_ids"] == list(
        factory.patch("W3").binding.atom_ids
    )
    assert len(evidence["physical_loss"]["per_atom"]) == 102
    assert evidence["segment_start_us"] == 2500
    assert evidence["segment_action_end_us"] == source.action_end_us
    assert evidence["segment_results_ready_us"] == source.results_ready_us
    assert evidence["activity_duration_us"] == pytest.approx(
        source.results_ready_us - 2500
    )
    assert evidence["quality_horizon"] == {
        "kind": "results_ready",
        "absolute_time_us": source.results_ready_us,
        "quality_estimated": False,
    }
    assert evidence["prefix_exposure_included"] is False
    assert evidence["post_horizon_storage_included"] is False
    assert evidence["detector_count"] == evidence["center_t_identity_checks"] == 12
    assert evidence["physical_loss"]["all_atoms_survive_probability"] < 1
    assert evidence["scope"] == "pauli_readout_only"


def test_private_cost_timeline_rebases_large_absolute_starts_exactly(raw_world):
    start = 105000.0
    factory, template, _ = raw_world
    source = template.bind(factory.patch("W3").binding).expand(
        InvocationContext("late/raw", start, 4000, factory.device, factory.world_state)
    )
    original_measurements = source.measurements
    original_operations = tuple(part.operations for part in source.parts)
    port = raw_t_pauli_port(source, factory.device, noise_params={})
    assert port.outcome("accepted").probability == 1
    document = _joint_document(source, factory.device)
    activity = prepare(document)
    assert activity.duration_us > 0
    assert source.measurements == original_measurements
    assert tuple(part.operations for part in source.parts) == original_operations
    records = {m["result"]["measurement_id"]: m for m in document["measurements"]}
    intervals = {}
    for local_start, step in decode_program(document["program"]).timeline():
        for action in step.actions:
            end = local_start + action.duration_us
            for operation in action.source_ids:
                if operation in intervals:
                    intervals[operation] = (
                        intervals[operation][0],
                        max(intervals[operation][1], end),
                    )
                else:
                    intervals[operation] = (local_start, end)
            if isinstance(action, Measure):
                for _, result in action.results:
                    assert (
                        records[result.measurement_id]["available_at_us"]
                        == end + factory.device.readout.latency_us
                    )
    for operation in document["operations"]:
        if operation["operation_id"] in intervals:
            assert (operation["start_us"], operation["end_us"]) == intervals[
                operation["operation_id"]
            ]
