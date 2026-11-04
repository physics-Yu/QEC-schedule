"""Public SMT outcomes preserve infeasibility and reproducible evidence."""

import json
from pathlib import Path

from smt_solver_support import tiny_context

from nadit_physical_compiler.cli import main
from nadit_physical_compiler.serialization import encode_device


def tiny_job(tmp_path: Path, *, feasible: bool) -> Path:
    """Use a real static CZ job with either an attainable or impossible pair."""
    context = tiny_context(radius=2.1 if feasible else 1)
    qasm = tmp_path / "input.qasm3"
    qasm.write_text('OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; cz q[0], q[1];')
    path = tmp_path / "job.json"
    path.write_text(
        json.dumps(
            {
                "schema": "nadit.job/1",
                "circuit": {"qasm": str(qasm)},
                "device": encode_device(context.device),
                "aod": "a",
                "entry": {"kind": "explicit", "atoms": [[0, "0", 0], [1, "10", 1]]},
                "strategy": {
                    "kind": "smt",
                    "xs": [0, 2, 10] if feasible else [0, 10],
                    "ys": [0],
                    "horizon": 5 if feasible else 3,
                    "timeout_s": 20,
                    "time_quantum_us": 0.1,
                },
            }
        )
    )
    return path


def test_cli_unsat_is_not_budget_exhaustion_and_saves_evidence(tmp_path, capsys):
    job = tiny_job(tmp_path, feasible=False)
    output = tmp_path / "result.json"
    assert main(["compile", str(job), "-o", str(output)]) == 2
    document = json.loads(capsys.readouterr().out)
    assert document["status"] == "unsat_in_domain"
    assert document["budget_hit"] is False
    assert not output.exists()
    evidence = json.loads(output.with_suffix(".evidence.json").read_text())
    assert evidence["result_sha256"] is None
    assert evidence["evidence"]["status"] == "unsat_in_domain"
