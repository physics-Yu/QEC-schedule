"""Independent small-profile checks, without frozen experiment files or atom work."""

from copy import deepcopy
from dataclasses import replace

import pytest
from nadit_physical_compiler import activity
from nadit_physical_compiler.atom_ir import AtomProgram

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.rotated_surface_d3.components.canonicalization import (
    PreparationCanonicalization,
)
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    BoundFactoryCall,
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.fast_cost import (
    FastCostCall,
    evaluate_factory_cost,
)
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    FastProfile,
    make_fast_layout,
)
from modules.logical_compiler.examples.factory_fast import run_fast
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.array_ledger import build_array_ledger
from modules.logical_compiler.src.protocols.events import EventDependency, EventJournal
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler
from modules.logical_compiler.tests.test_array_ledger import example


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
            "spaces": [],
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


def _kernel():
    profile = FastProfile.from_dict(_document())
    return ProfileExecutionKernel(profile, make_fast_layout(profile, 2))


def _wave(kernel, *, selections=(None, None)):
    scheduler = ComponentScheduler()
    call = ComponentCall("raw", "raw_t_postselection", ("work",))
    requests = tuple(
        ExecutionRequest(
            f"factory{i}/raw/attempt[0]",
            None,
            call,
            (f"factory{i}/W2",),
            selection=selection,
        )
        for i, selection in enumerate(selections)
    )
    scheduler.add(
        *(
            ComponentNode(
                request.invocation_id,
                kernel.describe(None, call, request.participant_blocks),
            )
            for request in requests
        )
    )
    return scheduler.admit(kernel.clock_us, snapshot_id=kernel.snapshot_id), requests


