"""Hand-verifiable shared-wave accounting, not quantum-quality evidence."""

from copy import deepcopy
from dataclasses import asdict, replace

import pytest
from nadit_physical_compiler.atom_ir import (
    AtomProgram,
    AtomStep,
    Load,
    Move,
    Rotation,
    Store,
    Wait,
)
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import (
    encode_device,
    encode_layout,
    encode_program,
)
from nadit_physical_compiler.state import AODGrid, AODLine

from experiments.msd import production_metrics
from experiments.msd.production_metrics import summarize_production
from experiments.msd.standard import ExperimentSpec, build_world
from modules.logical_compiler.src.protocols.resources import ResourceLedger


def fixture(*, moving=False):
    """Real standard geometry with hand-built actions; no compiler validation."""
    world = build_world(ExperimentSpec(3, 1))
    first, second = world.patches[:2]
    atoms = (first.binding.atom_ids[0], second.binding.atom_ids[0])
    if moving:
        atom = world.state.atom(atoms[0])
        x, y = atom.position.x, atom.position.y
        grid = AODGrid("transport", (AODLine(0, y),), (AODLine(0, x),))
        moved = AODGrid("transport", grid.rows, (AODLine(0, x + 1),))
        program = AtomProgram(
            (
                AtomStep((Load(grid, ((atom.id, 0, 0),), duration_us=10),)),
                AtomStep(
                    (Move(moved, ((atom.id, Position(x + 1, y)),), duration_us=2),)
                ),
                AtomStep((Move(grid, ((atom.id, Position(x, y)),), duration_us=2),)),
                AtomStep(
                    (
                        Store(
                            AODGrid("transport"),
                            ((atom.id, atom.holder.site_id),),
                            duration_us=10,
                        ),
                    )
                ),
            )
        )
    else:
        program = AtomProgram(
            (
                AtomStep((Rotation("local", atoms, "X", 1.0, duration_us=4),)),
                AtomStep((Wait(duration_us=2),)),
                AtomStep((Rotation("local", atoms, "X", 1.0, duration_us=2),)),
            )
        )
    trace = {
        "schema": "nadit.result/2",
        "device": encode_device(world.device),
        "entry_state": encode_layout(world.state),
        "exit_state": encode_layout(replay(program, world.state, world.device)),
        "program": encode_program(program),
        "measurements": [],
        "dag": {"nodes": []},
        # Synthetic admission metadata exercises the cost contract. These hand-
        # built fixtures are not evidence of a real component's valid lowering.
        "validation": {
            "ok": True,
            "checks": ["pulse", "timing"],
            "semantic": "checked",
            "scope": "synthetic_contract_fixture_not_external_validation",
        },
    }
    trace_hash = canonical_hash(trace)
    waves, calls = [], []
    for index, start in enumerate((0,) if moving else (0, 12)):
        end = start + program.duration_us
        ids = [f"wave{index}/member0", f"wave{index}/member1"]
        waves.append(
            {
                "batch_id": f"wave{index}",
                "start_us": start,
                "end_us": end,
                "invocations": ids,
            }
        )
        calls.extend(
            {
                "invocation_id": identity,
                "start_us": start,
                "action_end_us": end,
                "component_id": "test_fixture.rotation",
                "joint_trace_sha256": trace_hash,
                "cost_segments": [
                    {"category": "movement", "start_us": start, "end_us": 1_000_000}
                ],
            }
            for identity in ids
        )
    outputs, tokens, audit = [], [], []
    if not moving:
        ledger = ResourceLedger()
        ledger.register_logical_carrier(
            first.binding.block_id, code_id="rotated_surface_d3", distance=3
        )
        for cycle, ready in enumerate((8, 20)):
            token_id = f"factory0/cycle[{cycle}]/output"
            quality = {"model": "test_fixture"}
            owner, consumer = f"factory0/cycle[{cycle}]", f"fixture-consumer/{cycle}"
            carrier = ledger.begin_preparation(
                first.binding.block_id, owner=owner, at_us=12 * cycle
            )
            ledger.offer(
                token_id,
                carrier_id=carrier.carrier_id,
                epoch=carrier.epoch,
                owner=owner,
                resource_kind="A",
                producer="test_fixture",
                ready_at_us=ready,
                exit_at_us=ready,
                canonicalization="canonical",
                quality=quality,
            )
            ledger.reserve(
                token_id,
                consumer=consumer,
                at_us=ready,
                expected_code="rotated_surface_d3",
                expected_distance=3,
                expected_kind="A",
                expected_canonicalization="canonical",
            )
            ledger.consume(
                token_id, consumer=consumer, at_us=ready + 1, safe_exit_at_us=ready + 2
            )
            ledger.complete_use(carrier.carrier_id, owner=consumer, at_us=ready + 2)
            outputs.append(
                {
                    "cycle": cycle,
                    "batch": 0,
                    "token_id": token_id,
                    "carrier_id": first.binding.block_id,
                    "epoch": cycle + 1,
                    "code": "rotated_surface_d3",
                    "distance": 3,
                    "quality": quality,
                    "ready_at_us": ready,
                    "deliverable_at_us": ready + 1,
                    "consumed_at_us": ready + 1,
                    "released_at_us": ready + 2,
                    "delivery": {
                        "token_id": token_id,
                        "carrier_id": first.binding.block_id,
                        "consumer": consumer,
                        "deliverable_at_us": ready + 1,
                        "consumed_at_us": ready + 1,
                        "released_at_us": ready + 2,
                        "evidence": {"kind": "test_fixture"},
                    },
                }
            )
        tokens, audit = ledger.snapshot()["tokens"], ledger.snapshot()["audit"]
    milestones = [
        {"kind": "line_state_changed", "state": state, "at_us": at}
        for at, state in (
            (0, "running"),
            (8, "waiting_resources"),
            (12, "running"),
            (20, "waiting_peers"),
            (24, "complete"),
        )
    ]
    case = {
        "case_id": "hand-accounting",
        "status": "complete",
        "duration_us": 24,
        "factories": {
            "factory0": {
                "status": "complete",
                "failure": None,
                "outputs": outputs,
                "milestones": milestones,
                "completed_at_us": 24,
            }
        },
        "resources": {"tokens": tokens, "audit": audit},
        "execution": {
            "waves": waves,
            "calls": calls,
            "waits": []
            if moving
            else [{"start_us": 8, "end_us": 12}, {"start_us": 20, "end_us": 24}],
        },
        "calls": calls,
        "events": [],
    }
    return case, world, {trace_hash: trace}


