"""Run from the repository root: python examples/demo_code_topology.py."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qec_schedule.qec import create_code


def topology(code):
    return {
        "code": code.name,
        "data_qubits": code.data_qubits(),
        "ancilla_qubits": code.ancilla_qubits(),
        "stabilizers": [{"id": s.id, "ancilla": s.ancilla, "terms": s.operator.terms,
                         "interactions": s.interactions} for s in code.stabilizers()],
        "logical_x": [op.terms for op in code.logical_x()],
        "logical_z": [op.terms for op in code.logical_z()],
    }


if __name__ == "__main__":
    print(json.dumps(topology(create_code()), indent=2))
