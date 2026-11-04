"""Process-bounded SMT execution with durable, independently checked incumbents."""

import json
import os
import subprocess
import sys
from dataclasses import asdict
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any

from ..compilers.contracts import ProgramContext
from ..device import Position, loads_device
from ..execution import FakeBackend, MeasurementBackend
from ..serialization import (
    decode_dag,
    decode_layout,
    encode_dag,
    encode_device,
    encode_layout,
)
from ..support import UnsupportedJob
from .contracts import Domain, Plan, Snapshot, SolveResult


def decode_plan(value: dict[str, Any] | None) -> Plan | None:
    """Read the solver-independent plan interchange used by worker checkpoints."""
    if value is None:
        return None
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


def write_checkpoint(path: Path, solved: SolveResult) -> None:
    """Atomically replace a plan/evidence pair; never publish half a witness."""
    value = {
        "plan": asdict(solved.plan) if solved.plan is not None else None,
        "evidence": solved.evidence,
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def read_request(path: Path) -> tuple[ProgramContext, dict[str, Any], Plan | None]:
    """Decode explicit inputs in the isolated worker without reading source QASM."""
    value = json.loads(path.read_text(encoding="utf-8"))
    return (
        ProgramContext(
            decode_dag(value["dag"]),
            loads_device(json.dumps(value["device"])),
            value["aod_id"],
            None,
            decode_layout(value["entry"]),
        ),
        value["options"],
        decode_plan(value["seed"]),
    )


def solve_bounded(
    context: ProgramContext,
    options: dict[str, Any],
    case: MeasurementBackend,
    *,
    seed: Plan | None = None,
) -> SolveResult:
    """Bound model construction/search/child validation by a process wall deadline.

    The parent samples the supplied measurement backend only after recovering
    the final validated plan. A killed worker cannot consume case results.
    Parent-side input preparation and final witness verification are measured
    separately; they are not interruptible solver work.
    """
    if find_spec("z3") is None:
        raise UnsupportedJob(
            [
                {
                    "stage": "strategy",
                    "kind": "smt",
                    "reason": (
                        "requires optional dependency: "
                        "install nadit-physical-compiler[smt]"
                    ),
                }
            ]
        )
    from .solver import _checked, _rounded_duration, digest

    started = perf_counter()
    wall_budget = float(options.get("wall_timeout_s", options.get("timeout_s", 60)))
    if wall_budget <= 0:
        raise ValueError("SMT wall_timeout_s must be positive.")
    domain = Domain(
        tuple(options["xs"]),
        tuple(options["ys"]),
        options["horizon"],
        options.get("timeout_s", 60),
        options.get("time_quantum_us", 0.001),
    )
    evidence: dict[str, Any] = {
        "schema": "nadit.smt-evidence/1",
        "status": "unknown",
        "budget_hit": False,
        "domain": asdict(domain),
        "queries": [],
        "objective": "rounded_period_including_measurement_availability",
        "scope": (
            "finite coordinates, fixed horizon, full CZ-region pulse, one shared AOD"
        ),
        "input_hashes": {
            "dag": digest(encode_dag(context.dag)),
            "device": digest(encode_device(context.device)),
            "entry": digest(encode_layout(context.entry_state)),
        },
        "lower_bound_ticks": None,
        "upper_bound_ticks": None,
    }
    seed_result = _checked(context, seed, FakeBackend()) if seed is not None else None
    if seed_result is not None:
        assert seed is not None
        if len(seed.transitions) != domain.horizon or any(
            p.x not in domain.xs or p.y not in domain.ys
            for state in seed.states
            for p in state.positions
        ):
            raise ValueError("Seed is outside the declared coordinate/horizon domain.")
        if any(
            not set(state.columns) <= set(domain.xs)
            or not set(state.rows) <= set(domain.ys)
            for state in seed.states
        ):
            raise ValueError("Seed active lines are outside the coordinate domain.")
        evidence.update(
            status="feasible_unknown",
            solution_origin="constructive_upper_bound",
            witness_membership="unconfirmed",
            plan_sha256=digest(asdict(seed)),
            upper_bound_ticks=_rounded_duration(seed_result, context, domain),
        )
    with TemporaryDirectory(prefix="nadit-smt-") as directory:
        work = Path(directory)
        request, answer, checkpoint = (
            work / "request.json",
            work / "answer.json",
            work / "checkpoint.json",
        )
        request.write_text(
            json.dumps(
                {
                    "dag": encode_dag(context.dag),
                    "device": encode_device(context.device),
                    "entry": encode_layout(context.entry_state),
                    "aod_id": context.aod_id,
                    "options": options,
                    "seed": asdict(seed) if seed is not None else None,
                },
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        write_checkpoint(checkpoint, SolveResult(seed_result, seed, evidence))
        environment = os.environ.copy()
        environment["PYTHONPATH"] = (
            str(Path(__file__).resolve().parents[2])
            + os.pathsep
            + environment.get("PYTHONPATH", "")
        )
        command = [
            sys.executable,
            "-m",
            "nadit_physical_compiler.smt.worker",
            str(work),
        ]
        preparation_s = perf_counter() - started
        process_started = perf_counter()
        timed_out = False
        with (work / "worker.log").open("wb") as log:
            process = subprocess.Popen(
                command,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                process.wait(
                    timeout=max(0.001, wall_budget - (perf_counter() - process_started))
                )
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait()
            except BaseException:
                process.kill()
                process.wait()
                raise
        process_wall_s = perf_counter() - process_started
        if process.returncode and not timed_out:
            raise RuntimeError(
                "SMT worker failed: "
                + (work / "worker.log").read_text(encoding="utf-8", errors="replace")[
                    -4000:
                ]
            )
        if not timed_out and not answer.exists():
            raise RuntimeError("SMT worker exited without a final outcome.")
        saved = json.loads(
            (answer if answer.exists() and not timed_out else checkpoint).read_text(
                encoding="utf-8"
            )
        )
        evidence = saved["evidence"]
        plan = decode_plan(saved["plan"])
        if timed_out:
            evidence.update(
                status="feasible_unknown" if plan is not None else "unknown",
                budget_hit=True,
                termination_reason="process_wall_timeout",
            )
        evidence.update(
            wall_budget_s=wall_budget,
            process_wall_s=process_wall_s,
            preparation_s=preparation_s,
        )
        verification_started = perf_counter()
        result = _checked(context, plan, case) if plan is not None else None
        evidence["parent_verification_s"] = perf_counter() - verification_started
        evidence["total_wall_s"] = perf_counter() - started
        return SolveResult(result, plan, evidence)
