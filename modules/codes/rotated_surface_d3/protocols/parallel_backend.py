"""Bind existing preparation probabilities to a checked actual parallel embedding.

Only independent Pauli/rates models with zero spectator Pauli weights factorize.
The existing seventeen-wire estimator still evaluates its own participant source;
this adapter verifies its actual actions, clocks and trajectory in the merged
world. It never sends a multi-patch quantum circuit to that estimator.
"""

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, replace
from hashlib import sha256
from itertools import combinations, pairwise
from math import hypot, isfinite, prod
from typing import Any

from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    CZPulse,
    Load,
    LocalU,
    Measure,
    Move,
    Reset,
    Rotation,
    Store,
    Wait,
)
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.coverage import RegionSet
from nadit_physical_compiler.device import Device, Region
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.replay import apply_step
from nadit_physical_compiler.semantic_geometry import intersects_segment
from nadit_physical_compiler.serialization import (
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.state import AODHolder, AtomLayout, validate_layout

from ...contracts.component import ComponentExpansion
from ...contracts.event_probability import ProbabilityPort
from ...contracts.parallel import SharedAODClaim
from ..components.canonicalization import PreparationExpansion
from .cost_proxy import SurfaceCostProxyBackend
from .raw_t_postselection import RawTPostselectionExpansion


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError("INVALID_PARALLEL_EMBEDDING: " + message)


def _parts(source: PreparationExpansion) -> tuple[ComponentExpansion, ...]:
    if isinstance(source, RawTPostselectionExpansion):
        return source.parts
    if isinstance(source, ComponentExpansion):
        return (source,)
    raise ValueError("INVALID_PARALLEL_SOURCE: expected a concrete preparation source")


def _projection(
    world: AtomLayout, atoms: tuple[int, ...], aods: tuple[str, ...]
) -> dict[str, Any]:
    return {
        "atoms": [asdict(world.atom(atom)) for atom in sorted(atoms)],
        "aod_grids": [asdict(world.grid(aod)) for aod in sorted(aods)],
    }


def _shared_mapping(
    member: dict[str, Any], device: Device
) -> tuple[dict[int, int], SharedAODClaim]:
    mapping = member.get("shared_aod_mapping", {})
    _require(
        mapping.get("row_ids_unchanged") is True,
        "shared rows must keep their actual identities",
    )
    claim = SharedAODClaim(**member["execution_spec"]["shared_aod"])
    _require(
        member.get("aod_ids") == [claim.aod_id]
        and mapping.get("aod_id") == claim.aod_id,
        "shared AOD identity differs",
    )
    pairs = mapping.get("column_id_map")
    _require(
        isinstance(pairs, list)
        and bool(pairs)
        and all(
            isinstance(pair, list)
            and len(pair) == 2
            and all(type(value) is int and value >= 0 for value in pair)
            for pair in pairs
        ),
        "invalid shared column mapping",
    )
    columns = dict(pairs)
    _require(
        len(columns) == len(pairs) == len(set(columns.values())),
        "shared column mapping is not injective",
    )
    aod = device.aod(claim.aod_id)
    readout = device.readout
    _require(
        readout is not None
        and aod.motion == "flexible"
        and (claim.max_rows, claim.max_columns, claim.min_spacing)
        == (aod.max_rows, aod.max_columns, aod.min_spacing)
        and (claim.readout_channel, claim.max_readout_atoms)
        == (readout.channel, readout.max_atoms),
        "shared capacity declaration differs from Device",
    )
    return columns, claim


def _participant_projection(
    world: AtomLayout,
    atoms: tuple[int, ...],
    aods: tuple[str, ...],
    columns: dict[int, int] | None,
) -> dict[str, Any]:
    if columns is None:
        return _projection(world, atoms, aods)
    inverse = {global_id: local for local, global_id in columns.items()}
    projected = []
    for identity in sorted(atoms):
        atom = world.atom(identity)
        if isinstance(atom.holder, AODHolder):
            _require(
                atom.holder.aod_id in aods and atom.holder.column in inverse,
                "participant uses an unclaimed shared column",
            )
            atom = replace(
                atom, holder=replace(atom.holder, column=inverse[atom.holder.column])
            )
        projected.append(asdict(atom))
    return {
        "atoms": projected,
        "aod_grids": [
            asdict(
                replace(
                    world.grid(aod),
                    columns=tuple(
                        sorted(
                            (
                                replace(line, id=inverse[line.id])
                                for line in world.grid(aod).columns
                                if line.id in inverse
                            ),
                            key=lambda line: line.id,
                        )
                    ),
                )
            )
            for aod in sorted(aods)
        ],
    }


def _member_actions(
    step: AtomStep,
    record: dict[str, Any],
    atoms: tuple[int, ...],
    columns: dict[int, int] | None,
) -> tuple[tuple[Any, ...], tuple[int, ...]]:
    indices = _ids(record.get("batch_action_indices"), "action indices")
    _require(
        all(index < len(step.actions) for index in indices),
        "action map exceeds actual step",
    )
    if columns is None:
        return tuple(step.actions[index] for index in indices), indices
    entries = record.get("action_embeddings")
    _require(
        isinstance(entries, list)
        and all(type(item.get("source_action_index")) is int for item in entries)
        and [item["source_action_index"] for item in entries]
        == list(range(len(entries))),
        "incomplete source action embeddings",
    )
    assert isinstance(entries, list)
    mapped = [item.get("batch_action_index") for item in entries]
    _require(
        all(type(index) is int and index >= 0 for index in mapped)
        and len(set(mapped)) == len(mapped)
        and sorted(mapped) == list(indices),
        "inconsistent fused action indices",
    )
    inverse, owned = (
        {global_id: local for local, global_id in columns.items()},
        set(atoms),
    )
    actions = []
    for item, index in zip(entries, mapped, strict=True):
        actual = step.actions[index]
        ids = item.get("component_source_ids")
        _require(
            isinstance(ids, list)
            and all(type(value) is int and value >= 0 for value in ids)
            and len(set(ids)) == len(ids)
            and set(ids) <= set(actual.source_ids),
            "component source identities differ",
        )
        selected = replace(actual, source_ids=tuple(ids))
        if isinstance(actual, Load | Move | Store):
            grid = replace(
                actual.grid,
                columns=tuple(
                    sorted(
                        (
                            replace(line, id=inverse[line.id])
                            for line in actual.grid.columns
                            if line.id in inverse
                        ),
                        key=lambda line: line.id,
                    )
                ),
            )
            selected = replace(selected, grid=grid)
            if isinstance(actual, Load):
                bindings = tuple(
                    binding for binding in actual.bindings if binding[0] in owned
                )
                _require(
                    all(column in inverse for _, _, column in bindings),
                    "load names an unclaimed shared column",
                )
                selected = replace(
                    selected,
                    bindings=tuple(
                        (atom, row, inverse[column]) for atom, row, column in bindings
                    ),
                )
            elif isinstance(actual, Move):
                selected = replace(
                    selected,
                    targets=tuple(
                        (atom, target)
                        for atom, target in actual.targets
                        if atom in owned
                    ),
                )
            else:
                selected = replace(
                    selected,
                    bindings=tuple(
                        binding for binding in actual.bindings if binding[0] in owned
                    ),
                )
        else:
            _require(
                tuple(ids) == actual.source_ids,
                "nontransport component identities differ",
            )
        _require(
            item.get("component_action_sha256")
            == canonical_hash(encode_program(AtomProgram((AtomStep((selected,)),)))),
            "actual fused component hash differs",
        )
        actions.append(selected)
    return tuple(actions), tuple(mapped)


def _ids(value: Any, label: str) -> tuple[int, ...]:
    _require(
        isinstance(value, list)
        and all(type(item) is int and item >= 0 for item in value),
        label,
    )
    _require(value == sorted(set(value)), label + " must be sorted and unique")
    return tuple(value)


def _time(value: Any) -> float:
    _require(
        type(value) in (int, float) and isfinite(value) and value >= 0, "invalid time"
    )
    return float(value)


def _touched(action: Any, world: AtomLayout) -> set[int]:
    if isinstance(action, Load | Store):
        return {entry[0] for entry in action.bindings}
    if isinstance(action, Move):
        return {atom for atom, _ in action.targets}
    if isinstance(action, Measure):
        return {atom for atom, _ in action.results}
    if isinstance(action, Rotation | LocalU | Reset):
        return set(action.atoms)
    if isinstance(action, CZPulse):
        if isinstance(action.coverage, tuple):
            return set(action.coverage)
        regions = (
            action.coverage.regions
            if isinstance(action.coverage, RegionSet)
            else (action.coverage,)
        )
        _require(
            all(isinstance(region, Region) for region in regions),
            "unknown pulse coverage",
        )
        return {
            atom.id
            for atom in world.atoms
            if any(region.contains(atom.position) for region in regions)
        }
    _require(isinstance(action, Wait), "unsupported action in factorized batch")
    return set()


def _source_record(part: ComponentExpansion) -> dict[str, Any]:
    return {
        "invocation_id": part.invocation_id,
        "template_content_sha256": part.template_content_sha256,
        "program_sha256": canonical_hash(encode_program(part.program)),
        "standalone_entry_world_sha256": canonical_hash(
            encode_layout(part.entry_state)
        ),
        "standalone_exit_world_sha256": canonical_hash(encode_layout(part.exit_state)),
        "start_us": part.start_us,
        "action_end_us": part.action_end_us,
        "results_ready_us": part.results_ready_us,
    }


def _verify(
    source: PreparationExpansion,
    program: AtomProgram,
    entry: AtomLayout,
    evidence: dict[str, Any],
    device: Device,
) -> dict[str, Any]:
    """Reconstruct ownership, original actions and local trajectories independently."""
    parts = _parts(source)
    shared = evidence.get("mode") == "shared_aod_lockstep"
    _require(
        isinstance(program, AtomProgram) and isinstance(entry, AtomLayout),
        "missing actual program/world",
    )
    validation = evidence.get("validation", {})
    _require(
        evidence.get("schema") == "nadit.physical_lockstep_batch/1"
        and evidence.get("mode") in ("independent_aods_lockstep", "shared_aod_lockstep")
        and evidence.get("time_basis") == "ordered_global_atom_steps"
        and isinstance(evidence.get("batch_id"), str)
        and bool(evidence["batch_id"])
        and validation.get("ok") is True
        and validation.get("semantic") == "checked"
        and {"pulse", "timing"} <= set(validation.get("checks", ())),
        "missing validated batch evidence",
    )
    _require(
        evidence.get("participant_trajectory_projection_verified") is True
        and evidence.get("declared_space_envelopes_verified") is True
        and evidence.get("cross_patch_interaction_check")
        == "physical_pulse_and_addressing_validation"
        and evidence.get("noise_factorization_claimed") is False
        and evidence.get("global_noise_coverage_claimed") is False,
        "wrong batch evidence scope",
    )
    program_hash = canonical_hash(encode_program(program))
    _require(
        evidence.get("program_sha256") == program_hash, "actual program hash differs"
    )
    _require(
        evidence.get("entry_world_sha256") == canonical_hash(encode_layout(entry)),
        "actual entry hash differs",
    )
    _require(
        evidence.get("device_sha256") == canonical_hash(encode_device(device)),
        "actual device hash differs",
    )
    members = evidence.get("members")
    _require(isinstance(members, list) and bool(members), "missing members")
    assert isinstance(members, list)
    _require(
        isinstance(evidence.get("waveform_key"), str)
        and bool(evidence["waveform_key"]),
        "missing waveform identity",
    )
    matches = [
        member
        for member in members
        if [p.get("invocation_id") for p in member.get("source_parts", [])]
        == [part.invocation_id for part in parts]
    ]
    _require(len(matches) == 1, "source does not identify exactly one member")
    member = matches[0]
    _require(
        member.get("source_parts") == [_source_record(part) for part in parts],
        "source part evidence differs",
    )
    _require(
        member.get("pending_measurements")
        == json.loads(
            json.dumps([asdict(m) for part in parts for m in part.measurements])
        ),
        "measurement identity/readiness differs",
    )
    own_atoms = _ids(member.get("participant_atoms"), "participant atoms")
    _require(set(own_atoms) == set(parts[0].wire_atoms), "wrong participant atoms")
    all_atoms: set[int] = set()
    all_aods: set[str] = set()
    identities: set[str] = set()
    member_atoms, member_aods = [], []
    member_columns: list[dict[int, int] | None] = []
    shared_claims: list[SharedAODClaim] = []
    claimed_columns: dict[str, set[int]] = {}
    embeddings = []
    for item in members:
        identity = item.get("invocation_id")
        _require(
            isinstance(identity, str) and bool(identity) and identity not in identities,
            "duplicate member",
        )
        identities.add(identity)
        atoms = _ids(item.get("participant_atoms"), "member atoms")
        aods = item.get("aod_ids")
        _require(
            isinstance(aods, list)
            and all(isinstance(a, str) and a for a in aods)
            and aods == sorted(set(aods)),
            "invalid member AOD identities",
        )
        _require(
            bool(atoms)
            and not all_atoms.intersection(atoms)
            and (shared or not all_aods.intersection(aods)),
            "member ownership overlaps",
        )
        all_atoms.update(atoms)
        all_aods.update(aods)
        for aod in aods:
            device.aod(aod)
        spec = item.get("execution_spec", {})
        _require(
            spec.get("parallel_mode") == evidence["mode"]
            and spec.get("waveform_key") == evidence["waveform_key"]
            and spec.get("code_id") == parts[0].description.code_id
            and isinstance(spec.get("participant_blocks"), list)
            and len(spec["participant_blocks"]) == 1
            and set(spec.get("exclusive_resources", ()))
            == (set() if shared else {f"aod:{aod}" for aod in aods}),
            "inconsistent member execution declaration",
        )
        pending = item.get("pending_measurements")
        base, count = item.get("result_id_base"), item.get("result_count")
        _require(
            type(base) is int
            and base >= 0
            and type(count) is int
            and count >= 0
            and spec.get("result_count") == count
            and isinstance(pending, list)
            and len(pending) == count
            and all(record.get("value") is None for record in pending)
            and sorted(record["result"]["measurement_id"] for record in pending)
            == list(range(base, base + count)),
            "invalid unobserved result reservation",
        )
        member_atoms.append(atoms)
        member_aods.append(tuple(aods))
        if shared:
            columns, claim = _shared_mapping(item, device)
            occupied = claimed_columns.setdefault(claim.aod_id, set())
            _require(
                not occupied.intersection(columns.values()),
                "shared members reuse a column identity",
            )
            occupied.update(columns.values())
            member_columns.append(columns)
            shared_claims.append(claim)
        else:
            member_columns.append(None)
        records = item.get("steps")
        _require(
            isinstance(records, list) and len(records) == len(program.steps),
            "incomplete member step embedding",
        )
        _require(
            all(type(record.get("batch_step_index")) is int for record in records)
            and [record.get("batch_step_index") for record in records]
            == list(range(len(program.steps))),
            "wrong batch step indices",
        )
        embeddings.append(records)
    selected_index = members.index(member)
    own_aods = member_aods[selected_index]
    own_columns = member_columns[selected_index]
    if shared:
        assert own_columns is not None
        source_columns = {
            line.id
            for part in parts
            for step in part.program.steps
            for action in step.actions
            if isinstance(action, Load | Move | Store)
            for line in action.grid.columns
        }
        _require(
            set(own_columns) == source_columns,
            "shared column map does not cover the original source",
        )
        for aod_id in all_aods:
            claims = [claim for claim in shared_claims if claim.aod_id == aod_id]
            _require(
                len({claim.row_trajectory_key for claim in claims}) == 1,
                "shared row trajectory declarations differ",
            )
            capacity = device.aod(aod_id)
            _require(
                capacity.max_columns is None
                or sum(claim.peak_columns for claim in claims) <= capacity.max_columns,
                "shared column capacity exceeded",
            )
            ordered = sorted(claims, key=lambda claim: claim.column_min)
            _require(
                all(
                    b.column_min - a.column_max >= capacity.min_spacing
                    for a, b in pairwise(ordered)
                ),
                "shared column bands overlap or violate spacing",
            )
        if device.readout is not None and device.readout.max_atoms is not None:
            _require(
                sum(claim.peak_readout_atoms for claim in shared_claims)
                <= device.readout.max_atoms,
                "shared readout capacity exceeded",
            )
    expected = [
        (part, local, step)
        for part in parts
        for local, step in enumerate(part.program.steps)
    ]
    _require(len(expected) == len(program.steps), "source step count differs")
    actual, standalone = entry, parts[0].entry_state
    validate_layout(device, actual)
    clock = _time(evidence.get("start_us"))
    _require(clock == parts[0].start_us, "source starts at another time")
    actual_results: set[int] = set()
    for index, (merged, (part, local_step, original)) in enumerate(
        zip(program.steps, expected, strict=True)
    ):
        if local_step == 0:
            _require(clock == part.start_us, "source part start differs")
            _require(
                _projection(standalone, own_atoms, own_aods)
                == _projection(part.entry_state, own_atoms, own_aods),
                "source local entry differs",
            )
        used: set[int] = set()
        contributions: dict[int, list[tuple[int, Any]]] = {}
        extracted: list[tuple[Any, ...]] = []
        pulses: list[tuple[str, int, set[int]]] = []
        for owner, (atoms, aods, records) in enumerate(
            zip(member_atoms, member_aods, embeddings, strict=True)
        ):
            record = records[index]
            _require(
                _time(record.get("start_us")) == clock
                and _time(record.get("end_us")) == clock + merged.duration_us,
                "embedded time differs",
            )
            selected_actions, indices = _member_actions(
                merged, record, atoms, member_columns[owner]
            )
            extracted.append(selected_actions)
            _require(
                (shared or not used.intersection(indices))
                and all(i < len(merged.actions) for i in indices),
                "action map overlaps or exceeds actual step",
            )
            used.update(indices)
            for action_index, action in zip(indices, selected_actions, strict=True):
                contributions.setdefault(action_index, []).append((owner, action))
                touched = _touched(action, actual)
                _require(
                    touched <= set(atoms),
                    "action touches another patch or undeclared atom",
                )
                if isinstance(action, Load | Move | Store):
                    _require(
                        action.grid.aod_id in aods,
                        "transport uses another member's AOD",
                    )
                    if shared:
                        claim = shared_claims[owner]
                        _require(
                            len(action.grid.rows) <= claim.peak_rows
                            and len(action.grid.columns) <= claim.peak_columns
                            and all(
                                claim.column_min <= line.coordinate <= claim.column_max
                                for line in action.grid.columns
                            ),
                            "actual grid exceeds shared declaration",
                        )
                if isinstance(action, CZPulse):
                    pulses.append((action.channel, owner, touched))
                if isinstance(action, Measure):
                    ids = {ref.measurement_id for _, ref in action.results}
                    _require(
                        len(ids) == len(action.results)
                        and not actual_results.intersection(ids),
                        "duplicate actual result identities",
                    )
                    actual_results.update(ids)
        _require(
            used == set(range(len(merged.actions))),
            "actual actions are missing from the member partition",
        )
        if shared:
            for action_index, components in contributions.items():
                actual_action = merged.actions[action_index]
                _require(
                    len(components) == 1
                    or isinstance(actual_action, Load | Move | Store),
                    "only transport may be fused across members",
                )
                all_component_ids = [
                    identity
                    for _, action in components
                    for identity in action.source_ids
                ]
                _require(
                    len(set(all_component_ids)) == len(all_component_ids)
                    and set(all_component_ids) == set(actual_action.source_ids)
                    and len(set(actual_action.source_ids))
                    == len(actual_action.source_ids),
                    "fused source identities are not an exact partition",
                )
                _require(
                    set().union(*(_touched(action, actual) for _, action in components))
                    == _touched(actual_action, actual),
                    "fused atom ownership is not an exact partition",
                )
                if isinstance(actual_action, Load | Move | Store):
                    active_columns = {line.id for line in actual_action.grid.columns}
                    mapped_columns: set[int] = set()
                    for owner, _ in components:
                        column_mapping = member_columns[owner]
                        assert column_mapping is not None
                        mapped_columns.update(column_mapping.values())
                    _require(
                        active_columns <= mapped_columns,
                        "fused grid has unclaimed columns",
                    )
                    _require(
                        all(
                            action.grid.rows == actual_action.grid.rows
                            for _, action in components
                        ),
                        "fused row phases differ",
                    )
        if device.cz is not None:
            for (channel_a, owner_a, atoms_a), (
                channel_b,
                owner_b,
                atoms_b,
            ) in combinations(pulses, 2):
                if channel_a == channel_b and owner_a != owner_b:
                    _require(
                        all(
                            hypot(
                                actual.atom(a).position.x - actual.atom(b).position.x,
                                actual.atom(a).position.y - actual.atom(b).position.y,
                            )
                            > device.cz.radius_um + 1e-9
                            for a in atoms_a
                            for b in atoms_b
                        ),
                        "cross-patch CZ interaction",
                    )
        for pulse in (
            action for action in merged.actions if isinstance(action, CZPulse)
        ):
            if isinstance(pulse.coverage, tuple):
                regions = tuple(
                    Region(
                        actual.atom(atom).position.x,
                        actual.atom(atom).position.y,
                        actual.atom(atom).position.x,
                        actual.atom(atom).position.y,
                    )
                    for atom in pulse.coverage
                )
            else:
                regions = (
                    pulse.coverage.regions
                    if isinstance(pulse.coverage, RegionSet)
                    else (pulse.coverage,)
                )
            for move in (
                action for action in merged.actions if isinstance(action, Move)
            ):
                _require(
                    not any(
                        intersects_segment(region, actual.atom(atom).position, target)
                        for atom, target in move.targets
                        for region in regions
                    ),
                    "movement crosses concurrent CZ illumination",
                )
        record = embeddings[selected_index][index]
        _require(
            record.get("part_invocation_id") == part.invocation_id
            and type(record.get("local_step_index")) is int
            and record["local_step_index"] == local_step,
            "source local step identity differs",
        )
        selected = AtomStep(extracted[selected_index])
        _require(
            tuple(replace(a, source_ids=()) for a in selected.actions)
            == tuple(replace(a, source_ids=()) for a in original.actions)
            and selected.duration_us == merged.duration_us == original.duration_us,
            "actual source actions or duration differ",
        )
        before = _participant_projection(actual, own_atoms, own_aods, own_columns)
        _require(
            before == _projection(standalone, own_atoms, own_aods)
            and record.get("participant_entry_sha256") == canonical_hash(before),
            "participant entry trajectory differs",
        )
        actual = apply_step(actual, merged, device)
        standalone = apply_step(standalone, original, device)
        validate_layout(device, actual)
        after = _participant_projection(actual, own_atoms, own_aods, own_columns)
        _require(
            after == _projection(standalone, own_atoms, own_aods)
            and record.get("participant_exit_sha256") == canonical_hash(after),
            "participant exit trajectory differs",
        )
        clock += merged.duration_us
        if local_step == len(part.program.steps) - 1:
            _require(
                clock == part.action_end_us
                and after == _projection(part.exit_state, own_atoms, own_aods),
                "source local exit differs",
            )
    _require(clock == _time(evidence.get("action_end_us")), "batch exit time differs")
    _require(
        evidence.get("exit_world_sha256") == canonical_hash(encode_layout(actual)),
        "actual exit hash differs",
    )
    return {
        "schema": "nadit.parallel_preparation_embedding/1",
        "batch_id": evidence["batch_id"],
        "mode": evidence["mode"],
        "fused_transport_components_verified": shared,
        "member_invocation_id": member["invocation_id"],
        "actual_program_sha256": program_hash,
        "actual_entry_world_sha256": canonical_hash(encode_layout(entry)),
        "actual_exit_world_sha256": canonical_hash(encode_layout(actual)),
        "device_sha256": evidence["device_sha256"],
        "batch_evidence_sha256": canonical_hash(evidence),
        "member_embedding": member,
        "participant_atom_ids": list(own_atoms),
        "source_actions_and_times_verified": True,
        "participant_trajectory_verified": True,
        "other_members_do_not_touch_participant": True,
        "cross_patch_interactions_absent": True,
        "source_id_normalization": "native_operation_ids_only",
        "measurement_identities_preserved": True,
        "action_window_us": [parts[0].start_us, clock],
        "results_ready_us": source.results_ready_us,
        "global_noise_coverage_claimed": False,
        "logical_success_probability": None,
    }


@dataclass(frozen=True)
class SurfaceParallelCostBackend(SurfaceCostProxyBackend):
    """Add checked actual scheduling evidence without changing joint raw weights."""

    _parallel_sources: dict[str, tuple[str, str]] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    def register_parallel_source(
        self,
        source: PreparationExpansion,
        *,
        program: AtomProgram,
        entry_world: AtomLayout,
        evidence: Mapping[str, Any],
    ) -> None:
        """Verify one member's actual merged-program embedding before event use."""
        try:
            document = json.loads(
                json.dumps(dict(evidence), sort_keys=True, allow_nan=False)
            )
            proof = _verify(source, program, entry_world, document, self.device)
        except (KeyError, TypeError, AttributeError) as error:
            raise ValueError(
                f"INVALID_PARALLEL_EMBEDDING: incomplete evidence: {error}"
            ) from error
        identity = _parts(source)[0].invocation_id
        stored = (
            sha256(repr(source).encode()).hexdigest(),
            json.dumps(proof, sort_keys=True, separators=(",", ":"), allow_nan=False),
        )
        previous = self._parallel_sources.get(identity)
        if previous is not None and previous != stored:
            raise ValueError(
                "CONFLICTING_PARALLEL_SOURCE: registered source or embedding changed"
            )
        self._parallel_sources[identity] = stored

    def preparation_event(
        self,
        preparation: str,
        source: PreparationExpansion,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort:
        """Keep parent probabilities; attach only independently verified evidence."""
        port = super().preparation_event(preparation, source, parameters)
        registered = self._parallel_sources.get(_parts(source)[0].invocation_id)
        if registered is None:
            return port
        if registered[0] != sha256(repr(source).encode()).hexdigest():
            raise ValueError("CONFLICTING_PARALLEL_SOURCE: event source changed")
        proof = json.loads(registered[1])
        if isinstance(source, RawTPostselectionExpansion):
            if parameters is None or parameters.get("noise_model") != "noise/v1":
                raise ValueError(
                    "UNSUPPORTED_PARALLEL_NOISE: explicit noise/v1 required"
                )
            params = resolve(parameters["noise_params"])
            if (
                any(
                    gate["backend"] != "pauli"
                    for gate in (
                        params["single"],
                        params["cz"],
                        *params["single_overrides"].values(),
                    )
                )
                or params["transport"]["backend"] != "rates/v1"
            ):
                raise ValueError(
                    "UNSUPPORTED_PARALLEL_NOISE: independent Pauli/rates only"
                )
            if any(params["spectator_pauli"]):
                raise ValueError(
                    "UNSUPPORTED_PARALLEL_NOISE: spectator_pauli must be zero"
                )
            proof["factorization_profile"] = "independent_pauli_rates_zero_spectator/1"
            if proof["mode"] == "shared_aod_lockstep":
                proof["factorization_profile"] = (
                    "shared_aod_independent_participant_channels/1"
                )
                proof["shared_device_common_mode_noise"] = "unsupported"
                proof["empty_grid_intersection_noise_inferred"] = False
            proof["noise_params_hash"] = canonical_hash(params)
        document = port.to_dict()
        model = document["model"]
        evidence = model["evidence"]
        evidence["parallel_schedule_embedding"] = proof
        evidence["unembedded_reference_port_sha256"] = port.content_sha256
        if "physical_loss" in evidence:
            loss = evidence["physical_loss"]
            participants = set(proof["participant_atom_ids"])
            selected = [
                item for item in loss["per_atom"] if item["atom"] in participants
            ]
            _require(
                {item["atom"] for item in selected} == participants,
                "incomplete participant loss reference",
            )
            evidence["isolated_world_loss_reference_sha256"] = canonical_hash(loss)
            evidence["physical_loss"] = {
                "scope": "isolated_participant_projection_reference",
                "time_basis": "relative_to_source_segment_start",
                "global_parallel_loss_claimed": False,
                "participant_atom_ids": sorted(participants),
                "per_atom": selected,
                "expected_lost_atoms": sum(
                    item["loss_probability"] for item in selected
                ),
                "all_atoms_survive_probability": prod(
                    item["survival_probability"] for item in selected
                ),
                "events": [
                    item for item in loss["events"] if item["atom"] in participants
                ],
            }
            evidence["noise_report_scope"] = (
                "isolated_reference_report_with_verified_participant_actions"
            )
        model["assumptions"].extend(
            [
                "Actual merged actions, ordered step times, result IDs and participant trajectories match the source",
                "Independent member Pauli/readout weights require zero configured spectator Pauli noise",
                "Physical loss remains a participant-only isolated reference, not global parallel-world loss",
                "Result-ready idle tails exclude any later participant operation; accepted quantum quality remains unsupported",
            ]
        )
        return ProbabilityPort.from_dict(document)
