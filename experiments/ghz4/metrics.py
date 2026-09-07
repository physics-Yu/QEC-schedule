"""Experiment-level metrics derived from the shared execution trace."""
from collections import Counter
import math

from qec_schedule.compiler import GateType
from qec_schedule.trace import epoch_metrics


def _logical_depth(program):
    depth = {}
    for instruction in program.instructions:
        depth[instruction.id] = 1 + max((depth[parent] for parent in instruction.dependencies),
                                        default=0)
    return max(depth.values(), default=0)


def _critical_path(trace):
    end_by_id = {}
    path_by_id = {}
    for epoch in sorted(trace["epochs"], key=lambda item: (item["start_time"], item["id"])):
        dependency_end = max((end_by_id.get(parent, 0.0) for parent in epoch["dependencies"]),
                             default=0.0)
        path = max((path_by_id.get(parent, 0.0) for parent in epoch["dependencies"]),
                   default=0.0) + epoch["duration"]
        end_by_id[epoch["id"]] = epoch["end_time"]
        path_by_id[epoch["id"]] = path
    dependency_wait = sum(max(0.0, epoch["start_time"] - max(
        (end_by_id.get(parent, 0.0) for parent in epoch["dependencies"]), default=0.0))
                          for epoch in trace["epochs"])
    return max(path_by_id.values(), default=0.0), dependency_wait


def _operation_span(trace, operation_id):
    records = [epoch for epoch in trace["epochs"] if operation_id in epoch.get("logical_ops", [])]
    if not records:
        return None
    return {"start_time": min(epoch["start_time"] for epoch in records),
            "end_time": max(epoch["end_time"] for epoch in records),
            "epoch_ids": [epoch["id"] for epoch in records]}


def build_metrics(trace, program, circuit, *, basis, profile):
    base = epoch_metrics(trace)
    counts = Counter(gate.gate_type.value for gate in circuit.gates)
    ghz_cz = sum(gate.gate_type == GateType.CZ and
                 str(gate.metadata.get("logical_operation_id", "")).startswith("GHZ_CNOT")
                 for gate in circuit.gates)
    qec_cz = sum(gate.gate_type == GateType.CZ and
                 str(gate.metadata.get("logical_operation_id", "")).startswith("QEC_R")
                 for gate in circuit.gates)
    movement = [epoch for epoch in trace["epochs"] if epoch["type"] == "AOD_MOVEMENT"]
    distances = [
        math.dist(epoch["source_positions"][atom], epoch["target_positions"][atom])
        for epoch in movement for atom in epoch["atoms"]
    ]
    critical_path, dependency_wait = _critical_path(trace)
    logical_spans = {
        operation: _operation_span(trace, operation)
        for operation in ("GHZ_CNOT_L0_L1", "GHZ_CNOT_L0_L2", "GHZ_CNOT_L1_L3")
    }
    qec_epochs = [epoch for epoch in trace["epochs"]
                  if epoch["type"] == "RYDBERG" and
                  any(op.startswith("QEC_R") for op in epoch.get("logical_ops", []))]
    fanout_epochs = [epoch for epoch in trace["epochs"]
                     if epoch["type"] == "RYDBERG" and
                     any(op in ("GHZ_CNOT_L0_L2", "GHZ_CNOT_L1_L3")
                         for op in epoch.get("logical_ops", []))]
    rejection_counts = Counter(item.get("reason") for item in trace.get("diagnostics", [])
                               if item.get("reason"))
    return {
        **base,
        "experiment": "ghz4",
        "basis": basis,
        "hardware_profile": profile,
        "logical_operation_count": len(program.instructions),
        "logical_depth": _logical_depth(program),
        "logical_cnot_count": 3,
        "logical_entangling_depth": 2,
        "qec_round_count": sum(instruction.rounds for instruction in program.instructions
                                if instruction.operation.value == "LogicalQECBarrier"),
        "physical_gate_count": len(circuit.gates),
        "physical_cz_count": counts["CZ"],
        "ghz_transversal_cz_count": ghz_cz,
        "qec_cz_count": qec_cz,
        "single_qubit_gate_count": sum(counts[name] for name in ("H", "X", "Y", "Z")),
        "measurement_count": counts["MEASURE_X"] + counts["MEASURE_Z"],
        "reset_count": counts["RESET"],
        "prepare_count": counts["PREPARE"],
        "number_of_AOD_epochs": len(movement),
        "total_atom_distance_um": sum(distances),
        "maximum_atom_distance_um": max(distances, default=0.0),
        "total_motion_time_us": sum(epoch["duration"] for epoch in movement),
        "peak_atoms_per_AOD_epoch": max((len(epoch["atoms"]) for epoch in movement), default=0),
        "number_of_Rydberg_epochs": len([epoch for epoch in trace["epochs"]
                                         if epoch["type"] == "RYDBERG"]),
        "peak_pairs_per_Rydberg_epoch": max((epoch.get("pair_count", 0)
                                              for epoch in trace["epochs"]
                                              if epoch["type"] == "RYDBERG"), default=0),
        "peak_qec_pairs_per_Rydberg_epoch": max((epoch.get("pair_count", 0)
                                                  for epoch in qec_epochs), default=0),
        "peak_fanout_pairs_per_Rydberg_epoch": max((epoch.get("pair_count", 0)
                                                     for epoch in fanout_epochs), default=0),
        "makespan_us": trace["duration"],
        "critical_path_time_us": critical_path,
        "dependency_wait_time_us": dependency_wait,
        "resource_wait_time_us": 0.0,
        "geometry_wait_time_us": 0.0,
        "diagnostic_counts": dict(rejection_counts),
        "logical_operation_spans": logical_spans,
        "definitions": {
            "quantum_state": "Ideal symbolic GHZ stabilizer expectations; qec_schedule does not simulate amplitudes or noise.",
            "peak_pairs_per_Rydberg_epoch": "Largest pair batch read directly from the RYDBERG epochs.",
            "critical_path_time_us": "Longest dependency path over the physical epoch DAG.",
        },
    }
