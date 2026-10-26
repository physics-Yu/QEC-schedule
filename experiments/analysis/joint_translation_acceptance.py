"""Bounded native code-block relocation acceptance in a complete shared world.

An explicitly vacant receiving patch is part of this fixture. These fragments
prove mechanical identity-preserving delivery, not an L1/L2 token lifecycle,
continuous throughput, transported state fidelity or a code conversion.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.activity import derive_activity
from nadit_physical_compiler.compiler import compile_physical
from nadit_physical_compiler.experiments.journal import write_json
from nadit_physical_compiler.experiments.version import check_version, code_version
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import (
    decode_layout,
    decode_result,
    encode_dag,
    encode_device,
    encode_layout,
    encode_result,
)
from nadit_physical_compiler.state import SLMHolder
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result

from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes.rotated_surface.joint_factory_source import factory_component_source
from modules.codes.rotated_surface.translation import BlockTranslationComponent


def run(output: Path) -> dict[str, Any]:
    """Compile three declared d3 frontiers; save exact traces and native schedules.

    Args:
        output: New output directory; existing evidence is never overwritten.
    Returns:
        Audited fragment results with source identity and explicit scope limits.
    Raises:
        ValueError: Output exists, compilation fails or an evidence check fails.
    """
    if output.exists():
        raise ValueError("Use a new output directory; existing evidence is retained")
    source_path = Path(__file__).resolve().relative_to(Path.cwd()).as_posix()
    version = code_version(allow_dirty=True, scope="msd", source_paths=[source_path])
    output.mkdir(parents=True)
    world = build_world(ExperimentSpec(3, 2))
    mover, receiver = world.patch(0, "W1"), world.patch(1, "W1")
    removed = set(receiver.binding.atom_ids)
    atoms = tuple(atom for atom in world.state.atoms if atom.id not in removed)
    write_json(
        output / "manifest.json",
        {
            "source_identity": version,
            "world": world.document(),
            "declared_vacant_receiver": receiver.binding.block_id,
            "atoms_absent_at_entry": sorted(removed),
            "fixture_scope": "Explicit vacancy, not a normal prepared L2 factory",
        },
    )
    rows = []
    for name, roles in (
        ("se_round", ("W2",)),
        ("logical_mx", ("W2",)),
        ("transversal_cnot", ("W2", "W3")),
    ):
        source = factory_component_source(name, 3)
        participants = tuple(
            atom for role in roles for atom in world.patch(0, role).binding.atom_ids
        )
        gate_atoms = tuple(participants[index] for index in source.wire_indices)
        entry = replace(
            world.state,
            atoms=atoms,
            qubit_to_atom=(*gate_atoms, *mover.binding.atom_ids),
        )
        base = loads_qasm(source.source_qasm)
        node, goal, exit_binding = BlockTranslationComponent(3).native_goal(
            world.device,
            world=entry,
            binding=mover.binding,
            target_origin=receiver.binding.origin,
            target_home_sites=receiver.home_sites,
            operation_id=len(base.nodes),
        )
        dag = PhysicalDAG(
            len(entry.qubit_to_atom),
            base.num_clbits,
            (*base.nodes, node),
            base.edges,
            global_phase=base.global_phase,
        )
        started = perf_counter()
        result = compile_physical(
            dag,
            world.device,
            entry_state=entry,
            strategy=NonZonedStrategy(
                "transport",
                GatePairCatalog.from_pair_arrays(world.device),
                transport_goals=(goal,),
            ),
        )
        compile_seconds = perf_counter() - started
        started = perf_counter()
        validation = validate_result(
            result, entry_state=entry, device=world.device, dag=dag
        )
        if not validation["ok"]:
            raise ValueError(f"Native validation failed: {validation}")
        before = {atom.id: atom for atom in entry.atoms}
        after = {atom.id: atom for atom in result.exit_state.atoms}
        assert before.keys() == after.keys()
        assert result.exit_state.qubit_to_atom == entry.qubit_to_atom
        assert result.exit_state.aod_grids == ()
        assert result.exit_state == replay(result.program, entry, world.device)
        destinations = dict(
            zip(mover.binding.atom_ids, receiver.home_sites, strict=True)
        )
        for atom_id, atom in after.items():
            if atom_id in destinations:
                site = destinations[atom_id]
                assert atom.position == world.device.site(site).position
                assert atom.holder == SLMHolder(site)
            else:
                assert atom == before[atom_id]
        assert exit_binding.atom_ids == mover.binding.atom_ids
        assert len(result.measurements) == source.result_count
        validation_seconds = perf_counter() - started
        document = encode_result(
            result,
            entry_state=entry,
            dag=dag,
            device=world.device,
            validation=validation,
            job={"strategy": {"kind": "nonzoned"}},
            provenance={
                "source_identity": version,
                "fragment": name,
                "qasm_scope": "Quantum member only; native DAG includes relocation",
                "entry_binding": asdict(mover.binding),
                "exit_binding": asdict(exit_binding),
            },
            inputs={
                "qasm_sha256": sha256(source.source_qasm.encode()).hexdigest(),
                "native_dag_sha256": canonical_hash(encode_dag(dag)),
                "device_sha256": canonical_hash(encode_device(world.device)),
                "entry_sha256": canonical_hash(encode_layout(entry)),
            },
        )
        document["source_qasm"] = source.source_qasm
        assert decode_result(document) == result
        write_json(output / f"{name}-trace.json", document)
        started = perf_counter()
        activity = derive_activity(document)
        moving = set(mover.binding.atom_ids)
        acting = set(gate_atoms)
        shared_loads = sum(
            event.kind == "Load"
            and bool(moving.intersection(event.atoms))
            and bool(acting.intersection(event.atoms))
            for event in activity.events
        )
        with (output / f"{name}-schedule.csv").open(
            "w", newline="", encoding="utf-8"
        ) as file:
            writer = csv.writer(file)
            writer.writerow(
                (
                    "step",
                    "action",
                    "start_us",
                    "end_us",
                    "kind",
                    "atom_ids",
                    "source_ids",
                    "relocation_atoms",
                    "quantum_atoms",
                )
            )
            for event in activity.events:
                writer.writerow(
                    (
                        event.step_index,
                        event.action_index,
                        event.start_us,
                        event.start_us + event.duration_us,
                        event.kind,
                        json.dumps(event.atoms),
                        json.dumps(event.source_ids),
                        len(moving.intersection(event.atoms)),
                        len(acting.intersection(event.atoms)),
                    )
                )
        row = {
            "component": name,
            "distance": 3,
            "aods": len(world.device.aods),
            "entry_atoms": len(atoms),
            "relocated_atoms": len(moving),
            "duration_us": result.program.duration_us,
            "quantum_measurements": len(result.measurements),
            "relocation_end_us": result.operations[goal.operation_id].end_us,
            "shared_load_actions": shared_loads,
            "mixed_layers": sum(
                goal.operation_id in layer.operation_ids
                and len(layer.operation_ids) > 1
                for layer in result.layers
            ),
            "action_counts": dict(Counter(e.kind for e in activity.events)),
            "movement_distance_um": sum(a.move_distance_um for a in activity.per_atom),
            "idle_atom_us": sum(a.idle_us for a in activity.per_atom),
            "compile_seconds": compile_seconds,
            "validation_seconds": validation_seconds,
            "activity_and_export_seconds": perf_counter() - started,
            "trace_sha256": canonical_hash(document),
            "validation_passed": True,
        }
        rows.append(row)
        write_json(output / f"{name}-audit.json", row)
    check_version(version)
    report = {
        "schema": "nadit.msd.joint_translation_acceptance/1",
        "source_identity": version,
        "results": rows,
        "physical_execution": False,
        "two_level_runtime_complete": False,
        "logical_quality": None,
        "human_visual_acceptance": False,
        "scope": "Code-owned identity relocation and real quantum fragments on one AOD",
    }
    write_json(output / "audit.json", report)
    return report


def main() -> None:
    """Run the explicitly bounded local acceptance fragments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cached", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            run_cached(args.output) if args.cached else run(args.output),
            allow_nan=False,
        )
    )


