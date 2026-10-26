"""Profile applicability follows placed geometry and real readout regions."""

from copy import deepcopy

import pytest
from nadit_physical_compiler.device import Position

from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.geometry import geometry
from modules.codes.rotated_surface_d3.protocols.fast_context import (
    capture_applicability,
    component_context,
)
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    CODE_ID,
    SCHEMA,
    raw_t_protocol_identity,
)
from modules.logical_compiler.src.estimation.calibration import (
    CalibrationCache,
    CalibrationMiss,
    CalibrationRecord,
)
from modules.logical_compiler.src.placement import (
    BlockPlacement,
    BlockSpec,
    ExplicitPlacement,
    PlacementRequest,
    place,
)

CONTROL = {
    "timing": {"load_us": 10, "store_us": 10},
    "local": {"duration_us": 1},
    "readout": {"channel": "camera", "latency_us": 0},
    "aod": {"motion": "flexible", "min_spacing": 5},
}
SOURCES = {"components/source.py": "source-hash"}
NOISE = {"readout_flip": 0.01}


def entry(component="logical_mz", *, envelope=None):
    measured = component == "logical_mz"
    return {
        "component_id": component,
        "geometry": [],
        "selection_class": None,
        "waveform_key": component + "/v1",
        "phase_durations_us": [1],
        "events": [],
        "claim": {
            "parallel_mode": "shared_aod_lockstep" if measured else "local_parallel",
            "result_count": 9 if measured else 0,
            "spaces": [envelope or [-5, -5, 70, 130 if measured else 65, "component"]],
        },
    }


def make_plan(origins):
    return place(
        PlacementRequest(
            blocks=tuple(
                BlockSpec(identity, CODE_ID, 3, *identity.rsplit("/", 1))
                for identity in origins
            ),
            geometries={CODE_ID: geometry(CODE_ID, 3)},
            positions={
                identity: BlockPlacement(Position(*origin))
                for identity, origin in origins.items()
            },
        ),
        ExplicitPlacement(),
    )


def profile():
    return {
        "schema": SCHEMA,
        "code_id": CODE_ID,
        "distance": 3,
        "raw_t_protocol": raw_t_protocol_identity(),
        "control": CONTROL,
        "noise_params": NOISE,
        "provenance": {"source_hashes": SOURCES},
    }


def source_case(origins=None, *, component="logical_mz", envelope=None):
    origins = origins or {"factory0/W1": (0, 0), "factory0/W2": (100, 0)}
    plan = make_plan(origins)
    bindings, atoms, nodes = [], [], []
    for index, (identity, origin) in enumerate(origins.items()):
        ids = list(range(index * 17, (index + 1) * 17))
        bindings.append(
            {
                "block_id": identity,
                "origin": {"x": origin[0], "y": origin[1]},
                "atom_ids": ids,
                "aod_id": "transport",
            }
        )
        for atom, (x, y) in zip(ids, definition(3).reference_coordinates, strict=True):
            atoms.append(
                {
                    "id": atom,
                    "position": {"x": origin[0] + 10 * x, "y": origin[1] + 10 * y},
                    "holder": {"kind": "slm", "site_id": f"home{atom}"},
                }
            )
        nodes.append({"id": f"call{index}", "spec": {"participant_blocks": [identity]}})
    zones = [
        {
            "id": "shared",
            "operations": ["rotate", "cz", "reset"],
            "bounds": {"x_min": -22, "y_min": -2, "x_max": 2000, "y_max": 80},
        },
        {
            "id": "readout",
            "operations": ["measure"],
            "bounds": {"x_min": -20, "y_min": 90, "x_max": 2000, "y_max": 130},
        },
    ]
    case = {
        "component_schedule": {"nodes": nodes},
        "physical": {
            "bindings": bindings,
            "entry_state": {"atoms": atoms},
            "device": {
                "zones": zones,
                "aods": [
                    {
                        "workspace": {
                            "x_min": -25,
                            "y_min": -5,
                            "x_max": 2100,
                            "y_max": 140,
                        }
                    }
                ],
            },
            "validation": {"ok": True},
        },
    }
    entries = {component: entry(component, envelope=envelope)}
    evidence = {component: {"source_invocations": ["call0"]}}
    return case, entries, evidence, plan


def captured(case, entries, evidence):
    return capture_applicability(case, entries, evidence, CONTROL, SOURCES, NOISE)


def budget():
    return {
        "shared_bounds_um": [-22, -2, 585, 80],
        "readout_bounds_um": [-20, 90, 585, 130],
        "aod_workspace_bounds_um": [-25, -5, 600, 140],
        "aod_max_columns": 48,
        "max_readout_atoms": 96,
    }


def test_real_source_regions_match_query_and_remote_added_factory_reuses_record():
    case, entries, evidence, original = source_case()
    document = captured(case, entries, evidence)
    records = [CalibrationRecord.from_dict(item) for item in document["records"]]
    cache = CalibrationCache(records)
    request = component_context(
        profile(), original, ("factory0/W1",), entries["logical_mz"], budget()
    )
    assert cache.require(request).payload == entries["logical_mz"]
    expanded = make_plan(
        {"factory0/W1": (0, 0), "factory0/W2": (100, 0), "factory1/W1": (1000, 0)}
    )
    distant = component_context(
        profile(),
        expanded,
        ("factory0/W1",),
        entries["logical_mz"],
        {
            **budget(),
            "shared_bounds_um": [-22, -2, 2000, 80],
            "readout_bounds_um": [-20, 90, 2000, 130],
            "aod_max_columns": 99,
        },
    )
    assert request.geometry_fingerprint != distant.geometry_fingerprint
    assert request.key == distant.key
    assert cache.require(distant) is records[0]


