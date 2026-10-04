"""Bounded two-device transport evidence; no syndrome gates or native compile."""
from __future__ import annotations

from dataclasses import fields, replace
from hashlib import sha256
import json
from math import sqrt
from pathlib import Path
from time import perf_counter

from neutral_atom_kernel import KernelExecutor, Operation
from neutral_atom_kernel.model import thaw


PROPOSAL = "references/qec_pbc_validation/enola_patch_proposal_2026_10_04.json"
PLACEMENT_SHA = "49a2c2d531af2bad5e77d8d368c6809dd8386ffe19c3fe166c7e23882b44337c"
CONTRACT = "occupied-row-column-union/full-cartesian/v1"


def repository_root():
    return Path(__file__).resolve().parents[3]


def build_profile():
    """Bind the frozen 17-role home geometry and declare two actual 25-cell RFs."""
    raw = (repository_root() / PROPOSAL).read_bytes()
    proposal = json.loads(raw)
    coordinates = proposal["coordinates_um"]
    digest = sha256(json.dumps(coordinates, sort_keys=True, separators=(",", ":"),
                              ensure_ascii=False).encode()).hexdigest()
    names = [f"d{i}" for i in range(9)] + [f"{basis}{i}" for basis in "XZ" for i in range(4)]
    if digest != PLACEMENT_SHA or proposal["placement_sha256"] != digest:
        raise ValueError("Frozen Enola placement identity differs")
    if proposal["role_order"] != ["A." + name for name in names]:
        raise ValueError("The 17-role template order differs")
    positions, roles, modules = {}, {}, {}
    for patch, device, offset, displacement, dwell in (
        ("data", "AOD_0", 0., 140., 30.),
        ("resource", "AOD_MAGIC", 200., 100., 10.),
    ):
        atoms = []
        for index, local in enumerate(names):
            atom = f"Q{len(positions):03d}"
            x, y = coordinates["A." + local]
            positions[atom] = (x + offset, y)
            role = local if patch == "data" else f"r{index:02d}"
            roles[patch + "." + role] = atom
            atoms.append(atom)
        modules[device] = {"atoms": tuple(atoms), "displacement_um": displacement,
                           "dwell_us": dwell, "patch": patch}
    axes = {device: {"rows": (0., 10., 20., 30., 40.), "columns": ()}
            for device in modules}
    for device, item in modules.items():
        axes[device]["columns"] = tuple(sorted({positions[q][0] for q in item["atoms"]}))
    sites = set(positions.values())
    for item in modules.values():
        sites.update((positions[q][0], positions[q][1] + item["displacement_um"])
                     for q in item["atoms"])
    profile = {
        "id": "modular-aod-enola-home-34/v1", "profile_id": "modular-aod-enola-home-34/v1",
        "bounds_um": (-20., -20., 300., 200.), "slm_grid_um": 5., "slm_origin_um": (0., 0.),
        "transport_clearance_um": 1., "aod_axis_spacing_um": 2.,
        "load_duration_us": 15., "store_duration_us": 15.,
        "move_scale_us": 200., "move_reference_um": 110.,
        "active_axes_contract": CONTRACT, "motion_contract": "row-column-common-cubic-progress/v1",
        "initial_axes": axes, "declared_slm_sites_um": sorted(sites),
        "compute_zone_um": (-20., -10., 300., 60.),
        "cz_illumination": "global_x_band", "cz_zones_um": {"EZ": (-20., -10., 300., 60.)},
        "storage_zones_um": {"DATA_STAGE": (-10., 130., 50., 190.),
                              "RESOURCE_STAGE": (190., 90., 250., 150.)},
        "devices": {
            "AOD_0": {"rows": 5, "columns": 5, "capacity": 25,
                      "envelope_um": (-10., -10., 50., 190.)},
            "AOD_MAGIC": {"rows": 5, "columns": 5, "capacity": 25,
                          "envelope_um": (190., -10., 250., 190.)},
        },
        "placement_provenance": {"proposal_path": PROPOSAL, "proposal_raw_sha256": sha256(raw).hexdigest(),
                                 "placement_sha256": digest, "initial_sa_only": True},
        "scope": "34 admitted SLM homes; pure two-AOD transport, eight active empty intersections per device",
        "extra_empty_active_axes_supported": False, "initial_preparation_cost_known": False,
        "native_compilation_invoked": False, "syndrome_executed": False, "factory_executed": False,
        "full_shor_executed": False,
    }
    return positions, profile, roles, modules


