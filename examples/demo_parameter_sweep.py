"""Run YAML-defined hardware parameter cases and retain every trace."""
import argparse
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from qec_schedule.hardware import load_hardware_config
from qec_schedule.sweep import load_sweep, run_sweep, save_sweep_plot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT / 'configs/hardware_default.yaml')
    parser.add_argument('--sweep', type=Path, default=ROOT / 'configs/sweep_default.yaml')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'results/sweep')
    parser.add_argument('--rounds', type=int, default=1)
    parser.add_argument('--primitive', choices=('CZ', 'CNOT'), default='CZ')
    parser.add_argument('--no-plot', action='store_true')
    args = parser.parse_args()
    try:
        rows = run_sweep(load_hardware_config(args.config), load_sweep(args.sweep), args.output_dir,
                         rounds=args.rounds, primitive=args.primitive)
        if not args.no_plot:
            save_sweep_plot(rows, args.output_dir / 'sweep.png')
    except (ValueError, RuntimeError, OSError) as exc:
        parser.error(str(exc))
    for row in rows:
        print(f"{row['case']:26s} {row['total_execution_time_us']:10.3f} us")
    print(args.output_dir.resolve())


if __name__ == '__main__':
    main()
