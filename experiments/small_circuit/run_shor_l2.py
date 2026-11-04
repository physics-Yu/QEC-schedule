"""Derive a semiclassical Shor circuit and sample its physical schedule with the L2 engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
SHOR = HERE / "shor"
sys.path.insert(0, str(HERE.parents[1] / "modules" / "physical_compiler" / "src"))
sys.path.insert(0, str(HERE))

from nadit_physical_compiler.execution import FakeBackend
from nadit_physical_compiler.job import compile_job, loads_job
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import (
    decode_result,
    encode_dag,
    encode_device,
    encode_layout,
    encode_result,
)
from nadit_physical_compiler.validation import validate_result
from shor.guarded_plan import guarded_plan
from shor.semiclassical import semiclassical_source


def _job(n: int):
    source = (SHOR / "inputs" / f"n{n}.qasm3").read_text(encoding="utf-8")
    derived = semiclassical_source(source)
    name = f"n{n}.semiclassical.qasm3"
    spec = json.loads((SHOR / "zoned_job.json").read_bytes())
    spec["circuit"]["qasm"] = name
    with tempfile.TemporaryDirectory() as directory:
        (Path(directory) / name).write_bytes(derived.encode())
        job = loads_job(json.dumps(spec), base_dir=directory)

    # Reserve all conditional pulse slots once. Each shot supplies its own measurement outcomes.
    overrides = {node.result: 1 for node in job.dag.nodes if node.result is not None}
    seed = spec["case"]["seed"]
    document = {
        **job.document,
        "circuit": {**job.document["circuit"], "qasm": name},
        "case": {
            "seed": seed,
            "overrides": {str(ref.measurement_id): 1 for ref in overrides},
        },
    }
    return replace(
        job, document=document, measurement_backend=FakeBackend(seed, overrides)
    ), {
        "n": n,
        "coherent_qasm_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "semiclassical_qasm_sha256": job.inputs["qasm_sha256"],
    }


def _physical_result(job, source: dict, dag: dict, saved: Path | None):
    if saved is None:
        compiled = compile_job(job)
    else:
        document = json.loads(saved.read_bytes())
        expected = {
            "source_provenance": source,
            "inputs": job.inputs,
            "dag": dag,
            "job": job.document,
            "device": encode_device(job.device),
            "entry_state": encode_layout(job.entry_state),
        }
        for key, value in expected.items():
            if key not in document or canonical_hash(document[key]) != canonical_hash(
                value
            ):
                raise ValueError(
                    f"Saved {key} does not match the current input and resolved job"
                )
        compiled = decode_result(document)

    report = validate_result(
        compiled, entry_state=job.entry_state, device=job.device, dag=job.dag
    )
    if not report["ok"]:
        raise ValueError(f"Physical validation failed: {report}")
    if saved is None:
        document = encode_result(
            compiled,
            job=job.document,
            entry_state=job.entry_state,
            device=job.device,
            dag=job.dag,
            inputs=job.inputs,
            validation=report,
        )
        document["source_provenance"] = source
    return document, report


def prepare_physical_template(n: int, saved: Path | None = None) -> tuple[dict, dict]:
    """Return the validated maximal-slot result and its current validation report."""
    job, source = _job(n)
    return _physical_result(job, source, encode_dag(job.dag), saved)


def _sample(plan: dict, shots: int, seed: int) -> dict:
    script = """
const {plan, shots, seed} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
const engine = require(process.argv[1]);
const r = engine.sample(plan, engine.DEFAULTS, shots, seed);
const fields = ['backend', 'parameters', 'noise_model', 'n', 'shots', 'seed', 'plan_duration_us',
                'bit_order', 'histogram', 'valid_shots', 'lost_shots', 'first_loss_by_cause'];
process.stdout.write(JSON.stringify(Object.fromEntries(fields.map(key => [key, r[key]]))));
"""
    run = subprocess.run(
        ["node", "-e", script, str(SHOR / "browser_engine.js")],
        input=json.dumps({"plan": plan, "shots": shots, "seed": seed}),
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(run.stdout)


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode()
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, choices=(15, 21), default=15)
    parser.add_argument("--shots", type=int, default=32)
    parser.add_argument("--seed", type=int, default=17)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--compile",
        action="store_true",
        help="Compile and validate a fresh schedule (default)",
    )
    mode.add_argument(
        "--result",
        type=Path,
        help="Use a previously saved and compatible physical result",
    )
    parser.add_argument(
        "--save-result", type=Path, help="Save the newly compiled physical result"
    )
    parser.add_argument(
        "--ir-out",
        type=Path,
        help="Write the native PhysicalDAG JSON used for compilation",
    )
    parser.add_argument(
        "--out", type=Path, help="Write sample receipt JSON (stdout by default)"
    )
    args = parser.parse_args()
    if not 1 <= args.shots <= 10000 or not 0 <= args.seed <= 0xFFFFFFFF:
        parser.error(
            "shots must be 1..10000 and seed must be an unsigned 32-bit integer"
        )
    if args.result and args.save_result:
        parser.error("--save-result requires a fresh compilation")
    paths = [
        path.resolve()
        for path in (args.result, args.save_result, args.ir_out, args.out)
        if path
    ]
    if len(paths) != len(set(paths)):
        parser.error("--result, --save-result, --ir-out and --out need distinct paths")

    document, report = prepare_physical_template(args.n, args.result)
    source, dag = document["source_provenance"], document["dag"]
    plan = guarded_plan(args.n, document)
    sample = _sample(plan, args.shots, args.seed)
    receipt = {
        "physical_compilation_run": args.result is None,
        "validation": {"run_this_time": True, "report": report},
        "physical_dag_nodes": len(dag["nodes"]),
        "guarded_slots": sum(
            "guard" in action for step in plan["steps"] for action in step["actions"]
        ),
        "source": source,
        "physical_dag_sha256": canonical_hash(dag),
        "physical_result_sha256": canonical_hash(document),
        "l2_plan_sha256": canonical_hash(plan),
        "l2_engine_sha256": hashlib.sha256(
            (SHOR / "browser_engine.js").read_bytes()
        ).hexdigest(),
        "sample": sample,
    }
    if args.save_result:
        _write(args.save_result, document)
    if args.ir_out:
        _write(args.ir_out, dag)
    if args.out:
        _write(args.out, receipt)
    else:
        print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
