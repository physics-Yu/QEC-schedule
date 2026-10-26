"""Offline calibration of exact mixed component frontiers on the shared device."""

import json
from collections import Counter, defaultdict
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import qiskit.qasm3
from nadit_physical_compiler.activity import AtomActivity, derive_activity
from nadit_physical_compiler.atom_ir import Load, Measure, Move, Reset, Rotation, Store
from nadit_physical_compiler.compiler import compile_physical
from nadit_physical_compiler.cost import model_for, prepare
from nadit_physical_compiler.experiments.journal import write_json
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import (
    encode_device,
    encode_layout,
    encode_result,
)
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

from modules.codes._support.detector_probability import estimate_acceptance
from modules.codes._support.pauli_detector_events import detector_fault_channels
from modules.codes.rotated_surface.components import SurfaceComponent
from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.fast_factory import acceptance_port
from modules.codes.rotated_surface.growth import injection_indices
from modules.codes.rotated_surface.joint_factory_profile import joint_key
from modules.codes.rotated_surface.joint_factory_source import factory_component_source
from modules.codes.rotated_surface.translation import BlockTranslationComponent

from .calibrate import summarize
from .component_reuse import (
    ComponentOperationCache,
    ComponentOperations,
    compose_operations,
)
from .joint_transition import (
    TransportTargets,
    check_members,
    expected_exit,
    member_code_contract,
    member_definition,
    validate_transition,
)
from .parallel_se_metrics import RecordedStrategy
from .standard import ExperimentWorld


def projected_raw_port(
    activity: Any,
    channels: list[dict[str, Any]],
    atoms: tuple[int, ...],
    results: tuple[int, ...],
    *,
    shots: int,
    seed: int,
    trace_sha256: str,
    noise_sha256: str,
) -> dict[str, Any]:
    """Project actual joint exposure only after proving channel factorization.

    There are no ideal gates or multi-atom noise channels crossing this member.
    Shared pulse spectator channels are retained on their actual target atoms.
    """
    own = set(atoms)
    events: list[Any] = []
    event_ids: dict[int, int] = {}
    for i, event in enumerate(activity.events):
        indices = [j for j, atom in enumerate(event.atoms) if atom in own]
        if not indices:
            continue
        if any(bool(set(pair) & own) and not set(pair) <= own for pair in event.pairs):
            raise ValueError("JOINT_RAW_IDEAL_CROSS_MEMBER_COUPLING")
        event_ids[i] = len(events)
        events.append(
            replace(
                event,
                atoms=tuple(event.atoms[j] for j in indices),
                starts=tuple(event.starts[j] for j in indices),
                ends=tuple(event.ends[j] for j in indices),
                pairs=tuple(pair for pair in event.pairs if set(pair) <= own),
                measurement_ids=tuple(event.measurement_ids[j] for j in indices)
                if event.measurement_ids
                else (),
            )
        )
    selected = []
    for channel in channels:
        touched = set(channel["atoms"])
        if not touched & own:
            continue
        if not touched <= own:
            raise ValueError("JOINT_RAW_NOISE_DOES_NOT_FACTORIZE")
        item = dict(channel)
        if "event_id" in item:
            item["event_id"] = event_ids[item["event_id"]]
        selected.append(item)
    projected = AtomActivity(
        activity.duration_us,
        tuple(a for a in activity.per_atom if a.atom_id in own),
        tuple(events),
    )
    code = definition(3)
    checks = [
        code.check_roles.index(p) for p in SurfaceComponent("raw_t", 3).acceptance_ports
    ]
    detectors = tuple((results[j],) for j in checks) + tuple(
        (results[(r - 1) * 8 + j], results[r * 8 + j]) for r in (1, 2) for j in range(8)
    )
    signatures, proof = detector_fault_channels(
        projected,
        selected,
        detectors,
        wire_atoms=atoms,
        seed_atom=atoms[4],
        world_atom_ids=atoms,
    )
    estimate = estimate_acceptance(
        len(detectors),
        signatures,
        method="monte_carlo",
        shots=shots,
        seed=seed,
        batch_size=shots,
    )
    return acceptance_port(
        estimate["probability"],
        preparation="raw_t_postselection",
        evidence={
            "estimator": estimate,
            "joint_trace_sha256": trace_sha256,
            "noise_params_hash": noise_sha256,
            "participant_atom_ids": list(atoms),
            "factorized_actual_joint_channels": True,
            "detector_proof": proof,
            "scope": "d3 injection only; retained atoms; no output LER",
        },
    ).to_dict()