def test_shared_members_and_reused_trace_do_not_duplicate_atom_time(monkeypatch):
    case, world, traces = fixture()
    original = production_metrics.derive_activity
    derivations = []

    def counted(document):
        derivations.append(document)
        return original(document)

    monkeypatch.setattr(production_metrics, "derive_activity", counted)
    result = summarize_production(case, world, traces, stop_us=24)
    assert len(derivations) == result["unique_traces_loaded"] == 1
    assert result["wave_instances_in_window"] == 2
    assert result["configured_atoms"] == 102
    assert result["configured_atom_time_us"] == 102 * 24
    assert result["busy_atom_time_us"] == 24
    assert result["idle_atom_time_us"] == 102 * 24 - 24
    assert result["between_wave_idle_atom_us"] == 102 * 8
    assert result["resource_busy_union_us"] == {"channel:local": 12}
    assert result["exposure_by_action"]["Rotation"] == {
        "action_count": 4,
        "atom_events": 8,
        "overlapping_actions": 4,
        "atom_us": 24,
    }
    assert result["accepted_outputs"] == result["delivered_outputs"] == 2
    assert result["startup_deliverable_latency_us"] == 9
    assert result["peak_owned_atoms"] == 17
    assert result["owned_atom_time_us"] == 17 * 20
    assert result["global_wait_union_us"] == 8
    assert result["factory_wait_by_state_us"] == {
        "waiting_resources": 4,
        "waiting_peers": 4,
    }
    assert result["actual_output_error"] is None
    assert result["all_loaded_traces_validated"] is True


def test_window_clips_exposure_waits_and_counts_boundary_events_once():
    case, world, traces = fixture()
    result = summarize_production(case, world, traces, warmup_us=8, stop_us=20)
    assert result["actual_observation_us"] == 12
    assert result["accepted_outputs"] == result["delivered_outputs"] == 1
    assert len(result["outputs"]) == 2
    assert result["outputs"][1]["accepted_in_window"] is False
    assert result["busy_atom_time_us"] == 12
    assert result["configured_atom_time_us"] == 102 * 12
    assert result["idle_atom_time_us"] == 102 * 12 - 12
    assert result["resource_busy_union_us"] == {"channel:local": 6}
    assert result["owned_atom_time_us"] == 17 * 10
    assert result["global_wait_union_us"] == 4
    assert result["delivered_outputs_per_second"] == pytest.approx(1e6 / 12)


