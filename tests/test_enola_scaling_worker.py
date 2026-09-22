"""Independent negative/positive checks for the native benchmark accountant."""
import importlib.util
import math
import json
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "enola_scaling_worker", Path(__file__).parents[1] / "tools/enola_scaling_worker.py")
WORKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKER)


def program(move_us=100):
    return [
        {"type": "Init", "n_q": 3, "slm_qubit_idx": [0, 1, 2]},
        {"type": "Activate", "duration": 15, "pickup_qs": [0]},
        {"type": "Move", "duration": move_us},
        {"type": "Deactivate", "duration": 15, "dropoff_qs": [0]},
        {"type": "Rydberg", "duration": .36, "gates": [{"q0": 0, "q1": 1}]},
    ]


def test_atom_transfer_counts_and_global_spectator_idle():
    result = WORKER.score_program(3, [[0, 1]], program())
    assert result["transfers"] == 2
    assert result["spectator_excitations"] == 1
    assert result["idle_us"] == [100, 130, 130]
    expected = .995 * .9975 * .999 ** 2 * (1 - 100 / 1.5e6) * (1 - 130 / 1.5e6) ** 2
    assert math.isclose(result["fidelity"], expected, rel_tol=1e-12)


def test_reject_wrong_gate_and_transfer_bookkeeping():
    with pytest.raises(ValueError, match="multiset"):
        WORKER.score_program(3, [[1, 2]], program())
    broken = program()
    broken[3]["dropoff_qs"] = [1]
    with pytest.raises(ValueError, match="without loading"):
        WORKER.score_program(3, [[0, 1]], broken)


def test_model_nonpositive_domain_remains_explicit():
    result = WORKER.score_program(3, [[0, 1]], program(1.5e6))
    assert not result["model_valid"]
    assert result["fidelity"] is None
    assert result["log_fidelity"] is None
    assert result["losses"]["decoherence"] is None
    assert result["invalid_idle_atom_ids"] == [0, 1, 2]


def test_repeated_edges_are_not_silently_deduplicated():
    with pytest.raises(ValueError, match="unique"):
        WORKER.validate_case({"n": 3, "gates": [[0, 1], [1, 0]]})


def test_full_reference_parity_preserves_metadata_and_json_coordinates(tmp_path, monkeypatch):
    compact = program()
    compact[0]["slm_qubit_xys"] = [(0, 0), (19, 0), (38, 0)]
    score = WORKER.score_program(3, [[0, 1]], compact)
    full = json.loads(json.dumps(compact))
    full[0]["state"] = {"qubits": [{"id": 0}, {"id": 1}, {"id": 2}]}
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps(full))
    result = {
        "cir_fidelity": score["fidelity"], "cir_fidelity_2q_gate": .995,
        "cir_fidelity_2q_gate_for_idle": .9975,
        "cir_fidelity_atom_transfer": score["factors"]["transfer"],
        "cir_fidelity_coherence": score["factors"]["decoherence"],
    }
    monkeypatch.setitem(sys.modules, "simulator", SimpleNamespace(
        Simulator=lambda *_: SimpleNamespace(simulate=lambda: result)))
    check = WORKER.verify_full_parity({"n": 3, "gates": [[0, 1]]}, None, 16,
                                     tmp_path, compact, score, reference_full=reference)
    assert check["status"] == "passed"
    assert check["reference"]["sha256"] == WORKER.digest(reference)
