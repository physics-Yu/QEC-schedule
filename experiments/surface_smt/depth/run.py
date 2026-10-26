"""Frozen server experiment with a process-enforced two-hour wall deadline."""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules/physical_compiler/src"))

from nadit_physical_compiler.serialization import encode_device
from nadit_physical_compiler.visualization import build_result_trace, write_html

from modules.codes.rotated_surface_d3.components.circuits import se_layers

from .lowering import device_for, export, gate_source
from .model import DepthModel, Problem
from .validation import validate


def write(path: Path, value) -> None:
    """Replace one JSON record atomically without losing previous other files."""
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(out: Path) -> None:
    """Freeze the input and runtime bytes without invoking the solver."""
    if out.exists() and any(out.iterdir()):
        raise ValueError("Output already exists.")
    out.mkdir(parents=True, exist_ok=True)
    problem = Problem(17, se_layers())
    write(out / "problem.json", asdict(problem))
    write(out / "device.json", encode_device(device_for(problem)))
    (out / "circuit.qasm3").write_text(gate_source(), encoding="utf-8", newline="\n")
    files: set[Path] = set()
    for prefix in (
        "modules/physical_compiler/src",
        "modules/codes",
        "experiments/surface_smt/depth",
    ):
        files.update(
            p for p in (ROOT / prefix).rglob("*.py") if "__pycache__" not in p.parts
        )
    files.update(
        (
            ROOT
            / "modules/physical_compiler/src/nadit_physical_compiler/visualization/web"
        ).glob("*")
    )
    files.add(ROOT / "modules/physical_compiler/pyproject.toml")
    write(
        out / "manifest.json",
        {
            "schema": "nadit.depth-experiment/1",
            "wall_budget_s": 7200,
            "attempts": [3, 4],
            "depth3_cap_s": 60,
            "seed": 0,
            "initially_idle": True,
            "final_home": False,
            "readout_included": False,
            "objective": "parallel MOVE count",
            "source_base_commit": "85f5479",
            "source_hashes": {
                p.relative_to(ROOT).as_posix(): sha(p)
                for p in sorted(files)
                if p.is_file()
            },
            "input_hashes": {
                name: sha(out / name)
                for name in ("problem.json", "device.json", "circuit.qasm3")
            },
            "scope": "Fixed four N/Z matchings; free atom assignment to a 5x5 double-trap bank; one initially isolated atom per cell; full-field CZ; flexible AOD; unlimited line capacity; all endpoints SLM.",
        },
    )
    (out / "manifest.sha256").write_text(sha(out / "manifest.json") + "\n")
    print(
        json.dumps(
            {"prepared": str(out), "manifest_sha256": sha(out / "manifest.json")}
        )
    )


def verify(out: Path):
    """Verify frozen source and input bytes on either host."""
    if sha(out / "manifest.json") != (out / "manifest.sha256").read_text().strip():
        raise ValueError("Manifest changed.")
    manifest = json.loads((out / "manifest.json").read_text())
    for name, expected in manifest["source_hashes"].items():
        if sha(ROOT / name) != expected:
            raise ValueError(f"Source changed: {name}")
    for name, expected in manifest["input_hashes"].items():
        if sha(out / name) != expected:
            raise ValueError(f"Input changed: {name}")
    return manifest


def worker(out: Path, depth: int, seconds: float) -> None:
    """Build, solve and validate one depth in its own killable process."""
    manifest = verify(out)
    raw = json.loads((out / "problem.json").read_text())
    raw["layers"] = tuple(
        tuple(tuple(pair) for pair in layer) for layer in raw["layers"]
    )
    problem = Problem(**raw)
    start = perf_counter()
    try:
        model = DepthModel(problem, depth, manifest["seed"])
        built = perf_counter() - start
        report, witness = model.check(max(0.001, seconds - built))
        report.update(model_build_s=built)
        if witness is not None:
            write(out / f"depth-{depth}.witness.json", asdict(witness))
            errors = validate(problem, witness)
            if errors:
                raise ValueError(errors)
            document, checks = export(problem, witness)
            write(out / f"depth-{depth}.result.json", document)
            write(out / f"depth-{depth}.checks.json", checks)
            report.update(validated=True, metrics=document["metrics"])
        verify(out)
        report.update(
            worker_wall_s=perf_counter() - start, source_and_inputs_verified=True
        )
        write(out / f"depth-{depth}.json", report)
    except Exception as error:
        write(
            out / f"depth-{depth}.json",
            {
                "status": "error",
                "depth": depth,
                "error": str(error),
                "traceback": traceback.format_exc(),
                "worker_wall_s": perf_counter() - start,
            },
        )
        raise