def wait_case():
    return {
        "duration_us": 20,
        "factories": {
            "factory0": {
                "completed_at_us": 20,
                "milestones": [
                    {"kind": "line_state_changed", "state": state, "at_us": time}
                    for time, state in (
                        (0, "waiting_supply"),
                        (4, "waiting_buffer"),
                        (10, "waiting_supply"),
                        (18, "complete"),
                    )
                ],
            }
        },
        "execution": {"waits": [{"start_us": 0, "end_us": 18}]},
        "wait_instrumentation": {
            "schema": "nadit.resource_wait_instrumentation/1",
            "resource_wait_kinds": ["supply", "buffer"],
        },
    }


def test_wait_categories_clip_independently_to_the_observation_window():
    result = production_metrics._waiting(wait_case(), 2, 14)
    assert result["factory_wait_by_state_us"] == {
        "waiting_supply": 6,
        "waiting_buffer": 6,
    }
    assert result["buffer_wait_us"] == 6
    assert result["buffer_wait_status"] == "recorded"
    assert result["global_wait_union_us"] == 12


def test_no_buffer_wait_is_zero_only_when_instrumentation_is_declared():
    case = wait_case()
    current = production_metrics._waiting(case, 0, 3)
    assert current["buffer_wait_us"] == 0
    assert current["buffer_wait_status"] == "recorded"
    del case["wait_instrumentation"]
    historical = production_metrics._waiting(case, 0, 3)
    assert historical["buffer_wait_us"] is None
    assert historical["buffer_wait_status"] == "not_separately_instrumented"


def test_window_cut_inside_operation_has_exact_duration_and_onset_counts():
    case, world, traces = fixture()
    result = summarize_production(case, world, traces, warmup_us=1, stop_us=3)
    exposure = result["exposure_by_action"]["Rotation"]
    assert exposure["action_count"] == exposure["atom_events"] == 0
    assert exposure["overlapping_actions"] == 1
    assert exposure["atom_us"] == 4
    assert result["resource_busy_union_us"] == {"channel:local": 2}
    assert result["idle_atom_time_us"] == 100 * 2


def test_full_native_moves_have_distance_but_partial_moves_do_not_invent_paths():
    case, world, traces = fixture(moving=True)
    full = summarize_production(case, world, traces, warmup_us=10, stop_us=14)
    assert full["movement_distance_atom_um"] == 2
    assert full["transport_elapsed_us"] == 4
    assert full["busy_atom_time_us"] == 4
    assert full["actual_visited_bounds_um"] is not None
    partial = summarize_production(case, world, traces, warmup_us=11, stop_us=13)
    assert partial["movement_distance_atom_um"] is None
    assert partial["actual_visited_bounds_um"] is None
    assert partial["partial_move_actions"] == 2
    assert partial["transport_elapsed_us"] == 2
    assert partial["exposure_by_action"]["Move"]["atom_us"] == 2
    assert partial["idle_atom_time_us"] == 101 * 2


def test_early_failure_is_visible_and_not_reported_as_low_steady_rate():
    case, world, traces = fixture()
    case["status"] = "partial_failure"
    case["factories"]["factory0"]["failure"] = {
        "code": "production_cycle_budget_exhausted",
        "at_us": 24,
    }
    result = summarize_production(case, world, traces, stop_us=100)
    assert result["actual_observation_us"] == 24
    assert result["requested_window_complete"] is False
    assert result["window_status"] == "failed"
    assert result["delivered_outputs"] == 2
    assert result["delivered_outputs_per_second"] is None
    assert len(result["retry_exhaustions"]) == 1


