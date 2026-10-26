"""Prepare and run four frozen d3 architecture cases, one process per case.

Usage: python -m experiments.surface_smt.run prepare OUT
       python -m experiments.surface_smt.run run OUT --case zoned-rigid
       python -m experiments.surface_smt.run summarize OUT
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import socket
import subprocess
import sys
import traceback
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

# Both script and module invocation must import this frozen checkout's sources.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "modules/physical_compiler/src"))

from nadit_physical_compiler.atom_ir import Load, Move, Store
from nadit_physical_compiler.compilers.contracts import ProgramContext
from nadit_physical_compiler.device import Position
from nadit_physical_compiler.execution import FakeBackend
from nadit_physical_compiler.job import load_job
from nadit_physical_compiler.metrics import collect_metrics
from nadit_physical_compiler.serialization import (
    encode_dag,
    encode_device,
    encode_layout,
    encode_result,
)
from nadit_physical_compiler.smt.checker import check_lowering, check_plan
from nadit_physical_compiler.smt.contracts import Plan, Snapshot
from nadit_physical_compiler.smt.lowering import lower_plan
from nadit_physical_compiler.smt.solver import solve
from nadit_physical_compiler.validation import validate_result
from nadit_physical_compiler.visualization import (
    build_result_trace,
    write_html,
)

from experiments.surface_smt.fixtures import (
    ARCHITECTURES,
    MOTIONS,
    constructive_program,
    make_fixture,
    program_to_plan,
)
from experiments.surface_smt.oracle import verify_quantum

CASES = tuple(
    f"{architecture}-{motion}" for architecture in ARCHITECTURES for motion in MOTIONS
)
SOURCE_ROOTS = (
    "modules/physical_compiler/src",
    "modules/codes",
    "experiments/surface_smt",
)
PYPROJECT = "modules/physical_compiler/pyproject.toml"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_hashes() -> dict[str, str]:
    files = {
        ROOT / PYPROJECT,
        ROOT / "modules/codes/rotated_surface_d3/tests/quantum_checks.py",
    }
    for prefix in SOURCE_ROOTS:
        for path in (ROOT / prefix).rglob("*"):
            if not path.is_file() or any(
                part in ("tests", "__pycache__", "artifacts", ".venv")
                for part in path.parts
            ):
                continue
            if path.name.startswith("test_"):
                continue
            if path.suffix == ".py" or (
                "visualization/web" in path.as_posix()
                and path.suffix in (".html", ".css", ".js")
            ):
                files.add(path)
    return {path.relative_to(ROOT).as_posix(): _hash(path) for path in sorted(files)}


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _software() -> dict[str, Any]:
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("z3-solver", "qiskit", "stim", "numpy")
        },
        "git_commit": _git("rev-parse", "HEAD"),
        "git_status": _git("status", "--porcelain"),
    }


def _verify(out: Path) -> dict[str, Any]:
    manifest_path = out / "manifest.json"
    if _hash(manifest_path) != (out / "manifest.sha256").read_text().strip():
        raise ValueError("Frozen manifest hash mismatch.")
    manifest = _read(manifest_path)
    if _source_hashes() != manifest["source_hashes"]:
        raise ValueError("Frozen runtime source file set or content changed.")
    for relative, expected in manifest["input_hashes"].items():
        path = out / relative
        if not path.is_file() or _hash(path) != expected:
            raise ValueError(f"Frozen input hash mismatch: {relative}")
    return manifest


def _plan(value: dict[str, Any]) -> Plan:
    return Plan(
        tuple(
            Snapshot(
                tuple(Position(**p) for p in state["positions"]),
                tuple(state["carried"]),
                tuple(state["columns"]),
                tuple(state["rows"]),
            )
            for state in value["states"]
        ),
        tuple(value["transitions"]),
        tuple(tuple(group) for group in value["operations"]),
    )


def _context(job: Any) -> ProgramContext:
    return ProgramContext(
        job.dag, job.device, job.document["aod"], job.catalog, job.entry_state
    )


def _metrics(result: Any) -> dict[str, Any]:
    metrics = dict(collect_metrics(result))
    actions = [action for step in result.program.steps for action in step.actions]
    for label, kind in (("load", Load), ("move", Move), ("store", Store)):
        metrics[f"{label}_action_count"] = sum(
            isinstance(action, kind) for action in actions
        )
        metrics[f"{label}_duration_us"] = sum(
            action.duration_us for action in actions if isinstance(action, kind)
        )
    metrics["transport_occupancy_us"] = sum(
        max(
            (
                action.duration_us
                for action in step.actions
                if isinstance(action, Load | Move | Store)
            ),
            default=0,
        )
        for step in result.program.steps
    )
    return metrics


def prepare(out: Path, timeout_s: float, horizon: int) -> dict[str, Any]:
    """Freeze jobs, witness schedules, inputs, and runtime hashes without solving."""
    if out.exists() and any(out.iterdir()):
        raise ValueError("Preparation requires a new empty output directory.")
    if timeout_s <= 0 or horizon < 1:
        raise ValueError("Timeout and horizon must be positive.")
    out.mkdir(parents=True, exist_ok=True)
    sources = _source_hashes()
    software = _software()
    frozen_inputs: list[Path] = []
    cases = {}
    common_domain = None
    for name in CASES:
        architecture, motion = name.split("-")
        fixture = make_fixture(architecture, motion)
        case_dir = out / "cases" / name
        case_dir.mkdir(parents=True)
        original = case_dir / "original.qasm3"
        scheduling = case_dir / "scheduling.qasm3"
        original.write_text(fixture.source_qasm, encoding="utf-8", newline="\n")
        scheduling.write_text(fixture.scheduling_qasm, encoding="utf-8", newline="\n")
        xs = sorted({site.position.x for site in fixture.device.slm_sites})
        ys = sorted({site.position.y for site in fixture.device.slm_sites})
        domain = {
            "xs": xs,
            "ys": ys,
            "horizon": horizon,
            "timeout_s": timeout_s,
            "time_quantum_us": 0.001,
        }
        if common_domain is not None and domain != common_domain:
            raise ValueError("All four cases must use the same finite coordinate bank.")
        common_domain = domain
        document = {
            "schema": "nadit.job/1",
            "circuit": {"qasm": "scheduling.qasm3"},
            "device": encode_device(fixture.device),
            "aod": "transport",
            "strategy": {"kind": "smt", **domain},
            "entry": {
                "kind": "explicit",
                "atoms": [
                    [atom.id, atom.holder.site_id, wire]
                    for wire, atom in enumerate(fixture.entry_state.atoms)
                ],
            },
            "case": {"seed": 0},
        }
        _write(case_dir / "job.json", document)
        job = load_job(case_dir / "job.json")
        context = _context(job)
        seed = program_to_plan(fixture, constructive_program(fixture))
        witness_steps = len(seed.transitions)
        padding = horizon - witness_steps
        if padding < 0:
            raise ValueError(
                f"{name} witness needs {witness_steps} steps, exceeds H={horizon}."
            )
        seed = replace(
            seed,
            states=seed.states + (seed.states[-1],) * padding,
            transitions=seed.transitions + ("none",) * padding,
            operations=seed.operations + ((),) * padding,
        )
        issues = check_plan(context, seed)
        if issues:
            raise ValueError(f"Constructive witness plan failed: {issues}")
        result = lower_plan(context, seed, FakeBackend(seed=0))
        issues = check_lowering(context, seed, result)
        validation = validate_result(
            result, entry_state=job.entry_state, device=job.device, dag=job.dag
        )
        if issues or not validation["ok"]:
            raise ValueError(f"Constructive witness failed: {issues}; {validation}")
        quantum = verify_quantum(fixture, result.program)
        witness = encode_result(
            result,
            entry_state=job.entry_state,
            job=job.document,
            validation=validation,
            dag=job.dag,
            device=job.device,
            inputs=job.inputs,
        )
        witness["experiment"] = {
            "solution_origin": "constructive_upper_bound",
            "solver_optimized": False,
            "smt_membership": "not_queried",
        }
        _write(case_dir / "witness.plan.json", asdict(seed))
        _write(case_dir / "witness.result.json", witness)
        _write(case_dir / "witness.metrics.json", _metrics(result))
        _write(case_dir / "witness.quantum.json", quantum)
        _write(case_dir / "profile.json", fixture.profile)
        files = [
            original,
            scheduling,
            *(
                case_dir / filename
                for filename in (
                    "job.json",
                    "witness.plan.json",
                    "witness.result.json",
                    "witness.metrics.json",
                    "witness.quantum.json",
                    "profile.json",
                )
            ),
        ]
        frozen_inputs.extend(files)
        cases[name] = {
            "directory": case_dir.relative_to(out).as_posix(),
            "architecture": architecture,
            "motion": motion,
            "constructive_steps": witness_steps,
            "padded_steps": padding,
        }
        _write(
            case_dir / "status.json",
            {"phase": "pending", "status": "pending", "terminal": False},
        )
    if sources != _source_hashes():
        raise ValueError("Runtime source changed during preparation.")
    manifest = {
        "schema": "nadit.surface-smt-campaign/1",
        "created_at": _now(),
        "cases": cases,
        "software": software,
        "source_hashes": sources,
        "input_hashes": {
            path.relative_to(out).as_posix(): _hash(path) for path in frozen_inputs
        },
        "domain": common_domain,
        "measurement_seed": 0,
        "budgets": {
            "solver_query_total_s": timeout_s,
            "fixed_witness_query_cap_s": min(timeout_s, 30),
            "model_construction": "separately timed, excluded from solver query budget",
        },
        "scope": "One d3 SE round; fixed native per-wire order; finite common coordinate bank; fixed H; one shared AOD; unlimited row/column capacity; full CZ-zone illumination; SLM homes restored.",
        "claims": {
            "constructive_seed": "Feasible independently checked upper bound, NOT solver optimized.",
            "fixed_witness_sat": "Membership of this fixed witness only, NOT unrestricted-search SAT.",
            "optimal_in_domain": "Only the declared finite coordinates, horizon, and upward-rounded time objective.",
        },
    }
    _write(out / "manifest.json", manifest)
    (out / "manifest.sha256").write_text(
        _hash(out / "manifest.json") + "\n", encoding="ascii"
    )
    _verify(out)
    return {
        "prepared": str(out),
        "cases": list(cases),
        "manifest_sha256": _hash(out / "manifest.json"),
    }


def run_case(out: Path, name: str) -> dict[str, Any]:
    """Run one pending case once; preserve terminal UNKNOWN and failures."""
    case_dir = out / "cases" / name
    status_path = case_dir / "status.json"
    prior = _read(status_path)
    if prior.get("terminal"):
        _verify(out)
        return {"case": name, "already_terminal": True, "status": prior["status"]}
    if prior.get("phase") != "pending":
        raise ValueError(
            f"{name} is not pending; an interrupted/running case is not automatically retried."
        )
    lock = case_dir / "worker.lock"
    with lock.open("x", encoding="utf-8") as stream:
        json.dump(
            {"pid": os.getpid(), "host": socket.gethostname(), "started_at": _now()},
            stream,
        )
    started = perf_counter()
    state = {
        "case": name,
        "phase": "running",
        "status": "running",
        "terminal": False,
        "started_at": _now(),
        "pid": os.getpid(),
        "host": socket.gethostname(),
    }
    _write(status_path, state)
    output_files: list[str] = []
    phase = "hash_verification"
    failed = False
    try:
        manifest = _verify(out)
        job = load_job(case_dir / "job.json")
        context = _context(job)
        witness_document = _read(case_dir / "witness.result.json")
        if (
            encode_dag(job.dag) != witness_document["dag"]
            or encode_layout(job.entry_state) != witness_document["entry_state"]
        ):
            raise ValueError(
                "Runtime-loaded DAG or entry differs from the frozen witness."
            )
        state["runtime"] = _software()
        _write(status_path, state)
        seed = _plan(_read(case_dir / "witness.plan.json"))
        with (case_dir / "run.log").open("a", encoding="utf-8") as log:
            log.write(
                f"{_now()} Frozen hashes verified; starting model build and bounded solve.\n"
            )
            log.flush()
        phase = "solve"
        solved = solve(
            context, job.document["strategy"], job.measurement_backend, seed=seed
        )
        _write(case_dir / "evidence.json", solved.evidence)
        output_files.append("evidence.json")
        if solved.plan is not None:
            _write(case_dir / "plan.json", asdict(solved.plan))
            output_files.append("plan.json")
        phase = "result_validation"
        if solved.result is not None:
            if solved.plan is None:
                raise ValueError("Solver returned a result without a decoded plan.")
            issues = check_plan(context, solved.plan) + check_lowering(
                context, solved.plan, solved.result
            )
            validation = validate_result(
                solved.result,
                entry_state=job.entry_state,
                device=job.device,
                dag=job.dag,
            )
            document = encode_result(
                solved.result,
                entry_state=job.entry_state,
                job=job.document,
                validation=validation,
                dag=job.dag,
                device=job.device,
                inputs=job.inputs,
            )
            document["experiment"] = {
                "case": name,
                "manifest_sha256": _hash(out / "manifest.json"),
                "solution_origin": solved.evidence.get("solution_origin"),
                "solver_status": solved.evidence["status"],
            }
            _write(case_dir / "result.json", document)
            output_files.append("result.json")
            if issues or not validation["ok"]:
                raise ValueError(
                    f"Returned plan/result validation failed: {issues}; {validation}"
                )
            case = manifest["cases"][name]
            fixture = make_fixture(case["architecture"], case["motion"])
            quantum = verify_quantum(fixture, solved.result.program)
            _write(case_dir / "quantum.json", quantum)
            _write(case_dir / "metrics.json", _metrics(solved.result))
            output_files.extend(("quantum.json", "metrics.json"))
        else:
            _write(
                case_dir / "quantum.json",
                {"status": "not_applicable", "reason": "No feasible result returned."},
            )
            output_files.append("quantum.json")
        state.update(
            status=solved.evidence["status"],
            solution_origin=solved.evidence.get("solution_origin"),
        )
    except Exception as error:  # noqa: BLE001 - preserve failed worker evidence
        failed = True
        state.update(
            status="error",
            failed_phase=phase,
            error_type=type(error).__name__,
            error=str(error),
        )
        (case_dir / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        output_files.append("error.txt")
    finally:
        try:
            _verify(out)
            state["frozen_hashes_verified_after"] = True
        except Exception as error:  # noqa: BLE001 - report frozen-source failure
            failed = True
            state.update(
                status="hash_mismatch",
                hash_error=str(error),
                frozen_hashes_verified_after=False,
            )
        state.update(
            phase="terminal",
            terminal=True,
            completed_at=_now(),
            wall_s=perf_counter() - started,
            output_hashes={
                filename: _hash(case_dir / filename)
                for filename in output_files
                if (case_dir / filename).is_file()
            },
        )
        _write(status_path, state)
        with (case_dir / "run.log").open("a", encoding="utf-8") as log:
            log.write(
                f"{_now()} Terminal status {state['status']}; wall_s={state['wall_s']}.\n"
            )
        lock.unlink()
    if failed:
        raise RuntimeError(
            f"{name} ended with {state['status']}: {state.get('error', state.get('hash_error'))}"
        )
    return state


def summarize(out: Path) -> dict[str, Any]:
    """Report all four statuses and export one shared viewer without solving."""
    manifest = _verify(out)
    rows, traces = [], []
    for name, case in manifest["cases"].items():
        directory = out / case["directory"]
        state = _read(directory / "status.json")
        bad_outputs = [
            filename
            for filename, expected in state.get("output_hashes", {}).items()
            if not (directory / filename).is_file()
            or _hash(directory / filename) != expected
        ]
        evidence = (
            _read(directory / "evidence.json")
            if (directory / "evidence.json").is_file()
            else {}
        )
        valid_result = (
            state.get("terminal")
            and not bad_outputs
            and state["status"] in ("optimal_in_domain", "feasible_unknown")
            and (directory / "result.json").is_file()
        )
        metrics = _read(directory / "metrics.json") if valid_result else {}
        witness = _read(directory / "witness.metrics.json")
        quantum = manifest["domain"]["time_quantum_us"]
        row = {
            "case": name,
            "status": "output_hash_mismatch" if bad_outputs else state["status"],
            "terminal": state.get("terminal", False),
            "solution_origin": evidence.get("solution_origin"),
            "unrestricted_solver_solution": evidence.get("solution_origin")
            == "unrestricted_sat",
            "fixed_witness_membership": evidence.get(
                "witness_membership", "not_queried"
            ),
            "unrestricted_sat_queries": sum(
                query["status"] == "sat"
                and query["purpose"] != "fixed_witness_membership"
                for query in evidence.get("queries", [])
            ),
            "model_build_s": evidence.get("model_build_s"),
            "solver_s": evidence.get(
                "solver_s",
                sum(query["wall_s"] for query in evidence.get("queries", []))
                if evidence
                else None,
            ),
            "wall_s": state.get("wall_s"),
            "lower_bound_us": None
            if evidence.get("lower_bound_ticks") is None
            else evidence["lower_bound_ticks"] * quantum,
            "upper_bound_us": None
            if evidence.get("upper_bound_ticks") is None
            else evidence["upper_bound_ticks"] * quantum,
            "actual_program_duration_us": metrics.get("program_duration_us"),
            "transport_action_sum_us": metrics.get("transport_duration_us"),
            "transport_occupancy_us": metrics.get("transport_occupancy_us"),
            "atom_load_count": metrics.get("atom_load_count"),
            "atom_store_count": metrics.get("atom_store_count"),
            "load_actions": metrics.get("load_action_count"),
            "move_actions": metrics.get("move_action_count"),
            "store_actions": metrics.get("store_action_count"),
            "move_duration_us": metrics.get("move_duration_us"),
            "load_duration_us": metrics.get("load_duration_us"),
            "store_duration_us": metrics.get("store_duration_us"),
            "constructive_duration_us": witness["program_duration_us"],
            "ratio_to_constructive": metrics["program_duration_us"]
            / witness["program_duration_us"]
            if valid_result
            else None,
            "error": state.get("error")
            or state.get("hash_error")
            or (", ".join(bad_outputs) or None),
        }
        rows.append(row)
        viewer_file = "result.json" if valid_result else "witness.result.json"
        label = (
            evidence.get("solution_origin")
            if valid_result
            else "constructive_upper_bound"
        )
        traces.append(
            build_result_trace(
                _read(directory / viewer_file),
                title=f"{name}: {label}",
                description=f"Status: {row['status']}. Constructive schedules are NOT solver optimized. Fixed-witness SAT is not unrestricted-search SAT.",
            )
        )
    summary = {
        "schema": "nadit.surface-smt-summary/1",
        "manifest_sha256": _hash(out / "manifest.json"),
        "scope": manifest["scope"],
        "rows": rows,
    }
    _write(out / "summary.json", summary)
    with (out / "summary.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_html(
        traces, out / "index.html", title="d3 bounded SMT architecture comparison"
    )
    report = [
        "# d3 bounded SMT architecture comparison",
        "",
        manifest["scope"],
        "",
        "The constructive seed is an independently checked feasible upper bound, NOT a solver-optimized result. A fixed-witness SAT query proves membership of that fixed schedule, NOT unrestricted-search SAT. UNKNOWN, including timeout, proves neither infeasibility nor optimality.",
        "",
        "Optimality applies only to the declared finite coordinate bank, fixed horizon, and sum of upward-rounded step durations. The actual program uses the Device timing functions. Ideal stabilizer extraction and N/Z hook checks do not establish circuit-level fault distance.",
        "",
        f"Budget: {manifest['budgets']['solver_query_total_s']} s of Z3 queries per case; fixed-witness membership uses at most {manifest['budgets']['fixed_witness_query_cap_s']} s of that total. Model construction is timed separately. No terminal case is retried.",
        "",
        "| Case | Status | Origin | Actual duration (us) | Transport sum (us) | Loads / stores (atoms) | Bounds (us) |",
        "|---|---|---|---:|---:|---:|---|",
    ]

    def value(row: dict[str, Any], key: str) -> str:
        item = row[key]
        return (
            "—"
            if item is None
            else f"{item:.6g}"
            if isinstance(item, float)
            else str(item)
        )

    for row in rows:
        report.append(
            f"| {row['case']} | {row['status']} | {value(row, 'solution_origin')} | {value(row, 'actual_program_duration_us')} | {value(row, 'transport_action_sum_us')} | {value(row, 'atom_load_count')} / {value(row, 'atom_store_count')} | {value(row, 'lower_bound_us')} – {value(row, 'upper_bound_us')} |"
        )
    report.extend(
        [
            "",
            "| Case | Build / solver / total (s) | Move / load / store (us) | Fixed witness membership | Unrestricted SAT queries |",
            "|---|---:|---:|---|---:|",
        ]
    )
    for row in rows:
        report.append(
            f"| {row['case']} | {value(row, 'model_build_s')} / {value(row, 'solver_s')} / {value(row, 'wall_s')} | {value(row, 'move_duration_us')} / {value(row, 'load_duration_us')} / {value(row, 'store_duration_us')} | {value(row, 'fixed_witness_membership')} | {value(row, 'unrestricted_sat_queries')} |"
        )
    report.extend(
        [
            "",
            "## Domain and constructive reference",
            "",
            f"H = {manifest['domain']['horizon']}; time quantum = {manifest['domain']['time_quantum_us']} us. Both AOD models have unlimited row/column count; the finite coordinate alphabet is a separate modeling bound.",
            f"X coordinates (um): `{manifest['domain']['xs']}`.",
            f"Y coordinates (um): `{manifest['domain']['ys']}`.",
            "",
        ]
    )
    for row in rows:
        report.append(
            f"- {row['case']}: independently checked constructive duration {value(row, 'constructive_duration_us')} us; returned/constructive ratio {value(row, 'ratio_to_constructive')}."
        )
        if row["error"]:
            report.append(f"  Failure: `{row['error']}`.")
    report.extend(
        [
            "",
            "All four rows remain visible; pending/running/failed cases are not presented as completed measurements. Loss and logical-error sampling are outside this scheduling experiment.",
            "",
            "## Frozen inputs and evidence",
            "",
            "- [Manifest](manifest.json): source/input hashes, common domain, versions and budgets.",
            "- [Full numeric results](summary.csv) and [machine-readable summary](summary.json).",
            "- [Shared Atom IR viewer](index.html): selected validated result, or explicitly labelled constructive witness.",
            "",
        ]
    )
    for name, case in manifest["cases"].items():
        directory = case["directory"]
        report.append(
            f"- {name}: [status]({directory}/status.json), [job]({directory}/job.json), [witness]({directory}/witness.result.json), [query evidence]({directory}/evidence.json), [quantum checks]({directory}/quantum.json)."
        )
    (out / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    """Dispatch explicit preparation, one-case execution, or read-only summary."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparing = commands.add_parser("prepare")
    preparing.add_argument("out", type=Path)
    preparing.add_argument("--timeout-s", type=float, default=600)
    preparing.add_argument("--horizon", type=int, default=174)
    running = commands.add_parser("run")
    running.add_argument("out", type=Path)
    running.add_argument("--case", choices=CASES, required=True)
    summarizing = commands.add_parser("summarize")
    summarizing.add_argument("out", type=Path)
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    try:
        if args.command == "prepare":
            result = prepare(out, args.timeout_s, args.horizon)
        elif args.command == "run":
            result = run_case(out, args.case)
        else:
            result = summarize(out)
    except Exception as error:  # noqa: BLE001 - CLI reports worker/validation errors
        print(
            json.dumps(
                {"status": "error", "type": type(error).__name__, "message": str(error)}
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
