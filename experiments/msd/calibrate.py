"""Measure actual component lowering under the MSD standard, not factory yield."""

import argparse
import inspect
import json
from collections import defaultdict
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.activity import derive_activity
from nadit_physical_compiler.compiler import compile_physical
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.placement import GatePairCatalog
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_result
from nadit_physical_compiler.strategies.nonzoned import NonZonedStrategy
from nadit_physical_compiler.validation import validate_result

from modules.codes.rotated_surface import TransversalCNOTComponent, get_component

from .standard import REFERENCE_PATH, STANDARD_ID, ExperimentSpec, build_world

CALIBRATION_OPERATIONS = (
    "initialize_0",
    "initialize_plus",
    "se_round",
    "logical_x",
    "logical_y",
    "logical_z",
    "logical_s",
    "logical_sdag",
    "prepare_y",
    "raw_t",
    "logical_mx",
    "logical_mz",
    "transversal_cnot",
)


def source_snapshot() -> dict[str, str]:
    """Fingerprint local code used by the calculation, independent of dirty HEAD."""
    root = Path(__file__).resolve().parents[2]
    expected_compiler = (
        root / "modules/physical_compiler/src/nadit_physical_compiler/compiler.py"
    ).resolve()
    loaded_source = inspect.getsourcefile(compile_physical)
    if loaded_source is None or Path(loaded_source).resolve() != expected_compiler:
        raise ValueError(
            "Physical compiler must be imported from this experiment checkout; "
            "put its modules/physical_compiler/src first on PYTHONPATH."
        )
    paths = [
        path
        for directory in (
            "modules/physical_compiler/src",
            "modules/codes",
            "experiments/msd",
        )
        for path in (root / directory).rglob("*.py")
        if "tests" not in path.parts
    ]
    # The reference is reread for every world; changes must invalidate a run
    # even when all Python source files and the repository HEAD are unchanged.
    paths.append(REFERENCE_PATH)
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }


def _union_duration(intervals: list[tuple[float, float]]) -> float:
    total, end = 0.0, float("-inf")
    for start, stop in sorted(intervals):
        total += max(0.0, stop - max(start, end))
        end = max(end, stop)
    return total


def summarize(document: dict[str, Any]) -> dict[str, Any]:
    """Derive additive exposure and wall-time unions from admitted Atom IR.

    Noise exposure here means action counts and atom-time, not a probability of
    logical failure. Busy + idle is independently checked for the whole world.
    """
    activity = derive_activity(document)
    exposure: dict[str, dict[str, float]] = defaultdict(
        lambda: {"action_count": 0, "atom_events": 0, "atom_us": 0.0}
    )
    intervals = []
    positions = [
        (a["position"]["x"], a["position"]["y"])
        for a in document["entry_state"]["atoms"]
    ]
    for event in activity.events:
        row = exposure[event.kind]
        row["action_count"] += 1
        row["atom_events"] += len(event.atoms)
        row["atom_us"] += len(event.atoms) * event.duration_us
        positions.extend(event.starts)
        positions.extend(event.ends)
        if event.kind in ("Load", "Move", "Store"):
            intervals.append((event.start_us, event.start_us + event.duration_us))
    idle = sum(a.idle_us for a in activity.per_atom)
    busy = sum(a.busy_us for a in activity.per_atom)
    atom_time = len(activity.per_atom) * activity.duration_us
    if abs(busy + idle - atom_time) > max(1e-6, atom_time * 1e-10):
        raise ValueError("Whole-world busy + idle does not conserve atom-time.")
    xs, ys = zip(*positions, strict=True)
    return {
        "execution_duration_us": activity.duration_us,
        "atom_count": len(activity.per_atom),
        "atom_time_us": atom_time,
        "atom_idle_us": idle,
        "atom_busy_us": busy,
        "movement_distance_atom_um": sum(a.move_distance_um for a in activity.per_atom),
        "transport_elapsed_us": _union_duration(intervals),
        "transport_action_sum_us": sum(stop - start for start, stop in intervals),
        "trajectory_bbox_um": [min(xs), min(ys), max(xs), max(ys)],
        "trajectory_bbox_area_um2": (max(xs) - min(xs)) * (max(ys) - min(ys)),
        "exposure_by_action": dict(exposure),
        "accepted_outputs": None,
        "accepted_output_throughput_per_s": None,
        "logical_error_probability": None,
        "physical_validation_ok": document["validation"]["ok"],
    }


