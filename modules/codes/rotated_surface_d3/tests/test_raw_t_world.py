"""Raw preparation noise on the actual occupied world and bounded time segment."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from nadit_physical_compiler.atom_ir import Measure, Store
from nadit_physical_compiler.cost import model_for, prepare
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.serialization import decode_program
from nadit_physical_compiler.state import SLMHolder

from modules.codes.contracts.component import InvocationContext
from modules.codes.rotated_surface_d3.probabilities.raw_t import (
    _joint_document,
    raw_t_pauli_port,
)
from modules.codes.rotated_surface_d3.probabilities.raw_t_detectors import (
    detector_fault_channels,
    xor_distribution,
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
    template = RawTPostselection().compile(
        factory.device,
        home_sites=patch.home_sites,
        origin=patch.binding.origin,
        aod_id=patch.binding.aod_id,
    )
    source = template.bind(patch.binding).expand(
        InvocationContext("world/raw", 2500, 800, factory.device, factory.world_state)
    )
    return factory, template, source


def _detectors(source):
    return tuple(
        tuple(m.result.measurement_id for m in d.measurements) for d in source.detectors
    )


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


def test_only_spectator_noise_has_zero_detector_signature(raw_world):
    factory, _, source = raw_world
    activity = prepare(_joint_document(source, factory.device))
    participant = source.parts[0].wire_atoms
    world_ids = tuple(atom.atom_id for atom in activity.per_atom)
    spectators = set(world_ids) - set(participant)
    assert len(spectators) == 85
    channels = [
        {
            "instruction": "PAULI_CHANNEL_1",
            "probabilities": [0.2, 0.3, 0.1],
            "atoms": [atom],
            "placement": "after",
            "start_us": 0,
            "duration_us": activity.duration_us,
        }
        for atom in spectators
    ]
    signatures, proof = detector_fault_channels(
        activity,
        channels,
        _detectors(source),
        wire_atoms=participant,
        world_atom_ids=world_ids,
    )
    assert all(mask == 0 for channel in signatures for mask, _ in channel)
    assert xor_distribution(12, signatures)[0] == 1
    assert proof["world_atom_count"] == 102


def test_noise_model_includes_real_spectator_idle_without_dag_wires(raw_world):
    factory, _, source = raw_world
    document = _joint_document(source, factory.device)
    activity = prepare(document)
    noise = model_for("noise/v1").evaluate(activity, document, _noise_params())
    participants = set(source.parts[0].wire_atoms)
    spectators = {
        atom.atom_id for atom in activity.per_atom if atom.atom_id not in participants
    }
    external = [
        channel
        for channel in noise["noise"]["channels"]
        if set(channel["atoms"]) <= spectators
    ]
    assert {channel["atoms"][0] for channel in external} == spectators
    assert all(channel["qubits"] == [None] for channel in external)
    assert all(channel["instruction"] == "Z_ERROR" for channel in external)
    for atom in activity.per_atom:
        if atom.atom_id not in spectators:
            continue
        # Real CZ illumination counts as busy even for unpaired spectators.
        # This model excludes busy pulse time from its separate T2 channel.
        assert atom.busy_us > 0
        assert {interval.kind for interval in atom.busy} == {"CZPulse"}
        assert atom.idle_us + atom.busy_us == pytest.approx(activity.duration_us)
        assert sum(
            channel["duration_us"]
            for channel in external
            if channel["atoms"] == [atom.atom_id]
        ) == pytest.approx(atom.idle_us)


def test_incomplete_world_index_cannot_hide_spectator_channels(raw_world):
    factory, _, source = raw_world
    activity = prepare(_joint_document(source, factory.device))
    with pytest.raises(ValueError, match="complete-world"):
        detector_fault_channels(
            activity,
            [],
            _detectors(source),
            wire_atoms=source.parts[0].wire_atoms,
        )


@pytest.mark.parametrize("change", ("rotation", "cross_cz"))
def test_detector_profile_rejects_external_participant_gates(raw_world, change):
    factory, _, source = raw_world
    activity = prepare(_joint_document(source, factory.device))
    outsider = factory.patch("W1").binding.atom_ids[0]
    kind = "Rotation" if change == "rotation" else "CZPulse"
    index, event = next((i, e) for i, e in enumerate(activity.events) if e.kind == kind)
    if change == "rotation":
        replacement = replace(event, atoms=(outsider,))
    else:
        replacement = replace(
            event, pairs=((event.pairs[0][0], outsider), *event.pairs[1:])
        )
    events = list(activity.events)
    events[index] = replacement
    with pytest.raises(ValueError, match="participant|isolated"):
        detector_fault_channels(
            replace(activity, events=tuple(events)),
            [],
            _detectors(source),
            wire_atoms=source.parts[0].wire_atoms,
            world_atom_ids=tuple(atom.atom_id for atom in activity.per_atom),
        )


def test_real_world_guest_occupation_is_not_hidden_by_local_projection(raw_world):
    factory, _, source = raw_world
    destination = next(
        action.bindings[0][1]
        for step in source.parts[0].program.steps
        for action in step.actions
        if isinstance(action, Store)
    )
    outsider = factory.patch("W1").binding.atom_ids[0]
    occupied = replace(
        factory.world_state,
        atoms=tuple(
            replace(
                atom,
                position=factory.device.site(destination).position,
                holder=SLMHolder(destination),
            )
            if atom.id == outsider
            else atom
            for atom in factory.world_state.atoms
        ),
    )
    changed = replace(
        source,
        parts=tuple(
            replace(part, entry_state=occupied, exit_state=occupied)
            for part in source.parts
        ),
    )
    with pytest.raises(ValueError, match="semantic admission"):
        raw_t_pauli_port(changed, factory.device, noise_params={})


def test_translation_atom_ids_and_absolute_start_do_not_add_prefix_noise(raw_world):
    factory, template, source = raw_world
    shifted = make_factory_world(
        FactoryWorldConfig(
            origin=Position(230, -40),
            atom_id_base=700,
        )
    )
    other = template.bind(shifted.patch("W3").binding).expand(
        InvocationContext(
            "translated/raw", 9000, 4000, shifted.device, shifted.world_state
        )
    )
    first = raw_t_pauli_port(source, factory.device, noise_params=_noise_params())
    second = raw_t_pauli_port(other, shifted.device, noise_params=_noise_params())
    assert first.outcome("accepted").probability == pytest.approx(
        second.outcome("accepted").probability,
        abs=1e-12,
    )
    evidence = second.to_dict()["model"]["evidence"]
    assert evidence["segment_start_us"] == 9000
    assert evidence["world_atom_ids"] == list(range(700, 802))
    assert evidence["activity_duration_us"] == pytest.approx(
        first.to_dict()["model"]["evidence"]["activity_duration_us"],
        abs=1e-10,
    )


def test_inter_round_gap_affects_acceptance_but_post_readout_tail_does_not(raw_world):
    factory, _, source = raw_world
    params = {
        "exposure": {"slm_t2_us": 5000, "aod_t2_us": 5000, "include_transport": True}
    }
    baseline = raw_t_pauli_port(source, factory.device, noise_params=params)
    first, second = source.parts
    gap = 400
    delayed = replace(
        source,
        parts=(
            first,
            replace(
                second,
                start_us=second.start_us + gap,
                measurements=tuple(
                    replace(m, available_at_us=m.available_at_us + gap)
                    for m in second.measurements
                ),
            ),
        ),
    )
    gap_port = raw_t_pauli_port(delayed, factory.device, noise_params=params)
    assert (
        gap_port.outcome("accepted").probability
        < baseline.outcome("accepted").probability
    )
    assert gap_port.to_dict()["model"]["evidence"][
        "activity_duration_us"
    ] == pytest.approx(
        baseline.to_dict()["model"]["evidence"]["activity_duration_us"] + gap,
    )
    tail = 300
    later_results = replace(
        source,
        parts=(
            first,
            replace(
                second,
                measurements=tuple(
                    replace(m, available_at_us=m.available_at_us + tail)
                    for m in second.measurements
                ),
            ),
        ),
    )
    tail_port = raw_t_pauli_port(later_results, factory.device, noise_params=params)
    assert tail_port.outcome("accepted").probability == pytest.approx(
        baseline.outcome("accepted").probability,
        abs=1e-12,
    )
    assert tail_port.to_dict()["model"]["evidence"][
        "activity_duration_us"
    ] == pytest.approx(
        baseline.to_dict()["model"]["evidence"]["activity_duration_us"] + tail,
    )


@pytest.mark.parametrize("start", (105000.0, 1e6, 1e7))
def test_private_cost_timeline_rebases_large_absolute_starts_exactly(raw_world, start):
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


def test_private_rebasing_keeps_a_real_late_gap_and_delivery_delay(raw_world):
    factory, template, _ = raw_world
    binding = factory.patch("W3").binding
    source = template.bind(binding).expand(
        InvocationContext("late/gapped", 1e7, 5000, factory.device, factory.world_state)
    )
    first = source.parts[0]
    second = template.se_round.bind(binding).expand(
        InvocationContext(
            "late/gapped/round[1]",
            first.action_end_us + 400,
            5008,
            factory.device,
            first.exit_state,
        )
    )
    second = replace(
        second,
        measurements=tuple(
            replace(m, available_at_us=m.available_at_us + 137)
            for m in second.measurements
        ),
    )
    source = replace(source, parts=(first, second))
    document = _joint_document(source, factory.device)
    activity = prepare(document)
    records = {m["result"]["measurement_id"]: m for m in document["measurements"]}
    for local_start, step in decode_program(document["program"]).timeline():
        for action in step.actions:
            if isinstance(action, Measure):
                for _, result in action.results:
                    extra = 137 if result.measurement_id >= 5008 else 0
                    assert records[result.measurement_id]["available_at_us"] == (
                        local_start
                        + action.duration_us
                        + factory.device.readout.latency_us
                        + extra
                    )
    assert activity.duration_us == pytest.approx(
        1725.634980935729 + 400 + 137, abs=1e-10
    )


@pytest.mark.parametrize("offset", (-1, float("nan"), float("inf")))
def test_private_rebasing_does_not_repair_an_invalid_public_result(raw_world, offset):
    factory, _, source = raw_world
    first, second = source.parts
    invalid = replace(
        source,
        parts=(
            first,
            replace(
                second,
                measurements=tuple(
                    replace(m, available_at_us=m.available_at_us + offset)
                    for m in second.measurements
                ),
            ),
        ),
    )
    with pytest.raises(ValueError, match="Source measurement"):
        _joint_document(invalid, factory.device)
