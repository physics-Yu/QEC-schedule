"""Freeze the actual source content as well as the repository commit."""

import hashlib
import os
import subprocess
from collections.abc import Iterator, Sequence
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .suite import MODULE

_MSD_TREES = (
    "modules/physical_compiler/src",
    "modules/codes",
    "modules/logical_compiler",
    "experiments/msd",
)
_IGNORED_DIRECTORIES = frozenset(
    {
        "tests",
        "tests_hsim",
        "tests_simulation",
        "artifacts",
        "results",
        "docs",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".git",
        ".venv",
        "build",
        "dist",
    }
)
_SOURCE_SUFFIXES = frozenset(
    {
        ".py",
        ".json",
        ".toml",
        ".lock",
        ".yaml",
        ".yml",
        ".qasm",
        ".qasm3",
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".js",
        ".css",
        ".html",
        ".sh",
        ".ps1",
    }
)
_ENVIRONMENT_NAMES = (
    "pyproject.toml",
    "uv.lock",
    "requirements.txt",
    "requirements.lock",
    "environment.yml",
    "environment.yaml",
)


def _inside_workspace(path: Path, workspace: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"source_paths must stay inside the workspace: {path}")
    return resolved


def _normalize_paths(paths: Sequence[str]) -> tuple[str, ...]:
    if isinstance(paths, str) or not isinstance(paths, Sequence):
        raise ValueError(
            "source_paths must be a sequence of repository-relative strings"
        )
    normalized: set[str] = set()
    for value in paths:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("source_paths must contain nonempty strings")
        path = PurePosixPath(value.replace("\\", "/"))
        if (
            path.is_absolute()
            or PureWindowsPath(value).drive
            or ".." in path.parts
            or str(path) == "."
        ):
            raise ValueError(f"source_paths must be repository-relative: {value}")
        normalized.add(path.as_posix())
    return tuple(sorted(normalized))


def _source_files(path: Path, workspace: Path) -> Iterator[Path]:
    """Scan declared trees without descending into tests or runtime outputs."""
    _inside_workspace(path, workspace)
    if path.is_file():
        yield path
        return
    if not path.is_dir():
        raise ValueError(f"source_paths entry is missing: {path}")
    for directory, children, filenames in os.walk(path):
        children[:] = sorted(
            name for name in children if name not in _IGNORED_DIRECTORIES
        )
        for name in children:
            child = Path(directory) / name
            _inside_workspace(child, workspace)
            if child.is_symlink():
                raise ValueError(
                    f"source_paths directory links are unsupported: {child}"
                )
        for name in sorted(filenames):
            file = Path(directory) / name
            if file.suffix in _SOURCE_SUFFIXES or name in _ENVIRONMENT_NAMES:
                _inside_workspace(file, workspace)
                yield file


def _scoped_files(scope: str, paths: tuple[str, ...], workspace: Path) -> list[Path]:
    selected: set[Path] = set()
    roots = _MSD_TREES if scope == "msd" else ("modules/physical_compiler/src",)
    for relative in (*roots, *paths):
        selected.update(_source_files(workspace / relative, workspace))
    # Existing environment locks are mandatory, as in the legacy physical scope.
    for name in ("pyproject.toml", "uv.lock"):
        selected.update(_source_files(MODULE / name, workspace))
    if scope == "msd":
        for name in _ENVIRONMENT_NAMES:
            path = workspace / name
            if path.exists():
                selected.update(_source_files(path, workspace))
    return sorted(selected, key=lambda path: path.relative_to(workspace).as_posix())


def code_version(
    *,
    allow_dirty: bool,
    scope: str = "physical",
    source_paths: Sequence[str] = (),
) -> dict[str, Any]:
    """Freeze source bytes and declared inputs, preserving legacy defaults.

    ``scope='msd'`` also covers code/logical/MSD source and JSON configuration,
    while excluding tests and generated results. ``source_paths`` adds explicit
    repository-relative reference files or filtered directories; external JSON
    references must be listed by the caller, not inferred from arbitrary text.
    Explicit files are hashed regardless of suffix. Missing files, unsafe paths,
    unsupported scopes and unauthorized dirty checkouts raise ValueError.

    This is campaign drift detection, not an action/probability cache key. Source
    selection is saved in opt-in snapshots and reused by ``check_version``.
    """
    if scope not in ("physical", "msd"):
        raise ValueError("Unsupported experiment source scope")
    paths = _normalize_paths(source_paths)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=MODULE, text=True
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all"], cwd=MODULE, text=True
    )
    dirty = bool(status.strip())
    if dirty and not allow_dirty:
        raise ValueError(
            "Experiment requires a clean checkout; "
            "--allow-dirty records exact source content."
        )
    digest = hashlib.sha256()
    scoped = scope != "physical" or bool(paths)
    base = MODULE.resolve().parents[1] if scoped else MODULE
    files = (
        _scoped_files(scope, paths, base)
        if scoped
        else [
            *sorted((MODULE / "src").rglob("*.py")),
            MODULE / "pyproject.toml",
            MODULE / "uv.lock",
        ]
    )
    for path in files:
        digest.update(path.relative_to(base).as_posix().encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    result = {"commit": commit, "dirty": dirty, "source_hash": digest.hexdigest()}
    if scoped:
        result.update(source_scope=scope, source_paths=list(paths))
    return result


def check_version(expected: dict[str, Any]) -> None:
    """Stop dispatch/acceptance if the running experiment's code changed."""
    try:
        actual = code_version(
            allow_dirty=True,
            scope=expected.get("source_scope", "physical"),
            source_paths=expected.get("source_paths", ()),
        )
    except (OSError, ValueError) as error:
        raise ValueError(f"Code changed during experiment: {error}") from error
    if actual != expected:
        raise ValueError(
            "Code changed during experiment; stop and start a new version directory."
        )