def run(out: Path) -> None:
    """Use one total wall budget, kill overdue process groups, never retry."""
    manifest = verify(out)
    lock = out / "campaign.lock"
    with lock.open("x") as stream:
        stream.write(str(os.getpid()))
    started = perf_counter()
    write(
        out / "status.json",
        {
            "status": "running",
            "pid": os.getpid(),
            "wall_budget_s": manifest["wall_budget_s"],
        },
    )
    attempts = []
    try:
        for depth in manifest["attempts"]:
            path = out / f"depth-{depth}.json"
            if path.exists():
                attempts.append(json.loads(path.read_text()))
                continue
            remaining = manifest["wall_budget_s"] - (perf_counter() - started)
            if remaining <= 0:
                break
            allocation = (
                min(remaining, manifest["depth3_cap_s"]) if depth == 3 else remaining
            )
            command = [
                sys.executable,
                "-m",
                "experiments.surface_smt.depth.run",
                "worker",
                str(out),
                "--depth",
                str(depth),
                "--seconds",
                str(allocation),
            ]
            with (out / f"depth-{depth}.log").open("w") as log:
                process = subprocess.Popen(
                    command,
                    cwd=ROOT,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    start_new_session=(os.name == "posix"),
                )
                try:
                    process.wait(timeout=allocation)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        # POSIX names are absent from Windows platform type stubs.
                        getattr(os, "killpg")(process.pid, getattr(signal, "SIGKILL"))  # noqa: B009
                    else:
                        process.kill()
                    process.wait()
                    write(
                        path,
                        {
                            "status": "unknown",
                            "depth": depth,
                            "reason": "process_wall_timeout",
                            "allocated_wall_s": allocation,
                            "exit_code": process.returncode,
                        },
                    )
                if not path.exists():
                    write(
                        path,
                        {
                            "status": "error",
                            "depth": depth,
                            "reason": "worker_exited_without_record",
                            "exit_code": process.returncode,
                        },
                    )
            attempts.append(json.loads(path.read_text()))
        verify(out)
        by_depth = {a["depth"]: a for a in attempts}
        optimal = (
            by_depth.get(3, {}).get("status") == "unsat"
            and by_depth.get(4, {}).get("status") == "sat"
            and by_depth[4].get("validated")
        )
        status = {
            "status": "optimal_in_declared_model" if optimal else "inconclusive",
            "wall_s": perf_counter() - started,
            "attempts": attempts,
            "minimum_move_depth": 4 if optimal else None,
            "manifest_sha256": sha(out / "manifest.json"),
            "source_and_inputs_verified": True,
            "scope": manifest["scope"],
            "readout_included": False,
            "final_home": False,
        }
        outputs = [p for p in out.glob("depth-*") if p.is_file()]
        status["output_hashes"] = {p.name: sha(p) for p in outputs}
        write(out / "status.json", status)
        if optimal:
            document = json.loads((out / "depth-4.result.json").read_text())
            write_html(
                [
                    build_result_trace(
                        document,
                        title="SMT: four MOVE N/Z extraction",
                        description="Free initially idle layout; depth 3 UNSAT, depth 4 SAT; gate-only, no return or measurement.",
                    )
                ],
                out / "index.html",
            )
        print(json.dumps(status, indent=2))
    finally:
        lock.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "worker", "verify"))
    parser.add_argument("out", type=Path)
    parser.add_argument("--depth", type=int)
    parser.add_argument("--seconds", type=float)
    args = parser.parse_args()
    out = args.out.resolve()
    if args.command == "prepare":
        prepare(out)
    elif args.command == "run":
        run(out)
    elif args.command == "worker":
        worker(out, args.depth, args.seconds)
    else:
        print(json.dumps({"verified": bool(verify(out))}))


if __name__ == "__main__":
    main()
