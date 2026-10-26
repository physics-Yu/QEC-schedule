"""Explicit QEC annotations survive arbitrary wire-to-atom mappings."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from nadit_physical_compiler.atom_ir import AtomProgram
from nadit_physical_compiler.compiler import CompilationResult
from nadit_physical_compiler.device import Device, Position, SLMSite, Timing
from nadit_physical_compiler.serialization import encode_result
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder
from nadit_physical_compiler.visualization import build_result_trace
from nadit_physical_compiler.visualization.cli import view_results


def saved():
    ids = (20, 70, 50, 90)
    sites = tuple(SLMSite(str(i), Position(i * 10, 0)) for i in range(4))
    entry = AtomLayout(
        tuple(
            AtomState(a, s.position, SLMHolder(s.id))
            for a, s in zip(ids, sites, strict=True)
        ),
        (),
        ids,
    )
    device = Device("overlay", (), sites, (), Timing(1, 1, 1))
    result = CompilationResult(AtomProgram(()), entry, (), (), ())
    from nadit_physical_compiler.serialization import encode_device

    return encode_result(
        result, entry_state=entry, job={"device": encode_device(device)}, provenance={}
    )


def metadata():
    return {
        "schema": "nadit.qec-overlay/1",
        "title": "Example code",
        "checks": [
            {"id": "X0", "basis": "X", "ancilla_qubit": 2, "data_qubits": [0, 1]},
            {"id": "Z0", "basis": "Z", "ancilla_qubit": 3, "data_qubits": [0, 1]},
        ],
    }


def test_overlay_maps_physical_wires_to_atom_identities_without_mutating_result():
    document = saved()
    annotation = metadata()
    before = deepcopy(document)
    trace = build_result_trace(document, document["job"]["device"], qec=annotation)
    assert trace["qec"]["checks"][0]["ancilla"] == 50
    assert trace["qec"]["checks"][1]["ancilla"] == 90
    assert trace["qec"]["checks"][0]["data"] == [20, 70]
    assert trace["qec"]["data"] == [{"atom": 20, "qubit": 0}, {"atom": 70, "qubit": 1}]
    annotation["checks"][0]["data_qubits"].append(3)
    assert trace["qec"]["checks"][0]["data_qubits"] == [0, 1]
    assert document == before


def test_absent_annotation_does_not_infer_stabilizers_from_atom_numbers():
    document = saved()
    assert "qec" not in build_result_trace(document, document["job"]["device"])
    document["qec"] = metadata()
    assert (
        len(build_result_trace(document, document["job"]["device"])["qec"]["checks"])
        == 2
    )


@pytest.mark.parametrize(
    "change", ["unknown_qubit", "basis", "same_role", "duplicate_check"]
)
def test_invalid_annotations_do_not_silently_mislabel_atoms(change):
    document = saved()
    qec = metadata()
    if change == "unknown_qubit":
        qec["checks"][0]["ancilla_qubit"] = 10
    elif change == "basis":
        qec["checks"][0]["basis"] = "Y"
    elif change == "same_role":
        qec["checks"][0]["data_qubits"] = [2]
    else:
        qec["checks"][1]["id"] = "X0"
    with pytest.raises(ValueError, match="qec"):
        build_result_trace(document, document["job"]["device"], qec=qec)


def test_sidecar_export_preserves_saved_result_bytes(tmp_path: Path):
    result = tmp_path / "result.json"
    result.write_text(json.dumps(saved()))
    annotation = tmp_path / "qec.json"
    annotation.write_text(json.dumps(metadata()))
    before = result.read_bytes()
    output = tmp_path / "viewer.html"
    trace_path = tmp_path / "trace.json"
    view_results([result], output, qec_metadata=annotation, json_output=trace_path)
    assert result.read_bytes() == before
    trace = json.loads(trace_path.read_text())["traces"][0]
    assert trace["qec"]["checks"][0]["ancilla"] == 50
    html = output.read_text(encoding="utf-8")
    assert (
        "qec-x-toggle" in html and "qec-z-toggle" in html and "qec-links-toggle" in html
    )
    assert "AtomReplayQEC" in html


def test_qec_sidecar_cannot_be_overwritten_as_html(tmp_path: Path):
    result = tmp_path / "result.json"
    result.write_text(json.dumps(saved()))
    annotation = tmp_path / "qec.json"
    annotation.write_text(json.dumps(metadata()))
    with pytest.raises(ValueError, match="distinct"):
        view_results([result], annotation, qec_metadata=annotation)


def test_nadit_view_accepts_qec_sidecar(tmp_path: Path):
    from nadit_physical_compiler.cli import main

    result = tmp_path / "result.json"
    result.write_text(json.dumps(saved()))
    annotation = tmp_path / "qec.json"
    annotation.write_text(json.dumps(metadata()))
    trace = tmp_path / "trace.json"
    assert (
        main(
            [
                "view",
                str(result),
                "-o",
                str(tmp_path / "index.html"),
                "--qec",
                str(annotation),
                "--json",
                str(trace),
            ]
        )
        == 0
    )
    assert len(json.loads(trace.read_text())["traces"][0]["qec"]["checks"]) == 2
