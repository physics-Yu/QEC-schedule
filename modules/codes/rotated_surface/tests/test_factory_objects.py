"""Complete factory object costs use recorded inputs, never compiler fallbacks."""

from itertools import pairwise

import pytest

from modules.codes.rotated_surface.fast_factory import required_variants
from modules.codes.rotated_surface.object_factory import (
    FactoryObjectCatalog,
    FactoryObjectProfile,
)
from modules.logical_compiler.examples.factory_objects import run_factory_objects
from modules.logical_compiler.examples.object_cases import forbid_atom_work


def test_catalog_covers_real_recipe_and_preserves_three_round_injection():
    with forbid_atom_work():
        catalog = FactoryObjectCatalog.load()
        layout = catalog.layout(1)
        profile = FactoryObjectProfile(catalog, layout)
        for component, roles in required_variants(3):
            entry = profile.lookup(
                component,
                tuple(layout.factories[0].bindings[r] for r in roles),
                parameters={"injection_rounds": 3}
                if component == "raw_t_postselection"
                else {},
            )
            assert entry.stages
        raw = profile.lookup(
            "raw_t_postselection",
            (layout.factories[0].bindings["R"],),
            parameters={"injection_rounds": 3},
        )
        assert raw.primitive_counts["measure"] == 24
        assert raw.primitive_counts["reset"] == 33
        assert sum(p.results for p in raw.stages) == 24
        assert catalog.protocol["growth_rounds"] == 0
        s = profile.lookup("logical_s", (layout.factories[0].bindings["W1"],))
        assert s.primitive_counts["cz"] == 28 and s.primitive_counts["measure"] == 8
        se = profile.lookup("se_round", (layout.factories[0].bindings["R"],))
        assert se.primitive_counts["reset"] == 8 and se.primitive_counts["measure"] == 8


def test_factory_results_use_precomputed_probabilities_and_real_gate_recipe():
    with forbid_atom_work() as counters:
        catalog = FactoryObjectCatalog.load()
        result = run_factory_objects(catalog, factories=1, seed=0, cycles=2)
    assert result["case"]["status"] == "complete"
    summary = result["summary"]
    assert summary["accepted_outputs"] == 2
    assert summary["raw_rejections"] > 0
    assert summary["raw_acceptance_parameter"] == 51235 / 65536
    assert summary["raw_probability_policy"] == "precomputed_component_reference"
    assert summary["counts"]["transversal_cnot"] == 59 * summary["batches"]
    assert summary["counts"]["logical_s"] > 0
    assert summary["steady_state_throughput"] is None
    assert summary["actual_output_LER"] is None
    assert not any(counters.values())
    assert all(
        p["model"]["kind"] != "test_fixture"
        for p in result["case"]["probability_models"].values()
    )


def test_n_and_seeds_reuse_objects_and_single_aod_never_overlaps():
    catalog = FactoryObjectCatalog.load()
    before = {k: id(v) for k, v in catalog.entries.items()}
    with forbid_atom_work():
        for count, seed in ((1, 1), (2, 0)):
            result = run_factory_objects(catalog, factories=count, seed=seed, cycles=1)
            assert result["summary"]["accepted_outputs"] == count
            for wave in result["case"]["execution"]["waves"]:
                intervals = sorted(
                    (p["start_us"], p["end_us"])
                    for p in wave["stage_schedule"]
                    if "aod:transport" in p["resources"]
                )
                assert all(a[1] <= b[0] for a, b in pairwise(intervals))
    assert before == {k: id(v) for k, v in catalog.entries.items()}


def test_uncovered_distance_or_changed_protocol_is_an_error():
    catalog = FactoryObjectCatalog.load()
    with pytest.raises(ValueError, match="DISTANCE"):
        catalog.layout(1, distance=5)
    layout = catalog.layout(1)
    with pytest.raises(ValueError, match="PROTOCOL"):
        FactoryObjectProfile(catalog, layout).lookup(
            "raw_t_postselection",
            (layout.factories[0].bindings["R"],),
            parameters={"injection_rounds": 2},
        )


def test_probability_inputs_cannot_silently_change_without_new_provenance():
    catalog = FactoryObjectCatalog.load()
    document = catalog.document
    document["noise_params"]["readout_flip"] = 0.02
    with pytest.raises(ValueError, match="PROVENANCE"):
        FactoryObjectCatalog(document)