def test_common_upper_readout_does_not_reuse_horizontal_transport_context():
    case, entries, evidence, horizontal = source_case()
    cache = CalibrationCache(
        CalibrationRecord.from_dict(item)
        for item in captured(case, entries, evidence)["records"]
    )
    vertical = make_plan({"factory0/W1": (0, -60), "factory0/W2": (100, -60)})
    changed = component_context(
        profile(),
        vertical,
        ("factory0/W1",),
        entries["logical_mz"],
        {
            "shared_bounds_um": [-22, -80, 585, 0],
            "readout_bounds_um": [-20, 50, 585, 200],
            "aod_workspace_bounds_um": [-25, -100, 600, 220],
        },
    )
    assert isinstance(cache.lookup(changed), CalibrationMiss)
    assert (
        component_context(
            profile(), horizontal, ("factory0/W1",), entries["logical_mz"], budget()
        ).key
        != changed.key
    )


def test_capture_keeps_each_distinct_spectator_context_for_a_variant():
    case, entries, evidence, _ = source_case(
        {"factory0/W1": (0, 0), "factory0/W2": (100, 0), "factory1/W1": (1000, 0)},
        component="logical_x",
        envelope=[-5, -5, 170, 65, "addressing"],
    )
    evidence["logical_x"]["source_invocations"] = ["call0", "call2"]
    records = captured(case, entries, evidence)["records"]
    assert len(records) == 2
    keys = [record["context"]["key"] for record in records]
    assert sorted(len(key["spectators"]) for key in keys) == [0, 1]
    assert all(record["payload"] == entries["logical_x"] for record in records)


@pytest.mark.parametrize(
    "tamper",
    [
        "unregistered_atom",
        "missing_atom",
        "wrong_position",
        "non_slm",
        "unvalidated",
        "missing_world",
    ],
)
def test_capture_rejects_unrepresented_or_nonreturn_source_world(tamper):
    case, entries, evidence, _ = source_case()
    physical = case["physical"]
    atoms = physical["entry_state"]["atoms"]
    if tamper == "unregistered_atom":
        atoms.append({**deepcopy(atoms[0]), "id": 999})
    elif tamper == "missing_atom":
        atoms.pop()
    elif tamper == "wrong_position":
        atoms[0]["position"]["x"] += 1
    elif tamper == "non_slm":
        atoms[0]["holder"]["kind"] = "aod"
    elif tamper == "unvalidated":
        physical["validation"]["ok"] = False
    else:
        physical.pop("entry_state")
    with pytest.raises(ValueError, match="CALIBRATION"):
        captured(case, entries, evidence)


def test_correction_supplement_uses_declared_local_context_without_readout():
    case, _, _, plan = source_case()
    name = "raw_t_postselection/canonicalize:0"
    correction = entry("raw_t_postselection/canonicalize")
    correction["selection_class"] = 0
    correction["phase_durations_us"] = []
    result = captured(
        case, {name: correction}, {name: {"kind": "offline_finite_class_supplement"}}
    )
    record = CalibrationRecord.from_dict(result["records"][0])
    requested = component_context(profile(), plan, ("factory0/W1",), correction, {})
    assert record.context.key == requested.key
    assert requested.key.to_dict()["device"]["readout"] is None
    assert requested.key.to_dict()["device"]["transport"] is None


def test_required_device_regions_cannot_be_omitted_or_invented():
    _, entries, _, plan = source_case()
    with pytest.raises(ValueError, match="DEVICE_REGION"):
        component_context(profile(), plan, ("factory0/W1",), entries["logical_mz"], {})


def test_component_source_and_payload_changes_invalidate_context():
    _, entries, _, plan = source_case()
    base = component_context(
        profile(), plan, ("factory0/W1",), entries["logical_mz"], budget()
    )
    changed = profile()
    changed["provenance"] = {"source_hashes": {"components/source.py": "new-source"}}
    assert (
        base.key
        != component_context(
            changed, plan, ("factory0/W1",), entries["logical_mz"], budget()
        ).key
    )
    modified = deepcopy(entries["logical_mz"])
    modified["phase_durations_us"] = [2]
    assert (
        base.key
        != component_context(profile(), plan, ("factory0/W1",), modified, budget()).key
    )


def test_fixture_model_cannot_seed_a_production_calibration_cache():
    _, entries, _, plan = source_case()
    real = profile()
    fixture = deepcopy(real)
    fixture["provenance"]["kind"] = "test_fixture"
    synthetic = component_context(
        fixture, plan, ("factory0/W1",), entries["logical_mz"], budget()
    )
    actual = component_context(
        real, plan, ("factory0/W1",), entries["logical_mz"], budget()
    )
    assert synthetic.key != actual.key
    cache = CalibrationCache(
        [CalibrationRecord(synthetic, entries["logical_mz"], {"kind": "test_fixture"})]
    )
    assert isinstance(cache.lookup(actual), CalibrationMiss)


@pytest.mark.parametrize("slot,role", [(5, 0), (0, 17), (0, -1), (True, 0)])
def test_activity_outside_the_declared_influence_cannot_be_captured(slot, role):
    case, entries, evidence, _ = source_case(component="logical_x")
    entries["logical_x"]["busy"] = [[slot, role, 0, 1, "GlobalRY", "slm"]]
    with pytest.raises(ValueError, match="CALIBRATION_ACTIVITY"):
        captured(case, entries, evidence)


def test_covered_pulse_activity_keeps_its_declared_local_scope():
    case, entries, evidence, _ = source_case(component="logical_x")
    entries["logical_x"]["busy"] = [[0, 0, 0, 1, "GlobalRY", "slm"]]
    record = captured(case, entries, evidence)["records"][0]
    assert record["context"]["key"]["spectator_scope"] == "local"
