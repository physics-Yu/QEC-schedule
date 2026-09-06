"""Run a complete surface-code syndrome cycle and export its execution trace."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from qec_schedule.hardware import load_hardware_config
from qec_schedule.simulation import run_cycle, save_run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/hardware_default.yaml')
    parser.add_argument('--primitive', choices=('CZ', 'CNOT'), default='CZ')
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'results')
    parser.add_argument('--no-plot', action='store_true', help='Export only trace and metrics')
    parser.add_argument('--gif', action='store_true', help='Also render a Matplotlib animation GIF (slower)')
    args = parser.parse_args()
    try:
        trace, result = run_cycle(load_hardware_config(args.config), rounds=args.rounds, primitive=args.primitive)
        save_run(trace, result, args.output_dir)
        if not args.no_plot:
            from qec_schedule.visualization.animation import save_animation
            save_animation(trace, args.output_dir / 'demo_animation.html')
            from qec_schedule.visualization.timeline import save_timeline
            save_timeline(trace, args.output_dir / 'demo_timeline.png')
            if args.gif:
                from qec_schedule.visualization.animation import create_matplotlib_animation
                animation = create_matplotlib_animation(trace)
                animation.save(args.output_dir / 'demo_animation.gif', writer='pillow', fps=25)
    except (ValueError, OSError, RuntimeError) as exc:
        parser.error(str(exc))
    print(f"Completed {result['physical_gate_count']} gates / {result['action_count']} actions in {trace['duration']:.3f} us")
    print(f"Movement epochs: {result['movement_epochs']}; entangling batches: {result['entangling_batches']}")
    print(args.output_dir.resolve())


if __name__ == '__main__':
    main()