def test_complete_catalog_keeps_vertical_shared_readout_coordination():
    from modules.codes.contracts.factory_recipe import ComponentCall
    from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
    from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
    from modules.logical_compiler.src.scheduling import (
        ComponentNode,
        ComponentScheduler,
    )

    catalog = FactoryObjectCatalog.load()
    layout = catalog.layout(2)
    execution = ProfileExecutionKernel(FactoryObjectProfile(catalog, layout), layout)
    scheduler = ComponentScheduler()
    call = ComponentCall("read", "logical_mz", ("R",))
    requests = tuple(
        ExecutionRequest(f"factory{i}/read", None, call, (f"factory{i}/R",))
        for i in range(2)
    )
    scheduler.add(
        *(
            ComponentNode(
                r.invocation_id, execution.describe(None, call, r.participant_blocks)
            )
            for r in requests
        )
    )
    admission = scheduler.admit(0, snapshot_id=execution.snapshot_id)
    execution.execute(admission, requests)
    assert execution.clock_us == 520
    assert all(
        len(s["members"]) == 2
        for s in execution.snapshot()["waves"][0]["stage_schedule"]
    )


def _run_declared_wave(catalog, layout, component, placements):
    from modules.codes.contracts.factory_recipe import ComponentCall
    from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
    from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
    from modules.logical_compiler.src.scheduling import (
        ComponentNode,
        ComponentScheduler,
    )

    profile = FactoryObjectProfile(catalog, layout)
    execution = ProfileExecutionKernel(profile, layout)
    scheduler = ComponentScheduler()
    requests = []
    for i, (factory, roles) in enumerate(placements):
        call = ComponentCall(
            f"call{i}",
            component,
            tuple(roles),
            parameters=(("injection_rounds", 3),)
            if component == "raw_t_postselection"
            else (),
        )
        request = ExecutionRequest(
            f"factory{factory}/call{i}",
            None,
            call,
            tuple(f"factory{factory}/{role}" for role in roles),
        )
        requests.append(request)
        scheduler.add(
            ComponentNode(
                request.invocation_id,
                execution.describe(None, call, request.participant_blocks),
            )
        )
    admission = scheduler.admit(0, snapshot_id=execution.snapshot_id)
    assert admission is not None
    selected = tuple(r for r in requests if r.invocation_id in admission.node_ids)
    execution.execute(admission, selected)
    return execution.snapshot()["waves"][0]


def test_rectangular_raw_grid_shares_one_rigid_command():
    with forbid_atom_work() as counters:
        catalog = FactoryObjectCatalog.load()
        layout = catalog.layout(2)
        placements = [(f, (r,)) for f in range(2) for r in ("W2", "W3", "W4", "W5")]
        wave = _run_declared_wave(catalog, layout, "raw_t_postselection", placements)
        slowest = catalog.bind_cost(
            "raw_t_postselection", (layout.factories[1].bindings["W2"],)
        )
    assert wave["end_us"] == pytest.approx(slowest.action_duration_us)
    assert all(len(s["members"]) == 8 for s in wave["stage_schedule"])
    assert not wave["stage_waits"]
    assert not any(counters.values())


def test_shifted_equal_displacement_cnot_shares_one_rigid_command():
    catalog = FactoryObjectCatalog.load()
    layout = catalog.layout(2)
    wave = _run_declared_wave(
        catalog, layout, "transversal_cnot", [(0, ("W2", "W1")), (1, ("W3", "W2"))]
    )
    assert wave["end_us"] == 240.5
    assert all(len(s["members"]) == 2 for s in wave["stage_schedule"])
    assert not wave["stage_waits"]


def test_different_signed_cnot_displacements_still_compete_for_single_aod():
    catalog = FactoryObjectCatalog.load()
    wave = _run_declared_wave(
        catalog,
        catalog.layout(2),
        "transversal_cnot",
        [(0, ("W2", "W1")), (1, ("W3", "W1"))],
    )
    stages = [s for s in wave["stage_schedule"] if "aod:transport" in s["resources"]]
    assert all(len(s["members"]) == 1 for s in stages)
    assert wave["end_us"] > 440.5
    intervals = sorted((s["start_us"], s["end_us"]) for s in stages)
    assert all(a[1] <= b[0] for a, b in pairwise(intervals))


def _translated_factory(layout, *, dx=0, dy=0):
    from dataclasses import replace

    from nadit_physical_compiler.device import Position

    shifted = replace(
        layout.factories[1],
        patches=tuple(
            replace(p, origin=Position(p.origin.x + dx, p.origin.y + dy))
            for p in layout.factories[1].patches
        ),
    )
    return replace(layout, factories=(layout.factories[0], shifted))