@pytest.fixture
def no_physical(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Fast execution attempted physical binding or atom compilation")

    for target, names in (
        (PhysicalContext, ("__init__", "invoke", "invoke_batch", "finalize")),
        (SurfaceFactoryBackend, ("bind_call", "bind_canonicalization")),
        (BoundFactoryCall, ("expand",)),
        (PreparationCanonicalization, ("compile",)),
        (AtomProgram, ("__init__",)),
        (activity, ("derive_activity",)),
    ):
        for name in names:
            monkeypatch.setattr(target, name, forbidden)


def _events(seed):
    kernel = _kernel()
    admission, requests = _wave(kernel)
    receipts = kernel.execute(admission, requests)
    journal = EventJournal("review-fixed-case", seed)
    port = kernel.profile.preparation_port("raw_t_postselection")
    observations = []
    for request in requests:
        source = receipts[request.invocation_id][0]
        observation = journal.sample(
            port,
            invocation_id=request.invocation_id.split("/attempt", 1)[0],
            attempt=0,
            dependencies=(EventDependency.from_receipt(source),),
            context=kernel,
        )
        observations.append(observation)
    return kernel, journal, port, observations


def test_estimated_events_wait_for_readout_without_entering_physical_code(no_physical):
    kernel, journal, _, observations = _events(0)
    assert kernel.clock_us == 12
    assert [item.released_at_us for item in observations] == [12, 12]
    assert [
        item.action_end_us
        for item in (
            kernel.source(name)
            for name in ("factory0/raw/attempt[0]", "factory1/raw/attempt[0]")
        )
    ] == [5, 5]
    assert kernel.finalize() is None
    assert all(carrier.atom_ids == () for carrier in kernel.carriers.values())
    assert kernel.snapshot()["physical_validation"] == "not_run"
    assert kernel.snapshot()["accounting"]["work_by_category_us"] == {
        "measurement": 4,
        "movement": 6,
    }
    assert kernel.snapshot()["accounting"]["global_busy_union_us"] == 5
    assert kernel.snapshot()["accounting"]["explicit_global_wait_us"] == 7
    dependencies = [event["dependencies"][0] for event in journal.snapshot()["events"]]
    assert [item["results"] for item in dependencies] == [
        [{"result_id": i, "available_at_us": 12} for i in range(24)],
        [{"result_id": i, "available_at_us": 12} for i in range(24, 48)],
    ]
    assert all(
        item["result_identity_kind"] == "logical_interface" for item in dependencies
    )
    assert all(
        "value" not in result for item in dependencies for result in item["results"]
    )


def test_seed_replay_preserves_joint_rejection_and_class_not_independent_draws(
    no_physical,
):
    outcomes = set()
    for seed in range(16):
        _, journal, _, observations = _events(seed)
        _, replay, _, _ = _events(seed)
        assert journal.snapshot() == replay.snapshot()
        for observation in observations:
            pair = (
                observation.values["accepted"],
                observation.values["byproduct_class"],
            )
            assert pair in {(True, 5), (False, None)}
            outcomes.add(pair)
    assert outcomes == {(True, 5), (False, None)}


def test_bad_second_member_leaves_clock_receipts_and_result_allocator_unchanged(
    no_physical,
):
    kernel = _kernel()
    admission, requests = _wave(kernel, selections=(None, {"unexpected": True}))
    before = kernel.snapshot()
    with pytest.raises(ValueError, match="UNEXPECTED_FAST_CORRECTION_SELECTION"):
        kernel.execute(admission, requests)
    assert kernel.snapshot() == before
    assert not kernel.used and kernel.clock_us == 0
    admission, requests = _wave(kernel)
    receipts = kernel.execute(admission, requests)
    assert receipts[requests[0].invocation_id][0].result_availability == tuple(
        (i, 12) for i in range(24)
    )


def test_missing_calibration_cannot_fall_back_to_physical_compilation(no_physical):
    kernel = _kernel()
    before = kernel.snapshot()
    with pytest.raises(ValueError, match="UNCALIBRATED_FAST_COMPONENT"):
        kernel.describe(
            None, ComponentCall("missing", "logical_s", ("work",)), ("factory0/W2",)
        )
    with pytest.raises(ValueError, match="UNCALIBRATED_FAST_EVENT"):
        kernel.profile.consumption_port()
    assert kernel.snapshot() == before


def test_joint_correction_uses_ready_event_and_rejects_foreign_source(no_physical):
    # Find either accepted event among a fixed short list; no result is forced.
    candidates = [_events(seed) for seed in range(4)]
    kernel, _, port, observations = next(
        item for item in candidates if item[3][0].values["accepted"]
    )
    source = kernel.source("factory0/raw/attempt[0]")
    observation = observations[0]
    plan = kernel.correction_plan(
        None,
        "raw_t_postselection",
        source,
        port,
        observation,
        event_id="factory0/raw/event[0]",
    )
    assert plan.bound_factory is None
    assert plan.selection == {"accepted": True, "byproduct_class": 5}
    with pytest.raises(ValueError, match="INVALID_ESTIMATE_CORRECTION_EVENT"):
        kernel.correction_plan(
            None,
            "raw_t_postselection",
            source,
            port,
            replace(observation, dependencies=observations[1].dependencies),
            event_id="factory0/raw/event[0]",
        )


@pytest.mark.parametrize(
    "tamper", ["class", "result_id", "ready", "representation", "preparation"]
)
def test_correction_rejects_tampered_joint_values_or_dependency_evidence(
    no_physical, tamper
):
    kernel, _, port, observations = next(
        item
        for item in (_events(seed) for seed in range(4))
        if item[3][0].values["accepted"]
    )
    source, observation = kernel.source("factory0/raw/attempt[0]"), observations[0]
    preparation = "raw_t_postselection"
    dependency = observation.dependencies[0]
    if tamper == "class":
        observation = replace(
            observation, _values_json='{"accepted":true,"byproduct_class":4}'
        )
    elif tamper == "result_id":
        observation = replace(
            observation, dependencies=(replace(dependency, results=((99, 12),)),)
        )
    elif tamper == "ready":
        observation = replace(
            observation, dependencies=(replace(dependency, results=((0, 11),)),)
        )
    elif tamper == "representation":
        observation = replace(
            observation, dependencies=(replace(dependency, representation="physical"),)
        )
    else:
        preparation = "initialize_plus"
    before = kernel.snapshot()
    with pytest.raises(ValueError, match="INVALID_ESTIMATE_CORRECTION_EVENT"):
        kernel.correction_plan(
            None,
            preparation,
            source,
            port,
            observation,
            event_id="factory0/raw/event[0]",
        )
    assert kernel.snapshot() == before


def test_fixed_capacity_does_not_grow_with_factory_count():
    profile = FastProfile.from_dict(_document())
    small, large = make_fast_layout(profile, 1), make_fast_layout(profile, 16)
    for key, expected in (
        ("aod_count", 1),
        ("aod_max_rows", 4),
        ("aod_max_columns", 48),
        ("max_readout_atoms", 96),
    ):
        assert small.budget[key] == large.budget[key] == expected
    assert large.budget["shared_bounds_um"][2] > small.budget["shared_bounds_um"][2]
    assert large.budget["capacity_scales_with_factory_count"] is False


def test_logical_array_ledger_reports_unrun_physical_validation():
    case = example()
    case.pop("physical")
    case["execution_representation"] = "logical_estimate"
    case["resource_time_basis"] = "logical_estimated_us"
    ledger = build_array_ledger(case)
    assert ledger["physical_validation_ok"] is None
    assert ledger["physical_validation"] == "not_run"
    assert ledger["execution_representation"] == "logical_estimate"
    assert ledger["resource_time_basis"] == "logical_estimated_us"
    assert ledger["factory_acceptance_kind"] == "profile_estimate_no_fault_proxy"
    assert ledger["logical_success"] is None


def test_physical_array_metadata_and_missing_bundle_failure_remain_unchanged():
    case = example()
    ledger = build_array_ledger(case)
    assert ledger["schema"] == "nadit.factory_array_ledger/1"
    assert ledger["physical_validation_ok"] is True
    assert ledger["factory_acceptance_kind"] == "physical_no_fault_proxy"
    assert ledger["aod_ids"] == ["transport"]
    assert "execution_representation" not in ledger
    assert "physical_validation" not in ledger
    assert "resource_time_basis" not in ledger
    case.pop("physical")
    assert build_array_ledger(case)["physical_validation_ok"] is False


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


def test_full_real_recipe_retries_and_replays_using_only_logical_profiles(no_physical):
    profile = FastProfile.from_dict(_complete_document())
    first = run_fast(
        profile,
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
    )
    replay = run_fast(
        profile,
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
    )
    assert first.case == replay.case
    assert first.ledger == replay.ledger
    assert first.reports == replay.reports
    assert first.summary["execution_completed"] is True
    assert first.summary["outputs"] == 2
    assert first.case.get("physical") is None
    assert first.ledger["physical_validation_ok"] is None
    assert first.ledger["resources"]["schema"] == "nadit.resource_ledger/2"
    assert all(
        "atom_ids" not in carrier for carrier in first.ledger["resources"]["carriers"]
    )
    # The actual recipe adopts four and consumes eleven raw A resources per line.
    tokens = first.case["resources"]["tokens"]
    assert sum(token["status"] == "consumed" for token in tokens) == 30
    assert sum(token["status"] == "offered" for token in tokens) == 2
    assert first.ledger["counts"]["raw_rejections"] > 0
    assert (
        first.ledger["counts"]["raw_attempts"]
        == 30 + first.ledger["counts"]["raw_rejections"]
    )
    assert (
        sum(call["component_id"] == "transversal_cnot" for call in first.case["calls"])
        == 118
    )
    requested_s = sum(
        event["outcome_key"] == "m1"
        for event in first.case["events"]
        if event["occurrence"]["port_id"]
        == "rotated_surface_d3.t_consumption.reference_routing"
    )
    assert first.ledger["counts"]["s_calls"] == requested_s > 0
    assert all(
        event["dependencies"][0]["representation"] == "logical_estimate"
        for event in first.case["events"]
    )
    assert all(
        value == [1.0]
        for value in first.summary["factory_acceptance_probabilities"].values()
    )


def test_serial_admission_keeps_occurrence_randomness_and_protocol_calls(no_physical):
    profile = FastProfile.from_dict(_complete_document())
    parallel = run_fast(
        profile,
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
    )
    serial = run_fast(
        profile,
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
        max_parallel=1,
    )
    assert serial.summary["execution_completed"] is True
    assert serial.summary["parallel_wave_count"] == 0
    assert parallel.summary["parallel_wave_count"] > 0
    assert serial.summary["makespan_us"] > parallel.summary["makespan_us"]
    assert serial.ledger["counts"] == parallel.ledger["counts"]

    def decisions(run):
        return {
            (
                event["occurrence"]["invocation_id"],
                event["occurrence"]["attempt"],
                event["occurrence"]["port_id"],
            ): (event["outcome_key"], event["values"])
            for event in run.case["events"]
        }

    assert decisions(serial) == decisions(parallel)


def test_missing_final_measurement_profile_is_incomplete_not_a_success(no_physical):
    document = _complete_document()
    del document["entries"]["logical_mx"]
    result = run_fast(
        FastProfile.from_dict(document),
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
    )
    assert result.summary["execution_completed"] is False
    assert result.summary["outputs"] == 0
    assert result.summary["physical_validation_ok"] is None
    assert result.summary["factory_acceptance_probabilities"] == {
        "factory0": [],
        "factory1": [],
    }
    assert all(
        line["factory_final_accepted"] is None
        for line in result.ledger["lines"].values()
    )
    assert all(line["failure"] is not None for line in result.ledger["lines"].values())


@pytest.mark.parametrize("target", ["noise", "control", "claim", "event", "registry"])
def test_public_profile_mutation_cannot_change_hashed_cost_or_claims(target):
    document = _complete_document()
    document["entries"]["raw"]["events"] = [
        {"offset_us": 0, "duration_us": 1, "kind": "Reset", "log_survival": -0.1}
    ]
    profile = FastProfile.from_dict(document)
    layout = make_fast_layout(profile, 1)
    patch = layout.factories[0].bindings["W1"]
    call = FastCostCall("raw", "raw_t_postselection", (patch,), 0)
    before = profile.to_dict()
    fingerprint = profile.profile_sha256
    entry = profile.lookup("raw_t_postselection", (patch,))
    spec = profile.describe("raw_t_postselection", (patch,), budget=layout.budget)

    def cost():
        return evaluate_factory_cost(
            profile,
            [call],
            layout=layout,
            factory_id="factory0",
            window=(0, 10),
            raw_horizons=[],
        )

    expected = cost()
    try:
        if target == "noise":
            profile.noise_params["transport"]["slm_loss_per_us"] = 1
        elif target == "control":
            profile.control["aod"]["min_spacing"] = 1000
        elif target == "claim":
            entry.claim["result_count"] = 0
        elif target == "event":
            entry.events[0]["log_survival"] = -10
        else:
            profile.entries["raw"] = None
    except TypeError:
        pass  # Read-only views and independent copies are both valid public APIs.
    assert profile.to_dict() == before
    assert profile.profile_sha256 == fingerprint
    assert profile.noise_params == before["noise_params"]
    assert profile.control == before["control"]
    assert profile.entries["raw"] is not None
    assert (
        profile.describe("raw_t_postselection", (patch,), budget=layout.budget) == spec
    )
    assert cost() == expected