def module_operations(device, item, initial):
    """A complete return cycle, preserving identity and the actual SLM endpoints."""
    atoms = item["atoms"]
    dy = item["displacement_um"]
    travel = 200. * sqrt(dy / 110.)
    stage = tuple((q, (initial[q][0], initial[q][1] + dy)) for q in atoms)
    home = tuple((q, initial[q]) for q in atoms)
    prefix = item["patch"]
    def op(name, kind, duration, positions=()):
        return Operation(prefix + "." + name, kind, atoms, duration, positions,
                         aod_id=device, resources=(device,), motion_profile="row_column",
                         metadata={"label": prefix + " · " + name,
                                   "protocol_stage": "pure-transport-module",
                                   "transport_batch": prefix, "origin": "explicit-modular-transport"})
    return (op("load-out", "LOAD", 15.), op("move-out", "MOVE", travel, stage),
            op("store-stage", "STORE", 15.), op("dwell", "WAIT", item["dwell_us"]),
            op("load-return", "LOAD", 15.), op("move-return", "MOVE", travel, home),
            op("store-home", "STORE", 15.))


def build_schedule():
    from neutral_atom_strategies.scheduling.aod_modules import AODTransportModule, coordinate_aod_modules
    initial, profile, roles, descriptions = build_profile()
    holders = {q: "slm" for q in initial}
    modules = tuple(AODTransportModule.compile(device, module_operations(device, item, initial),
        initial, initial_axes=profile["initial_axes"], initial_holders=holders, profile=profile)
        for device, item in descriptions.items())
    schedule = coordinate_aod_modules(modules, initial, initial_axes=profile["initial_axes"],
                                      initial_holders=holders, profile=profile)
    return initial, profile, roles, schedule, modules


def serialize_operation(operation):
    return {field.name: thaw(getattr(operation, field.name)) for field in fields(operation)}


def review_input_sha256(initial, operations, profile):
    from neutral_atom_strategies.scheduling.aod_modules import review_input_sha256 as bind_digest
    return bind_digest(initial, operations, profile, initial_axes=profile["initial_axes"],
                       initial_holders={q: "slm" for q in initial})


def semantic(observation):
    return {key: thaw(getattr(observation, key)) for key in (
        "time_us", "positions", "holders", "completed_gate_ids", "measurement_results",
        "measurement_completion_times_us", "aod_axes", "completed", "pending_events")}


def run(output, *, geometry_guard):
    """Execute and restore actual concurrent events, with a required independent guard."""
    directory = Path(output)
    directory.mkdir(parents=True, exist_ok=False)
    try:
        return _execute(directory, geometry_guard=geometry_guard)
    except Exception as error:
        failure = {"schema": "modular-aod-demo-failure/1", "runtime_status": "rejected",
                   "type": type(error).__name__, "message": str(error),
                   "scope": "pure transport; failed attempt retained without overwriting"}
        (directory / "failure.json").write_text(json.dumps(failure, indent=2), encoding="utf-8")
        raise