@pytest.mark.parametrize("problem", ("outputs", "waves", "world", "nonhome", "hash"))
def test_duplicate_or_incompatible_evidence_is_rejected(problem):
    case, world, traces = fixture()
    key = next(iter(traces))
    if problem == "outputs":
        case["factories"]["factory0"]["outputs"].append(
            deepcopy(case["factories"]["factory0"]["outputs"][0])
        )
    elif problem == "waves":
        case["execution"]["waves"].append(deepcopy(case["execution"]["waves"][0]))
    elif problem == "world":
        world = replace(world, device=replace(world.device, name="another device"))
    else:
        trace = deepcopy(traces[key])
        if problem == "nonhome":
            trace["exit_state"]["atoms"][0]["position"]["x"] += 1
            replacement = canonical_hash(trace)
            traces = {replacement: trace}
            for call in case["execution"]["calls"]:
                call["joint_trace_sha256"] = replacement
        else:
            trace["validation"]["scope"] = "changed"
            traces[key] = trace
    with pytest.raises(ValueError):
        summarize_production(case, world, traces, stop_us=24)


@pytest.mark.parametrize("problem", ("failed", "missing_semantics", "missing_timing"))
def test_saved_semantic_admission_is_required_before_activity_derivation(
    problem, monkeypatch
):
    case, world, traces = fixture()
    trace = deepcopy(next(iter(traces.values())))
    if problem == "failed":
        trace["validation"]["ok"] = False
    elif problem == "missing_semantics":
        trace["validation"].pop("semantic")
    else:
        trace["validation"]["checks"] = ["pulse"]
    key = canonical_hash(trace)
    for call in case["execution"]["calls"]:
        call["joint_trace_sha256"] = key
    monkeypatch.setattr(
        production_metrics,
        "derive_activity",
        lambda *args: pytest.fail("unvalidated activity derivation"),
    )
    with pytest.raises(ValueError, match="semantically validated"):
        summarize_production(case, world, {key: trace}, stop_us=24)


@pytest.mark.parametrize(
    "problem",
    (
        "status",
        "consumer",
        "consumed_time",
        "receipt",
        "missing_consume",
        "duplicate_consume",
        "missing_release",
        "duplicate_release",
        "release_owner",
        "release_epoch",
        "release_time",
        "early_reuse",
        "same_time_reuse",
    ),
)
def test_delivered_outputs_require_matching_consumption_and_release_audit(problem):
    case, world, traces = fixture()
    output = case["factories"]["factory0"]["outputs"][0]
    token = next(
        row
        for row in case["resources"]["tokens"]
        if row["token_id"] == output["token_id"]
    )
    audit = case["resources"]["audit"]
    consume = next(
        row
        for row in audit
        if row["action"] == "consume" and row["token_id"] == output["token_id"]
    )
    release = next(
        row
        for row in audit
        if row["action"] == "complete_use" and row["epoch"] == output["epoch"]
    )
    if problem == "status":
        token["status"] = "offered"
    elif problem == "consumer":
        token["consumer"] = "another-consumer"
    elif problem == "consumed_time":
        token["consumed_at_us"] += 0.5
    elif problem == "receipt":
        output["delivery"]["released_at_us"] += 0.5
    elif problem == "missing_consume":
        audit.remove(consume)
    elif problem == "duplicate_consume":
        audit.append(deepcopy(consume))
    elif problem == "missing_release":
        audit.remove(release)
    elif problem == "duplicate_release":
        audit.append(deepcopy(release))
    elif problem == "release_owner":
        release["owner"] = "another-consumer"
    elif problem == "release_epoch":
        release["epoch"] = 7
    elif problem == "release_time":
        release["at_us"] += 0.5
    elif problem == "early_reuse":
        next(
            row
            for row in audit
            if row["action"] == "begin_preparation" and row["epoch"] == 2
        )["at_us"] = 9.5
    else:
        later = next(
            row
            for row in audit
            if row["action"] == "begin_preparation" and row["epoch"] == 2
        )
        later["at_us"] = release["at_us"]
        audit.remove(later)
        audit.insert(audit.index(release), later)
    with pytest.raises(ValueError, match="OUTPUT_DELIVERY"):
        summarize_production(case, world, traces, stop_us=24)


def test_ready_only_partial_output_does_not_claim_delivery_or_release():
    case, world, traces = fixture()
    output = case["factories"]["factory0"]["outputs"][-1]
    token = next(
        row
        for row in case["resources"]["tokens"]
        if row["token_id"] == output["token_id"]
    )
    output.update(
        deliverable_at_us=None, consumed_at_us=None, released_at_us=None, delivery=None
    )
    token.update(status="offered", consumer=None, consumed_at_us=None, usage_kind=None)
    case["resources"]["audit"] = [
        event
        for event in case["resources"]["audit"]
        if not (
            event["action"] in ("reserve", "consume")
            and event.get("token_id") == output["token_id"]
        )
        and not (
            event["action"] == "complete_use" and event["epoch"] == output["epoch"]
        )
    ]
    result = summarize_production(case, world, traces, stop_us=24)
    assert result["accepted_outputs"] == 2
    assert result["delivered_outputs"] == 1
    assert result["outputs"][-1]["delivery_lifecycle_verified"] is False
    assert result["outputs"][-1]["released_at_us"] is None


