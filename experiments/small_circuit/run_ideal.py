"""Sample a small OpenQASM circuit or a serialized NADiT PhysicalDAG."""

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from qiskit.circuit.library import (
    CPhaseGate,
    CZGate,
    HGate,
    PhaseGate,
    TdgGate,
    TGate,
    XGate,
)
from qiskit.quantum_info import Statevector

sys.path.insert(
    0, str(Path(__file__).resolve().parents[2] / "modules/physical_compiler/src")
)
from nadit_physical_compiler.frontend import GateSet, loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.serialization import decode_dag, encode_dag

GATES = {
    "h": HGate,
    "t": TGate,
    "tdg": TdgGate,
    "p": PhaseGate,
    "cz": CZGate,
    "cp": CPhaseGate,
}


def _shot(dag: PhysicalDAG, rng: np.random.Generator) -> list[int]:
    """Return the final classical wires for one all-zero-input Born trajectory."""
    state = Statevector.from_int(0, 2**dag.num_qubits)
    indices = np.arange(len(state.data))
    classical = [0] * dag.num_clbits
    outcomes: dict[int, int] = {}
    for op in dag.nodes:
        if (
            op.condition
            and outcomes[op.condition.result.measurement_id] != op.condition.value
        ):
            continue
        if op.name in ("barrier", "global_phase"):
            continue
        if op.name in ("measure", "reset"):
            (wire,) = op.qubits
            bit = int(rng.random() < state.probabilities([wire])[1])
            projected = np.where(((indices >> wire) & 1) == bit, state.data, 0)
            state = Statevector(projected / np.linalg.norm(projected))
            if op.name == "measure":
                (clbit,) = op.clbits
                assert op.result is not None
                outcomes[op.result.measurement_id] = classical[clbit] = bit
            elif bit:
                state = state.evolve(XGate(), [wire])
        else:
            state = state.evolve(GATES[op.name](*op.params), list(op.qubits))
    return classical


def main() -> None:
    """Read a circuit, optionally persist its IR, and print a seeded shot histogram."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("circuit", type=Path, help="OpenQASM or encode_dag JSON")
    parser.add_argument("--ir-out", type=Path, help="write native encode_dag JSON")
    parser.add_argument("--shots", type=int, default=256)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument(
        "--bits", type=int, nargs="+", help="output clbits, least significant first"
    )
    args = parser.parse_args()
    if args.shots < 1 or args.seed < 0:
        parser.error("shots must be positive and seed nonnegative")
    data = args.circuit.read_bytes()
    if args.circuit.suffix.lower() == ".json":
        dag = decode_dag(json.loads(data))
    else:
        dag = loads_qasm(data.decode("utf-8-sig"), gate_set=GateSet(tuple(GATES)))
    unsupported = (
        {op.name for op in dag.nodes}
        - GATES.keys()
        - {"barrier", "global_phase", "measure", "reset"}
    )
    if unsupported:
        parser.error(f"ideal trajectory sampler does not support {sorted(unsupported)}")
    if dag.num_qubits > 16 or not any(op.name == "measure" for op in dag.nodes):
        parser.error("expected at most 16 qubits and at least one measurement")
    bits = list(range(dag.num_clbits)) if args.bits is None else args.bits
    if len(set(bits)) != len(bits) or any(i < 0 or i >= dag.num_clbits for i in bits):
        parser.error("output bits must be distinct valid classical-wire indices")
    ir = encode_dag(dag)
    if args.ir_out:
        if args.ir_out.resolve() == args.circuit.resolve():
            parser.error("IR output must differ from the input file")
        args.ir_out.write_text(json.dumps(ir, indent=2) + "\n", encoding="utf-8")
    histogram: Counter[str] = Counter()
    for shot in range(args.shots):
        classical = _shot(
            dag, np.random.default_rng(np.random.SeedSequence([args.seed, shot]))
        )
        histogram["".join(str(classical[i]) for i in reversed(bits))] += 1
    canonical = json.dumps(ir, sort_keys=True, separators=(",", ":")).encode()
    print(
        json.dumps(
            {
                "model": "ideal Born trajectories from the all-zero state",
                "input_sha256": hashlib.sha256(data).hexdigest(),
                "dag_sha256": hashlib.sha256(canonical).hexdigest(),
                "qubits": dag.num_qubits,
                "nodes": len(dag.nodes),
                "edges": len(dag.edges),
                "output_clbits_lsb_first": bits,
                "shots": args.shots,
                "seed": args.seed,
                "histogram": dict(sorted(histogram.items())),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
