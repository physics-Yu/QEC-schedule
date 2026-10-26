"""Small local Git fixtures verify packaging, never server or physics execution."""

import json
import subprocess
from pathlib import Path

import pytest
from nadit_physical_compiler.provenance import canonical_hash

from experiments.msd import server_package


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(root), *args], stderr=subprocess.PIPE
    )


@pytest.fixture
def bundle_input(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q", "-b", "fixture")
    git(root, "config", "core.autocrlf", "true")
    files = {
        ".gitattributes": b"/vendor/* -text\r\n",
        "vendor/pinned.txt": b"preserve\r\nthis\nexactly\r\n",
        "modules/physical_compiler/src/runtime.py": b"physical = 1\r\n",
        "modules/physical_compiler/pyproject.toml": b"[project]\r\n",
        "modules/physical_compiler/uv.lock": b"version = 1\r\n",
        "modules/codes/component.py": b"component = 1\r\n",
        "modules/logical_compiler/src/runtime.py": b"logical = 1\r\n",
        "experiments/msd/campaign.py": b"# Fixture only, never executed.\r\n",
        "experiments/msd/server_package.py": b"# Fixture only, never executed.\r\n",
    }
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.invalid",
        "commit",
        "-qm",
        "Fixture source",
    )
    assert git(root, "status", "--porcelain") == b""
    config = {
        "schema": "nadit.msd.campaign/1",
        "standard": "nadit.msd.standard/2",
        "aod_count": 1,
        "sink": {"kind": "fixture_only"},
        "budget": {
            "workers": 1,
            "max_atoms": 100,
            "memory_bytes": 100_000_000,
            "calibration_timeout_s": 10,
            "production_timeout_s": 10,
            "pilot_timeout_s": 10,
            "export_timeout_s": 10,
            "export_reserve_s": 10,
            "export_reserve_bytes": 1000000,
            "campaign_timeout_s": 100,
            "max_storage_bytes": 1_000_000_000,
            "software_max_attempts": 1,
            "max_artifact_refreshes": 1,
        },
    }
    identity = server_package._source_identity(
        root, server_package._tracked_files(root), ()
    )
    task = {
        "kind": "msd.witness",
        "payload": {},
        "dependencies": [],
        "timeout_s": 1,
        "max_attempts": 1,
        "memory_bytes": 10_000_000,
    }
    task_id = canonical_hash(task)
    summary = {
        **task,
        "kind": "msd.summarize",
        "dependencies": [task_id],
        "dependency_mode": "terminal",
    }
    summary_id = canonical_hash(summary)
    campaign = {
        "schema": "nadit.msd.campaign_context/1",
        "runnable": True,
        "acceptance_complete": True,
        "two_level_ready": True,
        "source_identity": identity,
        "configuration": config,
        "configuration_sha256": canonical_hash(config),
    }
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for name, kind in server_package._EVIDENCE.items():
        evidence = {
            "evidence_kind": kind,
            "passed": True,
            "source_identity": identity,
            "checks": ["fixture-only format control; no physical acceptance claim"],
        }
        path = inputs / f"{name}.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        campaign[name] = {
            "path": str(path),
            "sha256": canonical_hash(evidence),
            "hash_kind": "canonical_json",
        }
    plan = {
        "schema": "nadit.task_plan/1",
        "tasks": [
            {"task_id": task_id, **task},
            {"task_id": summary_id, **summary},
        ],
        "finalization": {
            "task_ids": [summary_id],
            "reserve_seconds": 10,
            "reserve_bytes": 1000000,
        },
        "budget": {"campaign_timeout_s": 100, "max_storage_bytes": 1_000_000_000},
        "source_paths": [],
        "campaign": campaign,
    }
    configuration, resolved = inputs / "configuration.json", inputs / "plan.json"
    configuration.write_text(json.dumps(config), encoding="utf-8")
    resolved.write_text(json.dumps(plan), encoding="utf-8")
    return root, configuration, resolved