def test_partially_offset_columns_are_not_assumed_compatible():
    catalog = FactoryObjectCatalog.load()
    layout = _translated_factory(catalog.layout(2), dx=20)
    wave = _run_declared_wave(catalog, layout, "logical_mz", [(0, ("R",)), (1, ("R",))])
    assert wave["end_us"] == 840
    assert all(len(s["members"]) == 1 for s in wave["stage_schedule"])


def test_overlapping_home_envelopes_are_not_admitted_together():
    catalog = FactoryObjectCatalog.load()
    layout = _translated_factory(catalog.layout(2), dy=100)
    wave = _run_declared_wave(catalog, layout, "logical_mz", [(0, ("R",)), (1, ("R",))])
    assert len(wave["invocations"]) == 1
    assert wave["end_us"] == 320


def test_named_async_strategy_preserves_existing_complete_factory_trace():
    catalog = FactoryObjectCatalog.load()
    original = run_factory_objects(catalog, factories=1, seed=0, cycles=1)
    named = run_factory_objects(
        catalog, distance=3, factories=1, seed=0, cycles=1, strategy="asynchronous"
    )
    assert named["case"] == original["case"]
    assert named["summary"]["strategy"]["id"] == "asynchronous/v1"
    with pytest.raises(ValueError, match="UNKNOWN_FACTORY_STRATEGY"):
        run_factory_objects(catalog, factories=1, seed=0, strategy="unknown")


def test_async_entry_does_not_require_n2_in_config(tmp_path):
    from modules.logical_compiler.examples.factory_objects import run_acceptance

    config = {
        "schema": "nadit.factory_objects_local/1",
        "distance": 3,
        "factory_counts": [3],
        "seeds": [0],
        "cycles_per_factory": 1,
        "input_z_error": 0.01,
        "strategy": "asynchronous",
        "raw_probability_policy": "precomputed_component_reference",
        "raw_attempt_limit": 32,
        "batch_attempt_limit": 16,
        "case_timeout_seconds": 20,
    }
    result = run_acceptance(config, tmp_path)
    assert result["cases"][0]["accepted_outputs"] == 3
    assert result["cases"][0]["factories"] == 3
    assert result["strategy"]["id"] == "asynchronous/v1"
    assert result["reuse"]["physical_compile_attempts"] == 0
    assert (tmp_path / "d3-n3-seed0.json").exists()


@pytest.mark.parametrize("distance", [5, 7, 9, 11])
def test_full_distance_factory_grows_only_accepted_raw_states(distance):
    with forbid_atom_work() as counters:
        catalog = FactoryObjectCatalog.load(distance=distance)
        result = run_factory_objects(catalog, factories=1, seed=0, cycles=1)
    summary, case = result["summary"], result["case"]
    assert summary["distance"] == distance
    assert summary["allocated_atoms"] == 6 * (2 * distance**2 - 1)
    assert summary["growth_rounds_per_accepted_input"] == distance
    calls = {c["invocation_id"]: c for c in case["calls"]}
    raw_events = [
        e
        for e in case["events"]
        if e["occurrence"]["port_id"] == catalog.raw_port.port_id
    ]
    assert len(raw_events) == summary["raw_attempts"]
    assert summary["raw_rejections"] > 0
    for event in raw_events:
        occurrence = event["occurrence"]
        correction_id = (
            f"{occurrence['invocation_id']}"
            f"/attempt[{occurrence['attempt']}]/canonicalize"
        )
        assert (correction_id in calls) == event["values"]["accepted"]
        if correction_id in calls:
            assert calls[correction_id]["start_us"] >= event["released_at_us"]
    accepted = summary["raw_attempts"] - summary["raw_rejections"]
    assert accepted == 15 * summary["batches"]
    assert summary["growth_syndrome_rounds"] == distance * accepted
    assert summary["syndrome_rounds_in_components"] == (
        3 * summary["raw_attempts"]
        + distance * accepted
        + summary["counts"]["initialize_plus"]
        + summary["counts"]["logical_s"]
    )
    assert summary["actual_output_LER"] is None
    assert not any(counters.values())


