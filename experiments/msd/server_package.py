"""Prepare a verified, byte-preserving server package without uploading or running it.

The Git bundle preserves commit identity; copied working files preserve actual
source bytes, including Windows line endings and vendor files marked -text.
Final packages require committed sources and audited interface/delivery evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

SCHEMA = "nadit.msd.server_package/1"
_BUDGET_FIELDS = (
    "workers",
    "max_atoms",
    "memory_bytes",
    "calibration_timeout_s",
    "production_timeout_s",
    "pilot_timeout_s",
    "export_timeout_s",
    "export_reserve_s",
    "export_reserve_bytes",
    "campaign_timeout_s",
    "max_storage_bytes",
    "software_max_attempts",
    "max_artifact_refreshes",
)
_EVIDENCE = {
    "acceptance_evidence": "physical_interface_acceptance",
    "two_level_evidence": "physical_two_level_delivery",
}


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _git(repository: Path, *arguments: str) -> bytes:
    return subprocess.check_output(
        ["git", "-C", str(repository), *arguments], stderr=subprocess.PIPE
    )


def _relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Package paths must be nonempty relative POSIX paths")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or ":" in value:
        raise ValueError("Package path escapes its root")
    return path


def _tracked_files(repository: Path) -> dict[str, dict[str, Any]]:
    result = {}
    for row in _git(repository, "ls-files", "--stage", "-z").split(b"\0"):
        if not row:
            continue
        prefix, filename = row.split(b"\t", 1)
        mode, _, stage = prefix.decode().split()
        name = filename.decode("utf-8")
        path = repository / _relative(name)
        if (
            stage != "0"
            or mode not in ("100644", "100755")
            or path.is_symlink()
            or not path.is_file()
        ):
            raise ValueError(f"Unsupported/missing committed source: {name}")
        if not path.resolve().is_relative_to(repository):
            raise ValueError(f"Committed source escapes repository: {name}")
        result[name] = {
            "sha256": _sha(path),
            "mode": mode,
            "bytes": path.stat().st_size,
        }
    return result


def _source_identity(
    repository: Path, tracked: Mapping[str, Any], source_paths: Sequence[str]
) -> dict[str, Any]:
    # Reuse the experiment freeze's exact scope/filter rules, rooted at this
    # supplied checkout rather than changing the imported module's global root.
    from nadit_physical_compiler.experiments.version import (
        _ENVIRONMENT_NAMES,
        _MSD_TREES,
        _normalize_paths,
        _source_files,
    )

    paths = _normalize_paths(source_paths)
    selected: set[Path] = set()
    for name in (*_MSD_TREES, *paths):
        selected.update(_source_files(repository / name, repository))
    for name in ("pyproject.toml", "uv.lock"):
        selected.update(
            _source_files(repository / "modules/physical_compiler" / name, repository)
        )
    for name in _ENVIRONMENT_NAMES:
        if (repository / name).exists():
            selected.update(_source_files(repository / name, repository))
    digest = hashlib.sha256()
    for path in sorted(
        selected, key=lambda file: file.relative_to(repository).as_posix()
    ):
        name = path.relative_to(repository).as_posix()
        if name not in tracked:
            raise ValueError(f"Final package runtime source must be committed: {name}")
        digest.update(name.encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    return {
        "commit": _git(repository, "rev-parse", "HEAD").decode().strip(),
        "dirty": False,
        "source_hash": digest.hexdigest(),
        "source_scope": "msd",
        "source_paths": list(paths),
    }


def _checked_artifact(descriptor: Mapping[str, Any], base: Path) -> tuple[Path, Any]:
    if set(descriptor) != {"path", "sha256", "hash_kind"}:
        raise ValueError("Artifact requires path, sha256 and hash_kind")
    path = (base / descriptor["path"]).resolve()
    if not path.is_file():
        raise ValueError(f"MISSING_PACKAGE_ARTIFACT: {path}")
    if descriptor["hash_kind"] == "canonical_json":
        value = json.loads(path.read_text(encoding="utf-8"))
        actual = _hash(value)
    elif descriptor["hash_kind"] == "bytes":
        value, actual = None, _sha(path)
    else:
        raise ValueError("Unsupported artifact hash_kind")
    if actual != descriptor["sha256"]:
        raise ValueError(f"PACKAGE_ARTIFACT_HASH_MISMATCH: {path}")
    return path, value


def _validate_inputs(
    configuration: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    from nadit_physical_compiler.experiments.task_plan import validate_plan

    validate_plan(plan)
    if (
        configuration.get("schema") != "nadit.msd.campaign/1"
        or configuration.get("standard") != "nadit.msd.standard/2"
        or configuration.get("aod_count") != 1
    ):
        raise ValueError(
            "Final package requires the current single-AOD campaign standard"
        )
    budget = configuration.get("budget", {})
    for name in _BUDGET_FIELDS:
        value = budget.get(name)
        if type(value) not in (int, float) or not 0 < value < float("inf"):
            raise ValueError(f"UNRESOLVED_PACKAGE_BUDGET: {name}")
        if not name.endswith("_s") and type(value) is not int:
            raise ValueError(f"Package budget requires integer {name}")
    finalization = plan.get("finalization") or {}
    if (
        finalization.get("reserve_seconds") != budget["export_reserve_s"]
        or finalization.get("reserve_bytes") != budget["export_reserve_bytes"]
        or not any(
            task["kind"] == "msd.summarize"
            and task["task_id"] in finalization.get("task_ids", ())
            for task in plan["tasks"]
        )
    ):
        raise ValueError("PACKAGE_EXPORT_RESERVE_MISMATCH")
    sink = configuration.get("sink", {}).get("kind")
    if (
        not isinstance(sink, str)
        or not sink.strip()
        or sink.strip().lower() in {"pending", "required", "unknown", "unresolved"}
    ):
        raise ValueError("UNRESOLVED_PACKAGE_SINK")
    campaign: dict[str, Any] = plan.get("campaign", {})
    if (
        campaign.get("schema") != "nadit.msd.campaign_context/1"
        or any(
            campaign.get(name) is not True
            for name in ("runnable", "acceptance_complete", "two_level_ready")
        )
        or campaign.get("configuration") != configuration
        or campaign.get("configuration_sha256") != _hash(configuration)
    ):
        raise ValueError("PACKAGE_CONFIGURATION_OR_READINESS_MISMATCH")
    if not isinstance(campaign.get("source_identity"), dict):
        raise TypeError("PACKAGE_SOURCE_IDENTITY_REQUIRED")
    for task in plan["tasks"]:
        if (
            task["memory_bytes"] > budget["memory_bytes"]
            or task["max_attempts"] > budget["software_max_attempts"]
        ):
            raise ValueError("Task exceeds frozen campaign worker budget")
        timeout_field = {
            "msd.calibrate": "calibration_timeout_s",
            "msd.prepare_cache": "calibration_timeout_s",
            "msd.witness": "production_timeout_s",
            "msd.transport_witness": "production_timeout_s",
            "msd.two_level_witness": "production_timeout_s",
            "msd.two_level_pilot": "pilot_timeout_s",
            "msd.two_level_produce": "production_timeout_s",
            "msd.produce": "production_timeout_s",
            "msd.pilot": "pilot_timeout_s",
            "msd.layout_driver": "export_timeout_s",
            "msd.two_level_driver": "export_timeout_s",
            "msd.two_level_layout_driver": "export_timeout_s",
            "msd.audit": "export_timeout_s",
            "msd.summarize": "export_timeout_s",
            "msd.export": "export_timeout_s",
            "msd.finalize": "export_timeout_s",
        }.get(task["kind"])
        if timeout_field is None:
            raise ValueError("PACKAGE_TASK_KIND_NOT_BUDGETED")
        if task["timeout_s"] > budget[timeout_field]:
            raise ValueError("Task exceeds frozen campaign timeout budget")
    for name in ("campaign_timeout_s", "max_storage_bytes"):
        if plan["budget"][name] > budget[name]:
            raise ValueError(f"Resolved plan exceeds campaign budget: {name}")
    if (
        plan["budget"].get("max_artifact_refreshes", 1)
        > budget["max_artifact_refreshes"]
    ):
        raise ValueError("Resolved plan exceeds artifact refresh budget")
    return campaign


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _cache_files(
    root: Path | None, descriptors: Sequence[Mapping[str, Any]]
) -> dict[str, Path]:
    if descriptors and root is None:
        raise ValueError("cache_root is required with cache_artifacts")
    if root is None:
        return {}
    root = root.resolve()
    files, documents = {}, {}
    for descriptor in descriptors:
        path, value = _checked_artifact(descriptor, root)
        if not path.is_relative_to(root):
            raise ValueError("Packaged cache artifact escapes cache_root")
        name = path.relative_to(root).as_posix()
        files[name] = path
        documents[name] = (
            value if value is not None else json.loads(path.read_text(encoding="utf-8"))
        )
    traces = set()
    for name, value in documents.items():
        if Path(name).name not in {"action.json", "probability.json"}:
            continue
        if (
            not isinstance(value, dict)
            or not {"inputs", "record", "record_sha256", "key", "complete", "schema"}
            <= value.keys()
        ):
            raise ValueError("INVALID_PACKAGED_CACHE_ENVELOPE")
        if (
            value.get("schema")
            != (
                "nadit.joint_action_cache/1"
                if Path(name).name == "action.json"
                else "nadit.joint_probability_cache/1"
            )
            or value.get("complete") is not True
            or value.get("key") != _hash(value["inputs"])
            or value.get("record_sha256") != _hash(value["record"])
        ):
            raise ValueError("INVALID_PACKAGED_CACHE_ENVELOPE")
        if Path(name).name == "action.json":
            trace_name = (Path(name).parent / "trace.json").as_posix()
            if trace_name not in documents or value["record"]["trace_sha256"] != _hash(
                documents[trace_name]
            ):
                raise ValueError("MISSING_PACKAGED_CACHE_DEPENDENCY: action trace")
            traces.add(value["record"]["trace_sha256"])
    for name, value in documents.items():
        if (
            Path(name).name == "probability.json"
            and value["record"].get("trace_sha256") not in traces
        ):
            raise ValueError(
                "MISSING_PACKAGED_CACHE_DEPENDENCY: probability action/trace"
            )
    return files


def _scripts(entry: str, workers: int) -> dict[str, str]:
    header = """#!/usr/bin/env bash
