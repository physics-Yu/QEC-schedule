"""Raw upstream environment smoke; not a T000 integration/qualification claim."""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import time

from enola_environment import ROOT, verify, write


def main():
    receipt = verify()
    from enola.enola import Enola
    from enola.scheduler.gate_scheduler import gate_scheduling
    from enola.router.router_mis import compatible_2D, maximalis_solve_sort
    out = ROOT / "scripts/outputs/T703/smoke"
    pairs = [[0, 1], [2, 3], [1, 2]]
    config = {"name": "r7-dependency-smoke", "trivial_layout": True, "routing_strategy": "maximalis_sorted", "dependency": True, "reverse_to_initial": False, "full_code": True, "to_verify": False}
    input_data = {"scope": "upstream_environment_smoke_only", "pairs": pairs, "nqubit": 4, "architecture": [4, 4, 4, 4], "config": config}
    write(out / "input.json", input_data)
    model = Enola(**config)
    model.setArchitecture(input_data["architecture"])
    model.setProgram(pairs, nqubit=4)
    stdout = io.StringIO()
    started = time.perf_counter()
    with redirect_stdout(stdout):
        output = model.solve(save_file=False)
    elapsed = time.perf_counter() - started
    write(out / "output.json", output)
    (out / "stdout.log").write_bytes(stdout.getvalue().encode("utf-8"))
    checks = {"raw_solver_returned_instructions": isinstance(output, list) and bool(output), "compatible_shared_row": compatible_2D((0, 1, 0, 1), (0, 1, 2, 3)), "reject_row_crossing": not compatible_2D((0, 1, 0, 1), (1, 0, 2, 3)), "independent_set_uses_edges": maximalis_solve_sort(3, [(0, 1)]) == [0, 2], "scheduler_independent_pairs_one_layer": len(gate_scheduling(4, [(0, 1), (2, 3)])) == 1}
    if not all(checks.values()):
        raise ValueError(f"SMOKE_FAILED: {checks}")
    write(out / "receipt.json", {"schema_version": "enola-smoke/0.1.0", "created_at_utc": datetime.now(timezone.utc).isoformat(), "environment": receipt, "wall_seconds": elapsed, "input_byte_sha256": hashlib.sha256((out / "input.json").read_bytes()).hexdigest(), "output_byte_sha256": hashlib.sha256((out / "output.json").read_bytes()).hexdigest(), "instruction_count": len(output), "checks": checks, "passed": True, "t000_qualified": False, "physics_mapping_verified": False, "scope": "library_environment_and_function_smoke_not_R4_strategy_or_project_geometry"})
    print(json.dumps({"out": str(out), "instruction_count": len(output), "wall_seconds": elapsed, "checks": checks, "t000_qualified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
