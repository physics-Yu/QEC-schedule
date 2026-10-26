"""Selection and collection guards must not silently omit affected tests."""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from tools.testing.policy import audit, load_policy, resolve_tier, select


@pytest.fixture
def policy_file(tmp_path: Path) -> Path:
    """Create a small dependency graph with real test files."""
    tests = tmp_path / "tests"
    tests.mkdir()
    for name in ("base", "consumer", "other"):
        (tests / f"test_{name}.py").write_text("def test_ok():\n    assert True\n")
    document = {
        "schema": 1,
        "repository": "..",
        "roots": ["tests"],
        "areas": {
            "base": {"sources": ["src/base/"], "consumers": ["consumer"]},
            "consumer": {"sources": ["src/consumer/"], "consumers": []},
            "other": {"sources": ["src/other/"], "consumers": []},
        },
        "tests": {
            "tests/test_base.py": {"areas": ["base"], "tier": "fast"},
            "tests/test_consumer.py": {"areas": ["consumer"], "tier": "slow"},
            "tests/test_other.py": {"areas": ["other"], "tier": "bench"},
        },
    }
    path = tests / "test-map.json"
    path.write_text(json.dumps(document))
    return path


def rewrite(path: Path, update: Callable[[dict[str, Any]], None]) -> None:
    """Apply a fixture-only policy edit."""
    document = json.loads(path.read_text())
    update(document)
    path.write_text(json.dumps(document))


def test_changed_source_includes_transitive_consumers(policy_file: Path) -> None:
    policy = load_policy(policy_file)
    selection = select(policy, changed=["src/base/rules.py"])
    assert selection.areas == ("base", "consumer")
    assert selection.files == ("tests/test_base.py", "tests/test_consumer.py")
    assert "base" in selection.reasons["consumer"]


def test_area_selection_is_deterministic_and_deduplicated(policy_file: Path) -> None:
    policy = load_policy(policy_file)
    first = select(policy, areas=["other", "base", "base"])
    second = select(policy, areas=["base", "other"])
    assert first.files == second.files
    assert len(first.files) == 3


def test_directory_selection_includes_its_descendant_areas(policy_file: Path) -> None:
    selection = select(load_policy(policy_file), changed=["src/"])
    assert selection.areas == ("base", "consumer", "other")


def test_windows_relative_paths_are_supported(policy_file: Path) -> None:
    selection = select(load_policy(policy_file), changed=[r"src\base\rules.py"])
    assert selection.areas == ("base", "consumer")


@pytest.mark.parametrize("path", ["src/unknown.py", "../outside.py", "C:/outside.py"])
def test_unknown_or_external_changes_fail_instead_of_selecting_nothing(
    policy_file: Path, path: str
) -> None:
    with pytest.raises(ValueError):
        select(load_policy(policy_file), changed=[path])


def test_documentation_change_needs_no_runtime_tests(policy_file: Path) -> None:
    selection = select(load_policy(policy_file), changed=["docs/decision.md"])
    assert selection.files == ()
    assert selection.documentation == ("docs/decision.md",)


def test_changed_shared_test_helper_includes_importers(policy_file: Path) -> None:
    root = policy_file.parent.parent
    (root / "tests/helper.py").write_text("VALUE = 1\n")
    (root / "tests/test_base.py").write_text(
        "from helper import VALUE\ndef test_ok():\n    assert VALUE == 1\n"
    )
    (root / "tests/test_consumer.py").write_text(
        "from test_base import VALUE\ndef test_ok():\n    assert VALUE == 1\n"
    )
    selection = select(load_policy(policy_file), changed=["tests/helper.py"])
    assert selection.files == ("tests/test_base.py", "tests/test_consumer.py")


def test_cycles_in_consumer_graph_terminate(policy_file: Path) -> None:
    rewrite(policy_file, lambda d: d["areas"]["consumer"].update(consumers=["base"]))
    assert select(load_policy(policy_file), areas=["base"]).areas == (
        "base",
        "consumer",
    )


@pytest.mark.parametrize("tier", ["fast", "slow", "bench"])
def test_file_tier_is_assigned_to_unmarked_existing_tests(
    policy_file: Path, tier: str
) -> None:
    rewrite(policy_file, lambda d: d["tests"]["tests/test_base.py"].update(tier=tier))
    policy = load_policy(policy_file)
    assert resolve_tier(policy, "tests/test_base.py", "test_ok", ()) == tier


