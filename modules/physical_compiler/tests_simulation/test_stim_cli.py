"""Installed-style CLI export and sampling without a compiler side effect."""

import json
from pathlib import Path

import pytest
from test_stim_method import compile_document

from nadit_physical_compiler.cli import main
from nadit_physical_compiler.discovery import describe
from nadit_physical_compiler.methods.surface_memory import prepare_memory


def test_method_cli_and_sampling_do_not_recompile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    paths = prepare_memory(tmp_path / "input", distance=3)
    document = compile_document(Path(paths["jobs"]["nonzoned"]))
    saved = tmp_path / "result.json"
    saved.write_text(json.dumps(document))
    before = saved.read_bytes()

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Post-processing invoked a compiler")

    monkeypatch.setattr("nadit_physical_compiler.job.compile_job", forbidden)
    monkeypatch.setattr("nadit_physical_compiler.cli.compile_job", forbidden)
    output = tmp_path / "export.stim"
    assert (
        main(
            [
                "method",
                "stim/v1",
                str(saved),
                "--annotations",
                paths["annotations"],
                "-o",
                str(output),
            ]
        )
        == 0
    )
    response = json.loads(capsys.readouterr().out)
    assert response["counts"]["measurements"] == 33
    assert response["counts"]["detectors"] == 24
    assert (
        main(
            [
                "memory",
                "sample",
                str(output.with_suffix(".json")),
                "--shots",
                "16",
                "--seed",
                "11",
            ]
        )
        == 0
    )
    stats = json.loads(capsys.readouterr().out)
    assert stats["shots"] == 16 and stats["failures"] == 0
    assert saved.read_bytes() == before
    assert describe()["methods"]["stim/v1"]["cost_model"] == "noise/v1"
    assert main(["method", "stim/v1", str(saved), "-o", str(saved)]) == 1
    assert saved.read_bytes() == before


def test_memory_prepare_cli_has_no_compilation(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        main(
            [
                "memory",
                "prepare",
                "--distance",
                "5",
                "--basis",
                "x",
                "-o",
                str(tmp_path),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert set(result["jobs"]) == {"qec", "nonzoned"}
    annotations = json.loads(Path(result["annotations"]).read_text())
    assert annotations["workload"]["rounds"] == 5