def compile_joint_actions(
    world: ExperimentWorld,
    members: tuple[str, ...],
    *,
    family: str,
    transport_targets: TransportTargets | None = None,
    component_cache: ComponentOperationCache | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Compile and validate one complete frontier independently of noise/shots.

    Returns a portable action record and its exact serialized atom trace. All
    spectators remain in the supplied world; no default placement is generated.
    """
    started = perf_counter()
    members = tuple(sorted(members))
    if not members or len(set(members)) != len(members):
        raise ValueError("INVALID_JOINT_FRONTIER")
    check_members(members, transport_targets)
    patches = {p.binding.block_id: p for p in world.patches}
    local, atom_groups, templates = [], [], []
    clbit_ranges: list[tuple[int, ...]] = []
    source_contracts = {}
    wires: list[int] = []
    registers: list[Any] = []
    classical: list[Any] = []
    offset = 0
    for i, member in enumerate(members):
        component, blocks = member.split(":", 1)
        selected = tuple(patches[b] for b in blocks.split(","))
        code = member_definition(world, component, selected)
        code_contract = member_code_contract(world, code)
        if component == "block_translation":
            atoms = selected[0].binding.atom_ids
            atom_groups.append(atoms)
            wires.extend(atoms)
            circuit = QuantumCircuit(len(atoms))
            if component_cache is not None:
                templates.append(
                    ComponentOperations(
                        PhysicalDAG(len(atoms), 0, (), ()),
                        0,
                        "native_transport_goal",
                        (),
                    )
                )
            source_contracts[member] = {
                **code_contract,
                "native_component": "block_translation/1",
                "wire_indices": list(range(len(atoms))),
                "result_count": 0,
            }
            local.append(circuit)
            registers.append(QuantumRegister(len(atoms), f"q_m{i}"))
            classical.append(None)
            clbit_ranges.append(())
            continue
        source = factory_component_source(component, code.distance)
        if component_cache is not None:
            templates.append(component_cache.get(component, code.distance))
        source_contracts[member] = {
            **code_contract,
            "source_sha256": sha256(source.source_qasm.encode()).hexdigest(),
            "wire_indices": list(source.wire_indices),
            "result_count": source.result_count,
        }
        atoms = tuple(a for p in selected for a in p.binding.atom_ids)
        active = tuple(atoms[j] for j in source.wire_indices)
        atom_groups.append(active)
        wires.extend(active)
        circuit = qiskit.qasm3.loads(source.source_qasm)
        local.append(circuit)
        registers.append(QuantumRegister(circuit.num_qubits, f"q_m{i}"))
        classical.append(
            ClassicalRegister(circuit.num_clbits, f"c_m{i}")
            if circuit.num_clbits
            else None
        )
        clbit_ranges.append(tuple(range(offset, offset + circuit.num_clbits)))
        offset += circuit.num_clbits
    if len(wires) != len(set(wires)):
        raise ValueError("JOINT_COMPONENT_PARTICIPANTS_OVERLAP")
    circuit = QuantumCircuit(*registers, *(c for c in classical if c is not None))
    for local_circuit, qr, cr in zip(local, registers, classical, strict=True):
        circuit.compose(local_circuit, qubits=qr, clbits=cr or (), inplace=True)
    source_qasm = qiskit.qasm3.dumps(circuit)
    dag = (
        loads_qasm(source_qasm)
        if component_cache is None
        else compose_operations(templates)
    )
    entry = replace(world.state, qubit_to_atom=tuple(wires))
    goals, binding_updates = [], {}
    endpoint_sites: dict[int, str] = {}
    for member, (origin, homes) in sorted((transport_targets or {}).items()):
        patch = patches[member.split(":", 1)[1]]
        code = world.block_definition(patch.binding.block_id)
        node, goal, binding = BlockTranslationComponent(code.distance).native_goal(
            world.device,
            world=entry,
            binding=patch.binding,
            target_origin=origin,
            target_home_sites=homes,
            operation_id=len(dag.nodes),
        )
        dag = PhysicalDAG(
            dag.num_qubits,
            dag.num_clbits,
            (*dag.nodes, node),
            dag.edges,
            global_phase=dag.global_phase,
        )
        goals.append(goal)
        binding_updates[member] = {
            "distance": code.distance,
            "entry": asdict(patch.binding),
            "exit": asdict(binding),
            "home_sites": list(homes),
        }
        endpoint_sites.update(zip(binding.atom_ids, homes, strict=True))
    target = expected_exit(entry, world.device, endpoint_sites) if goals else entry
    owner_by_atom = {a: i for i, atoms in enumerate(atom_groups) for a in atoms}
    owners = []
    for node in dag.nodes:
        own = {owner_by_atom[wires[q]] for q in node.qubits}
        if len(own) != 1:
            raise ValueError("JOINT_SOURCE_CROSSES_MEMBER_BOUNDARY")
        owners.append(own.pop())
    if any(owners[a] != owners[b] for a, b in dag.edges):
        raise ValueError("JOINT_SOURCE_HAS_CROSS_MEMBER_DEPENDENCY")
    assert world.device.readout is not None
    base = NonZonedStrategy(
        "transport",
        GatePairCatalog.from_pair_arrays(world.device),
        max_measurements=world.device.readout.max_atoms,
        transport_goals=tuple(goals),
    )
    recorder = RecordedStrategy(base, tuple(owners), owner_by_atom)
    compile_started = perf_counter()
    result = compile_physical(dag, world.device, strategy=recorder, entry_state=entry)
    compile_seconds = perf_counter() - compile_started
    validation_started = perf_counter()
    validation = validate_result(
        result, entry_state=entry, device=world.device, dag=dag
    )
    if not validation["ok"] or result.exit_state != target:
        raise ValueError(f"JOINT_FACTORY_PHYSICAL_VALIDATION_FAILED: {validation}")
    validation_seconds = perf_counter() - validation_started
    document = encode_result(
        result,
        entry_state=entry,
        dag=dag,
        device=world.device,
        validation=validation,
        job={"strategy": {"kind": "nonzoned"}, "case": {"seed": 0}},
        provenance={
            "joint_family": family,
            **(
                {
                    "member_codes": {
                        member: {key: contract[key] for key in ("code_id", "distance")}
                        for member, contract in source_contracts.items()
                    }
                }
                if world.spec.mixed_distances
                else {}
            ),
        },
        inputs={
            "qasm_sha256": sha256(source_qasm.encode()).hexdigest(),
            "device_sha256": canonical_hash(encode_device(world.device)),
        },
    )
    document["source_qasm"] = source_qasm
    trace_hash = canonical_hash(document)
    phases = [step.duration_us for step in result.program.steps]
    details: dict[str, dict[str, Any]] = {
        member: {
            "measurement_phases": [],
            "cost_segments": [],
            "primitive_counts": dict(
                Counter(
                    n.name
                    for n, owner in zip(dag.nodes, owners, strict=True)
                    if owner == i and n.name != "barrier"
                )
            ),
        }
        for i, member in enumerate(members)
    }
    categories = {
        "Load": ("transfer", "aod:transport"),
        "Store": ("transfer", "aod:transport"),
        "Move": ("movement", "aod:transport"),
        "Measure": ("measurement", "camera"),
        "Reset": ("reset", "local"),
        "Rotation": ("gate", "local"),
        "CZPulse": ("gate", "rydberg"),
    }
    seen = set()
    member_factories = [m.split(":", 1)[1].split("/", 1)[0] for m in members]
    activity_edges: dict[float, Counter[str]] = defaultdict(Counter)
    resource_intervals: dict[str, list[list[float]]] = defaultdict(list)
    native_action_counts: Counter[str] = Counter()
    for step_index, (start, step) in enumerate(result.program.timeline()):
        for action in step.actions:
            # Transport source_ids can name the whole gate layer. Attribute
            # work only to atoms actually moved in this particular batch.
            if isinstance(action, Load | Store):
                touched = tuple(b[0] for b in action.bindings)
            elif isinstance(action, Move):
                touched = tuple(a for a, _ in action.targets)
            elif isinstance(action, Measure):
                touched = tuple(a for a, _ in action.results)
            elif isinstance(action, Rotation | Reset):
                touched = action.atoms
            else:
                touched = tuple(
                    wires[q] for n in action.source_ids for q in dag.nodes[n].qubits
                )
            action_owners = {owner_by_atom[a] for a in touched if a in owner_by_atom}
            category, resource = categories.get(
                type(action).__name__, ("other", "none")
            )
            end = start + action.duration_us
            resource_intervals[resource].append([start, end])
            native_action_counts[type(action).__name__] += 1
            for factory in {member_factories[i] for i in action_owners}:
                activity_edges[start][factory] += 1
                activity_edges[end][factory] -= 1
            for i in action_owners:
                key = (i, start, action.duration_us, category, resource)
                if key not in seen:
                    details[members[i]]["cost_segments"].append(
                        {
                            "start_offset_us": start,
                            "end_offset_us": end,
                            "category": category,
                            "resource": resource,
                        }
                    )
                    seen.add(key)
            if isinstance(action, Measure):
                for atom, _mid in action.results:
                    details[members[owner_by_atom[atom]]]["measurement_phases"].append(
                        (step_index, world.device.readout.latency_us)
                    )
    by_bit = {
        n.clbits[0]: n.result.measurement_id for n in dag.nodes if n.result is not None
    }
    measurement_ids = {
        member: [by_bit[c] for c in clbit_ranges[i]] for i, member in enumerate(members)
    }
    schedule = recorder.report(result, entry, world.device)
    schedule["owner_kind"] = "component_member_index"
    active_counts: Counter[str] = Counter()
    previous, overlap, peak = 0.0, 0.0, 0
    for time, changes in sorted(activity_edges.items()):
        count = sum(v > 0 for v in active_counts.values())
        peak = max(peak, count)
        if count > 1:
            overlap += time - previous
        active_counts.update(changes)
        previous = time
    shared_batches = sum(
        len({member_factories[i] for i in batch["factory_ids"]}) > 1
        for batch in schedule["transport_batches"]
    )
    grids = [
        a.grid
        for step in result.program.steps
        for a in step.actions
        if hasattr(a, "grid")
    ]
    metrics_started = perf_counter()
    shared_metrics = summarize(document)
    metrics_seconds = perf_counter() - metrics_started
    group = {
        "schema": "nadit.joint_actions/1",
        "family": family,
        "members": details,
        "phase_durations_us": phases or [0.0],
        "validation_ok": True,
        "trace_sha256": trace_hash,
        "measurement_ids": measurement_ids,
        "source_contracts": source_contracts,
        "shared_metrics": shared_metrics,
        "shared_resource_intervals": dict(resource_intervals),
        "native_action_counts": dict(native_action_counts),
        "peak_rows": max((len(g.rows) for g in grids), default=0),
        "peak_columns": max((len(g.columns) for g in grids), default=0),
        "peak_readout_atoms": max(
            (
                sum(len(a.results) for a in step.actions if isinstance(a, Measure))
                for step in result.program.steps
            ),
            default=0,
        ),
        "member_factories": dict(zip(members, member_factories, strict=True)),
        "participant_atoms": dict(zip(members, atom_groups, strict=True)),
        "factory_concurrency": {
            "peak_active_factories": peak,
            "multi_factory_active_us": overlap,
            "shared_transport_batches": shared_batches,
        },
        "schedule": schedule,
        "calibration_wall_seconds": perf_counter() - started,
        "software_seconds": {
            "physical_compile": compile_seconds,
            "shared_schedule": compile_seconds,
            **(
                {"component_operations": component_cache.seconds}
                if component_cache is not None
                else {}
            ),
            "validation": validation_seconds,
            "activity_metrics": metrics_seconds,
        },
    }
    if component_cache is not None:
        group["component_reuse"] = {
            **dict(component_cache.statistics),
            "keys": sorted({t.key for t in templates}),
            "shared_schedule_calls": 1,
            "scope": "native operations and dependencies; transport/readout/timing/noise recomputed from actual world",
        }
    if goals:
        group["state_transition"] = {
            "schema": "nadit.joint_world_transition/1",
            "entry_state_sha256": canonical_hash(encode_layout(entry)),
            "exit_state_sha256": canonical_hash(encode_layout(target)),
            "bindings": json.loads(json.dumps(binding_updates)),
        }
    validate_transition(group, document)
    return group, document


def evaluate_joint_probabilities(
    action: dict[str, Any],
    trace: dict[str, Any],
    *,
    noise_params: dict[str, Any],
    shots: int,
    seed: int,
    revalidate: bool = True,
) -> dict[str, Any]:
    """Evaluate actual saved joint exposure without compiling new atom actions.

    Stored input is revalidated by default. The in-memory wrapper may set
    revalidate=False immediately after compile_joint_actions validated that exact
    trace. No growth syndrome is included in the raw acceptance event.
    """
    started = perf_counter()
    if type(shots) is not int or shots < 1 or type(seed) is not int or seed < 0:
        raise ValueError("INVALID_JOINT_PROBABILITY_SAMPLING")
    if (
        action.get("schema") != "nadit.joint_actions/1"
        or action.get("validation_ok") is not True
        or canonical_hash(trace) != action["trace_sha256"]
    ):
        raise ValueError("INVALID_JOINT_ACTION_ARTIFACT")
    validate_transition(action, trace)
    raw_members = [m for m in action["members"] if m.startswith("raw_t_postselection:")]
    for member in raw_members:
        contract = action.get("source_contracts", {}).get(member, {})
        distance = contract.get("distance")
        if (
            len(action["participant_atoms"][member]) != 17
            or len(action["measurement_ids"][member]) != 24
            or (
                distance is not None
                and (
                    contract.get("code_id") != f"rotated_surface_d{distance}"
                    or contract.get("wire_indices") != list(injection_indices(distance))
                )
            )
        ):
            raise ValueError("JOINT_RAW_PROJECTION_INTERFACE_MISMATCH")
    ports = {}
    noise = None
    validation_started = perf_counter()
    activity = (
        (prepare(trace) if revalidate else derive_activity(trace))
        if raw_members
        else None
    )
    validation_seconds = perf_counter() - validation_started
    if activity is not None:
        noise = model_for("noise/v1").evaluate(activity, trace, noise_params)
        for member in raw_members:
            ports[member] = projected_raw_port(
                activity,
                noise["noise"]["channels"],
                tuple(action["participant_atoms"][member]),
                tuple(action["measurement_ids"][member]),
                shots=shots,
                seed=seed,
                trace_sha256=action["trace_sha256"],
                noise_sha256=noise["params_hash"],
            )
    return {
        "schema": "nadit.joint_probabilities/1",
        "trace_sha256": action["trace_sha256"],
        "raw_ports": ports,
        "noise_params": noise_params,
        "noise_params_hash": None if noise is None else noise["params_hash"],
        "shots": shots,
        "seed": seed,
        "model": "noise/v1+raw_detector_monte_carlo/1",
        "validation_activity_wall_seconds": validation_seconds,
        "probability_wall_seconds": perf_counter() - started,
    }


def combine_joint_group(
    action: dict[str, Any], probability: dict[str, Any], *, family: str
) -> dict[str, Any]:
    """Join separately identified records into the existing fast-profile contract."""
    if (
        action.get("schema") != "nadit.joint_actions/1"
        or probability.get("schema") != "nadit.joint_probabilities/1"
        or action["trace_sha256"] != probability["trace_sha256"]
    ):
        raise ValueError("JOINT_CALIBRATION_ARTIFACT_MISMATCH")
    return {
        **action,
        "family": family,
        "raw_ports": probability["raw_ports"],
        "calibration_wall_seconds": action.get("calibration_wall_seconds", 0)
        + probability.get("probability_wall_seconds", 0),
        "probability_calibration": {
            key: value for key, value in probability.items() if key != "raw_ports"
        },
    }


def compile_joint_group(
    world: ExperimentWorld,
    members: tuple[str, ...],
    *,
    family: str,
    noise_params: dict[str, Any],
    shots: int,
    seed: int,
    output: Path,
) -> dict[str, Any]:
    """Preserve the legacy offline API using split action/probability producers."""
    action, trace = compile_joint_actions(world, members, family=family)
    probability = evaluate_joint_probabilities(
        action,
        trace,
        noise_params=noise_params,
        shots=shots,
        seed=seed,
        revalidate=False,
    )
    group = combine_joint_group(action, probability, family=family)
    key = joint_key(members)
    write_json(output / f"{key}.trace.json", trace)
    if (
        canonical_hash(
            json.loads((output / f"{key}.trace.json").read_text(encoding="utf-8"))
        )
        != action["trace_sha256"]
    ):
        raise ValueError("PUBLISHED_JOINT_TRACE_HASH_MISMATCH")
    write_json(output / f"{key}.group.json", group)
    return group
