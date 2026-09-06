"""Step 5: export unscheduled action requests and show CZ / measurement chains."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.qec import create_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/hardware_default.yaml")
    parser.add_argument("--primitive", choices=("CZ", "CNOT"), default="CZ")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    try:
        config, code = load_hardware_config(args.config), create_code()
        circuit = code.syndrome_round(rounds=args.rounds, primitive=args.primitive)
        state = build_initial_state(code, config)
        plan = GateLowerer(config.timing).lower(circuit, state)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / "experimental_requests.json"
    output.write_text(json.dumps(plan.to_dict(), indent=2), encoding="utf-8")
    print(f"Physical gates: {len(circuit.gates)}; experimental requests: {len(plan.actions)}")
    print("Action counts:", dict(sorted(Counter(a.action_type.value for a in plan.actions).items())))
    print("NOT SCHEDULED: all start_time fields are null; durations are estimates in us.")
    for kind in (args.primitive, "MEASURE_Z", "RESET"):
        gate = next(g for g in circuit.gates if g.gate_type == kind and (kind != "RESET" or g.metadata.get("round") == 0))
        print(f"\n{gate.gate_type.value} {gate.qubits} ->")
        for action in plan.actions_for_gate(gate.id):
            route = ", ".join(f"{s.zone}/{s.site}->{t.zone}/{t.site}" for s, t in zip(action.sources, action.targets))
            print(f"  {action.action_type.value:12s} {route:55s} {action.duration:8.3f} us")
    print(f"\nRequests: {output.resolve()}")


if __name__ == "__main__":
    main()
