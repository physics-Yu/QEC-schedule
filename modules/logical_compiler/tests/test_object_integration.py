"""Object stages use the original execution boundary and factory ownership flow."""

from dataclasses import replace

import pytest
from nadit_physical_compiler.device import Position

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.rotated_surface.object_readout import (
    SurfaceReadoutCatalog,
    SurfaceReadoutProfile,
)
from modules.logical_compiler.examples.object_fixtures import (
    RAW,
    FixtureCatalog,
    run_retry_case,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


def readout_run(catalog, *, count=2, distance=3, shifted=False):
    layout = catalog.layout(distance, count)
    if shifted:
        factories = list(layout.factories)
        f = factories[1]
        factories[1] = replace(
            f,
            patches=tuple(
                replace(p, origin=Position(p.origin.x + 20, p.origin.y))
                for p in f.patches
            ),
        )
        layout = replace(layout, factories=tuple(factories))
    profile = SurfaceReadoutProfile(catalog, layout)
    execution = ProfileExecutionKernel(profile, layout)
    scheduler = ComponentScheduler()
    call = ComponentCall("mz", "logical_mz", ("W2",))
    requests = tuple(
        ExecutionRequest(f.factory_id + "/mz", None, call, (f.bindings["W2"].block_id,))
        for f in layout.factories
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
    receipts = execution.execute(admission, requests)
    return execution.snapshot(), receipts, layout


def test_real_readout_objects_match_the_independently_derived_vertical_schedule():
    result, receipts, layout = readout_run(SurfaceReadoutCatalog())
    steps = result["waves"][0]["stage_schedule"]
    assert [(s["start_us"], s["end_us"]) for s in steps] == [
        (0, 10),
        (10, 210),
        (210, 310),
        (310, 510),
        (510, 520),
    ]
    assert all(r[0].action_end_us == 520 for r in receipts.values())
    assert all(len(r[0].result_availability) == 9 for r in receipts.values())
    assert all(t == 310 for r in receipts.values() for _, t in r[0].result_availability)
    assert layout.budget["atom_count_estimate"] == 204


def test_column_mismatch_serializes_single_aod_instead_of_using_maximum():
    result, _, _ = readout_run(SurfaceReadoutCatalog(), shifted=True)
    assert result["waves"][0]["end_us"] == 840  # 320 + 520, not max(320, 520).
    assert result["waves"][0]["stage_waits"][0]["end_us"] == 320


def test_catalog_reused_for_new_n_and_distance_combinations(monkeypatch):
    import nadit_physical_compiler.compiler as compiler

    import modules.codes._support.atom_template as atoms

    def forbidden(*args, **kwargs):
        pytest.fail("Physical compilation/atom expansion entered an object combination")

    monkeypatch.setattr(compiler, "compile_physical", forbidden)
    monkeypatch.setattr(atoms, "compile_template", forbidden)
    monkeypatch.setattr(atoms.BoundAtomComponent, "expand", forbidden)
    catalog = SurfaceReadoutCatalog()
    identities = {d: id(p) for d, p in catalog.entries.items()}
    for distance in (3, 5, 7):
        for count in (1, 2, 4, 8):
            result, _, _ = readout_run(catalog, distance=distance, count=count)
            assert result["physical_validation"] == "not_run"
    assert catalog.template_builds == 3
    assert identities == {d: id(p) for d, p in catalog.entries.items()}
    with pytest.raises(ValueError, match="UNPREPARED_COMPONENT"):
        catalog.lookup(3, "raw_t_postselection")


def test_postselection_retry_is_local_and_next_cycle_really_resets():
    catalog = FixtureCatalog()
    case = run_retry_case(catalog)
    assert case["status"] == "complete"
    raw = [c for c in case["calls"] if c["component_id"] == RAW]
    assert (
        len(raw) == 10
    )  # Two roles * two factories * two cycles + two rejected attempts.
    assert (
        sum(
            "factory0/" in c["invocation_id"] and "/initial/W2/" in c["invocation_id"]
            for c in raw
        )
        == 4
    )
    times = {}
    for factory, row in case["factories"].items():
        times[factory] = next(
            m["at_us"]
            for m in row["milestones"]
            if m["kind"] == "initial_preparations_ready"
        )
        assert len(row["production_cycles"]) == 2
    assert times["factory1"] < times["factory0"]
    outputs = [
        t for t in case["resources"]["tokens"] if t["token_id"].endswith("/output")
    ]
    assert len(outputs) == 4 and all(t["status"] == "consumed" for t in outputs)
    for wave in case["component_schedule"]["admissions"]:
        assert len({n["spec"]["component_id"] for n in wave["nodes"]}) == 1
    reset_members = sum(
        len(s["members"])
        for w in case["execution"]["waves"]
        for s in w["stage_schedule"]
        if s["phase"] == "reset"
    )
    assert reset_members == 10


def test_final_rejection_restarts_work_batch_and_seed_retry_counts_reuse_objects():
    catalog = FixtureCatalog()
    identities = tuple(map(id, catalog.entries.values()))
    case = run_retry_case(catalog, cycles=1, reject_attempts=0, reject_final_once=True)
    assert case["status"] == "complete"
    assert len([c for c in case["calls"] if c["component_id"] == RAW]) == 8
    for seed, count in ((7, 1), (23, 4)):
        assert (
            run_retry_case(
                catalog, factories=count, seed=seed, reject_attempts=2, cycles=1
            )["status"]
            == "complete"
        )
    assert catalog.template_builds == 3
    assert tuple(map(id, catalog.entries.values())) == identities


def test_runtime_timeout_is_an_error_not_an_accepted_partial_case():
    with pytest.raises(TimeoutError, match="factory_runtime.*budget"):
        run_retry_case(FixtureCatalog(), timeout_seconds=0)
