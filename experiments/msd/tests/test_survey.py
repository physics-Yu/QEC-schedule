"""Reject ambiguous campaign inputs and source changes after the final child."""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd import survey


@pytest.mark.parametrize(
    "options",
    (
        ["--cell-timeout", "nan"],
        ["--campaign-timeout", "inf"],
        ["--distances", "3", "3"],
        ["--pipelines", "1", "1"],
        ["--operations", "se_round", "se_round"],
        ["--operations", "logical_h"],
    ),
)
def test_invalid_campaign_rejected_before_output_creation(
    monkeypatch, tmp_path, options
):
    output = tmp_path / "campaign"
    monkeypatch.setattr(sys, "argv", ["survey", "--output", str(output), *options])
    with pytest.raises(SystemExit) as error:
        survey.main()
    assert error.value.code == 2
    assert not output.exists()


def test_last_child_source_change_prevents_complete_summary(monkeypatch, tmp_path):
    snapshot = {"module.py": "a" * 64}
    changed = {"module.py": "b" * 64}
    calls = iter((snapshot, snapshot, changed))
    monkeypatch.setattr(survey, "source_snapshot", lambda: next(calls))
    monkeypatch.setattr(
        survey.subprocess, "check_output", lambda *args, **kwargs: "head\n"
    )

    def child(command, **kwargs):
        path = Path(command[command.index("--output") + 1])
        path.write_text(
            json.dumps({"source_tree_sha256": canonical_hash(snapshot)}),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(survey.subprocess, "run", child)
    output = tmp_path / "campaign"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "survey",
            "--output",
            str(output),
            "--distances",
            "3",
            "--pipelines",
            "1",
            "--operations",
            "logical_x",
        ],
    )
    with pytest.raises(RuntimeError, match="Source files changed during campaign"):
        survey.main()
    assert not (output / "summary.json").exists()
    assert not (output / "journal.jsonl").exists()
