"""Exercise dynamic readiness; completion order is illustrative, not timed."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qec_schedule.compiler import PhysicalCircuitDAG
from qec_schedule.qec import create_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--primitive", choices=("CZ", "CNOT"), default="CZ")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    try:
        dag = PhysicalCircuitDAG(create_code().syndrome_round(rounds=args.rounds, primitive=args.primitive))
    except ValueError as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "physical_dag.json").write_text(json.dumps(dag.to_dict(), indent=2), encoding="utf-8")
    initial_ready = [g.id for g in dag.ready_operations()]
    print(f"Nodes: {len(dag.gates)}, edges: {dag.edge_count}")
    print(f"Initially ready: {len(initial_ready)}")
    for gate in dag.ready_operations():
        print(f"  {gate.id}: {gate.gate_type.value} {', '.join(gate.qubits)}")
    transitions = []
    while not dag.is_complete:
        ready = [gate.id for gate in dag.ready_operations()]
        dag.start_operations(ready)
        running = dag.running_operations()
        if not running:
            raise RuntimeError("Unfinished DAG has no running or ready gates")
        # Finish a single gate, then immediately reconsider new ready operations.
        # There are deliberately no durations, fixed layers or hardware resources.
        completed = running[0].id
        dag.complete(completed)
        transitions.append({"started": ready, "completed": completed,
                            "ready_after": [g.id for g in dag.ready_operations()],
                            "running_after": [g.id for g in dag.running_operations()]})
    progress = {"schema_version": 1, "kind": "dependency_progress_demo",
                "initial_ready": initial_ready, "transitions": transitions,
                "completed_count": len(dag.completed_operations()), "is_complete": dag.is_complete}
    (args.output_dir / "dag_progress.json").write_text(json.dumps(progress, indent=2), encoding="utf-8")
    print(f"Completed: {len(dag.completed_operations())}; ready: {len(dag.ready_operations())}; running: {len(dag.running_operations())}")
    print(f"DAG and dependency progress: {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