def calibrate(
    spec: ExperimentSpec, operation: str, *, factory_index: int = 0
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Lower one actual code component with every factory atom present.

    Other components are idle spectators. This is a per-invocation calibration,
    not N-pipeline scheduling or an accepted-output production measurement.
    """
    if operation == "logical_h":
        raise ValueError(
            "logical_h requires its physical permutation template path; "
            "source-only lowering omits carrier rotation and is not calibrated here."
        )
    if operation not in CALIBRATION_OPERATIONS:
        raise ValueError(
            f"Unsupported source-only calibration operation: {operation!r}."
        )
    snapshot = source_snapshot()
    world = build_world(spec)
    control = world.patch(factory_index, "W1")
    ids = control.binding.atom_ids
    if operation == "transversal_cnot":
        source = TransversalCNOTComponent(spec.distance).source_qasm
        ids += world.patch(factory_index, "W2").binding.atom_ids
    else:
        source = get_component(operation, spec.distance).source_qasm
    dag = loads_qasm(source)
    source_hash = sha256(source.encode("utf-8")).hexdigest()
    entry = replace(world.state, qubit_to_atom=ids)
    strategy = NonZonedStrategy(
        "transport", GatePairCatalog.from_pair_arrays(world.device)
    )
    started = perf_counter()
    result = compile_physical(dag, world.device, strategy=strategy, entry_state=entry)
    compile_wall_s = perf_counter() - started
    validation = validate_result(
        result, entry_state=entry, device=world.device, dag=dag
    )
    if not validation["ok"]:
        raise ValueError(f"Physical validation failed: {validation}")
    if result.exit_state != entry:
        raise ValueError(
            "Component must retain and return every atom to its entry home."
        )
    document = encode_result(
        result,
        entry_state=entry,
        job={"strategy": {"kind": "nonzoned"}, "case": {"seed": 0}},
        provenance={
            "standard": STANDARD_ID,
            "component_source_sha256": source_hash,
            "source_tree_sha256": canonical_hash(snapshot),
        },
        dag=dag,
        device=world.device,
        inputs={
            "qasm_sha256": source_hash,
            "device_sha256": canonical_hash(encode_device(world.device)),
        },
        validation=validation,
    )
    row = {
        "schema": "nadit.msd.component_calibration/1",
        "standard": STANDARD_ID,
        "scope": "one_component_in_complete_spectator_world",
        "parameters": asdict(spec),
        "factory_index": factory_index,
        "operation": operation,
        "compile_wall_s": compile_wall_s,
        "metrics": summarize(document),
        "source_sha256": source_hash,
        "device_sha256": canonical_hash(encode_device(world.device)),
        "source_tree_sha256": canonical_hash(snapshot),
        "physical_execution": False,
        "measurement_values": "compiler fixtures; not sampled quantum outcomes",
    }
    if source_snapshot() != snapshot:
        raise ValueError(
            "Sources changed during calibration; discard and rerun the cell."
        )
    return row, document


def main() -> None:
    """Write one compact measurement and optionally its reproducible full witness."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, required=True)
    parser.add_argument("--pipelines", type=int, required=True)
    parser.add_argument("--operation", choices=CALIBRATION_OPERATIONS, required=True)
    parser.add_argument("--factory-index", type=int, default=0)
    parser.add_argument("--padding", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--witness", action="store_true")
    args = parser.parse_args()
    row, document = calibrate(
        ExperimentSpec(args.distance, args.pipelines, window_padding_um=args.padding),
        args.operation,
        factory_index=args.factory_index,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(row, stream, indent=2, allow_nan=False)
        stream.write("\n")
    if args.witness:
        with args.output.with_suffix(".result.json").open(
            "x", encoding="utf-8"
        ) as stream:
            json.dump(document, stream, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"output": str(args.output), "metrics": row["metrics"]}))


if __name__ == "__main__":
    main()