def test_function_override_handles_parameterized_node_ids(policy_file: Path) -> None:
    rewrite(
        policy_file,
        lambda d: d["tests"]["tests/test_base.py"].update(
            overrides={"test_ok": "slow"}
        ),
    )
    assert (
        resolve_tier(load_policy(policy_file), "tests/test_base.py", "test_ok[2]", ())
        == "slow"
    )


def test_explicit_tier_can_override_file_default(policy_file: Path) -> None:
    assert (
        resolve_tier(
            load_policy(policy_file), "tests/test_base.py", "test_ok", ("slow",)
        )
        == "slow"
    )


def test_conflicting_markers_are_rejected(policy_file: Path) -> None:
    with pytest.raises(ValueError, match="conflicting"):
        resolve_tier(
            load_policy(policy_file), "tests/test_base.py", "test_ok", ("fast", "slow")
        )


def test_missing_test_classification_is_rejected(policy_file: Path) -> None:
    with pytest.raises(ValueError, match="Unclassified"):
        resolve_tier(load_policy(policy_file), "tests/test_new.py", "test_ok", ())


def test_audit_detects_unclassified_files_before_a_narrow_run(
    policy_file: Path,
) -> None:
    (policy_file.parent / "test_new.py").write_text("def test_new():\n    pass\n")
    with pytest.raises(ValueError, match="test_new.py"):
        audit(load_policy(policy_file))


def test_audit_detects_stale_overrides(policy_file: Path) -> None:
    rewrite(
        policy_file,
        lambda d: d["tests"]["tests/test_base.py"].update(
            overrides={"test_deleted": "bench"}
        ),
    )
    with pytest.raises(ValueError, match="test_deleted"):
        audit(load_policy(policy_file))


@pytest.mark.parametrize("kind", ["tier", "consumer", "area", "schema"])
def test_invalid_manifest_fails_with_context(policy_file: Path, kind: str) -> None:
    def update(document: dict[str, Any]) -> None:
        if kind == "tier":
            document["tests"]["tests/test_base.py"]["tier"] = "typo"
        elif kind == "consumer":
            document["areas"]["base"]["consumers"] = ["missing"]
        elif kind == "area":
            document["tests"]["tests/test_base.py"]["areas"] = ["missing"]
        else:
            document["schema"] = 99

    rewrite(policy_file, update)
    with pytest.raises(ValueError):
        load_policy(policy_file)


def run_pytest(policy_file: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Exercise real pytest collection without importing project fixtures."""
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root)}
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tools.testing.plugin",
            "-o",
            "addopts=",
            "--test-map",
            str(policy_file),
            *arguments,
        ],
        cwd=policy_file.parent.parent,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_default_pytest_excludes_bench_but_keeps_slow(policy_file: Path) -> None:
    result = run_pytest(policy_file, "-q")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 passed, 1 deselected" in result.stdout
    assert "bench" in result.stdout


def test_logical_module_local_collection_excludes_factory_bench(tmp_path: Path) -> None:
    """The module's own config must filter bench without root pytest options."""
    root = Path(__file__).resolve().parents[1]
    report = tmp_path / "logical-collection.json"
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--test-report",
            str(report),
            "tests/test_fast_metrics.py",
            "tests/test_factory_integration.py",
        ],
        cwd=root / "modules/logical_compiler",
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    tiers = json.loads(report.read_text())["tiers"]
    assert tiers["fast"]["selected"] > 0
    assert tiers["bench"]["collected"] > 0
    assert tiers["bench"]["selected"] == 0
    assert tiers["bench"]["not_run"] == tiers["bench"]["collected"]


def test_explicit_full_profile_runs_bench(policy_file: Path) -> None:
    result = run_pytest(policy_file, "-q", "--test-tier", "full")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout


def test_unknown_test_marker_fails_with_strict_markers(policy_file: Path) -> None:
    (policy_file.parent / "test_base.py").write_text(
        "import pytest\n@pytest.mark.fats\ndef test_ok():\n    pass\n"
    )
    result = run_pytest(policy_file, "-q", "--strict-markers")
    assert result.returncode != 0
    assert "fats" in result.stdout + result.stderr


