"""Saved-result translation and decoded surface-memory integration."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import stim

from nadit_physical_compiler.job import compile_job, load_job
from nadit_physical_compiler.methods import run_method
from nadit_physical_compiler.methods.memory import sample_memory
from nadit_physical_compiler.methods.surface_memory import prepare_memory
from nadit_physical_compiler.replay import replay
from nadit_physical_compiler.serialization import encode_result
from nadit_physical_compiler.validation import validate_result


def compile_document(path: Path) -> dict[str, Any]:
    job = load_job(path)
    result = compile_job(job)
    assert replay(result.program, job.entry_state, job.device) == result.exit_state
    validation = validate_result(
        result, entry_state=job.entry_state, device=job.device, dag=job.dag
    )
    assert validation["ok"], validation
    return encode_result(
        result,
        entry_state=job.entry_state,
        job=job.document,
        device=job.device,
        dag=job.dag,
        inputs=job.inputs,
        validation=validation,
    )


@pytest.mark.parametrize("distance", [3, 5, 7, 9])
@pytest.mark.parametrize("basis", ["x", "z"])
def test_standard_memory_generation(distance: int, basis: str, tmp_path: Path) -> None:
    paths = prepare_memory(tmp_path, distance=distance, basis=basis)
    reference = stim.Circuit.from_file(paths["reference"])
    assert reference.num_measurements == distance * (distance**2 - 1) + distance**2
    assert len(reference.get_final_qubit_coordinates()) == 2 * distance**2 - 1
    samples, obs = reference.compile_detector_sampler(seed=1).sample(
        shots=32, separate_observables=True
    )
    assert not samples.any() and not obs.any()
    for path in paths["jobs"].values():
        job = load_job(Path(path))
        assert len(job.entry_state.atoms) == 2 * distance**2 - 1
        assert job.document["entry"]["kind"] == "explicit"


@pytest.mark.parametrize("backend", ["nonzoned", "qec"])
@pytest.mark.parametrize("basis", ["x", "z"])
def test_compiled_memory_zero_noise_and_pauli_decoding(
    backend: str, basis: str, tmp_path: Path
) -> None:
    paths = prepare_memory(tmp_path, distance=3, basis=basis)
    document = compile_document(Path(paths["jobs"][backend]))
    annotations = json.loads(Path(paths["annotations"]).read_text())
    before = deepcopy(document)
    exported = run_method("stim/v1", document, annotations=annotations)
    circuit = stim.Circuit(exported.circuit)
    reference = stim.Circuit.from_file(paths["reference"])
    assert circuit.num_measurements == reference.num_measurements
    assert circuit.num_detectors == reference.num_detectors
    assert circuit.num_observables == 1
    assert circuit.num_ticks == len(document["program"]["steps"])
    samples, obs = circuit.compile_detector_sampler(seed=1).sample(
        shots=128, separate_observables=True
    )
    assert not samples.any() and not obs.any()
    assert sample_memory(exported, shots=64, seed=1)["failures"] == 0
    noisy = run_method(
        "stim/v1",
        document,
        annotations=annotations,
        noise_params={"readout_flip": 0.01, "transport": {"move_pauli": [0.001] * 3}},
    )
    stats = sample_memory(noisy, shots=128, seed=2)
    assert stats["shots"] == 128
    assert stats["scope"] == "pauli_readout_only"
    assert stats == sample_memory(noisy, shots=128, seed=2)
    assert document == before


def test_loss_is_reported_without_inventing_erasure(tmp_path: Path) -> None:
    paths = prepare_memory(tmp_path, distance=3)
    document = compile_document(Path(paths["jobs"]["nonzoned"]))
    annotations = json.loads(Path(paths["annotations"]).read_text())
    exported = run_method(
        "stim/v1",
        document,
        annotations=annotations,
        noise_params={"transport": {"load_loss": 0.1}},
    )
    assert exported.report["noise_report"]["noise"]["loss"]["expected_lost_atoms"] > 0
    assert "HERALDED" not in exported.circuit
    assert sample_memory(exported, shots=32, seed=3)["failures"] == 0
    annotations["qasm_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="source"):
        run_method("stim/v1", document, annotations=annotations)


@pytest.mark.parametrize("backend", ["nonzoned", "qec"])
def test_compiled_parities_have_zero_absolute_reference_and_distance_three(
    backend: str, tmp_path: Path
) -> None:
    paths = prepare_memory(tmp_path, distance=3)
    document = compile_document(Path(paths["jobs"][backend]))
    annotations = json.loads(Path(paths["annotations"]).read_text())
    exported = run_method(
        "stim/v1",
        document,
        annotations=annotations,
        noise_params={
            "single": {"probabilities": [0.001] * 3},
            "cz": {"probabilities": [0.001] * 15},
            "readout_flip": 0.001,
            "reset_flip": 0.001,
        },
    )
    circuit = stim.Circuit(exported.circuit)
    reference = circuit.reference_sample()
    mapping = exported.report["measurement_records"]
    for parity in annotations["detectors"] + annotations["observables"]:
        assert (
            sum(bool(reference[mapping[str(mid)]]) for mid in parity["measurement_ids"])
            % 2
            == 0
        )
    # Wrong hook order or a missing logical boundary can lower the distance.
    assert len(circuit.shortest_graphlike_error()) == 3
