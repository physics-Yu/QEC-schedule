"""Small subprocess boundary around frozen NADiT APIs; no compiler modifications."""

import json
import sys
import time
from pathlib import Path


def write(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(document, allow_nan=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def main():
    command, root, label, destination, *rest = sys.argv[1:]
    root, destination = Path(root), Path(destination)
    manifest = json.loads((root / "manifest.json").read_text())
    case = next(c for c in manifest["cases"] if c["label"] == label)
    if command == "compile":
        from nadit_physical_compiler.job import compile_job, load_job
        from nadit_physical_compiler.replay import replay
        from nadit_physical_compiler.serialization import encode_result
        from nadit_physical_compiler.validation import validate_result

        job = load_job(root / case["job"])
        start = time.perf_counter()
        result = compile_job(job)
        compile_s = time.perf_counter() - start
        validation = validate_result(
            result, entry_state=job.entry_state, device=job.device, dag=job.dag
        )
        assert validation["ok"], validation
        assert replay(result.program, job.entry_state, job.device) == result.exit_state
        assert result.exit_state == job.entry_state
        doc = encode_result(
            result,
            entry_state=job.entry_state,
            job=job.document,
            device=job.device,
            dag=job.dag,
            inputs=job.inputs,
            validation=validation,
        )
        assert doc["provenance"]["git_commit"] == manifest["commit"]
        write(destination / "result.json", doc)
        write(
            destination / "compile-metrics.json",
            {
                "compile_wall_s": compile_s,
                "metrics": doc["metrics"],
                "replay": True,
                "home_return": True,
            },
        )
    elif command == "export":
        import stim

        from nadit_physical_compiler.methods import run_method

        doc = json.loads((destination / "result.json").read_text())
        annotations = json.loads((root / case["annotations"]).read_text())
        exported = run_method(
            "stim/v1",
            doc,
            annotations=annotations,
            noise_params=json.loads((root / "noise.json").read_text()),
        )
        circuit = stim.Circuit(exported.circuit)
        d = case["distance"]
        assert circuit.num_measurements == d * (d * d - 1) + d * d
        assert circuit.num_detectors == d * (d * d - 1) and circuit.num_observables == 1
        ideal = circuit.without_noise()
        ideal.detector_error_model()
        samples, obs = ideal.compile_detector_sampler(seed=1).sample(
            shots=64, separate_observables=True
        )
        assert not samples.any() and not obs.any()
        reference = ideal.reference_sample()
        indices = exported.report["measurement_records"]
        assert all(
            sum(bool(reference[indices[str(mid)]]) for mid in p["measurement_ids"]) % 2
            == 0
            for p in annotations["detectors"] + annotations["observables"]
        )
        circuit.detector_error_model(
            decompose_errors=True, approximate_disjoint_errors=True
        )
        (destination / "circuit.stim").write_text(
            exported.circuit, encoding="utf-8", newline="\n"
        )
        write(destination / "export.json", exported.report)
    elif command == "sample":
        from nadit_physical_compiler.methods.memory import sample_memory
        from nadit_physical_compiler.methods.stim_export import StimExport

        shard, shots = int(rest[0]), int(rest[1])
        exported = StimExport(
            (destination / "circuit.stim").read_text(),
            json.loads((destination / "export.json").read_text()),
        )
        stats = sample_memory(
            exported,
            shots=shots,
            seed=case["seeds"][shard],
            batch_size=manifest["config"]["budget"]["batch_size"],
        )
        stats.pop("loss")  # Stored once, unchanged, in export.json.
        stats.update(shard=shard, run_id=case["run_id"], loss_report="../export.json")
        write(destination / "shards" / f"{shard:02d}.json", stats)
    else:
        raise ValueError(command)


if __name__ == "__main__":
    main()
