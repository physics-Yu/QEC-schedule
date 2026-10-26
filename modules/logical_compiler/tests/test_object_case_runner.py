"""Reproducibility, fail-closed atom guards and the real worker wall deadline."""

import json
import sys

import pytest

from modules.logical_compiler.examples.object_cases import (
    ROOT,
    execute_worker,
    forbid_atom_work,
    run_cases,
)


def test_three_cases_and_scaling_are_reproducible_without_atom_work(tmp_path):
    config = json.loads((ROOT / "experiments/msd/object-cases.json").read_text())
    result = run_cases(config, tmp_path)
    assert result["status"] == "complete"
    assert result["reuse"]["surface_templates_built"] == 3
    assert result["reuse"]["fixture_templates_built"] == 3
    assert result["reuse"]["same_objects_preserved"]
    assert all(
        result["reuse"][k] == 0
        for k in (
            "physical_compile_attempts",
            "atom_expansion_attempts",
            "atom_construction_attempts",
        )
    )
    assert len(result["readout_scaling"]) == 12
    assert not result["full_factory_scaling_run"]
    assert result["steady_state_throughput"] is None
    assert (tmp_path / "schedule.html").is_file()
    retry = json.loads((tmp_path / "postselection_retry_offset.json").read_text())
    assert retry["status"] == "complete"
    second = tmp_path / "repeat"
    second.mkdir()
    repeated = run_cases(config, second)
    assert repeated["reuse"] == result["reuse"]
    assert json.loads((second / "postselection_retry_offset.json").read_text()) == retry


def test_wall_timeout_records_the_last_stage_and_does_not_run_next_command(tmp_path):
    (tmp_path / "progress.json").write_text(
        json.dumps({"stage": "deliberate_timeout_probe"})
    )
    marker = tmp_path / "must_not_exist"
    command = [
        sys.executable,
        "-c",
        "import sys,time,pathlib; time.sleep(10); pathlib.Path(sys.argv[1]).touch()",
        str(marker),
    ]
    assert execute_worker(command, tmp_path, 0.1) == 124
    error = json.loads((tmp_path / "error.json").read_text())
    assert error["code"] == "LOCAL_CASE_TIMEOUT"
    assert error["last_progress"]["stage"] == "deliberate_timeout_probe"
    assert not error["partial_output_is_success"]
    assert not marker.exists()
    assert not (tmp_path / "summary.json").exists()


def test_compiler_and_atom_construction_guards_are_real():
    from nadit_physical_compiler.atom_ir import AtomProgram

    import modules.codes._support.atom_template as templates

    with forbid_atom_work() as counters:
        with pytest.raises(RuntimeError, match="FORBIDDEN_SCAN_WORK"):
            templates.compile_template()
        with pytest.raises(RuntimeError, match="FORBIDDEN_SCAN_WORK"):
            AtomProgram()
    assert counters["physical_compile_attempts"] == 1
    assert counters["atom_construction_attempts"] == 1


def test_late_timeout_invalidates_an_already_written_summary(tmp_path):
    (tmp_path / "summary.json").write_text(json.dumps({"status": "complete"}))
    assert (
        execute_worker(
            [sys.executable, "-c", "import time; time.sleep(10)"], tmp_path, 0.1
        )
        == 124
    )
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["status"] == "error"
    assert summary["invalidated_by"] == "LOCAL_CASE_TIMEOUT"


@pytest.mark.parametrize("budget", (None, 0, -1, float("inf"), float("nan")))
def test_invalid_wall_budget_never_launches_the_worker(tmp_path, budget):
    marker = tmp_path / "must_not_exist"
    code = execute_worker(
        [sys.executable, "-c", "raise AssertionError('launched')"], tmp_path, budget
    )
    assert code == 2
    assert (
        json.loads((tmp_path / "error.json").read_text())["code"]
        == "INVALID_WALL_TIMEOUT"
    )
    assert not marker.exists()


