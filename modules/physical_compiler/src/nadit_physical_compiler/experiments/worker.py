"""One isolated compile/validate job; invoked only by the experiment runner."""

import hashlib
import importlib
import json
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .journal import write_json

if TYPE_CHECKING:
    from ..validation import ValidationReport


def validate_result(*args: Any, **kwargs: Any) -> "ValidationReport":
    """Keep the existing overridable validation seam without task startup imports."""
    from ..validation import validate_result as validate

    return validate(*args, **kwargs)


def execute(run: dict[str, Any]) -> dict[str, Any]:
    """Classify every admission/compile/validation outcome without losing errors."""
    from ..activity import _area
    from ..compilers.contracts import InvalidProgramResult
    from ..compilers.registry import identity as compiler_identity
    from ..errors import SearchExhausted
    from ..job import compile_job, loads_job
    from ..serialization import encode_result
    from ..support import UnsupportedJob

    started = time.perf_counter()
    record = {key: value for key, value in run.items() if key != "job"}
    record.update(
        status="invalid_job",
        reason=None,
        metrics={},
        cost=[],
        validation=None,
        compile={
            "wall_s": None,
            "peak_rss_mb": None,
            "search_nodes": None,
            "budget_hit": None,
        },
        hardware={},
        provenance={"job_hash": None, "result_path": None},
    )
    try:
        qasm = Path(run["job"]["circuit"]["qasm"])
        if hashlib.sha256(qasm.read_bytes()).hexdigest() != run["circuit_sha256"]:
            raise ValueError("Circuit bytes differ from the frozen suite.")
        job = loads_job(json.dumps(run["job"]), base_dir=qasm.parent)
        if job.dag.num_qubits != run["qubits"]:
            raise ValueError("Suite width differs from the loaded circuit.")
    except UnsupportedJob as error:
        record.update(status="unsupported", reason=error.document()["reasons"])
    except (ValueError, OSError, KeyError, TypeError) as error:
        record["reason"] = f"{type(error).__name__}: {error}"
    else:
        record["compiler"] = compiler_identity(job.document["strategy"])
        aod = job.device.aod(job.document["aod"])
        record["hardware"] = {
            "slm_sites": len(job.device.slm_sites),
            "gate_pairs": job.catalog.capacity if job.catalog else 0,
            "aod_capacity": {"rows": aod.max_rows, "columns": aod.max_columns},
            "zone_area_um2": _area(tuple(zone.bounds for zone in job.device.zones)),
        }
        compile_start = time.perf_counter()
        try:
            result = compile_job(job)
        except InvalidProgramResult as error:
            record.update(
                status="validation_failed", reason=str(error), validation=error.report
            )
        except SearchExhausted as error:
            record.update(status="search_exhausted", reason=str(error))
            record["compile"]["budget_hit"] = True
        except Exception as error:
            record.update(
                status="compile_error", reason=f"{type(error).__name__}: {error}"
            )
        else:
            record["compile"]["wall_s"] = time.perf_counter() - compile_start
            try:
                validation = validate_result(
                    result, entry_state=job.entry_state, device=job.device, dag=job.dag
                )
                document = encode_result(
                    result,
                    entry_state=job.entry_state,
                    job=job.document,
                    dag=job.dag,
                    device=job.device,
                    inputs=job.inputs,
                    validation=validation,
                )
            except Exception as error:
                record.update(
                    status="validation_failed",
                    reason=f"{type(error).__name__}: {error}",
                )
            else:
                record.update(
                    status="ok" if validation["ok"] else "validation_failed",
                    reason=validation["failure"],
                    metrics=document["metrics"],
                    validation=validation,
                    result=document,
                )
                record["provenance"]["job_hash"] = document["provenance"]["job_hash"]
        if record["compile"]["wall_s"] is None:
            record["compile"]["wall_s"] = time.perf_counter() - compile_start
    record["worker_wall_s"] = time.perf_counter() - started
    return record


def execute_task_run(run: dict[str, Any]) -> dict[str, Any]:
    """Call the explicit task adapter, preserving telemetry and software failures."""
    from .task_plan import WORKER_STATUSES, resident_bytes, validate_task

    started = time.perf_counter()
    observed = 0
    try:
        task = validate_task(run["task"])
        initial = resident_bytes(os.getpid())
        if initial is None:
            return {
                "status": "budget_exceeded",
                "reason": "Worker RSS monitoring unavailable",
            }
        observed = initial
        if initial > task["memory_bytes"]:
            return {
                "status": "budget_exceeded",
                "reason": "memory_bytes exceeded at worker startup",
                "resource_usage": {"peak_observed_worker_rss_bytes": observed},
            }
        module, function = run["executor"].split(":")
        handler = getattr(importlib.import_module(module), function)
        record = handler(task)
        if not isinstance(record, dict) or record.get("status") not in WORKER_STATUSES:
            raise ValueError("Task handler must return a supported status object")
        observed = max(observed, resident_bytes(os.getpid()) or 0)
        if observed > task["memory_bytes"]:
            record = {
                "status": "budget_exceeded",
                "reason": "memory_bytes exceeded before worker publication",
            }
    except Exception as error:
        record = {
            "status": "software_error",
            "reason": f"{type(error).__name__}: {error}",
            "failure_kind": "handler",
        }
    return {
        **record,
        "worker_wall_s": time.perf_counter() - started,
        "resource_usage": {
            **record.get("resource_usage", {}),
            "peak_observed_worker_rss_bytes": observed,
        },
    }


def main() -> None:
    """Read one resolved run and atomically write its completion record."""
    run = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    output = Path(sys.argv[2])
    if run.get("schema") == "nadit.experiment_task/1":
        write_json(
            output.with_suffix(".started.json"),
            {"run_id": run["run_id"], "pid": os.getpid()},
        )
        write_json(output, execute_task_run(run))
    else:
        write_json(output, execute(run))


if __name__ == "__main__":
    main()