set -euo pipefail
PACKAGE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
SOURCE="$PACKAGE/source"
"""
    runtime = """PYTHON=${PYTHON:-"$SOURCE/modules/physical_compiler/.venv/bin/python"}
export PYTHONPATH="$SOURCE/modules/physical_compiler/src:$SOURCE${PYTHONPATH:+:$PYTHONPATH}"
OUTPUT=${1:?Usage: script.sh /absolute/campaign/output}
cd "$SOURCE"
"""
    verify = '"$PYTHON" "$SOURCE/experiments/msd/server_package.py" verify --package "$PACKAGE"\n'
    scripts = {
        "setup.sh": header
        + """PYTHON=${PYTHON:-python3}
"$PYTHON" "$SOURCE/experiments/msd/server_package.py" restore --package "$PACKAGE"
uv sync --frozen --project "$SOURCE/modules/physical_compiler" --extra simulation --no-dev
""",
        "run.sh": header
        + runtime
        + verify
        + f'exec "$PYTHON" -m {entry} run --plan "$PACKAGE/inputs/execution-plan.json" --output "$OUTPUT" --workers {workers}\n',
        "resume.sh": header + 'exec "$PACKAGE/scripts/run.sh" "$@"\n',
        "status.sh": header
        + runtime
        + f'exec "$PYTHON" -m {entry} status --output "$OUTPUT"\n',
        "summarize.sh": header
        + runtime
        + verify
        + f'exec "$PYTHON" -m {entry} summarize --plan "$PACKAGE/inputs/execution-plan.json" --output "$OUTPUT"\n',
        "submit.sh": header
        + """OUTPUT=${1:?Usage: submit.sh /absolute/campaign/output}
