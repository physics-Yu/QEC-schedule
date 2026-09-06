"""Step 4: map any QECCode to configured hardware and render a static array."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.qec import create_code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=ROOT / "configs/hardware_default.yaml")
    parser.add_argument("--block-id", default="L0")
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    parser.add_argument("--no-plot", action="store_true", help="Export state JSON without requiring Matplotlib")
    args = parser.parse_args()
    try:
        state = build_initial_state(create_code(block_id=args.block_id), load_hardware_config(args.config))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    snapshot = args.output_dir / "hardware_state.json"
    snapshot.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
    print(f"Atoms: {len(state.atoms)}; mapped qubits: {len(state.qubit_to_atom)}; time: {state.current_time:g} us")
    for zone in state.zones:
        print(f"{zone.id}: {len(state.atoms_in_zone(zone.id))}/{zone.capacity} atoms, {len(zone.sites)} sites, {len(zone.pair_slots)} pair slots")
    print(f"State: {snapshot.resolve()}")
    if not args.no_plot:
        from qec_schedule.visualization.layout import save_layout
        try:
            figure_path = save_layout(state, args.output_dir / "hardware_layout.png")
        except ModuleNotFoundError as exc:
            if exc.name != "matplotlib":
                raise
            parser.error('Install plotting support: python -m pip install -e ".[visualization]"')
        print(f"Layout: {figure_path.resolve()}")


if __name__ == "__main__":
    main()
