"""Statistical/reporting boundaries for saved native scaling experiments."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "enola_scaling_report", Path(__file__).resolve().parents[1] / "tools/render_enola_scaling.py"
)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


def saved(root, n, graph, method, *, status="completed", loss=3., valid=True):
    path = root / f"n{n}_g{graph}" / method / "result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = dict(n=n, graph_id=graph, method=method, status=status, process_wall_seconds=8.)
    if status == "completed":
        raw.update(compile_seconds=2., score={
            "losses": {"two_qubit": loss / 3, "transfer": loss / 3, "decoherence": loss / 3},
            "fidelity": 0., "log_fidelity": -loss, "model_valid": valid,
            "pulses": 4, "transfers": n * 2, "execution_us": 1000.,
        })
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


def test_loss_statistics_require_both_matching_runs_and_do_not_fill_failures(tmp_path):
    saved(tmp_path, 30, 0, "enola", loss=2.)
    saved(tmp_path, 30, 0, "qmap", loss=6.)
    saved(tmp_path, 30, 1, "enola", loss=200.)
    saved(tmp_path, 30, 1, "qmap", status="timeout")
    saved(tmp_path, 100, 0, "enola", loss=2.)
    saved(tmp_path, 100, 0, "qmap", loss=6.)
    saved(tmp_path, 100, 1, "enola", loss=4.)
    saved(tmp_path, 100, 1, "qmap", loss=8.)
    result = REPORT.aggregate(REPORT.load_results(tmp_path))
    groups = {(g["n"], g["method"]): g for g in result["paired_loss_groups"]}
    assert groups[30, "enola"]["total_loss_mean"] == pytest.approx(2.)
    assert groups[30, "enola"]["count"] == 1
    assert groups[30, "enola"]["total_loss_std"] is None
    assert groups[100, "enola"]["total_loss_mean"] == pytest.approx(3.)
    assert groups[100, "enola"]["total_loss_std"] == pytest.approx(2 ** .5)
    assert groups[100, "enola"]["per_qubit_loss_mean"] == pytest.approx(.03)
    assert len(result["excluded_pairs"]) == 1


def test_fidelity_underflow_is_valid_but_inconsistent_log_loss_is_excluded(tmp_path):
    enola = saved(tmp_path, 5000, 0, "enola", loss=2000.)
    qmap = saved(tmp_path, 5000, 0, "qmap", loss=2000.)
    rows = REPORT.load_results(tmp_path)
    assert all(row["loss_eligible"] for row in rows)
    assert all(row["fidelity"] == 0 for row in rows)
    raw = json.loads(qmap.read_text(encoding="utf-8"))
    raw["score"]["log_fidelity"] = -1.
    qmap.write_text(json.dumps(raw), encoding="utf-8")
    rows = REPORT.load_results(tmp_path)
    assert REPORT.aggregate(rows)["paired_loss_groups"] == []
    assert next(row for row in rows if row["method"] == "qmap")["warnings"]


def test_report_exports_missing_native_time_without_zero_and_embeds_figures(tmp_path):
    saved(tmp_path, 30, 0, "enola")
    saved(tmp_path, 30, 0, "qmap")
    saved(tmp_path, 100, 0, "enola", valid=False)
    saved(tmp_path, 100, 0, "qmap", status="memory_limit")
    summary = REPORT.render(tmp_path)
    assert summary["paired_instances"] == 1
    data = json.loads((tmp_path / "report-data.json").read_text(encoding="utf-8"))
    failed = next(row for row in data["rows"] if row["status"] == "memory_limit")
    assert failed["native_compile_seconds"] is None
    assert failed["total_loss"] is None
    page = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert page.count("data:image/svg+xml;base64,") == 3
    assert "没有连续路径碰撞" in page
    assert "memory_limit" in page
    for stem in ("loss-scaling", "runtime-scaling", "operation-scaling"):
        for ext in ("png", "svg", "pdf"):
            assert (tmp_path / f"{stem}.{ext}").stat().st_size > 1000