def test_output_lifecycle_indexes_do_not_scan_the_whole_audit_per_output():
    class CountedAudit(list):
        scans = 0

        def __iter__(self):
            self.scans += 1
            return super().__iter__()

    case, world, traces = fixture()
    audit = CountedAudit(case["resources"]["audit"])
    case["resources"]["audit"] = audit
    result = summarize_production(case, world, traces, stop_us=24)
    assert result["delivered_outputs"] == 2
    assert audit.scans <= 2  # Delivery indexing plus independent ownership accounting.


def stateful_fixture():
    """One explicit native block displacement and a later unchanged-world wave."""
    from nadit_physical_compiler.compiler import CompilationResult, CompiledOperation
    from nadit_physical_compiler.contracts import GateLayer
    from nadit_physical_compiler.physical_ir import PhysicalDAG
    from nadit_physical_compiler.serialization import encode_dag
    from nadit_physical_compiler.validation import validate_result

    from experiments.msd.joint_transition import apply_joint_transition
    from experiments.msd.standard import add_buffer_sites
    from modules.codes.rotated_surface.translation import BlockTranslationComponent

    world, slots = add_buffer_sites(
        build_world(ExperimentSpec(3, 1)), {"parking": Position(-100, -60)}
    )
    patch = world.patches[0]
    origin, homes = slots["parking"]
    entry = replace(world.state, qubit_to_atom=patch.binding.atom_ids)
    node, goal, binding = BlockTranslationComponent(3).native_goal(
        world.device,
        world=entry,
        binding=patch.binding,
        target_origin=origin,
        target_home_sites=homes,
        operation_id=0,
    )
    xs = sorted({entry.atom(atom).position.x for atom in patch.binding.atom_ids})
    ys = sorted({entry.atom(atom).position.y for atom in patch.binding.atom_ids})
    grid = AODGrid(
        "transport",
        tuple(AODLine(i, y) for i, y in enumerate(ys)),
        tuple(AODLine(i, x) for i, x in enumerate(xs)),
    )
    moved = AODGrid(
        "transport", grid.rows, tuple(AODLine(i, x - 100) for i, x in enumerate(xs))
    )
    program = AtomProgram(
        (
            AtomStep(
                (
                    Load(
                        grid,
                        tuple(
                            (
                                atom,
                                ys.index(entry.atom(atom).position.y),
                                xs.index(entry.atom(atom).position.x),
                            )
                            for atom in patch.binding.atom_ids
                        ),
                        duration_us=10,
                        source_ids=(0,),
                    ),
                )
            ),
            AtomStep(
                (
                    Move(
                        moved,
                        tuple(
                            (atom, world.device.site(home).position)
                            for atom, home in zip(
                                patch.binding.atom_ids, homes, strict=True
                            )
                        ),
                        duration_us=world.device.timing.move_duration(100),
                        source_ids=(0,),
                    ),
                )
            ),
            AtomStep(
                (
                    Store(
                        AODGrid("transport"),
                        tuple(zip(patch.binding.atom_ids, homes, strict=True)),
                        duration_us=10,
                        source_ids=(0,),
                    ),
                )
            ),
        )
    )
    dag = PhysicalDAG(len(patch.binding.atom_ids), 0, (node,), ())
    compiled = CompilationResult(
        program,
        replay(program, entry, world.device),
        (CompiledOperation(0, "emitted", 0, program.duration_us),),
        (),
        (GateLayer((0,)),),
        (goal,),
    )
    validation = validate_result(
        compiled, entry_state=entry, device=world.device, dag=dag
    )
    assert validation["ok"], validation
    trace = {
        "schema": "nadit.result/2",
        "device": encode_device(world.device),
        "entry_state": encode_layout(entry),
        "exit_state": encode_layout(compiled.exit_state),
        "program": encode_program(program),
        "dag": encode_dag(dag),
        "transport_goals": [asdict(goal)],
        "measurements": [],
        "validation": validation,
    }
    key = canonical_hash(trace)
    member = "block_translation:" + patch.binding.block_id
    bindings = {
        member: {
            "distance": 3,
            "entry": asdict(patch.binding),
            "exit": asdict(binding),
            "home_sites": list(homes),
        }
    }
    action = {
        "schema": "nadit.joint_actions/1",
        "validation_ok": True,
        "trace_sha256": key,
        "members": {member: {}},
        "state_transition": {
            "schema": "nadit.joint_world_transition/1",
            "entry_state_sha256": canonical_hash(trace["entry_state"]),
            "exit_state_sha256": canonical_hash(trace["exit_state"]),
            "bindings": bindings,
        },
    }
    after = apply_joint_transition(world, action, trace)
    stop = program.duration_us + 9
    later = {
        **deepcopy(trace),
        "entry_state": encode_layout(after.state),
        "exit_state": encode_layout(after.state),
        "program": encode_program(AtomProgram((AtomStep((Wait(duration_us=4),)),))),
        "dag": {"nodes": []},
        "transport_goals": [],
    }
    later_key = canonical_hash(later)
    transition = {
        "joint_group_key": "fixture",
        "trace_sha256": key,
        "entry_world_sha256": canonical_hash(world.document()),
        "exit_world_sha256": canonical_hash(after.document()),
        "bindings": bindings,
    }
    calls = [
        {
            "invocation_id": "move",
            "component_id": "block_translation",
            "participant_blocks": [patch.binding.block_id],
            "start_us": 0,
            "action_end_us": program.duration_us,
            "joint_trace_sha256": key,
        },
        {
            "invocation_id": "after",
            "component_id": "test_fixture.wait",
            "participant_blocks": [patch.binding.block_id],
            "start_us": stop - 4,
            "action_end_us": stop,
            "joint_trace_sha256": later_key,
        },
    ]
    case = {
        "case_id": "stateful-fixture",
        "status": "complete",
        "duration_us": stop,
        "factories": {
            "factory0": {
                "status": "complete",
                "outputs": [],
                "milestones": [],
                "completed_at_us": stop,
            }
        },
        "resources": {"tokens": [], "audit": []},
        "execution": {
            "calls": calls,
            "waves": [
                {
                    "batch_id": "move",
                    "invocations": ["move"],
                    "start_us": 0,
                    "end_us": program.duration_us,
                    "state_transition": transition,
                },
                {
                    "batch_id": "after",
                    "invocations": ["after"],
                    "start_us": stop - 4,
                    "end_us": stop,
                },
            ],
            "waits": [{"start_us": program.duration_us, "end_us": stop - 4}],
        },
        "calls": calls,
        "events": [],
    }
    return case, world, {key: trace, later_key: later}, after


