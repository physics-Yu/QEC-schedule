"""Distance-specific object inputs retain original costs and probability ports."""

from pathlib import Path

import pytest

from modules.codes.rotated_surface.fast_factory import required_variants
from modules.codes.rotated_surface.object_factory import (
    FactoryObjectCatalog,
    FactoryObjectProfile,
)
from modules.logical_compiler.examples.object_cases import forbid_atom_work


@pytest.mark.parametrize("distance", [5, 7])
def test_recorded_distance_catalog_covers_recipe_and_accepted_only_growth(distance):
    with forbid_atom_work() as counters:
        catalog = FactoryObjectCatalog.load(distance=distance)
        layout = catalog.layout(2)
        profile = FactoryObjectProfile(catalog, layout)
        assert catalog.distance == distance
        assert catalog.code_id == f"rotated_surface_d{distance}"
        assert catalog.protocol["injection_rounds"] == 3
        assert catalog.protocol["growth_rounds"] == distance
        assert catalog.raw_probability == 50957 / 65536
        for component, roles in required_variants(distance):
            entry = profile.lookup(
                component,
                tuple(layout.factories[0].bindings[r] for r in roles),
                parameters={"injection_rounds": 3}
                if component == "raw_t_postselection"
                else {},
            )
            assert entry.stages
        raw = catalog.entries["raw_t_postselection"]
        growth = catalog.entries["raw_t_postselection/canonicalize"]
        assert sum(p.results for p in raw.stages) == 24
        assert sum(p.results for p in growth.stages) == distance * (distance**2 - 1)
        assert growth.action_duration_us == pytest.approx(
            {5: 4352.087452349999, 7: 6649.722433289999}[distance]
        )
        rounds = {}
        for stage in raw.stages:
            if stage.results:
                key = stage.name.split("/")[0]
                rounds[key] = rounds.get(key, 0) + stage.results
        assert rounds == {"round[0]": 8, "round[1]": 8, "round[2]": 8}
        s = catalog.entries["logical_s"]
        assert (
            s.primitive_counts["cz"]
            == 4 * distance * (distance - 1) + (distance - 1) ** 2
        )
        spec = profile.describe(
            "logical_mz", (layout.factories[0].bindings["R"],), budget=layout.budget
        )
        assert spec.code_id == f"rotated_surface_d{distance}"
    assert not any(counters.values())


@pytest.mark.parametrize("distance", [5, 7])
def test_larger_distance_plus_port_is_original_binary_reference_without_frame(distance):
    catalog = FactoryObjectCatalog.load(distance=distance)
    port = FactoryObjectProfile(catalog, catalog.layout(1)).preparation_port(
        "initialize_plus"
    )
    assert port.outcome("accepted").probability == 1
    assert dict(port.outcome("accepted").values) == {"accepted": True}
    assert port.to_dict()["model"]["kind"] == "ideal_exact"
    assert port.to_dict() == catalog.document["plus_port"]


def test_default_d3_inputs_and_local_byproduct_port_are_unchanged():
    catalog = FactoryObjectCatalog.load()
    assert catalog.distance == 3
    assert catalog.fingerprint == (
        "959321fe6566d9434bb2e514ec27b1131843b4cfa4fec62f4e856514f2ce6599"
    )
    port = FactoryObjectProfile(catalog, catalog.layout(1)).preparation_port(
        "initialize_plus"
    )
    assert len([o for o in port.outcomes if o.probability]) == 16
    assert dict(port.outcome("accepted_0").values)["byproduct_class"] == 0


def test_distance_mismatch_and_uncovered_distance_are_explicit_errors():
    with pytest.raises(ValueError, match="DISTANCE"):
        FactoryObjectCatalog.load(distance=13)
    with pytest.raises(ValueError, match="DISTANCE"):
        FactoryObjectCatalog.load(distance=True)
    catalog = FactoryObjectCatalog.load(distance=5)
    with pytest.raises(ValueError, match="DISTANCE"):
        catalog.layout(1, distance=7)
    path = Path(__file__).parents[1] / "configs" / "object_d5_reference.json"
    assert FactoryObjectCatalog.load(path).distance == 5
    with pytest.raises(ValueError, match="DISTANCE"):
        FactoryObjectCatalog.load(path, distance=7)


def test_target_distance_cannot_silently_change_in_probability_identity():
    document = FactoryObjectCatalog.load(distance=5).document
    document["protocol"]["target_distance"] = 7
    with pytest.raises(ValueError, match="PROTOCOL"):
        FactoryObjectCatalog(document)