def _execute(directory, *, geometry_guard):
    started = perf_counter()
    initial, profile, roles, schedule, modules = build_schedule()
    def save(name, value):
        (directory / name).write_text(json.dumps(thaw(value), ensure_ascii=False, indent=2,
                                                allow_nan=False), encoding="utf-8")
    save("initial.json", {"positions": initial, "holders": {q: "slm" for q in initial},
                          "initial_axes": profile["initial_axes"], "gates": (), "role_to_atom": roles})
    save("profile.json", profile)
    save("operations.json", [serialize_operation(op) for op in schedule.operations])
    kernel = KernelExecutor(initial, initial_aod_axes=profile["initial_axes"], recording=True)
    def guard(*args, **kwargs):
        review = geometry_guard(*args, **kwargs)
        save("pre-execution-audit.json", review)
        return review
    block = schedule.bind_block(kernel, "independent-dual-aod-transport", geometry_guard=guard)
    moves = {op.id: op for op in schedule.operations if op.kind == "MOVE"}
    left, right = moves["data.move-out"], moves["resource.move-out"]
    start, end = max(left.start_us, right.start_us), min(left.end_us, right.end_us)
    if end <= start:
        raise AssertionError("Actual scheduled loaded MOVE intervals do not overlap")
    cut = (start + end) / 2
    kernel.run(block, until_us=cut)
    mid = kernel.observe()
    if not {left.id, right.id}.issubset(mid.inflight_operations):
        raise AssertionError("Both device MOVE operations must be actually in flight")
    checkpoint = kernel.checkpoint(include_journal=True)
    save("checkpoint-midflight.json", checkpoint)
    restored = KernelExecutor.restore(json.loads(json.dumps(checkpoint)))
    resource_done = schedule.device_completion_us["AOD_MAGIC"]
    kernel.run(until_us=resource_done)
    resource_finish = kernel.observe()
    if (any(resource_finish.holders[q] != "slm" or resource_finish.positions[q] != initial[q]
            for q in initial if int(q[1:]) >= 17) or
            "data.move-return" not in resource_finish.inflight_operations):
        raise AssertionError("Resource must finish at home while data return MOVE remains in flight")
    save("resource-finished-data-inflight.json", {
        **semantic(resource_finish), "inflight_operations": resource_finish.inflight_operations})
    checkpoint_after_resource = kernel.checkpoint(include_journal=True)
    save("checkpoint-resource-finished.json", checkpoint_after_resource)
    restored_after_resource = KernelExecutor.restore(json.loads(json.dumps(checkpoint_after_resource)))
    kernel.run(); restored.run(); restored_after_resource.run()
    final = kernel.observe()
    recovery_equal = (semantic(final) == semantic(restored.observe()) and
                      thaw(kernel.journal) == thaw(restored.journal))
    if not recovery_equal or dict(final.positions) != initial or set(final.holders.values()) != {"slm"}:
        raise AssertionError("Actual cold restore or complete original-holder return differs")
    resource_recovery_equal = (semantic(final) == semantic(restored_after_resource.observe()) and
                               thaw(kernel.journal) == thaw(restored_after_resource.journal))
    if not resource_recovery_equal:
        raise AssertionError("Recovery after resource completion differs")
    recorded = KernelExecutor(initial, initial_aod_axes=profile["initial_axes"], recording=True)
    recorded.run(schedule.bind_block(recorded, "clean-recording-on", geometry_guard=geometry_guard))
    quiet = KernelExecutor(initial, initial_aod_axes=profile["initial_axes"], recording=False)
    quiet.run(schedule.bind_block(quiet, "clean-recording-off", geometry_guard=geometry_guard))
    recording_equal = semantic(final) == semantic(recorded.observe()) == semantic(quiet.observe())
    if not recording_equal or quiet.journal:
        raise AssertionError("Recording changes the semantic final state")
    # The serial control uses these same finalized physical primitives, with
    # both complete device cycles in order. Only scheduling fields differ.
    cursor, previous, serial_ops = 0., None, []
    for module in modules:
        for operation in module.operations:
            end_us = cursor + operation.duration_us
            serial_ops.append(replace(operation, start_us=cursor, end_us=end_us,
                                      depends_on=(previous,) if previous else ()))
            cursor, previous = end_us, operation.id
    serial_ops = tuple(serial_ops)
    serial_review = geometry_guard(initial, serial_ops, profile, initial_axes=profile["initial_axes"],
                                  initial_holders={q: "slm" for q in initial})
    save("serial-pre-execution-audit.json", serial_review)
    if (serial_review.get("status") != "PASS" or serial_review.get("passed") is not True or
            serial_review.get("input_sha256") != review_input_sha256(initial, serial_ops, profile)):
        raise AssertionError("Same-profile serial control failed independent geometry review")
    serial = KernelExecutor(initial, initial_aod_axes=profile["initial_axes"], recording=True)
    serial.run(serial.bind_block("same-profile-serial-control", serial_ops, execution_mode="scheduled",
        native_provenance={"geometry_review_input_sha256": serial_review["input_sha256"]}))
    serial_state = semantic(serial.observe())
    parallel_state = semantic(final)
    serial_state.pop("time_us"); parallel_state.pop("time_us")
    physical_fields = ("id", "kind", "atoms", "duration_us", "positions", "aod_id", "motion_profile")
    concurrent_by_id = {op.id: op for op in schedule.operations}
    primitives_equal = (len(serial_ops) == len(schedule.operations) and
        all(all(getattr(op, field) == getattr(concurrent_by_id[op.id], field) for field in physical_fields)
            for op in serial_ops))
    if serial_state != parallel_state or not primitives_equal or serial.time_us <= final.time_us:
        raise AssertionError("Serial control differs in physical primitives or final state")
    save("serial-operations.json", [serialize_operation(op) for op in serial_ops])
    save("serial-journal.json", serial.journal)
    serial_checkpoint = serial.checkpoint(include_journal=True)
    save("serial-checkpoint-final.json", serial_checkpoint)
    serial_audit = geometry_guard(initial, serial_ops, profile, initial_axes=profile["initial_axes"],
        initial_holders={q: "slm" for q in initial}, journal=serial.journal,
        final_checkpoint=serial_checkpoint)
    save("serial-offline-audit.json", serial_audit)
    if (serial_audit.get("status") != "PASS" or serial_audit.get("passed") is not True or
            serial_audit.get("actual_execution_verified") is not True or
            serial_audit.get("input_sha256") != review_input_sha256(initial, serial_ops, profile)):
        raise AssertionError("Same-profile serial actual execution failed independent review")
    journal = thaw(kernel.journal)
    checkpoint_final = kernel.checkpoint(include_journal=True)
    audit = geometry_guard(initial, schedule.operations, profile, initial_axes=profile["initial_axes"],
                           initial_holders={q: "slm" for q in initial}, journal=journal,
                           final_checkpoint=checkpoint_final)
    passed = (audit.get("status") == "PASS" and audit.get("passed") is True and
              audit.get("actual_execution_verified") is True and
              audit.get("input_sha256") == review_input_sha256(initial, schedule.operations, profile))
    save("journal.json", journal)
    save("checkpoint-final.json", checkpoint_final)
    save("offline-audit.json", audit)
    result = {
        "schema": "modular-aod-transport-demo/1", "runtime_status": "completed",
        "offline_physical_status": "PASS" if passed else "FAIL", "profile": profile["id"],
        "runtime": "neutral_atom_kernel", "atoms": len(initial), "aods": 2,
        "operations": len(schedule.operations), "journal_events": len(journal), "gates": 0, "reports": 0,
        "physical_time_us": final.time_us, "device_completion_us": dict(schedule.device_completion_us),
        "resource_early_return_us": final.time_us - resource_done,
        "actual_execution_verified": passed,
        "loaded_move_overlap_us": end - start, "resource_complete_data_still_moving": True,
        "checkpoint_two_moves_inflight": {"cut_us": cut, "operations": [left.id, right.id],
                                         "exact_final_and_journal_equal": recovery_equal},
        "checkpoint_after_resource_completed": {"cut_us": resource_done,
            "data_move_inflight": "data.move-return", "exact_final_and_journal_equal": resource_recovery_equal},
        "recording_off_on_semantic_equal": recording_equal,
        "same_profile_serial_control": {"physical_time_us": serial.time_us,
            "same_physical_primitives": primitives_equal, "same_final_state_except_time": True,
            "actual_execution_verified": True, "offline_physical_status": "PASS",
            "time_reduction_percent": 100. * (serial.time_us - final.time_us) / serial.time_us,
            "saved_operations": "serial-operations.json", "saved_journal": "serial-journal.json",
            "saved_audit": "serial-offline-audit.json"},
        "initial_preparation_cost_known": False, "native_compilation_invoked": False,
        "legacy_env_execution_calls": 0, "syndrome_executed": False, "factory_executed": False,
        "full_shor_executed": False, "fidelity": None, "wall_seconds_before_export": perf_counter() - started,
        "bookmarks": [{"label": "初始双区域", "time": 0.},
                      {"label": "两台 AOD 同时带载 MOVE", "time": cut},
                      {"label": "资源回家，数据仍在运输", "time": resource_done},
                      {"label": "实际完整终态", "time": final.time_us}],
    }
    save("summary.json", result)
    evidence = {"initial": initial, "initial_holders": {q: "slm" for q in initial}, "profile": profile,
                "gates": (), "operations": schedule.operations, "journal": journal,
                "role_to_atom": roles, "final": semantic(final), "report_source": {}, "summary": result}
    return result, evidence