def test_stateful_metrics_use_pre_window_transition_for_idle_positions():
    case, world, traces, after = stateful_fixture()
    end = case["execution"]["waves"][0]["end_us"]
    result = summarize_production(
        case, world, traces, warmup_us=end + 1, stop_us=end + 4
    )
    assert result["state_transitions_verified"] == 1
    assert result["exit_world_sha256"] == canonical_hash(after.document())
    assert result["configured_atom_time_us"] == 102 * 3
    assert result["idle_atom_time_us"] == 102 * 3
    assert result["actual_visited_bounds_um"] == production_metrics._bounds(
        [(a.position.x, a.position.y) for a in after.state.atoms]
    )
    assert result["actual_occupied_bbox_area_time_um2_us"] is None


@pytest.mark.parametrize(
    "damage", ("missing", "entry_hash", "exit_hash", "reused_trace")
)
def test_every_stateful_wave_must_match_current_world_even_with_cached_trace(damage):
    case, world, traces, _after = stateful_fixture()
    wave = case["execution"]["waves"][0]
    if damage == "missing":
        del wave["state_transition"]
    elif damage in ("entry_hash", "exit_hash"):
        wave["state_transition"][
            "entry_world_sha256" if damage == "entry_hash" else "exit_world_sha256"
        ] = "wrong"
    else:
        end = case["duration_us"]
        extra = deepcopy(wave)
        extra.update(
            batch_id="reused",
            invocations=["reused"],
            start_us=end,
            end_us=end + wave["end_us"],
        )
        case["execution"]["waves"].append(extra)
        call = {
            **case["execution"]["calls"][0],
            "invocation_id": "reused",
            "start_us": end,
            "action_end_us": extra["end_us"],
        }
        case["execution"]["calls"].append(call)
        case["duration_us"] = extra["end_us"]
    with pytest.raises(ValueError):
        summarize_production(case, world, traces, stop_us=case["duration_us"])