@pytest.mark.parametrize(
    "distance,growth_us,s_us",
    [
        (9, 9267.357414210772, 9157.923395780059),
        (11, 12204.992395146495, 15601.455922462277),
    ],
)
def test_large_recorded_objects_keep_exact_probability_and_complete_growth(
    distance, growth_us, s_us
):
    with forbid_atom_work() as counters:
        catalog = FactoryObjectCatalog.load(distance=distance)
        layout = catalog.layout(4, placement="grid", columns=2)
        profile = FactoryObjectProfile(catalog, layout)
        for component, roles in required_variants(distance):
            assert profile.lookup(
                component,
                tuple(layout.factories[0].bindings[r] for r in roles),
                parameters={"injection_rounds": 3}
                if component == "raw_t_postselection"
                else {},
            ).stages
        assert len(catalog.entries) == 10
        assert catalog.raw_probability == 0.7791076605693193
        estimator = catalog.raw_port.to_dict()["model"]["evidence"]["estimator"]
        assert estimator["kind"] == "exact" and estimator["shots"] is None
        assert estimator["probability"] == catalog.raw_probability
        assert catalog.entries["logical_s"].action_duration_us == pytest.approx(s_us)
        raw = catalog.entries["raw_t_postselection"]
        growth = catalog.entries["raw_t_postselection/canonicalize"]
        assert raw.action_duration_us == pytest.approx(4601.898463625351)
        assert sum(p.results for p in raw.stages) == 24
        assert growth.action_duration_us == pytest.approx(growth_us)
        assert sum(p.results for p in growth.stages) == distance * (distance**2 - 1)
        assert growth.claim["growth_rounds"] == distance
        assert layout.budget["atom_count_estimate"] == 4 * 6 * (2 * distance**2 - 1)
        assert not any(counters.values())


@pytest.mark.parametrize("change", ["probability", "method", "shots"])
def test_exact_probability_evidence_cannot_silently_change(change):
    document = FactoryObjectCatalog.load(distance=9).document
    estimator = document["raw_port"]["model"]["evidence"]["estimator"]
    estimator[change] = {"probability": 0.9, "method": "unsupported", "shots": 100}[
        change
    ]
    with pytest.raises(ValueError, match="PROVENANCE"):
        FactoryObjectCatalog(document)


@pytest.mark.parametrize(
    "distance,fingerprint",
    [
        (3, "959321fe6566d9434bb2e514ec27b1131843b4cfa4fec62f4e856514f2ce6599"),
        (5, "287b37a2affc8c119e7086049aa4a401d5569d942d60ee5352bffcd7070e4d20"),
        (7, "c3a5dae62c849dcb72abfe28788f1c92d61bcabfeffec2a7badd7aa3d31e2b30"),
    ],
)
def test_existing_numeric_catalogs_are_unchanged(distance, fingerprint):
    assert FactoryObjectCatalog.load(distance=distance).fingerprint == fingerprint


def test_offline_projection_rejects_modified_or_mixed_saved_steps():
    from copy import deepcopy
    from hashlib import sha256

    from experiments.msd.extract_d9_d11_objects import _hash, _project

    template = {
        "source_qasm": "saved",
        "source_sha256": sha256(b"saved").hexdigest(),
        "description": {"component_id": "logical_x"},
        "timing_profile": [
            {
                "load_us": 10,
                "store_us": 10,
                "move_us_per_um": 1,
                "move_profile": "linear",
            },
            1,
            5,
            0.5,
            100,
            0,
        ],
        "dag": {"nodes": [{"name": "rx"}]},
        "relative_program": {
            "steps": [{"actions": [{"kind": "Rotation", "duration_us": 1}]}]
        },
    }
    template["content_sha256"] = _hash(template)
    with forbid_atom_work():
        assert _project(template, 9)["phases"] == [[1, "gate", "local", 0, None]]
        bad = deepcopy(template)
        bad["relative_program"]["steps"][0]["actions"][0]["duration_us"] = 2
        with pytest.raises(ValueError, match="HASH_MISMATCH"):
            _project(bad, 9)
        bad["relative_program"]["steps"][0]["actions"].append(
            {"kind": "Move", "duration_us": 2}
        )
        bad.pop("content_sha256")
        bad["content_sha256"] = _hash(bad)
        with pytest.raises(ValueError, match="MIXED_STEP"):
            _project(bad, 9)
