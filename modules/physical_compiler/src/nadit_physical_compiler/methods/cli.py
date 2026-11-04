"""Packaged entry points for saved-result methods and memory workloads."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from . import describe_methods, run_method
from .memory import sample_memory
from .stim_export import StimExport
from .surface_memory import prepare_memory


def configure(method: argparse.ArgumentParser, memory: argparse.ArgumentParser) -> None:
    """Register result translation, workload preparation and decoded sampling."""
    method.add_argument("method", choices=tuple(describe_methods()))
    method.add_argument("result", type=Path, help="Validated nadit.result/2 JSON")
    method.add_argument(
        "--params", type=Path, help="JSON parameters for the selected cost model"
    )
    method.add_argument(
        "--annotations", type=Path, help="stim/v1 detector/observable annotations"
    )
    method.add_argument(
        "--allow-fixed-case", action="store_true", help="stim/v1 fixed-case export"
    )
    method.add_argument(
        "-o",
        "--output",
        type=Path,
        required=True,
        help="Stim circuit or re-timing JSON",
    )
    method.add_argument("--report", type=Path, help="Separate stim/v1 JSON report")
    commands = memory.add_subparsers(dest="memory_command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--distance", type=int, required=True)
    prepare.add_argument("--rounds", type=int)
    prepare.add_argument("--basis", choices=("x", "z"), default="z")
    prepare.add_argument("--pitch-um", type=float, default=8)
    prepare.add_argument("-o", "--output", type=Path, required=True)
    sample = commands.add_parser("sample")
    sample.add_argument("report", type=Path)
    sample.add_argument("--shots", type=int, required=True)
    sample.add_argument("--seed", type=int, default=0)
    sample.add_argument("--batch-size", type=int, default=1024)
    sample.add_argument("-o", "--output", type=Path)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(document, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def execute(args: argparse.Namespace) -> dict[str, Any]:
    """Execute the selected post-processing operation without compiler calls."""
    if args.command == "method":
        output = args.output.resolve()
        inputs = {
            p.resolve()
            for p in (args.result, args.params, args.annotations)
            if p is not None
        }
        if output in inputs:
            raise ValueError("Method output must be distinct from all inputs.")
        if args.method == "retiming/v1":
            if args.report or args.annotations or args.allow_fixed_case:
                raise ValueError(
                    "--report, --annotations and --allow-fixed-case require stim/v1."
                )
            retimed = run_method(
                "retiming/v1",
                _read(args.result),
                error_params=_read(args.params) if args.params else None,
            )
            _write(output, retimed)
            return {
                "output": str(output),
                "retiming_exact": retimed["acceptance"]["retiming_exact"],
            }
        report_path = (args.report or args.output.with_suffix(".json")).resolve()
        if output == report_path or report_path in inputs:
            raise ValueError(
                "Method output paths must be distinct from inputs and each other."
            )
        exported = run_method(
            "stim/v1",
            _read(args.result),
            noise_params=_read(args.params) if args.params else None,
            annotations=_read(args.annotations) if args.annotations else None,
            allow_fixed_case=args.allow_fixed_case,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(exported.circuit, encoding="utf-8", newline="\n")
        report = {
            **exported.report,
            "circuit_file": os.path.relpath(output, report_path.parent),
        }
        _write(report_path, report)
        return {
            "circuit": str(output),
            "report": str(report_path),
            "counts": report["counts"],
        }
    if args.memory_command == "prepare":
        return prepare_memory(
            args.output,
            distance=args.distance,
            rounds=args.rounds,
            basis=args.basis,
            pitch_um=args.pitch_um,
        )
    report = _read(args.report)
    circuit_path = args.report.parent / report["circuit_file"]
    if args.output and args.output.resolve() in (
        args.report.resolve(),
        circuit_path.resolve(),
    ):
        raise ValueError(
            "Sampling output must not overwrite the circuit or export report."
        )
    exported = StimExport(circuit_path.read_text(encoding="utf-8"), report)
    stats = sample_memory(
        exported, shots=args.shots, seed=args.seed, batch_size=args.batch_size
    )
    if args.output:
        _write(args.output, stats)
    return stats
