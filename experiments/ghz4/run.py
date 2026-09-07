"""Run the four-logical GHZ experiment end to end.

Example::

    python -m experiments.ghz4.run --config configs/ghz4_rich.yaml \
        --output runs/ghz4_rich

The default ``both`` mode produces independent Z- and X-basis shots.  They
share the same logical/physical design but have separate execution traces,
because the two final logical measurements are incompatible observables.
"""
import argparse
import json
from pathlib import Path

from qec_schedule.compiler import PhysicalCircuitDAG
from qec_schedule.hardware import build_initial_state, load_hardware_config
from qec_schedule.lowering import GateLowerer
from qec_schedule.scheduler import RuntimeScheduler
from qec_schedule.visualization.animation import save_animation
from qec_schedule.visualization.timeline import save_timeline

from .config import build_block_placements, hardware_summary, logical_block_visualization
from .logical_program import FourLogicalSurfaceCode, build_logical_program, build_physical_circuit
from .metrics import build_metrics
from .verify import verify_ghz_trace


def _write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False),
                    encoding="utf-8")
    return path


def run_shot(config_path, output_dir, *, basis, qec_rounds_after_prepare=1,
             qec_rounds_between_layers=1, qec_rounds_before_measure=1,
             primitive="CZ", make_gif=False):
    """Compile, schedule, validate and render one basis shot."""
    config_path = Path(config_path)
    output_dir = Path(output_dir)
    profile = config_path.stem
    config = load_hardware_config(config_path)
    code = FourLogicalSurfaceCode()
    program = build_logical_program(
        measurement_basis=basis,
        qec_rounds_after_prepare=qec_rounds_after_prepare,
        qec_rounds_between_layers=qec_rounds_between_layers,
        qec_rounds_before_measure=qec_rounds_before_measure,
    )
    circuit = build_physical_circuit(program, code=code,
                                     measurement_basis=basis, primitive=primitive)
    placements = build_block_placements(code, config)
    state = build_initial_state(code, config, placements=placements)

    # This is the repository's normal path: physical DAG -> semantic requests
    # -> runtime resource/geometry planner -> execution epochs.
    plan = GateLowerer().lower(circuit, state)
    trace = RuntimeScheduler(config).run(plan, state)
    trace["experiment"] = {
        "name": "4-logical GHZ state preparation",
        "id": "ghz4",
        "basis": basis,
        "logical_state": "(|0000>_L + |1111>_L) / sqrt(2)",
        "primitive": primitive,
        "profile": profile,
    }
    trace["configuration"] = {
        "profile": profile,
        "basis": basis,
        "code": code.name,
        "qec_rounds_after_prepare": qec_rounds_after_prepare,
        "qec_rounds_between_layers": qec_rounds_between_layers,
        "qec_rounds_before_measure": qec_rounds_before_measure,
        "primitive": primitive,
        "hardware": hardware_summary(config),
    }
    trace["logical_program"] = program.to_dict()
    trace["physical_gate_dag"] = PhysicalCircuitDAG(circuit).to_dict()
    trace["semantic_request_count"] = len(plan.requests)
    trace["visualization"] = {
        "logical_blocks": logical_block_visualization(code, config),
        "zone_layout": "dynamic_working_regions",
    }
    trace["metrics"] = build_metrics(trace, program, circuit, basis=basis, profile=profile)
    verification = verify_ghz_trace(
        trace,
        basis=basis,
        require_full_concurrency=profile.endswith("rich"),
    )
    trace["verification"] = verification

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(output_dir / "logical_program.json", program.to_dict())
    _write_json(output_dir / "physical_gate_dag.json", trace["physical_gate_dag"])
    _write_json(output_dir / "semantic_requests.json", plan.to_dict())
    _write_json(output_dir / "execution_trace.json", trace)
    _write_json(output_dir / "metrics.json", trace["metrics"])
    _write_json(output_dir / "verification.json", verification)
    save_animation(trace, output_dir / "animation.html")
    save_timeline(trace, output_dir / "timeline.png")
    if make_gif:
        from qec_schedule.visualization.animation import create_matplotlib_animation
        animation = create_matplotlib_animation(trace, frames=240, interval=40)
        animation.save(output_dir / "animation.gif", writer="pillow", fps=25)
    return {
        "basis": basis,
        "output_dir": str(output_dir),
        "trace": trace,
        "metrics": trace["metrics"],
        "verification": verification,
        "logical_program": program,
        "physical_gate_dag": trace["physical_gate_dag"],
        "semantic_requests": plan.to_dict(),
    }