def test_final_factory_filter_changes_only_output_denominator():
    case, world, traces = fixture()
    case["factories"]["factory1"] = {
        "status": "complete",
        "outputs": [case["factories"]["factory0"]["outputs"].pop()],
        "milestones": [],
        "completed_at_us": 24,
    }
    result = summarize_production(
        case, world, traces, stop_us=24, output_factory_ids={"factory1"}
    )
    assert result["accepted_outputs"] == result["delivered_outputs"] == 1
    assert (
        len(result["outputs"]) == 1 and result["outputs"][0]["factory_id"] == "factory1"
    )
    assert result["configured_atom_time_us"] == 102 * 24
    assert result["busy_atom_time_us"] == 24
    assert result["per_accepted_output"]["configured_atom_time_us"] == 102 * 24
    assert result["factory_wait_by_state_us"] == {
        "waiting_resources": 4,
        "waiting_peers": 4,
    }
    with pytest.raises(ValueError):
        summarize_production(
            case, world, traces, stop_us=24, output_factory_ids={"absent"}
        )


def test_mechanical_epoch_zero_leases_contribute_to_ownership():
    case, world, traces = fixture()
    replacement = world.patches[1].binding.block_id
    case["resources"]["audit"].extend(
        [
            {
                "action": "acquire_transport",
                "at_us": 1,
                "carrier_id": replacement,
                "epoch": 0,
                "owner": "routing",
            },
            {
                "action": "complete_use",
                "at_us": 3,
                "carrier_id": replacement,
                "epoch": 0,
                "owner": "routing",
            },
        ]
    )
    result = summarize_production(case, world, traces, stop_us=24)
    assert result["owned_atom_time_us"] == 17 * 22
    assert result["peak_owned_atoms"] == 34


def transfer_output_fixture(*, retained=False):
    """Audit fixtures distinguish historical transfer from terminal consumption."""
    case, world, traces, after = stateful_fixture()
    patch = world.patches[0]
    end = case["execution"]["waves"][0]["end_us"]
    ready = end + 5 if retained else 0
    owner, consumer = "factory0/output", "factory1/input"
    ledger = ResourceLedger()
    ledger.register_logical_carrier(
        patch.binding.block_id, code_id="rotated_surface_d3", distance=3
    )
    replacement = world.patches[1].binding.block_id
    ledger.register_logical_carrier(
        replacement, code_id="rotated_surface_d3", distance=3
    )
    carrier = ledger.begin_preparation(patch.binding.block_id, owner=owner, at_us=0)
    token = ledger.offer(
        "output",
        carrier_id=patch.binding.block_id,
        epoch=carrier.epoch,
        owner=owner,
        resource_kind="A",
        producer="factory0",
        ready_at_us=ready,
        exit_at_us=ready,
        canonicalization="canonical",
        quality={"fixture": True},
    )
    output = {
        "token_id": token.token_id,
        "carrier_id": token.carrier_id,
        "epoch": token.epoch,
        "quality": token.quality,
        "ready_at_us": ready,
        "deliverable_at_us": None,
        "consumed_at_us": None,
        "released_at_us": None,
        "delivery": None,
    }
    if retained:
        output.update(
            retained_at_us=end + 6,
            retention_reason="accepted final output",
            retention={
                "token_id": token.token_id,
                "carrier_id": token.carrier_id,
                "producer_owner": owner,
                "retained_at_us": end + 6,
                "reason": "accepted final output",
                "evidence": {"scope": "fixture retained state"},
            },
        )
    else:
        ledger.reserve(
            token.token_id,
            consumer=consumer,
            at_us=0,
            expected_code="rotated_surface_d3",
            expected_kind="A",
            expected_distance=3,
            expected_canonicalization="canonical",
        )
        key = case["execution"]["calls"][0]["joint_trace_sha256"]
        output.update(
            handoff_at_us=end,
            replacement_carrier_id=replacement,
            replacement_ready_at_us=end,
            handoff={
                "token_id": token.token_id,
                "carrier_id": token.carrier_id,
                "consumer": consumer,
                "handoff_at_us": end,
                "replacement_carrier_id": replacement,
                "replacement_ready_at_us": end,
                "validation_scope": "ledger_lifecycle_only",
                "evidence": {
                    "scope": "native transfer fixture",
                    "delivery_trace_ref": key,
                },
            },
        )
        ledger.consume(
            token.token_id, consumer=consumer, at_us=end + 1, safe_exit_at_us=end + 2
        )
        ledger.complete_use(token.carrier_id, owner=consumer, at_us=end + 2)
    case["resources"] = ledger.snapshot()
    case["factories"]["factory0"]["outputs"] = [output]
    return case, world, traces, after