def run_cached(output: Path) -> dict[str, Any]:
    """Verify cached forward/backward relocations carry current-world endpoints.

    This is an explicit offline calibration witness; production role ownership
    and token handoff are outside its scope. One read-only replay must hit both
    caches, and a reverse request must use a different action identity.
    """
    from nadit_physical_compiler.device import Position

    from experiments.msd.joint_cache import JointCalibrationCache

    if output.exists():
        raise ValueError("Use a new output directory")
    version = code_version(
        allow_dirty=True,
        scope="msd",
        source_paths=[
            Path(__file__).resolve().relative_to(Path.cwd()).as_posix(),
            "modules/physical_compiler/cost_params/noise_illustrative.json",
        ],
    )
    output.mkdir(parents=True)
    world = build_world(ExperimentSpec(3, 2))
    source, receiver = world.patch(0, "W1"), world.patch(1, "W1")
    absent = set(receiver.binding.atom_ids)
    world = replace(
        world,
        state=replace(
            world.state,
            atoms=tuple(a for a in world.state.atoms if a.id not in absent),
            qubit_to_atom=tuple(
                a for a in world.state.qubit_to_atom if a not in absent
            ),
        ),
        patches=tuple(p for p in world.patches if p is not receiver),
    )
    original = world
    cache = JointCalibrationCache(output / "cache")
    noise = json.loads(
        Path(
            "modules/physical_compiler/cost_params/noise_illustrative.json"
        ).read_text()
    )
    member = "block_translation:factory0/W1"
    rows = []
    for direction, destination in (("outbound", receiver), ("return", source)):
        targets = {member: (destination.binding.origin, destination.home_sites)}
        members = (member, "se_round:factory0/W2")
        arguments = {
            "family": "stateful-offline-acceptance",
            "noise_params": noise,
            "shots": 1,
            "seed": 0,
            "transport_targets": targets,
        }
        record = cache.get_or_create(world, members, **arguments)
        hit = cache.lookup(world, members, **arguments)
        assert not record.action_hit and not record.probability_hit
        assert hit.action_hit and hit.probability_hit
        assert record.group == hit.group
        trace = json.loads(record.trace_path.read_text())
        result = decode_result(trace)
        update = record.group["state_transition"]["bindings"][member]
        current = world.patch(0, "W1")
        assert canonical_hash(asdict(current.binding)) == canonical_hash(
            update["entry"]
        )
        binding = replace(
            current.binding,
            origin=Position(**update["exit"]["origin"]),
            site_ids=tuple(tuple(pair) for pair in update["exit"]["site_ids"]),
        )
        world = replace(
            world,
            state=replace(result.exit_state, qubit_to_atom=world.state.qubit_to_atom),
            patches=tuple(
                replace(p, binding=binding, home_sites=tuple(update["home_sites"]))
                if p is current
                else p
                for p in world.patches
            ),
        )
        assert tuple(a.id for a in world.state.atoms) == tuple(
            a.id for a in original.state.atoms
        )
        assert decode_layout(trace["exit_state"]).atoms == world.state.atoms
        rows.append(
            {
                "direction": direction,
                "action_key": record.action_key,
                "probability_key": record.probability_key,
                "duration_us": result.program.duration_us,
                "trace_path": str(record.trace_path.resolve()),
                "trace_sha256": record.group["trace_sha256"],
                "software_seconds": record.software_seconds,
                "readonly_reuse_seconds": hit.software_seconds,
                "validation": trace["validation"],
                "current_world_sha256": canonical_hash(world.document()),
            }
        )
    assert world == original
    assert rows[0]["action_key"] != rows[1]["action_key"]
    check_version(version)
    report = {
        "schema": "nadit.msd.cached_translation_acceptance/1",
        "source_identity": version,
        "results": rows,
        "whole_world_returned": True,
        "readonly_cache_reuse": True,
        "two_level_runtime_complete": False,
        "logical_quality": None,
    }
    write_json(output / "audit.json", report)
    return report


if __name__ == "__main__":
    main()