def test_conflicting_tiers_fail_even_when_mark_expression_would_hide_them(
    policy_file: Path,
) -> None:
    (policy_file.parent / "test_base.py").write_text(
        "import pytest\n@pytest.mark.fast\n@pytest.mark.slow\n"
        "def test_ok():\n    pass\n"
    )
    result = run_pytest(policy_file, "-q", "-m", "bench")
    assert result.returncode != 0
    assert "conflicting" in result.stdout + result.stderr


def test_report_distinguishes_selected_passed_and_not_run(
    policy_file: Path, tmp_path: Path
) -> None:
    report = tmp_path / "report.json"
    result = run_pytest(
        policy_file, "-q", "--test-tier", "fast", "--test-report", str(report)
    )
    assert result.returncode == 0, result.stdout + result.stderr
    document = json.loads(report.read_text())
    assert document["tiers"]["fast"]["passed"] == 1
    assert document["tiers"]["slow"]["not_run"] == 1
    assert document["tiers"]["bench"]["not_run"] == 1


def test_failed_test_is_not_reported_as_a_pass(
    policy_file: Path, tmp_path: Path
) -> None:
    (policy_file.parent / "test_base.py").write_text(
        "def test_ok():\n    assert False\n"
    )
    report = tmp_path / "failed.json"
    result = run_pytest(
        policy_file, "-q", "--test-tier", "fast", "--test-report", str(report)
    )
    assert result.returncode == 1
    assert json.loads(report.read_text())["tiers"]["fast"]["failed"] == 1


@pytest.mark.parametrize("phase", ["setup", "teardown"])
def test_fixture_failure_remains_a_failure_in_tier_report(
    policy_file: Path, tmp_path: Path, phase: str
) -> None:
    fixture = "    raise RuntimeError('broken fixture')\n"
    if phase == "teardown":
        fixture = "    yield\n" + fixture
    (policy_file.parent / "test_base.py").write_text(
        "import pytest\n@pytest.fixture\ndef broken():\n"
        + fixture
        + "def test_ok(broken):\n    assert True\n"
    )
    report = tmp_path / "fixture-report.json"
    result = run_pytest(policy_file, "-q", "--test-report", str(report))
    assert result.returncode == 1
    counts = json.loads(report.read_text())["tiers"]["fast"]
    assert counts["failed"] == 1
    assert counts["passed"] == 0


def test_cli_preserves_pytest_failure_and_passes_selected_files(
    policy_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.testing import run

    monkeypatch.setattr(run, "DEFAULT_MAP", policy_file)
    monkeypatch.setattr(sys, "argv", ["run", "fast", "--changed", "src/base/rules.py"])
    captured: list[str] = []

    def failing_pytest(arguments: list[str]) -> int:
        captured.extend(arguments)
        return 1

    monkeypatch.setattr(pytest, "main", failing_pytest)
    assert run.main() == 1
    assert str(policy_file.parent / "test_base.py") in captured
    assert str(policy_file.parent / "test_consumer.py") in captured
    assert str(policy_file.parent / "test_other.py") not in captured
    assert captured[captured.index("--test-tier") + 1] == "fast"


@pytest.mark.parametrize("arguments", [[], ["fast", "--changed", "src/unknown.py"]])
def test_cli_rejects_missing_or_unknown_scope(
    policy_file: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    from tools.testing import run

    monkeypatch.setattr(run, "DEFAULT_MAP", policy_file)
    monkeypatch.setattr(sys, "argv", ["run", *arguments])
    with pytest.raises(SystemExit) as error:
        run.main()
    assert error.value.code == 2


def test_cli_plan_does_not_execute_pytest(
    policy_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.testing import run

    monkeypatch.setattr(run, "DEFAULT_MAP", policy_file)
    monkeypatch.setattr(sys, "argv", ["run", "fast", "--area", "base", "--plan"])

    def unexpected_pytest(arguments: list[str]) -> int:
        raise AssertionError("plan must not execute tests")

    monkeypatch.setattr(pytest, "main", unexpected_pytest)
    assert run.main() == 0


def test_cli_empty_runtime_scope_is_not_successful_verification(
    policy_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tools.testing import run

    rewrite(
        policy_file,
        lambda d: d["areas"].update(empty={"sources": ["src/empty/"], "consumers": []}),
    )
    monkeypatch.setattr(run, "DEFAULT_MAP", policy_file)
    monkeypatch.setattr(sys, "argv", ["run", "fast", "--area", "empty"])
    with pytest.raises(SystemExit) as error:
        run.main()
    assert error.value.code == 2
