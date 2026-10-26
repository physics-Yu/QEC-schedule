"""Jointly compile a real SE round across factory instances in one full world."""

import argparse
import json
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any, Literal

from nadit_physical_compiler.compiler import compile_physical
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_result
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result

from .calibrate import source_snapshot, summarize
from .parallel_se_metrics import RecordedStrategy
from .parallel_se_source import assemble_se
from .standard import STANDARD_ID, ExperimentSpec, build_world

PARALLEL_SE_VERSION = "nadit.msd.parallel_se/1"


def compile_se_case(
    spec: ExperimentSpec,
    mode: Literal["joint", "serial", "solo"] = "joint",
    *,
    factory_index: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Compile all selected SE sources once with the existing global scheduler.

    Joint: one W1 SE per factory with no cross-factory dependencies. Serial:
    the same sources with explicit full barriers between instances. Solo: one
    selected W1 SE while retaining the identical complete spectator world.
    Returns a compact row, a full validated result, and scheduling evidence.
    """
    if mode not in ("joint", "serial", "solo"):
        raise ValueError(f"Unknown SE execution mode {mode!r}.")
    indices: tuple[int, ...]
    if mode == "solo":
        if type(factory_index) is not int or not 0 <= factory_index < spec.pipelines:
            raise ValueError("Solo control requires a valid explicit factory index.")
        indices = (factory_index,)
    else:
        if factory_index is not None:
            raise ValueError("Joint/serial modes select all factories, not one index.")
        indices = tuple(range(spec.pipelines))
    snapshot = source_snapshot()
    world = build_world(spec)
    source = assemble_se(world, indices, serial=mode == "serial")
    entry = replace(world.state, qubit_to_atom=source.atom_ids)
    assert world.device.readout is not None
    base = NonZonedStrategy(
        "transport",
        GatePairCatalog.from_pair_arrays(world.device),
        max_measurements=world.device.readout.max_atoms,
    )
    atom_owners = {
        atom: i for i in indices for atom in world.patch(i, "W1").binding.atom_ids
    }
    recorder = RecordedStrategy(base, source.node_owners, atom_owners)
    started = perf_counter()
    result = compile_physical(
        source.dag, world.device, strategy=recorder, entry_state=entry
    )
    compile_wall_s = perf_counter() - started
    validation_started = perf_counter()
    validation = validate_result(
        result, entry_state=entry, device=world.device, dag=source.dag
    )
    validation_wall_s = perf_counter() - validation_started
    if not validation["ok"] or result.exit_state != entry:
        raise ValueError(f"Joint SE physical validation/return failed: {validation}")
    if len(result.measurements) != source.expected_results:
        raise ValueError(
            "SE results do not cover every selected instance exactly once."
        )
    source_hash = sha256(source.source_qasm.encode("utf-8")).hexdigest()
    document = encode_result(
        result,
        entry_state=entry,
        job={"strategy": {"kind": "nonzoned"}, "case": {"seed": 0}},
        provenance={
            "standard": STANDARD_ID,
            "experiment": PARALLEL_SE_VERSION,
            "source_tree_sha256": canonical_hash(snapshot),
        },
        dag=source.dag,
        device=world.device,
        inputs={
            "qasm_sha256": source_hash,
            "device_sha256": canonical_hash(encode_device(world.device)),
        },
        validation=validation,
    )
    document["source_qasm"] = source.source_qasm
    document["se_instances"] = {
        "mode": mode,
        "factory_indices": indices,
        "role": "W1",
        "node_owners": source.node_owners,
        "measurement_owners": source.measurement_owners,
        "submitted_at_us": 0,
    }
    schedule = recorder.report(result, entry, world.device)
    row = {
        "schema": PARALLEL_SE_VERSION,
        "standard": STANDARD_ID,
        "parameters": asdict(spec),
        "mode": mode,
        "factory_indices": indices,
        "active_patch_role": "W1",
        "se_instances": len(indices),
        "expected_measurements": source.expected_results,
        "compile_wall_s": compile_wall_s,
        "validation_wall_s": validation_wall_s,
        "metrics": summarize(document),
        "scheduler": {
            "identity": "compile_physical / NonZonedStrategy / ReadyScheduler",
            "single_physical_compile": True,
            "submitted_at_us": 0,
            "time_partition_us": schedule["time_partition_us"],
            "concurrency": schedule["concurrency"],
            "per_factory": schedule["per_factory"],
            "layer_count": len(schedule["layers"]),
            "transport_batch_count": len(schedule["transport_batches"]),
        },
        "source_sha256": source_hash,
        "source_tree_sha256": canonical_hash(snapshot),
        "device_sha256": canonical_hash(encode_device(world.device)),
        "physical_execution": False,
        "scope": "joint SE round; not a complete distillation production cycle",
        "measurement_values": "compiler fixtures; not sampled quantum outcomes",
    }
    if source_snapshot() != snapshot:
        raise ValueError("Sources changed during SE case; discard and rerun.")
    return row, document, schedule


def main() -> None:
    """Save a case and its complete physical/scheduler witnesses exclusively."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, required=True)
    parser.add_argument("--pipelines", type=int, required=True)
    parser.add_argument("--mode", choices=("joint", "serial", "solo"), default="joint")
    parser.add_argument("--factory-index", type=int)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    row, document, schedule = compile_se_case(
        ExperimentSpec(args.distance, args.pipelines),
        args.mode,
        factory_index=args.factory_index,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for path, value in (
        (args.output, row),
        (args.output.with_suffix(".result.json"), document),
        (args.output.with_suffix(".schedule.json"), schedule),
    ):
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "mode": args.mode,
                "round_time_us": row["metrics"]["execution_duration_us"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
