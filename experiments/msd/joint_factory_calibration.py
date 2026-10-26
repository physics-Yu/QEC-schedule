"""Offline calibration of exact mixed component frontiers on the shared device."""

import json
from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

import qiskit.qasm3
from nadit_physical_compiler.activity import AtomActivity, derive_activity
from nadit_physical_compiler.atom_ir import Load, Measure, Move, Reset, Rotation, Store
from nadit_physical_compiler.compiler import compile_physical
from nadit_physical_compiler.cost import model_for
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_result
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

from modules.codes._support.detector_probability import estimate_acceptance
from modules.codes._support.pauli_detector_events import detector_fault_channels
from modules.codes.rotated_surface.components import SurfaceComponent
from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.fast_factory import acceptance_port
from modules.codes.rotated_surface.joint_factory_profile import joint_key
from modules.codes.rotated_surface.joint_factory_source import factory_component_source

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
    """Compile all source members together and retain replay/noise evidence."""
    started = perf_counter()
    members = tuple(sorted(members))
    patches = {p.binding.block_id: p for p in world.patches}
    local, atom_groups, clbit_ranges = [], [], []
    wires: list[int] = []
    registers, classical, offset = [], [], 0
    for i, member in enumerate(members):
        component, blocks = member.split(":", 1)
        selected = tuple(patches[b] for b in blocks.split(","))
        source = factory_component_source(component, world.spec.distance)
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
    dag = loads_qasm(source_qasm)
    owner_by_atom = {a: i for i, atoms in enumerate(atom_groups) for a in atoms}
    owners = []
    for node in dag.nodes:
        own = {owner_by_atom[wires[q]] for q in node.qubits}
        if len(own) != 1:
            raise ValueError("JOINT_SOURCE_CROSSES_MEMBER_BOUNDARY")
        owners.append(own.pop())
    if any(owners[a] != owners[b] for a, b in dag.edges):
        raise ValueError("JOINT_SOURCE_HAS_CROSS_MEMBER_DEPENDENCY")
    entry = replace(world.state, qubit_to_atom=tuple(wires))
    assert world.device.readout is not None
    base = NonZonedStrategy(
        "transport",
        GatePairCatalog.from_pair_arrays(world.device),
        max_measurements=world.device.readout.max_atoms,
    )
    recorder = RecordedStrategy(base, tuple(owners), owner_by_atom)
    result = compile_physical(dag, world.device, strategy=recorder, entry_state=entry)
    validation = validate_result(
        result, entry_state=entry, device=world.device, dag=dag
    )
    if not validation["ok"] or result.exit_state != entry:
        raise ValueError(f"JOINT_FACTORY_PHYSICAL_VALIDATION_FAILED: {validation}")
    document = encode_result(
        result,
        entry_state=entry,
        dag=dag,
        device=world.device,
        validation=validation,
        job={"strategy": {"kind": "nonzoned"}, "case": {"seed": 0}},
        provenance={"joint_family": family},
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
    ports = {}
    if any(m.startswith("raw_t_postselection:") for m in members):
        # This exact in-memory result already passed validate_result above.
        # Derive exposure without repeating the same validation a second time.
        activity = derive_activity(document)
        noise = model_for("noise/v1").evaluate(activity, document, noise_params)
        for i, member in enumerate(members):
            if not member.startswith("raw_t_postselection:"):
                continue
            by_bit = {
                n.clbits[0]: n.result.measurement_id
                for n in dag.nodes
                if n.result is not None
            }
            mids = tuple(by_bit[c] for c in clbit_ranges[i])
            ports[member] = projected_raw_port(
                activity,
                noise["noise"]["channels"],
                atom_groups[i],
                mids,
                shots=shots,
                seed=seed,
                trace_sha256=trace_hash,
                noise_sha256=noise["params_hash"],
            )
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
    group = {
        "family": family,
        "members": details,
        "phase_durations_us": phases or [0.0],
        "validation_ok": True,
        "trace_sha256": trace_hash,
        "raw_ports": ports,
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
    }
    output.mkdir(parents=True, exist_ok=True)
    group_key = joint_key(members)
    for suffix, data in (("trace", document), ("group", group)):
        (output / f"{group_key}.{suffix}.json").write_text(
            json.dumps(data, separators=(",", ":")), encoding="utf-8"
        )
    return group
