"""Physical no-fault proxy on owned atoms in the actual shared world timeline.

This is a marginal channel selection from physically validated global activity,
not a replay of an isolated factory or a logical-success estimate. Source owner
labels never select noise: actual illuminated/transported/measured atoms do.
"""

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import replace
from typing import Any

from nadit_physical_compiler.activity import ActivityEvent, AtomActivity
from nadit_physical_compiler.cost import model_for, prepare
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.provenance import canonical_hash

from .assembly import PhysicalBundle
from .cost import (
    PhysicalCostError,
    _annotate_report,
    _generated_qasm,
    _include_intervals,
    _project_activity,
    _structural_document,
    _validated_snapshot,
)


def _participant_activity(
    activity: AtomActivity, selected: frozenset[int]
) -> tuple[AtomActivity, list[int]]:
    """Filter actual targets while retaining full event time and source identity.

    A cross-participant CZ anywhere in this source trace is rejected, even if it
    is outside selected time. This conservative boundary avoids silently treating
    an entangled cross-line interaction as an independent factory-local channel.
    """
    events: list[ActivityEvent] = []
    source_indices: list[int] = []
    for index, event in enumerate(activity.events):
        if any((a in selected) != (b in selected) for a, b in event.pairs):
            raise PhysicalCostError(
                f"CROSS_PARTICIPANT_CZ: source event {index} joins selected and unselected atoms"
            )
        offsets = tuple(i for i, atom in enumerate(event.atoms) if atom in selected)
        if not offsets and event.kind != "Wait":
            continue
        events.append(
            replace(
                event,
                atoms=tuple(event.atoms[i] for i in offsets),
                starts=tuple(event.starts[i] for i in offsets),
                ends=tuple(event.ends[i] for i in offsets),
                pairs=tuple((a, b) for a, b in event.pairs if a in selected),
                measurement_ids=tuple(event.measurement_ids[i] for i in offsets)
                if event.measurement_ids
                else (),
            )
        )
        source_indices.append(index)
    return AtomActivity(
        activity.duration_us,
        tuple(atom for atom in activity.per_atom if atom.atom_id in selected),
        tuple(events),
    ), source_indices


def evaluate_participant_cost(
    bundle: PhysicalBundle,
    noise_params: Mapping[str, Any],
    *,
    participant_atom_ids: Iterable[int],
    include_intervals: Iterable[tuple[float, float]],
    owner_id: str,
) -> dict[str, Any]:
    """Evaluate independent Pauli/rates noise for a named actual atom subset.

    The complete unobserved bundle is structurally bridged and physically
    revalidated by cost.prepare. Activity is derived once from that full trace.
    Fused action target lists, transport endpoints, and measurement identities
    are restricted together to selected atoms. Foreign illumination affecting a
    selected atom remains charged. Cross-boundary CZ pairs are unsupported.

    Callers supply absolute included time intervals, excluding only this owner's
    conditioned raw horizons. Waiting while a different factory retries remains
    ordinary selected-atom storage exposure. No other owner's horizon is inferred.
    Non-Wait actions affecting selected atoms cannot straddle an interval boundary;
    unrelated actions can. Original residence/idle partitions are intersected with
    the interval union, without generating a second latency tail.

    Returns the noise/v1 report plus reproducible atom/time projection evidence.
    no_fault_probability already includes configured loss. It is neither logical
    success nor a claim that disjoint T2 interval products equal a whole trace.
    The immutable bundle and its pending measurement values are never changed.
    """
    if not isinstance(owner_id, str) or not owner_id.strip():
        raise PhysicalCostError("INVALID_COST_OWNER: require a nonempty owner identity")
    try:
        atoms = tuple(participant_atom_ids)
    except TypeError as error:
        raise PhysicalCostError(
            "INVALID_COST_PARTICIPANTS: require atom identities"
        ) from error
    if (
        not atoms
        or any(type(atom) is not int or atom < 0 for atom in atoms)
        or len(set(atoms)) != len(atoms)
    ):
        raise PhysicalCostError(
            "INVALID_COST_PARTICIPANTS: require distinct nonnegative integer atom identities"
        )
    if not isinstance(noise_params, Mapping):
        raise PhysicalCostError("INVALID_COST_PARAMETERS: supply an explicit mapping")
    params = resolve(deepcopy(dict(noise_params)))
    if any(
        config["backend"] != "pauli"
        for config in (
            params["single"],
            params["cz"],
            *params["single_overrides"].values(),
        )
    ):
        raise PhysicalCostError(
            "UNSUPPORTED_PARTICIPANT_NOISE_PROFILE: require independent Pauli gates and rates/v1"
        )
    snapshot = _validated_snapshot(bundle)
    selected = frozenset(atoms)
    if not selected <= {atom.id for atom in bundle.entry_world.atoms}:
        raise PhysicalCostError(
            "INVALID_COST_PARTICIPANTS: unknown source-world atom identity"
        )
    bundle_hash = canonical_hash(snapshot)
    source = _generated_qasm(bundle.dag)
    document = _structural_document(bundle, bundle_hash, source)
    activity = prepare(document)
    selection = _include_intervals(include_intervals, activity.duration_us)
    participant_activity, source_indices = _participant_activity(activity, selected)
    projected, index_map = _project_activity(participant_activity, selection)
    for entry in index_map:
        entry["source_event_id"] = source_indices[entry["source_event_id"]]
    report = model_for("noise/v1").evaluate(projected, document, params)
    source_hash = canonical_hash(activity.document())
    selected_hash = canonical_hash(projected.document())
    return {
        **_annotate_report(bundle, bundle_hash, source, activity, report),
        "time_scope": "disjoint_include_intervals",
        "probability_kind": "physical_no_fault_proxy",
        "interval_selection": {
            "schema": "nadit.physical_cost_intervals/1",
            "time_basis": "absolute_us",
            "include_intervals": [list(interval) for interval in selection],
            "source_horizon_us": activity.duration_us,
            "selected_duration_us": sum(end - start for start, end in selection),
            "selected_event_indices": sorted(
                {entry["source_event_id"] for entry in index_map}
            ),
            "event_index_map": index_map,
            "source_activity_sha256": source_hash,
            "selected_activity_sha256": selected_hash,
            "exposure_partition": "original_activity_interval_intersections_with_merged_include_intervals",
            "discrete_channels": "complete_action_ownership",
            "noise_profile": "independent_pauli_rates_v1",
            "full_trace_probability_equivalence_claimed": False,
        },
        "participant_selection": {
            "schema": "nadit.physical_cost_participants/1",
            "owner_id": owner_id,
            "atom_ids": sorted(selected),
            "atom_ids_sha256": canonical_hash({"atom_ids": sorted(selected)}),
            "selection_basis": "actual_activity_affected_atoms_not_source_owner",
            "source_activity_sha256": source_hash,
            "selected_activity_sha256": selected_hash,
            "source_atom_count": len(activity.per_atom),
            "cross_participant_cz": "rejected_in_complete_source_trace",
            "global_noise_coverage_claimed": False,
            "independent_factory_success_claimed": False,
            "other_participant_waiting_excluded": False,
            "events": [
                {
                    "selected_event_id": entry["selected_event_id"],
                    "source_event_id": entry["source_event_id"],
                    "source_atom_ids": list(
                        activity.events[entry["source_event_id"]].atoms
                    ),
                    "selected_atom_ids": list(
                        projected.events[entry["selected_event_id"]].atoms
                    ),
                    "source_ids": list(
                        projected.events[entry["selected_event_id"]].source_ids
                    ),
                }
                for entry in index_map
            ],
        },
    }
