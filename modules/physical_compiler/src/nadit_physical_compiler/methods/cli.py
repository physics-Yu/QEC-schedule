"""Packaged entry points for saved-result methods and memory workloads."""

import argparse
import json
import os
from pathlib import Path
from typing import Any

from . import run_method
from .memory import sample_memory
from .stim_export import StimExport
from .surface_memory import prepare_memory


def configure(method: argparse.ArgumentParser, memory: argparse.ArgumentParser) -> None:
    """Register result translation, workload preparation and decoded sampling."""
    method.add_argument("method", choices=("stim/v1",))
    method.add_argument("result", type=Path)
    method.add_argument("--params", type=Path)
    method.add_argument("--annotations", type=Path)
    method.add_argument("--allow-fixed-case", action="store_true")
    method.add_argument("-o", "--output", type=Path, required=True)
    method.add_argument("--report", type=Path)
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
        report_path = (args.report or args.output.with_suffix(".json")).resolve()
        output = args.output.resolve()
        inputs = {
            p.resolve()
            for p in (args.result, args.params, args.annotations)
            if p is not None
        }
        if output == report_path or inputs.intersection({output, report_path}):
            raise ValueError(
                "Method output paths must be distinct from inputs and each other."
            )
        exported = run_method(
            args.method,
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