def test_package_preserves_working_bytes_and_restores_clean_git_without_checkout(
    bundle_input, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, configuration, resolved = bundle_input
    output = tmp_path / "package"
    manifest = server_package.build_package(
        root, output, configuration=configuration, resolved_plan=resolved
    )
    assert git(root, "show", "HEAD:modules/codes/component.py") == b"component = 1\n"
    assert (
        output / "source/modules/codes/component.py"
    ).read_bytes() == b"component = 1\r\n"
    assert (output / "source/vendor/pinned.txt").read_bytes() == (
        root / "vendor/pinned.txt"
    ).read_bytes()
    assert (output / "inputs/original-plan.json").read_bytes() == resolved.read_bytes()
    server_package.restore_git(output)
    assert git(output / "source", "status", "--porcelain") == b""
    assert (
        git(output / "source", "rev-parse", "HEAD").decode().strip()
        == manifest["source_identity"]["commit"]
    )
    assert (
        server_package._source_identity(output / "source", manifest["source_files"], ())
        == manifest["source_identity"]
    )
    from nadit_physical_compiler.experiments import version

    monkeypatch.setattr(version, "MODULE", output / "source/modules/physical_compiler")
    assert (
        version.code_version(allow_dirty=False, scope="msd")
        == manifest["source_identity"]
    )
    execution = json.loads((output / "inputs/execution-plan.json").read_text())
    original = json.loads(resolved.read_text())
    assert execution["tasks"] == original["tasks"]
    assert execution["finalization"] == original["finalization"]
    assert (
        execution["campaign"]["acceptance_evidence"]["path"]
        == "evidence/acceptance_evidence.json"
    )
    assert "nohup" in (output / "scripts/submit.sh").read_text()
    assert "git checkout" not in (output / "scripts/setup.sh").read_text()
    setup = (output / "scripts/setup.sh").read_text()
    assert "--extra simulation --no-dev" in setup and "--all-extras" not in setup


@pytest.mark.parametrize("field", ("export_reserve_s", "export_reserve_bytes"))
def test_package_requires_exact_frozen_export_reserves(bundle_input, field):
    _root, configuration, resolved = bundle_input
    config = json.loads(configuration.read_text())
    plan = json.loads(resolved.read_text())
    config["budget"][field] *= 2
    plan["campaign"]["configuration"] = config
    plan["campaign"]["configuration_sha256"] = canonical_hash(config)
    with pytest.raises(ValueError, match="PACKAGE_EXPORT_RESERVE_MISMATCH"):
        server_package._validate_inputs(config, plan)


@pytest.mark.parametrize(
    ("kind", "budget_field"),
    (
        ("msd.prepare_cache", "calibration_timeout_s"),
        ("msd.transport_witness", "production_timeout_s"),
        ("msd.two_level_witness", "production_timeout_s"),
        ("msd.two_level_pilot", "pilot_timeout_s"),
        ("msd.two_level_produce", "production_timeout_s"),
        ("msd.two_level_driver", "export_timeout_s"),
        ("msd.two_level_layout_driver", "export_timeout_s"),
    ),
)
def test_supply_tasks_use_their_frozen_timeout_budget(bundle_input, kind, budget_field):
    _root, configuration, resolved = bundle_input
    config = json.loads(configuration.read_text())
    config["budget"].update(
        calibration_timeout_s=3, production_timeout_s=5, pilot_timeout_s=7
    )

    def plan_with_timeout(timeout):
        plan = json.loads(resolved.read_text())
        first, summary = plan["tasks"]
        first.pop("task_id")
        first.update(kind=kind, timeout_s=timeout)
        first["task_id"] = canonical_hash(first)
        summary.pop("task_id")
        summary["dependencies"] = [first["task_id"]]
        summary["task_id"] = canonical_hash(summary)
        plan["finalization"]["task_ids"] = [summary["task_id"]]
        plan["campaign"]["configuration"] = config
        plan["campaign"]["configuration_sha256"] = canonical_hash(config)
        return plan

    limit = config["budget"][budget_field]
    server_package._validate_inputs(config, plan_with_timeout(limit))
    with pytest.raises(ValueError, match="frozen campaign timeout budget"):
        server_package._validate_inputs(config, plan_with_timeout(limit + 1))


def test_package_rejects_missing_export_reserve_inputs(bundle_input):
    _root, configuration, resolved = bundle_input
    config = json.loads(configuration.read_text())
    plan = json.loads(resolved.read_text())
    del plan["finalization"]
    with pytest.raises(ValueError, match="PACKAGE_EXPORT_RESERVE_MISMATCH"):
        server_package._validate_inputs(config, plan)
    plan["finalization"] = None
    with pytest.raises(ValueError, match="PACKAGE_EXPORT_RESERVE_MISMATCH"):
        server_package._validate_inputs(config, plan)
    del config["budget"]["export_reserve_s"]
    with pytest.raises(ValueError, match="UNRESOLVED_PACKAGE_BUDGET"):
        server_package._validate_inputs(config, plan)


@pytest.mark.parametrize("field", ("sink", "budget", "evidence"))
def test_unresolved_readiness_prevents_package_publication(
    bundle_input, tmp_path: Path, field: str
) -> None:
    root, configuration, resolved = bundle_input
    config, plan = (
        json.loads(configuration.read_text()),
        json.loads(resolved.read_text()),
    )
    if field == "sink":
        config["sink"]["kind"] = "pending"
    elif field == "budget":
        config["budget"]["workers"] = None
    else:
        plan["campaign"]["acceptance_evidence"]["path"] = "absent-evidence.json"
    configuration.write_text(json.dumps(config), encoding="utf-8")
    resolved.write_text(json.dumps(plan), encoding="utf-8")
    output = tmp_path / "package"
    with pytest.raises(ValueError):
        server_package.build_package(
            root, output, configuration=configuration, resolved_plan=resolved
        )
    assert not output.exists()


def test_dirty_source_is_rejected_before_copy(bundle_input, tmp_path: Path) -> None:
    root, configuration, resolved = bundle_input
    (root / "modules/codes/component.py").write_bytes(b"changed\r\n")
    with pytest.raises(ValueError, match="CLEAN_COMMITTED_SOURCE"):
        server_package.build_package(
            root,
            tmp_path / "package",
            configuration=configuration,
            resolved_plan=resolved,
        )


def test_configuration_drift_during_build_prevents_publication(
    bundle_input, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, configuration, resolved = bundle_input
    original = server_package._copy

    def change(source, target):
        original(source, target)
        if source == configuration:
            configuration.write_bytes(configuration.read_bytes() + b"\n")

    monkeypatch.setattr(server_package, "_copy", change)
    output = tmp_path / "package"
    with pytest.raises(ValueError, match="INPUT_CHANGED_DURING_PACKAGE"):
        server_package.build_package(
            root, output, configuration=configuration, resolved_plan=resolved
        )
    assert not output.exists()


def test_missing_and_dangling_cache_artifacts_fail_before_publication(
    bundle_input, tmp_path: Path
) -> None:
    root, configuration, resolved = bundle_input
    cache = tmp_path / "cache"
    cache.mkdir()
    descriptor = {
        "path": "actions/key/action.json",
        "sha256": "0" * 64,
        "hash_kind": "canonical_json",
    }
    with pytest.raises(ValueError, match="MISSING_PACKAGE_ARTIFACT"):
        server_package.build_package(
            root,
            tmp_path / "package",
            configuration=configuration,
            resolved_plan=resolved,
            cache_root=cache,
            cache_artifacts=[descriptor],
        )
    inputs, record = (
        {"fixture": True},
        {"trace_sha256": canonical_hash({"trace": "missing"})},
    )
    envelope = {
        "schema": "nadit.joint_action_cache/1",
        "key": canonical_hash(inputs),
        "inputs": inputs,
        "record": record,
        "record_sha256": canonical_hash(record),
        "complete": True,
    }
    path = cache / descriptor["path"]
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(envelope), encoding="utf-8")
    descriptor["sha256"] = canonical_hash(envelope)
    with pytest.raises(ValueError, match="MISSING_PACKAGED_CACHE_DEPENDENCY"):
        server_package.build_package(
            root,
            tmp_path / "package",
            configuration=configuration,
            resolved_plan=resolved,
            cache_root=cache,
            cache_artifacts=[descriptor],
        )


def test_corrupted_copy_cannot_replace_frozen_source_byte_identity(
    bundle_input,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, configuration, resolved = bundle_input
    original = server_package._copy

    def corrupt(source, target):
        original(source, target)
        if source == root / "modules/codes/component.py":
            target.write_bytes(b"corrupted copied source\n")

    monkeypatch.setattr(server_package, "_copy", corrupt)
    output = tmp_path / "package"
    with pytest.raises(ValueError, match="PACKAGED_BYTES_DIFFER_FROM_FROZEN_INPUTS"):
        server_package.build_package(
            root, output, configuration=configuration, resolved_plan=resolved
        )
    assert not output.exists()
