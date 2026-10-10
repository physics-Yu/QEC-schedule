"""Offline finite table generator; runtime frontend has no pygridsynth dependency.

Use an existing, explicitly supplied dependency directory. Does not install or
modify it. Each completed angle has a checkpoint; --resume reuses only matching
generator configuration and dependency hashes. No state vectors are created.
"""

import argparse
from fractions import Fraction
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import platform
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, data):
    path.write_bytes((json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deps-dir", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    deps = args.deps_dir.resolve(strict=True)
    sys.path.insert(0, str(deps))
    import mpmath as mp
    from pygridsynth.gridsynth import gridsynth_circuit
    if version("pygridsynth") != "1.2.0" or version("mpmath") != "1.3.0":
        raise SystemExit("Only pygridsynth==1.2.0 and mpmath==1.3.0 are qualified for this generator")
    root = Path(__file__).resolve().parents[2]
    output = root / "examples/logical/synthesis-generation"
    output.mkdir(exist_ok=True)
    hashes = {str(p.relative_to(deps)).replace('\\', '/'): digest(p)
              for module in ("pygridsynth", "mpmath") for p in sorted((deps / module).rglob("*.py"))}
    config = {"schema_version": "R2RotationGeneration/0.1.0", "artifact_id": "R2-T202-generation",
              "provenance": {"owner": "R2", "task": "T202", "kb": "kb-0004"},
              "packages": {"pygridsynth": "1.2.0", "mpmath": "1.3.0"},
              "dependency_source_sha256": hashes, "generator_sha256": digest(Path(__file__)),
              "seed": 7, "dps": 80, "requested_epsilon": "0.00001", "up_to_phase": False,
              "denominators": [8, 16, 32, 64, 128],
              "budget": {"wall_seconds": 900, "parallelism": 1, "memory_mib": 512,
                         "scope": "five_single_qubit_syntheses", "enforcement": "diagnostic"}}
    identity = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
    records = []
    start = time.perf_counter()
    for denominator in config["denominators"]:
        checkpoint = output / f"minus_pi_over_{denominator}.json"
        if args.resume and checkpoint.is_file():
            record = json.loads(checkpoint.read_text(encoding="utf-8"))
            if record["generation_identity"] != identity:
                raise SystemExit("Checkpoint input mismatch; refusing to reuse " + str(checkpoint))
        else:
            begin = time.perf_counter()
            with mp.workdps(80):
                circuit = gridsynth_circuit(theta=-mp.pi / denominator, epsilon=mp.mpf("0.00001"),
                                            seed=7, dps=80, up_to_phase=False)
                names = []
                phase = circuit.phase
                upstream_word = [g.to_simple_str() for g in circuit]
                for name in reversed(upstream_word):
                    if name == "W":
                        phase += mp.pi / 4
                    elif name in ("H", "T", "S", "X"):
                        names.append(name)
                    else:
                        raise RuntimeError("UNSUPPORTED_SYNTHESIZER_GATE: " + name)
                eighths = int(mp.nint(phase / mp.pi * 8))
                if abs(phase / mp.pi - mp.mpf(eighths) / 8) > mp.mpf("1e-70"):
                    raise RuntimeError("UNSUPPORTED_NONRATIONAL_GLOBAL_PHASE")
                correction = Fraction(eighths, 8) - Fraction(1, 2 * denominator)
                correction %= 2
                if correction > 1:
                    correction -= 2
                record = {"generation_identity": identity, "denominator": denominator,
                          "angle_pi": {"numerator": -1, "denominator": denominator},
                          "chronological_gates": names,
                          "global_phase_pi": {"numerator": correction.numerator,
                                              "denominator": correction.denominator},
                          "upstream_gates_matrix_order": upstream_word,
                          "upstream_circuit_phase_over_pi": mp.nstr(circuit.phase / mp.pi, 80),
                          "t_count": names.count("T"), "tdg_count": 0,
                          "elapsed_seconds": time.perf_counter() - begin}
            write_json(checkpoint, record)
        records.append(record)
        print(json.dumps({"denominator": denominator, "gates": len(record["chronological_gates"]),
                          "t_count": record["t_count"], "seconds": record["elapsed_seconds"]}), flush=True)
    table = {str(r["denominator"]): {k: r[k] for k in ("angle_pi", "chronological_gates", "global_phase_pi")}
             for r in records}
    header = '# Generated by examples/logical/generate_rotation_table.py. Do not hand-edit.\n'
    header += '# pygridsynth 1.2.0; mpmath 1.3.0; seed=7; dps=80; epsilon=1e-5.\n'
    payload = header + 'TABLE_VERSION = "shor15-feedback/1"\nROTATIONS = ' + repr(table) + '\n'
    table_path = root / "src/na_pipeline/frontend/rotation_table.py"
    table_path.write_bytes(payload.encode("utf-8"))
    write_json(output / "generation.json", {**config, "generation_identity": identity,
               "deps_dir": str(deps), "python_executable": sys.executable, "python": sys.version,
               "host": platform.node(), "elapsed_seconds": time.perf_counter() - start,
               "table_sha256": digest(table_path), "complete": True,
               "execution_kind": "compile_plan", "quantum_state_simulated": False,
               "hardware_executed": False, "loss_enabled": False})


if __name__ == "__main__":
    main()