def run_experiment(config_path, output_dir, *, basis="both", **kwargs):
    """Run one or both measurement shots and write a comparison summary."""
    output_dir = Path(output_dir)
    bases = ("Z", "X") if basis == "both" else (basis,)
    shots = {}
    for shot_basis in bases:
        shots[shot_basis] = run_shot(config_path, output_dir / shot_basis.lower(),
                                     basis=shot_basis, **kwargs)

    primary = shots[bases[0]]
    # Keep the command-line artifact names from the experiment design at the
    # root while preserving a complete subdirectory for every shot.
    for name, value in (
        ("logical_program.json", primary["logical_program"].to_dict()),
        ("physical_gate_dag.json", primary["physical_gate_dag"]),
        ("semantic_requests.json", primary["semantic_requests"]),
        ("execution_trace.json", primary["trace"]),
    ):
        _write_json(output_dir / name, value)
    save_animation(primary["trace"], output_dir / "animation.html")
    save_timeline(primary["trace"], output_dir / "timeline.png")
    if "X" in shots:
        save_animation(shots["X"]["trace"], output_dir / "animation_x.html")
        save_timeline(shots["X"]["trace"], output_dir / "timeline_x.png")

    if len(shots) == 1:
        metrics_report = primary["metrics"]
        verification_report = primary["verification"]
    else:
        metrics_report = {
            "schema_version": 1,
            "experiment": "ghz4",
            "primary_basis": bases[0],
            "shots": {key: value["metrics"] for key, value in shots.items()},
        }
        verification_report = {
            "schema_version": 1,
            "experiment": "ghz4",
            "passed": all(value["verification"]["passed"] for value in shots.values()),
            "shots": {key: value["verification"] for key, value in shots.items()},
        }
    _write_json(output_dir / "metrics.json", metrics_report)
    _write_json(output_dir / "verification.json", verification_report)
    return {"output_dir": str(output_dir), "shots": {
        key: {"metrics": value["metrics"], "verification": value["verification"]}
        for key, value in shots.items()
    }}


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/ghz4_rich.yaml",
                        help="Hardware YAML profile")
    parser.add_argument("--output", "--output-dir", dest="output",
                        default="runs/ghz4_rich", help="Output directory")
    parser.add_argument("--basis", choices=("both", "z", "x"), default="both",
                        help="Final logical measurement shot(s)")
    parser.add_argument("--primitive", choices=("CZ", "CNOT"), default="CZ")
    parser.add_argument("--qec-rounds-after-prepare", type=int, default=1)
    parser.add_argument("--qec-rounds-between-layers", type=int, default=1)
    parser.add_argument("--qec-rounds-before-measure", type=int, default=1)
    parser.add_argument("--gif", action="store_true", help="Also render a Matplotlib GIF")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    basis = args.basis.upper() if args.basis != "both" else "both"
    summary = run_experiment(
        args.config, args.output, basis=basis,
        qec_rounds_after_prepare=args.qec_rounds_after_prepare,
        qec_rounds_between_layers=args.qec_rounds_between_layers,
        qec_rounds_before_measure=args.qec_rounds_before_measure,
        primitive=args.primitive,
        make_gif=args.gif,
    )
    compact = {
        "output_dir": summary["output_dir"],
        "shots": {
            basis: {
                "passed": value["verification"]["passed"],
                "makespan_us": value["metrics"]["makespan_us"],
                "peak_fanout_pairs": value["metrics"]["peak_fanout_pairs_per_Rydberg_epoch"],
                "peak_qec_pairs": value["metrics"]["peak_qec_pairs_per_Rydberg_epoch"],
                "peak_aod_atoms": value["metrics"]["peak_atoms_per_AOD_epoch"],
            }
            for basis, value in summary["shots"].items()
        },
    }
    print(json.dumps(compact, indent=2, ensure_ascii=False))
    return summary


if __name__ == "__main__":
    main()