mkdir -p -- "$OUTPUT"
if [ -f "$OUTPUT/launcher.pid" ] && kill -0 "$(cat "$OUTPUT/launcher.pid")" 2>/dev/null; then
  echo "Recorded launcher is still running" >&2
  exit 1
fi
nohup "$PACKAGE/scripts/run.sh" "$OUTPUT" >"$OUTPUT/launcher.log" 2>&1 </dev/null &
printf '%s\\n' "$!" >"$OUTPUT/launcher.pid"
""",
    }
    return scripts


def build_package(
    repository: Path,
    destination: Path,
    *,
    configuration: Path,
    resolved_plan: Path,
    cache_root: Path | None = None,
    cache_artifacts: Sequence[Mapping[str, Any]] = (),
    campaign_entry: str = "experiments.msd.campaign",
) -> dict[str, Any]:
    """Publish a final local submission directory from clean, approved evidence.

    No SSH, install, upload, or campaign launch occurs. Exact tracked working
    bytes and a Git bundle are retained. Only evidence paths in the execution-plan
    copy become package-relative; immutable task definitions are never rewritten.
    Raises ValueError for unresolved budgets/sink/readiness, dirty or changing
    inputs, missing/mismatched artifacts, or an existing output directory.
    """
    repository, destination = repository.resolve(), destination.resolve()
    configuration, resolved_plan = configuration.resolve(), resolved_plan.resolve()
    if destination.exists():
        raise ValueError("Package destination already exists")
    if _git(repository, "status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("FINAL_PACKAGE_REQUIRES_CLEAN_COMMITTED_SOURCE")
    if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", campaign_entry):
        raise ValueError("Invalid campaign module entry")
    if destination.is_relative_to(repository):
        ignored = subprocess.run(
            ["git", "-C", str(repository), "check-ignore", "-q", str(destination)],
            capture_output=True,
            check=False,
        )
        if ignored.returncode:
            raise ValueError("Package output inside repository must be Git-ignored")
    config = json.loads(configuration.read_text(encoding="utf-8"))
    plan = json.loads(resolved_plan.read_text(encoding="utf-8"))
    campaign = _validate_inputs(config, plan)
    tracked = _tracked_files(repository)
    entry_path = campaign_entry.replace(".", "/") + ".py"
    if entry_path not in tracked:
        raise ValueError("Campaign entry must be part of the committed source")
    identity = _source_identity(repository, tracked, plan.get("source_paths", ()))
    if campaign["source_identity"] != identity:
        raise ValueError("PACKAGE_SOURCE_IDENTITY_MISMATCH")
    evidence = {}
    inputs = {configuration: _sha(configuration), resolved_plan: _sha(resolved_plan)}
    for name, kind in _EVIDENCE.items():
        descriptor = campaign.get(name)
        if (
            not isinstance(descriptor, dict)
            or descriptor.get("hash_kind") != "canonical_json"
        ):
            raise ValueError(f"PACKAGE_AUDIT_EVIDENCE_REQUIRED: {name}")
        path, document = _checked_artifact(descriptor, resolved_plan.parent)
        if (
            document.get("passed") is not True
            or document.get("evidence_kind") != kind
            or not isinstance(document.get("checks"), list)
            or not document["checks"]
            or not (
                document.get("source_identity") == identity
                or document.get("source_hash") == identity["source_hash"]
            )
        ):
            raise ValueError(f"PACKAGE_AUDIT_EVIDENCE_MISMATCH: {name}")
        evidence[name] = path
        inputs[path] = _sha(path)
    cache = _cache_files(cache_root, cache_artifacts)
    inputs.update({path: _sha(path) for path in cache.values()})
    settings = {}
    for name, default in (
        ("core.autocrlf", "false"),
        ("core.eol", "native"),
        ("core.filemode", "false"),
    ):
        command = subprocess.run(
            ["git", "-C", str(repository), "config", "--get", name],
            capture_output=True,
            text=True,
            check=False,
        )
        settings[name] = command.stdout.strip() if command.returncode == 0 else default
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(
        prefix=f".{destination.name}-stage-", dir=destination.parent
    ) as temporary:
        stage = Path(temporary).resolve() / "package"
        stage.mkdir()
        for name, row in tracked.items():
            target = stage / "source" / _relative(name)
            _copy(repository / name, target)
            target.chmod(0o755 if row["mode"] == "100755" else 0o644)
        _git(repository, "bundle", "create", str(stage / "source.bundle"), "HEAD")
        _copy(configuration, stage / "inputs/original-configuration.json")
        _copy(resolved_plan, stage / "inputs/original-plan.json")
        execution = json.loads(json.dumps(plan))
        for name, path in evidence.items():
            relative = f"evidence/{name}.json"
            _copy(path, stage / "inputs" / relative)
            execution["campaign"][name]["path"] = relative
        (stage / "inputs/execution-plan.json").write_text(
            json.dumps(execution, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        for name, path in cache.items():
            _copy(path, stage / "cache" / _relative(name))
        for name, content in _scripts(
            campaign_entry, config["budget"]["workers"]
        ).items():
            path = stage / "scripts" / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            path.chmod(0o755)
        (stage / "README.txt").write_text(
            "NADiT frozen MSD server package\n\n"
            "Requires Git, Python 3.12 and uv. No script is executed by packaging.\n"
            "1. Run: bash scripts/setup.sh\n"
            "2. Start: bash scripts/submit.sh /configured/campaign/output\n"
            "3. Resume: bash scripts/resume.sh /configured/campaign/output\n"
            "4. Inspect: bash scripts/status.sh /configured/campaign/output\n"
            "5. Export: bash scripts/summarize.sh /configured/campaign/output\n\n"
            "The output and cache locations must match the frozen server plan.\n"
            "Git metadata is rebuilt from the local bundle without checking out\n"
            "or normalizing working files. Original config/plan bytes are retained;\n"
            "only evidence paths change in inputs/execution-plan.json.\n"
            "Manifest checks cover file integrity and cache reference closure;\n"
            "scientific acceptance belongs to the packaged independent audits.\n",
            encoding="utf-8",
            newline="\n",
        )
        files = {
            path.relative_to(stage).as_posix(): {
                "sha256": _sha(path),
                "bytes": path.stat().st_size,
            }
            for path in sorted(stage.rglob("*"))
            if path.is_file()
        }
        manifest = {
            "schema": SCHEMA,
            "source_identity": identity,
            "source_tree": _git(repository, "rev-parse", "HEAD^{tree}")
            .decode()
            .strip(),
            "git_config": settings,
            "source_files": tracked,
            "input_files": {
                "inputs/original-configuration.json": inputs[configuration],
                "inputs/original-plan.json": inputs[resolved_plan],
                **{
                    f"inputs/evidence/{name}.json": inputs[path]
                    for name, path in evidence.items()
                },
                **{f"cache/{name}": inputs[path] for name, path in cache.items()},
            },
            "files": files,
            "campaign_entry": campaign_entry,
            "configuration_sha256": _hash(config),
            "resolved_plan_sha256": _hash(plan),
            "execution_plan_transform": "only audited evidence paths become package-relative",
            "cache_validation": "file hashes and reference closure; runtime rechecks applicability",
            "environment": {
                "python": "3.12",
                "lock": "source/modules/physical_compiler/uv.lock",
                "setup_script": "scripts/setup.sh",
                "extras": ["simulation"],
                "development_dependencies": False,
            },
        }
        (stage / "manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if (
            any(_sha(path) != expected for path, expected in inputs.items())
            or _tracked_files(repository) != tracked
            or _git(repository, "rev-parse", "HEAD").decode().strip()
            != identity["commit"]
            or _git(
                repository, "status", "--porcelain", "--untracked-files=all"
            ).strip()
        ):
            raise ValueError("INPUT_CHANGED_DURING_PACKAGE")
        verify_package(stage)
        if (
            stage.parent != Path(temporary).resolve()
            or destination.parent != Path(temporary).resolve().parent
        ):
            raise ValueError("Package staging path changed")
        stage.replace(destination)
    return manifest


def verify_package(directory: Path) -> dict[str, Any]:
    """Verify exact packaged file bytes without requiring the runtime environment."""
    directory = directory.resolve()
    manifest: dict[str, Any] = json.loads(
        (directory / "manifest.json").read_text(encoding="utf-8")
    )
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Unsupported server package schema")
    for name, row in manifest["files"].items():
        path = directory / _relative(name)
        if (
            not path.resolve().is_relative_to(directory)
            or not path.is_file()
            or _sha(path) != row["sha256"]
        ):
            raise ValueError(f"PACKAGE_FILE_CHANGED_OR_MISSING: {name}")
    expected = {
        **{
            f"source/{name}": row["sha256"]
            for name, row in manifest["source_files"].items()
        },
        **manifest["input_files"],
    }
    if any(
        manifest["files"].get(name, {}).get("sha256") != value
        for name, value in expected.items()
    ):
        raise ValueError("PACKAGED_BYTES_DIFFER_FROM_FROZEN_INPUTS")
    return manifest


def restore_git(directory: Path) -> dict[str, Any]:
    """Restore only Git metadata/index; never rewrite packaged working files."""
    directory = directory.resolve()
    manifest = verify_package(directory)
    source = directory / "source"
    commit = manifest["source_identity"]["commit"]
    for name, row in manifest["source_files"].items():
        (source / _relative(name)).chmod(0o755 if row["mode"] == "100755" else 0o644)
    for path in (directory / "scripts").glob("*.sh"):
        path.chmod(0o755)
    if not (source / ".git").exists():
        _git(source, "init", "-q", "-b", "codex/msd-frozen")
        for name, value in manifest["git_config"].items():
            _git(source, "config", name, value)
        _git(source, "fetch", "--quiet", str(directory / "source.bundle"), "HEAD")
        _git(source, "update-ref", "refs/heads/codex/msd-frozen", commit)
        _git(source, "read-tree", commit)
    if (
        _git(source, "rev-parse", "HEAD").decode().strip() != commit
        or _git(source, "status", "--porcelain", "--untracked-files=all").strip()
    ):
        raise ValueError("RESTORED_PACKAGE_CHECKOUT_NOT_CLEAN")
    verify_package(directory)
    return manifest


def main() -> None:
    """Verify/restore an already built package; no command launches experiments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("verify", "restore"))
    parser.add_argument("--package", required=True, type=Path)
    args = parser.parse_args()
    result = (
        restore_git(args.package)
        if args.command == "restore"
        else verify_package(args.package)
    )
    print(
        json.dumps(
            {
                "schema": result["schema"],
                "commit": result["source_identity"]["commit"],
                "verified": True,
            }
        )
    )


if __name__ == "__main__":
    main()
