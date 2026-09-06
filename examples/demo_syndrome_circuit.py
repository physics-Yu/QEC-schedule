"""Print interaction sequences and export physical gates (not a hardware trace)."""
import argparse
from collections import Counter
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from qec_schedule.qec import create_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--primitive", choices=("CZ", "CNOT"), default="CZ")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--block-id", default="L0")
    parser.add_argument("--output", type=Path, default=Path("results/syndrome_circuit.json"))
    args = parser.parse_args()
    code = create_code(block_id=args.block_id)
    try:
        circuit = code.syndrome_round(rounds=args.rounds, primitive=args.primitive)
    except ValueError as exc:
        parser.error(str(exc))
    for check in code.stabilizers():
        sequence = " -> ".join(f"{q} [slot {slot}]" for slot, q in check.interactions)
        direction = "ancilla -> data" if check.basis == "X" else "data -> ancilla"
        print(f"{check.id} ({check.ancilla}), CNOT {direction}: {sequence}")
    print("Gate counts:", dict(sorted(Counter(g.gate_type.value for g in circuit.gates).items())))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(circuit.to_dict(), indent=2), encoding="utf-8")
    print(f"Physical circuit: {args.output.resolve()}")


if __name__ == "__main__":
    main()
