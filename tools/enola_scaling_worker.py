"""Run unmodified UCLA-VAST/Enola with compact native instruction output.

Usage: python tools/enola_scaling_worker.py case.json output --source ENOLA

Input: {"id": "n100_g0", "n": 100, "graph_id": 0, "gates": [[0, 1], ...]}.
The parent process owns time/memory limits. This worker never silently changes
the placement or routing algorithm and is not a QEC Env/continuous-path audit.

Upstream: https://github.com/UCLA-VAST/Enola, BSD-3-Clause, copyright (c) 2024
UCLA VAST Lab. Native modules are imported, not vendored or rewritten here.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stdout
import hashlib
import gzip
import importlib.metadata
import json
import math
from pathlib import Path
import random
import re
import subprocess
import sys
import time
import traceback

PARAMETERS = {"f2": 0.995, "fexc": 0.9975, "ftrans": 0.999,
              "t2_us": 1_500_000.0}
PINNED_COMMIT = "2944dbf4e163e8d2eeeec607add0d9139edce689"


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               allow_nan=False), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_case(case: dict) -> None:
    n = case["n"]
    if type(n) is not int or n < 2:
        raise ValueError("n must be an integer >= 2")
    if not case["gates"]:
        raise ValueError("The scaling workload requires at least one 2Q gate")
    for pair in case["gates"]:
        if (len(pair) != 2 or any(type(q) is not int or q < 0 or q >= n for q in pair)
                or pair[0] == pair[1]):
            raise ValueError(f"Invalid gate {pair!r}")
    # The upstream edge-coloring frontend is a simple graph; preserve failures
    # explicitly instead of collapsing repeated edges and changing the circuit.
    if len({tuple(sorted(p)) for p in case["gates"]}) != len(case["gates"]):
        raise ValueError("This commutable-graph worker requires unique 2Q pairs")


def score_program(n: int, gates: list, program: list) -> dict:
    """Independent O(instructions + transfers + n) Eq. (1) accounting.

    All atoms are globally exposed during an Enola Rydberg pulse; those pulses
    contribute no idle time, exactly as in author Simulator.simulate(). Every
    moved atom still accumulates idle time. Only atoms actively transferred are
    excluded from a transfer instruction's idle contribution.
    """
    if not program or program[0]["type"] != "Init" or program[0]["n_q"] != n:
        raise ValueError("Missing/mismatched initial instruction")
    seen = Counter()
    held = set(program[0].get("aod_qubit_idx", []))
    if held or sorted(program[0]["slm_qubit_idx"]) != list(range(n)):
        raise ValueError("Expected all atoms initially in SLM")
    active_transfer_us = [0.0] * n
    transfer_counts = [0] * n
    base_idle = execution_us = logical_us = 0.0
    pulses = spectators = max_parallel = transfers = moves = 0
    durations = Counter()
    instruction_counts = Counter()
    for index, ins in enumerate(program):
        kind = ins["type"]
        instruction_counts[kind] += 1
        if kind == "Init":
            if index != 0:
                raise ValueError("Unexpected interior Init")
            continue
        if kind == "Rydberg" and not ins["gates"]:
            continue
        dt = float(ins["duration"])
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("Invalid native instruction duration")
        execution_us += dt
        durations[kind] += dt
        if kind == "Rydberg":
            pairs = [(g["q0"], g["q1"]) for g in ins["gates"]]
            atoms = [q for pair in pairs for q in pair]
            if len(set(atoms)) != len(atoms) or any(not 0 <= q < n for q in atoms):
                raise ValueError("Invalid/overlapping gate pulse")
            seen.update(tuple(sorted(pair)) for pair in pairs)
            pulses += 1
            spectators += n - len(atoms)
            max_parallel = max(max_parallel, len(pairs))
            logical_us = execution_us
        elif kind in ("Activate", "Deactivate"):
            qs = ins["pickup_qs" if kind == "Activate" else "dropoff_qs"]
            if len(qs) != len(set(qs)) or any(not 0 <= q < n for q in qs):
                raise ValueError("Invalid transfer atom list")
            if kind == "Activate":
                if set(qs) & held:
                    raise ValueError("Atom loaded twice without unloading")
                held.update(qs)
            else:
                if not set(qs) <= held:
                    raise ValueError("Atom unloaded without loading")
                held.difference_update(qs)
            transfers += len(qs)
            base_idle += dt
            for q in qs:
                transfer_counts[q] += 1
                active_transfer_us[q] += dt
        elif kind == "Move":
            # The author Simulator ignores Move durations <= 1e-4 us. Keep its
            # model convention, while execution_us retains every duration.
            if dt > 1e-4:
                base_idle += dt
                moves += 1
        else:
            raise ValueError(f"Unsupported native instruction {kind!r}")
    if seen != Counter(tuple(sorted(pair)) for pair in gates):
        raise ValueError("Executed CZ multiset differs from the input")
    if held:
        raise ValueError("Terminal AOD remains occupied")
    idle = [max(0.0, base_idle - active) for active in active_transfer_us]
    invalid = [q for q, duration in enumerate(idle) if duration >= PARAMETERS["t2_us"]]
    losses = {
        "two_qubit": -len(gates) * math.log(PARAMETERS["f2"])
                     - spectators * math.log(PARAMETERS["fexc"]),
        "transfer": -transfers * math.log(PARAMETERS["ftrans"]),
        "decoherence": None if invalid else -sum(
            math.log1p(-t / PARAMETERS["t2_us"]) for t in idle),
    }
    log_fidelity = None if invalid else -sum(losses.values())
    return {
        "parameters": PARAMETERS, "exposure": "global",
        "model_valid": not invalid, "invalid_idle_atom_ids": invalid,
        "losses": losses, "log_fidelity": log_fidelity,
        "fidelity": None if invalid else math.exp(log_fidelity),
        "fidelity_underflow": False if invalid else math.exp(log_fidelity) == 0.0,
        "factors": {key: None if loss is None else math.exp(-loss)
                    for key, loss in losses.items()},
        "pulses": pulses, "transfers": transfers,
        "spectator_excitations": spectators, "idle_us": idle,
        "execution_us": execution_us, "logical_completion_us": logical_us,
        "max_parallel_cz": max_parallel, "movement_instructions": moves,
        "transfer_counts_by_atom": transfer_counts,
        "duration_by_instruction_us": dict(durations),
        "instruction_counts": dict(instruction_counts),
        "checks": {"cz_multiset_equal": True, "no_shared_qubit_within_pulse": True,
                   "transfer_holder_accounting": True, "terminal_aod_empty": True,
                   "continuous_collision_validation": False},
    }


class LogCapture:
    """Stream diagnostics and extract native timings without changing code."""
    def __init__(self, target):
        self.target = target
        self.pending = ""
        self.phases = {}

    def write(self, value):
        self.target.write(value)
        self.target.flush()
        self.pending += value
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            match = re.search(r"Time for (scheduling|placement|routing): ([\deE.+-]+)s", line)
            if match:
                self.phases[match[1]] = float(match[2])
            match = re.search(r"Toal Time: ([\deE.+-]+)s", line)
            if match:
                self.phases["author_total"] = float(match[1])
        return len(value)

    def flush(self):
        self.target.flush()


def native_run(case: dict, source: Path, arch: int, folder: Path,
               *, full_code=False, log_name="compiler.log"):
    # Avoid writing __pycache__ into the referenced research repository.
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source))
    import enola.enola as native_module
    Enola = native_module.Enola
    random.seed(0)
    compiler = Enola(case["id"], full_code=full_code,
                     trivial_layout=False, routing_strategy="maximalis_sorted",
                     reverse_to_initial=False, use_window=True, dependency=False,
                     l2=False, to_verify=False)
    compiler.setArchitecture([arch] * 4)
    compiler.setProgram(case["gates"], nqubit=case["n"])
    # Observe the native route function's already-computed phase times. The
    # wrapper passes every argument/result unchanged and does no extra search.
    native_route = native_module.route_qubit
    route_times = {}

    def timed_route(*args, **kwargs):
        answer = native_route(*args, **kwargs)
        route_times.update(routing=answer[1], codegen=answer[2], dynamic_placement=answer[3])
        return answer

    native_module.route_qubit = timed_route
    try:
        with (folder / log_name).open("w", encoding="utf-8") as file:
            capture = LogCapture(file)
            tick = time.perf_counter()
            with redirect_stdout(capture):
                program = compiler.solve(save_file=False)
            elapsed = time.perf_counter() - tick
    finally:
        native_module.route_qubit = native_route
    phases = capture.phases
    phases["initial_placement"] = phases.pop("placement", None)
    phases.update(route_times)
    phases["placement"] = phases["initial_placement"] + route_times["dynamic_placement"]
    phases["other"] = (
        phases.get("author_total", elapsed)
        - sum(phases.get(key, 0.0) or 0.0
              for key in ("scheduling", "placement", "routing", "codegen")))
    return program, elapsed, phases


def verify_full_parity(case, source, arch, folder, compact_program, compact_score,
                       *, reference_full=None):
    """Small-case, untimed validation against full snapshots and Simulator."""
    if case["n"] > 30:
        raise ValueError("Full-state validation is deliberately limited to n <= 30")
    if reference_full is None:
        full, elapsed, _ = native_run(case, source, arch, folder, full_code=True,
                                    log_name="parity-full-compiler.log")
        reference_metadata = {"kind": "fresh full_code=True native compilation"}
    else:
        path = Path(reference_full)
        raw = gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_bytes()
        full = json.loads(raw)
        if not full or not full[0].get("state", {}).get("qubits"):
            raise ValueError("Parity reference must contain original full-state snapshots")
        elapsed = None
        reference_metadata = {"kind": "existing full_code=True instructions; exact comparison required",
                              "path": str(path.resolve()), "sha256": digest(path)}
    reduced = [{key: value for key, value in ins.items() if key != "state"} for ins in full]
    executable = [{key: value for key, value in ins.items() if key != "state"}
                  for ins in compact_program]
    # Native tuples and their stored JSON arrays have identical instructions.
    if json.dumps(reduced, sort_keys=True) != json.dumps(executable, sort_keys=True):
        raise AssertionError("full_code changes executable native instructions")
    dump(folder / "parity-full-program.json", full)
    from simulator import Simulator
    author = Simulator(str(folder / "parity-full-program.json"), {}).simulate()
    expected = {
        "cir_fidelity": compact_score["fidelity"],
        "cir_fidelity_2q_gate": PARAMETERS["f2"] ** len(case["gates"]),
        "cir_fidelity_2q_gate_for_idle": PARAMETERS["fexc"] ** compact_score["spectator_excitations"],
        "cir_fidelity_atom_transfer": compact_score["factors"]["transfer"],
        "cir_fidelity_coherence": compact_score["factors"]["decoherence"],
    }
    for key, value in expected.items():
        if not math.isclose(author[key], value, rel_tol=1e-10, abs_tol=1e-12):
            raise AssertionError(f"Author Simulator mismatch in {key}")
    check = {"status": "passed", "executable_instructions_identical": True,
             "author_simulator_equal": True, "full_compile_seconds_excluded": elapsed,
             "reference": reference_metadata,
             "author_simulator": author, "expected": expected,
             "scope": "Instruction and Eq1 parity, not continuous swept safety"}
    dump(folder / "full-parity.json", check)
    return {key: value for key, value in check.items() if key not in ("author_simulator", "expected")}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("case", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--arch", type=int, help="Square architecture side; default max(16, ceil(sqrt(n)) + 4)")
    parser.add_argument("--window-size", type=int, choices=[1000], default=1000,
                        help="The pinned native implementation supports its fixed window1000")
    parser.add_argument("--verify-full", action="store_true")
    parser.add_argument("--reference-full", type=Path,
                        help="Validate against existing full-state JSON/JSON.gz instead of rerunning SA")
    args = parser.parse_args(argv)
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    if (folder / "result.json").exists():
        raise FileExistsError("Refusing to overwrite an existing benchmark result")
    case = json.loads(args.case.read_text(encoding="utf-8"))
    result = {"id": case.get("id"), "n": case.get("n"),
              "graph_id": case.get("graph_id"), "method": "enola"}
    start = time.perf_counter()
    try:
        validate_case(case)
        source = args.source.resolve()
        router_text = (source / "enola/router/router_mis.py").read_text(encoding="utf-8")
        if "vector_threshold = 1000" not in router_text:
            raise ValueError("Upstream window implementation changed; review before benchmarking")
        arch = args.arch if args.arch is not None else max(16, math.ceil(math.sqrt(case["n"])) + 4)
        if arch < 1 or arch * arch < case["n"]:
            raise ValueError("Architecture must contain every atom")
        source_files = [source / "LICENSE", source / "simulator.py", source / "animation.py",
                        *sorted((source / "enola").rglob("*.py"))]
        hashes = {p.relative_to(source).as_posix(): digest(p) for p in source_files}
        try:
            commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"],
                                             text=True, stderr=subprocess.DEVNULL).strip()
        except subprocess.CalledProcessError:
            commit = None  # Source-only snapshots still retain per-file SHA256.
        provenance = {"upstream": "https://github.com/UCLA-VAST/Enola",
                      "expected_commit": PINNED_COMMIT, "checkout_commit": commit,
                      "source": str(source), "sha256": hashes,
                      "license": "BSD-3-Clause; copyright (c) 2024 UCLA VAST Lab",
                      "worker_sha256": digest(Path(__file__)),
                      "input_sha256": digest(args.case),
                      "python": sys.version,
                      "versions": {name: importlib.metadata.version(name)
                                   for name in ("networkx", "rustworkx")}}
        configuration = {"architecture": [arch] * 4, "trivial_layout": False,
                         "placement": "native initial SA and dynamic partial SA",
                         "reverse_to_initial": False, "routing_strategy": "maximalis_sorted",
                         "use_window": True, "window_size": 1000, "full_code": False,
                         "seed": 0, "dependency": False, "l2": False,
                         "native_code_modified": False,
                         "instrumentation": "route return-value timings observed; all arguments/results unchanged",
                         "architecture_rule": "Explicit override" if args.arch else "max(16, ceil(sqrt(n)) + 4); local scaling resource convention, not exact paper hardware",
                         "geometry_note": "Native Enola unzoned model; not QEC Env geometry"}
        dump(folder / "provenance.json", provenance)
        dump(folder / "configuration.json", configuration)
        program, elapsed, phases = native_run(case, source, arch, folder)
        dump(folder / "program.json", program)
        score = score_program(case["n"], case["gates"], program)
        dump(folder / "score.json", score)
        if hashes != {p.relative_to(source).as_posix(): digest(p) for p in source_files}:
            raise RuntimeError("Native source changed during compilation")
        result.update(status="completed", native_compile_seconds=elapsed,
                      compile_seconds=elapsed, phases=phases, score=score,
                      model_valid=score["model_valid"], execution_us=score["execution_us"],
                      pulses=score["pulses"], transfers=score["transfers"],
                      max_parallel_cz=score["max_parallel_cz"],
                      configuration=configuration,
                      native_execution_model="Author codegen sequential instruction durations in us",
                      physical_certification="Native instruction bookkeeping only; no QEC Env or continuous collision validation")
        if args.verify_full or args.reference_full:
            result["full_parity"] = verify_full_parity(
                case, source, arch, folder, program, score, reference_full=args.reference_full)
    except Exception as exc:
        result.update(status="failed", error={"type": type(exc).__name__,
                      "message": str(exc), "traceback": traceback.format_exc()})
    result["worker_seconds"] = time.perf_counter() - start
    dump(folder / "result.json", result)
    print(json.dumps({key: result[key] for key in ("id", "status", "worker_seconds")}), flush=True)
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