@pytest.mark.parametrize(
    "placement,columns,bounds,origins,readout_us",
    [
        (
            "vertical",
            None,
            [0, -360, 560, 0],
            [(0, -60), (0, -160), (0, -260), (0, -360)],
            920,
        ),
        (
            "horizontal",
            None,
            [0, -60, 2360, 0],
            [(0, -60), (600, -60), (1200, -60), (1800, -60)],
            320,
        ),
        (
            "grid",
            2,
            [0, -160, 1160, 0],
            [(0, -60), (600, -60), (0, -160), (600, -160)],
            520,
        ),
    ],
)
def test_whole_factory_layout_binds_costs_without_changing_internal_geometry(
    placement, columns, bounds, origins, readout_us
):
    with forbid_atom_work() as guards:
        catalog = FactoryObjectCatalog.load()
        identities = {key: id(entry) for key, entry in catalog.entries.items()}
        layout = catalog.layout(4, placement=placement, columns=columns)
        assert layout.budget["storage_bounds_um"] == bounds
        assert layout.budget["atom_count_estimate"] == 408
        for index, factory in enumerate(layout.factories):
            assert factory.factory_id == f"factory{index}"
            x, y = origins[index]
            assert [(p.origin.x, p.origin.y) for p in factory.patches] == [
                (x + 100 * j, y) for j in range(6)
            ]
        readout = _run_declared_wave(
            catalog, layout, "logical_mz", [(i, ("R",)) for i in range(4)]
        )
        assert readout["end_us"] == readout_us
        assert all(len(s["members"]) == 4 for s in readout["stage_schedule"])
        cnot = _run_declared_wave(
            catalog, layout, "transversal_cnot", [(i, ("W2", "W1")) for i in range(4)]
        )
        assert cnot["end_us"] == 240.5
        assert all(len(s["members"]) == 4 for s in cnot["stage_schedule"])
        assert identities == {key: id(entry) for key, entry in catalog.entries.items()}
        assert not any(guards.values())


def test_layout_degeneracy_and_default_vertical_coordinates():
    catalog = FactoryObjectCatalog.load()
    assert catalog.layout(4) == catalog.layout(4, placement="vertical")
    one = catalog.layout(1)
    for kind, columns in (("horizontal", None), ("grid", 2)):
        other = catalog.layout(1, placement=kind, columns=columns)
        assert other.factories == one.factories
        assert (
            other.budget["placement_fingerprint"] == one.budget["placement_fingerprint"]
        )
    for kind, columns in (("vertical", 1), ("horizontal", 2)):
        grid = catalog.layout(2, placement="grid", columns=columns)
        named = catalog.layout(2, placement=kind)
        assert grid.factories == named.factories
        assert (
            grid.budget["placement_fingerprint"]
            == named.budget["placement_fingerprint"]
        )


@pytest.mark.parametrize(
    "kind,columns",
    [
        ("unknown", None),
        ("grid", None),
        ("grid", 0),
        ("grid", True),
        ("vertical", 2),
        ("horizontal", 2),
    ],
)
def test_invalid_layout_configuration_is_explicit_error(kind, columns):
    with pytest.raises(ValueError, match="PLACEMENT|COLUMNS"):
        FactoryObjectCatalog.load().layout(4, placement=kind, columns=columns)


def test_complete_small_factories_share_catalog_across_layouts_and_policies():
    import json

    catalog = FactoryObjectCatalog.load()
    before = {key: id(entry) for key, entry in catalog.entries.items()}
    reference = {}
    with forbid_atom_work() as guards:
        for count in (1, 2):
            for kind, columns in (
                ("vertical", None),
                ("horizontal", None),
                ("grid", 2),
            ):
                for strategy in ("asynchronous", "synchronous"):
                    result = run_factory_objects(
                        catalog,
                        factories=count,
                        seed=1,
                        cycles=1,
                        production_basis="production_rounds",
                        strategy=strategy,
                        placement=kind,
                        columns=columns,
                    )
                    case = result["case"]
                    signature = {
                        json.dumps(e["occurrence"], sort_keys=True): (
                            e["outcome_key"],
                            e["values"],
                            e["port_sha256"],
                        )
                        for e in case["events"]
                    }
                    assert signature == reference.setdefault(count, signature)
                    if count == 1:
                        assert result["summary"]["makespan_us"] == reference.setdefault(
                            "n1_time", result["summary"]["makespan_us"]
                        )
                    assert result["summary"]["batches"] == count
                    timing = result["summary"]["timing_breakdown"]
                    motion = timing["command_microseconds"]
                    assert motion["readout_transport"] + motion[
                        "gate_transport"
                    ] == pytest.approx(
                        result["summary"]["accounting"]["category_busy_us"]["movement"]
                    )
                    assert (
                        result["summary"]["sum_block_footprint_um2"] == 6 * count * 3600
                    )
        assert before == {key: id(entry) for key, entry in catalog.entries.items()}
        assert not any(guards.values())