def test_server_matrix_merges_only_identical_layout_aliases():
    from experiments.msd.scan_objects import make_cells

    cells = make_cells(
        {"distances": [3, 5, 7, 9, 11], "factory_counts": [1, 2, 4, 6, 8, 10]}
    )
    assert len(cells) == 180
    subset = [c for c in cells if c["distance"] == 3 and c["strategy"] == "synchronous"]
    assert {c["columns"] for c in subset if c["factories"] == 2} == {1, 2}
    assert {c["columns"] for c in subset if c["factories"] == 6} == {1, 2, 3, 6}
    assert len({c["id"] for c in cells}) == 180


def test_server_cpu_limit_counts_physical_cores_and_balances_sockets(monkeypatch):
    import experiments.msd.scan_objects as scan

    monkeypatch.setattr(
        scan.os, "sched_getaffinity", lambda pid: set(range(8)), raising=False
    )
    monkeypatch.setattr(
        scan.subprocess,
        "check_output",
        lambda *a, **k: "0,0,0\n1,1,0\n2,2,1\n3,3,1\n4,0,0\n5,1,0\n6,2,1\n7,3,1\n",
    )
    assert scan.select_cpus({"cpu_fraction": 0.8, "worker_cap": 89}) == [0, 2, 1]


def test_report_ratio_uncertainty_and_incomplete_scan_rejection(tmp_path):
    from experiments.msd.report_object_scan import _ratio_variance, audit_data

    assert _ratio_variance([100, 200], [0, 2]) == 10000
    assert _ratio_variance([10, 5], [0, 1]) == 400
    assert _ratio_variance([10, 10], [0, 0]) is None
    (tmp_path / "summary.json").write_text(json.dumps({"status": "running"}))
    with pytest.raises(ValueError, match="COMPLETE_SCAN_REQUIRED"):
        audit_data(tmp_path)


def test_report_projections_preserve_uncertainty_and_fit_panel_limits():
    from experiments.msd.report_object_scan import _plot_limits, _plot_points

    cells = [
        {
            "cell": {
                "distance": d,
                "factories": n,
                "columns": n,
                "rows": 1,
                "strategy": "synchronous",
            },
            "statistics": {
                "metrics": {"atoms": {"mean": value, "variance": variance, "n": 100}}
            },
        }
        for d, n, value, variance in (
            (3, 1, 100, 0),
            (3, 2, 200, 100),
            (5, 1, 300, None),
            (5, 2, 600, 400),
        )
    ]
    by_n = _plot_points(cells, "atoms", "horizontal", "synchronous", "N", 3)
    by_d = _plot_points(cells, "atoms", "horizontal", "synchronous", "d", 1)
    assert by_n == [(1, 100, 0), (2, 200, 1.96)]
    assert by_d == [(3, 100, 0), (5, 300, None)]
    assert _plot_points(cells, "atoms", "two_rows", "synchronous", "N", 3) == []
    assert _plot_limits(by_n, 1) == pytest.approx((0, 1.08 * 201.96))
    assert _plot_limits(by_d, 1) == pytest.approx((0, 1.08 * 300))
    assert _plot_limits(by_n, 1000)[1] == pytest.approx(_plot_limits(by_n, 1)[1] / 1000)
    assert _plot_limits([], 1) == (0, 1)


def test_shot_statistics_include_failed_shots_in_resource_denominators():
    from experiments.msd.scan_metrics import aggregate

    rows = [
        {
            "outputs": 0,
            "duration_us": 10,
            "startup_us": None,
            "atom_time_us": 100,
            "storage_area_time_um2_us": 1000,
        },
        {
            "outputs": 2,
            "duration_us": 20,
            "startup_us": 5,
            "atom_time_us": 200,
            "storage_area_time_um2_us": 2000,
        },
    ]
    result = aggregate(rows)
    assert result["metrics"]["duration_us"]["mean"] == 15
    assert result["metrics"]["duration_us"]["variance"] == 50
    assert result["pooled_rate_per_second"] == pytest.approx(2e6 / 30)
    assert result["atom_us_per_output"] == 150
    assert result["no_output_fraction"] == 0.5
    assert result["renewal_startup_mean_us"] == 15
    assert result["renewal_startup_variance_us2"] == 200
    empty = aggregate(rows[:1])
    assert empty["pooled_rate_per_second"] == 0
    assert empty["atom_us_per_output"] is None
    assert empty["renewal_startup_mean_us"] is None