def test_handoff_is_audited_historically_after_consumer_has_used_token():
    case, world, traces, after = transfer_output_fixture()
    assert case["resources"]["tokens"][0]["status"] == "consumed"
    result = summarize_production(case, world, traces, stop_us=case["duration_us"])
    output = result["outputs"][0]
    assert result["accepted_outputs"] == result["handed_off_outputs"] == 1
    assert result["delivered_outputs"] == result["terminal_deliveries_total"] == 0
    assert output["output_disposition"] == "handoff"
    assert output["handoff_lifecycle_verified"] is True
    assert output["delivery_lifecycle_verified"] is False
    assert output["consumed_at_us"] is output["released_at_us"] is None
    initial = world.patches[0].binding.origin
    final = after.patches[0].binding.origin
    assert output["position_um"] == [initial.x, initial.y]
    assert output["handoff_position_um"] == [final.x, final.y]


@pytest.mark.parametrize(
    "damage", ("consume_before", "reserve_owner", "trace", "terminal_time")
)
def test_handoff_requires_matching_reservation_and_native_delivery_history(damage):
    case, world, traces, _after = transfer_output_fixture()
    output = case["factories"]["factory0"]["outputs"][0]
    if damage == "consume_before":
        token = case["resources"]["tokens"][0]
        token["consumed_at_us"] = output["handoff_at_us"] - 1
        next(
            event
            for event in case["resources"]["audit"]
            if event["action"] == "consume"
        )["at_us"] = token["consumed_at_us"]
    elif damage == "reserve_owner":
        next(
            event
            for event in case["resources"]["audit"]
            if event["action"] == "reserve"
        )["consumer"] = "wrong"
    elif damage == "trace":
        output["handoff"]["evidence"]["delivery_trace_ref"] = "wrong"
    else:
        output["consumed_at_us"] = output["handoff_at_us"] + 1
    with pytest.raises(ValueError):
        summarize_production(case, world, traces, stop_us=case["duration_us"])


def test_retained_output_counts_accepted_but_never_terminal_delivery():
    case, world, traces, after = transfer_output_fixture(retained=True)
    result = summarize_production(case, world, traces, stop_us=case["duration_us"])
    assert result["accepted_outputs"] == result["retained_outputs"] == 1
    assert result["delivered_outputs"] == result["handed_off_outputs"] == 0
    output = result["outputs"][0]
    assert output["output_disposition"] == "retained"
    assert output["retention_lifecycle_verified"] is True
    final = after.patches[0].binding.origin
    assert output["position_um"] == output["retained_position_um"] == [final.x, final.y]
    assert output["consumed_at_us"] is output["released_at_us"] is None


@pytest.mark.parametrize("damage", ("owner", "status", "release", "evidence"))
def test_retention_requires_live_offered_owned_carrier_and_audit(damage):
    case, world, traces, _after = transfer_output_fixture(retained=True)
    output = case["factories"]["factory0"]["outputs"][0]
    if damage == "owner":
        output["retention"]["producer_owner"] = "wrong"
    elif damage == "status":
        case["resources"]["tokens"][0]["status"] = "consumed"
    elif damage == "release":
        case["resources"]["audit"].append(
            {
                "action": "complete_use",
                "at_us": output["retained_at_us"],
                "carrier_id": output["carrier_id"],
                "epoch": output["epoch"],
                "owner": output["retention"]["producer_owner"],
            }
        )
    else:
        output["retention"]["evidence"] = {}
    with pytest.raises(ValueError, match="OUTPUT_RETENTION"):
        summarize_production(case, world, traces, stop_us=case["duration_us"])
