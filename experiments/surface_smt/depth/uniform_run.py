"""Frozen uniform-rigid, return-home search; run only on the selected server."""

import argparse
import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

from nadit_physical_compiler.serialization import encode_device
from nadit_physical_compiler.visualization import build_result_trace, write_html

from modules.codes.rotated_surface_d3.components.circuits import se_layers

from .lowering import checks_metadata, device_for, export, gate_source
from .model import Problem
from .run import ROOT, sha, write
from .run import verify as verify_manifest
from .uniform import UniformModel

SCHEMA = "nadit.uniform-rigid-depth/1"


def verify(out: Path) -> dict:
    """Verify the bytes and identity of the uniform cyclic study."""
    manifest = verify_manifest(out)
    if manifest["schema"] != SCHEMA:
        raise ValueError("Expected a uniform-rigid depth manifest.")
    return manifest


def prepare(out: Path) -> None:
    """Freeze the actual source and inputs, without starting a search."""
    out.mkdir(parents=True, exist_ok=False)
    problem = Problem(17, se_layers(), motion="rigid", cyclic=True)
    write(out / "problem.json", asdict(problem))
    write(out / "device.json", encode_device(device_for(problem)))
    (out / "circuit.qasm3").write_text(gate_source(), encoding="utf-8", newline="\n")
    paths = [
        ROOT / "experiments/surface_smt/gate_oracle.py",
        ROOT / "modules/physical_compiler/pyproject.toml",
    ]
    for prefix in (
        "experiments/surface_smt/depth",
        "modules/codes",
        "modules/physical_compiler/src",
    ):
        paths.extend(
            p
            for p in (ROOT / prefix).rglob("*")
            if p.is_file() and p.suffix in (".py", ".js", ".css", ".html")
        )
    write(
        out / "manifest.json",
        {
            "schema": SCHEMA,
            "seed": 0,
            "wall_budget_s": 7200,
            "per_depth_s": 300,
            "attempts": list(range(5, 49)),
            "analytic_lower_bound": 5,
            "final_home": True,
            "readout_included": False,
            "pitch": "per MOVE, independent x/y; complete arithmetic progressions",
            "scope": "5x5 double-trap bank, initially idle free layout, fixed four N/Z matchings, rigid uniform Cartesian grid, unlimited capacity, atom-wise return, final SLM holders",
            "source_hashes": {
                p.relative_to(ROOT).as_posix(): sha(p) for p in sorted(paths)
            },
            "input_hashes": {
                n: sha(out / n)
                for n in ("problem.json", "device.json", "circuit.qasm3")
            },
        },
    )
    (out / "manifest.sha256").write_text(sha(out / "manifest.json") + "\n")


def worker(out: Path, depth: int, seconds: float) -> None:
    """Solve and validate one candidate, retaining its complete AOD arrays."""
    manifest = verify(out)
    raw = json.loads((out / "problem.json").read_text())
    raw["layers"] = tuple(tuple(tuple(p) for p in layer) for layer in raw["layers"])
    problem = Problem(**raw)
    started = perf_counter()
    model = UniformModel(problem, depth, manifest["seed"])
    (out / f"depth-{depth}.smt2").write_text(model.solver.to_smt2(), encoding="utf-8")
    report, witness = model.check(max(0.001, seconds - (perf_counter() - started)))
    if witness is not None:
        write(out / f"depth-{depth}.witness.json", asdict(witness))
        document, checks = export(problem, witness)
        document["experiment"]["uniform_rigid"] = True
        checks["uniform_grid"] = True
        write(out / f"depth-{depth}.result.json", document)
        write(out / f"depth-{depth}.checks.json", checks)
        report.update(validated=True, gate_states=witness.gate_states)
    verify(out)
    report["worker_wall_s"] = perf_counter() - started
    write(out / f"depth-{depth}.json", report)


def run(out: Path) -> None:
    """Bound worker processes; never turn UNKNOWN lower depths into optimality."""
    if os.name != "posix":
        raise ValueError("Launching the uniform-rigid campaign requires POSIX.")
    manifest = verify(out)
    if (out / "status.json").exists() or any(out.glob("depth-*")):
        raise ValueError("Campaign already started; use a fresh prepared directory.")
    lock = out / "campaign.lock"
    with lock.open("x") as stream:
        stream.write(str(os.getpid()))
    started, attempts = perf_counter(), []
    try:
        for depth in manifest["attempts"]:
            remaining = manifest["wall_budget_s"] - (perf_counter() - started)
            if remaining <= 0:
                break
            path = out / f"depth-{depth}.json"
            if not path.exists():
                seconds = min(remaining, manifest["per_depth_s"])
                write(
                    out / "status.json",
                    {"status": "running", "depth": depth, "attempts": attempts},
                )
                with (out / f"depth-{depth}.log").open("w") as log:
                    process = subprocess.Popen(
                        [
                            sys.executable,
                            "-m",
                            "experiments.surface_smt.depth.uniform_run",
                            "worker",
                            str(out),
                            "--depth",
                            str(depth),
                            "--seconds",
                            str(seconds),
                        ],
                        cwd=ROOT,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    try:
                        process.wait(timeout=seconds)
                    except subprocess.TimeoutExpired:
                        getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))  # noqa: B009
                        process.wait()
                        write(
                            path,
                            {
                                "status": "unknown",
                                "depth": depth,
                                "reason": "process_wall_timeout",
                            },
                        )
                if not path.exists():
                    write(
                        path,
                        {
                            "status": "error",
                            "depth": depth,
                            "exit_code": process.returncode,
                        },
                    )
            report = json.loads(path.read_text())
            attempts.append(report)
            if report["status"] in ("sat", "error"):
                break
        sat = next(
            (a for a in attempts if a["status"] == "sat" and a.get("validated")), None
        )
        optimal = bool(sat) and all(a["status"] == "unsat" for a in attempts[:-1])
        verify(out)
        write(
            out / "status.json",
            {
                "status": "optimal_in_declared_model"
                if optimal
                else "feasible"
                if sat
                else "inconclusive",
                "attempts": attempts,
                "minimum_move_depth": sat["depth"] if optimal else None,
                "wall_s": perf_counter() - started,
            },
        )
        if sat:
            doc = json.loads((out / f"depth-{sat['depth']}.result.json").read_text())
            write_html(
                [
                    build_result_trace(
                        doc,
                        title=f"Uniform rigid: {sat['depth']} MOVEs",
                        qec=checks_metadata(),
                        description="One gate-only N/Z round; atom-wise return; free initial layout.",
                    )
                ],
                out / "index.html",
            )
    finally:
        lock.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "worker", "verify"))
    parser.add_argument("out", type=Path)
    parser.add_argument("--depth", type=int)
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    if args.command == "worker":
        if os.name != "posix" or args.depth is None or args.seconds is None:
            parser.error("worker requires POSIX, --depth and --seconds")
        worker(args.out.resolve(), args.depth, args.seconds)
    elif args.command == "verify":
        verify(args.out.resolve())
        print(f"Verified {args.out.resolve() / 'manifest.json'}")
    elif args.command == "prepare":
        prepare(args.out.resolve())
        print(f"Prepared {args.out.resolve() / 'manifest.json'}")
    else:
        run(args.out.resolve())