def test_motion_reference_counts_all_atoms_and_shared_commands_separately():
    from experiments.msd.scan_metrics import MotionAccounting
    from modules.codes.rotated_surface.object_factory import FactoryObjectCatalog
    from modules.codes.rotated_surface.tests.test_factory_objects import (
        _run_declared_wave,
    )

    catalog = FactoryObjectCatalog.load()
    wave = _run_declared_wave(
        catalog, catalog.layout(2), "logical_mz", [(0, ("R",)), (1, ("R",))]
    )
    case = {
        "calls": [
            {"invocation_id": key, "component_id": "logical_mz"}
            for key in wave["invocations"]
        ],
        "execution": {"waves": [wave]},
    }
    metrics = MotionAccounting(catalog).motion(case)
    assert metrics["aod_move_command_distance_um"] == 400
    assert metrics["atom_distance_estimate_um"] == 6660
    assert metrics["load_command_us"] == metrics["store_command_us"] == 10


def test_scan_worker_stops_on_first_failed_shot(monkeypatch, tmp_path):
    import modules.logical_compiler.examples.factory_objects as factory
    from experiments.msd.scan_objects import make_cells, run_worker

    original = factory.run_factory_objects
    observed = []

    def run(*args, **kwargs):
        observed.append(kwargs["seed"])
        if kwargs["seed"] == 1:
            raise TimeoutError("intentional worker stop test")
        return original(*args, **kwargs)

    monkeypatch.setattr(factory, "run_factory_objects", run)
    config = {
        "distances": [3],
        "factory_counts": [1],
        "seed_start": 0,
        "seed_count": 3,
        "raw_attempt_limit": 32,
        "input_z_error": 0.01,
        "case_timeout_seconds": 20,
    }
    with pytest.raises(TimeoutError, match="intentional"):
        run_worker(config, make_cells(config)[0], tmp_path)
    assert observed == [0, 1]
    assert json.loads((tmp_path / "error.json").read_text())["seed"] == 1
    assert not (tmp_path / "summary.json").exists()


def test_scan_coordinator_terminates_only_its_children_after_failure(
    monkeypatch, tmp_path
):
    import experiments.msd.scan_objects as scan

    processes = []

    class Process:
        def __init__(self, *args, **kwargs):
            self.pid = 9000 + len(processes)
            self.returncode = 1 if not processes else None
            self.terminated = False
            processes.append(self)

        def poll(self):
            return self.returncode

        def terminate(self):
            self.terminated = True
            self.returncode = -15

        def wait(self, timeout):
            return self.returncode

    def kill_group(pid, signal):
        next(p for p in processes if p.pid == pid).terminate()

    monkeypatch.setattr(scan, "select_cpus", lambda config: [0, 1])
    monkeypatch.setattr(scan.subprocess, "Popen", Process)
    monkeypatch.setattr(scan.os, "killpg", kill_group, raising=False)
    config = {
        "distances": [3],
        "factory_counts": [1, 2],
        "seed_count": 100,
        "scan_wall_seconds": 3600,
        "cell_wall_seconds": 2060,
    }
    output = tmp_path / "scan"
    with pytest.raises(RuntimeError, match="CELL_FAILED"):
        scan.coordinate(config, tmp_path / "config.json", output)
    assert len(processes) == 2
    assert processes[1].terminated
    assert not (output / "summary.json").exists()
    assert (
        json.loads((output / "error.json").read_text())["partial_output_is_success"]
        is False
    )
