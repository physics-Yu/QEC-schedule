"""Reproduce input clobbering and unsupported schedules admitted by the old exporter."""

import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from nadit_physical_compiler.job import compile_job, loads_job
from nadit_physical_compiler.serialization import encode_result
from nadit_physical_compiler.validation import validate_result

from experiments.se_tradeoff import retiming


@pytest.fixture(scope="module")
def saved_result(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    from nadit_physical_compiler.methods.surface_memory import prepare_memory

    base = tmp_path_factory.mktemp("memory")
    qec_job = prepare_memory(base, distance=3, rounds=1)["jobs"]["qec"]
    job = json.loads(Path(qec_job).read_text("utf-8"))
    loaded = loads_job(json.dumps(job), base_dir=base)
    result = compile_job(loaded)
    report = validate_result(
        result, entry_state=loaded.entry_state, device=loaded.device, dag=loaded.dag
    )
    assert report["ok"], report
    return encode_result(
        result,
        entry_state=loaded.entry_state,
        job=loaded.document,
        device=loaded.device,
        dag=loaded.dag,
        inputs=loaded.inputs,
        validation=report,
    )


def test_legacy_cli_preserves_result_when_output_aliases_input(
    saved_result: dict[str, Any],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = tmp_path / "result.json"
    original = json.dumps(saved_result).encode()
    result.write_bytes(original)
    monkeypatch.setattr(sys, "argv", ["retiming", str(result), "-o", str(result)])
    with pytest.raises(SystemExit) as error:
        retiming.main()
    assert error.value.code == 2
    assert "Output must differ" in capsys.readouterr().err
    assert result.read_bytes() == original


@pytest.mark.parametrize(
    "unsupported", ["CPhasePulse", "feedback", "rotation duration"]
)
def test_retiming_rejects_out_of_model_inputs(
    saved_result: dict[str, Any], unsupported: str
) -> None:
    document = deepcopy(saved_result)
    actions = [a for s in document["program"]["steps"] for a in s["actions"]]
    if unsupported == "feedback":
        document["dag"]["nodes"][-1]["condition"] = {
            "result": {"measurement_id": 1},
            "value": 1,
        }
    elif unsupported == "CPhasePulse":
        action = next(a for a in actions if a["kind"] == "CZPulse")
        action.update(kind="CPhasePulse", angle=0.7)
    else:
        action = next(a for a in actions if a["kind"] in ("Rotation", "LocalU"))
        action["duration_us"] += 1
    with pytest.raises(retiming.UnsupportedSchedule, match=unsupported):
        retiming.export(document)
