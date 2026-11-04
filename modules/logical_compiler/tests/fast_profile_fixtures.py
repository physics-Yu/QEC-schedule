"""Independent small-profile checks, without frozen experiment files or atom work."""

from copy import deepcopy


def _document():
    """Invent finite timings and a correlated table solely for these unit tests."""
    raw = {
        "component_id": "raw_t_postselection",
        "geometry": [],
        "selection_class": None,
        "waveform_key": "review-raw",
        "phase_durations_us": [2, 3],
        "measurement_phases": [[0, 10]] * 24,
        "result_ready_offsets_us": [12] * 24,
        "cost_segments": [
            {
                "start_offset_us": 0,
                "end_offset_us": 2,
                "category": "measurement",
                "resource": "camera",
            },
            {
                "start_offset_us": 2,
                "end_offset_us": 5,
                "category": "movement",
                "resource": "aod",
            },
        ],
        "primitive_counts": {"Measure": 24},
        "events": [],
        "busy": [],
        "claim": {
            "parallel_mode": "independent_aods_lockstep",
            "result_count": 24,
            "spaces": [[0, 0, 60, 110, "fixture_return_and_readout"]],
            "shared": None,
        },
    }
    entries = {"raw": raw}
    for preparation in ("initialize_plus", "raw_t_postselection"):
        for value in range(16):
            item = deepcopy(raw)
            item.update(
                component_id=preparation + "/canonicalize",
                selection_class=value,
                waveform_key="review-local",
                phase_durations_us=[] if value == 0 else [1],
                measurement_phases=[],
                result_ready_offsets_us=[],
                cost_segments=[],
                primitive_counts={} if value == 0 else {"Rotation": 1},
                claim={
                    "parallel_mode": "local_parallel",
                    "result_count": 0,
                    "spaces": [],
                    "shared": None,
                },
            )
            entries[f"{preparation}:{value}"] = item
    port = {
        "schema": "nadit.event_probability/1",
        "port_id": "rotated_surface_d3.raw_t_postselection.canonical_preparation",
        "protocol_id": "rotated_surface_d3.raw_t_postselection",
        "protocol_version": "2",
        "model": {
            "id": "review",
            "kind": "test_fixture",
            "assumptions": ["Synthetic unit-test distribution"],
            "parameters": {
                "distance": 3,
                "round_policy": "distance",
                "total_rounds": 3,
                "extra_rounds": 2,
            },
            "evidence": {},
        },
        "outcomes": [
            {
                "key": "keep",
                "probability": 0.75,
                "values": {"accepted": True, "byproduct_class": 5},
                "branch_id": "keep",
            },
            {
                "key": "reject",
                "probability": 0.25,
                "values": {"accepted": False, "byproduct_class": None},
                "branch_id": "retry",
            },
        ],
        "branches": [
            {"key": "keep", "transition": "deliver", "steps": []},
            {"key": "retry", "transition": "retry", "steps": []},
        ],
    }
    return {
        "schema": "nadit.fast_surface_factory_profile/2",
        "code_id": "rotated_surface_d3",
        "distance": 3,
        "raw_t_protocol": {
            "protocol_version": "2",
            "round_policy": "distance",
            "distance": 3,
            "total_rounds": 3,
            "extra_rounds": 2,
        },
        "entries": entries,
        "noise_params": {},
        "control": {"aod": {"min_spacing": 1}, "readout": {"channel": "camera"}},
        "provenance": {"kind": "test_fixture"},
        "preparation_ports": {"raw_t_postselection": port},
        "consumption_port": {},
    }


def _complete_document():
    """Cover the real recipe with synthetic finite timing, never real calibration."""
    document = _document()
    entries = document["entries"]
    for component in (
        "initialize_plus",
        "logical_mx",
        "logical_mz",
        "logical_s",
        "logical_x",
    ):
        item = deepcopy(entries["raw"])
        item["component_id"] = component
        item["waveform_key"] = "review-" + component
        if component in ("logical_s", "logical_x"):
            item.update(
                measurement_phases=[],
                result_ready_offsets_us=[],
                primitive_counts={"Rotation": 1},
            )
            item["claim"]["result_count"] = 0
        entries[component] = item
    for delta in (-500, -400, -300, -200, -100, 100, 200, 300, 400, 500):
        item = deepcopy(entries["logical_x"])
        item.update(
            component_id="transversal_cnot",
            geometry=[delta, 0],
            waveform_key=f"review-cx-{delta}",
            primitive_counts={"CZ": 9},
        )
        entries[f"cx:{delta}"] = item
    document["noise_params"] = {
        "exposure": {"slm_t2_us": None, "aod_t2_us": None, "include_transport": True},
        "transport": {"slm_loss_per_us": 0, "aod_loss_per_us": 0},
    }
    initial = deepcopy(document["preparation_ports"]["raw_t_postselection"])
    initial["port_id"] = "review.initial"
    initial["outcomes"] = [dict(initial["outcomes"][0], probability=1)]
    document["preparation_ports"]["initialize_plus"] = initial
    from modules.codes.rotated_surface_d3.protocols.cost_proxy import (
        ROUTING_REFERENCE,
        _routing_port,
    )
    from modules.codes.rotated_surface_d3.protocols.fast_calibration import (
        _compact_port,
    )

    document["consumption_port"] = _compact_port(
        _routing_port(
            {
                "routing_reference": ROUTING_REFERENCE,
                "actual_quality_status": "unsupported",
                "actual_quality_source_port_sha256": "0" * 64,
            }
        ).to_dict()
    )
    return document
