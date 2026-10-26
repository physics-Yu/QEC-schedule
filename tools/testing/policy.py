"""Explicit test ownership, tiers, and conservative consumer selection."""

from __future__ import annotations

import ast
import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

TIERS = ("fast", "slow", "bench")
DEFAULT_MAP = Path(__file__).resolve().parents[2] / "tests/test-map.json"


@dataclass(frozen=True)
class Policy:
    """Validated manifest with paths relative to root."""

    root: Path
    roots: tuple[str, ...]
    areas: dict[str, Any]
    tests: dict[str, Any]


@dataclass(frozen=True)
class Selection:
    """Sorted affected areas and files, including the reasons for selection."""

    areas: tuple[str, ...]
    files: tuple[str, ...]
    reasons: dict[str, str]
    documentation: tuple[str, ...]


def _relative(value: str) -> str:
    path = value.replace("\\", "/")
    if PureWindowsPath(path).drive or path.startswith("/") or ".." in path.split("/"):
        raise ValueError(f"Expected repository-relative path: {value}")
    normalized = PurePosixPath(path).as_posix()
    if normalized == ".":
        raise ValueError(f"Expected a file or module path: {value}")
    return normalized


def load_policy(path: Path = DEFAULT_MAP) -> Policy:
    """Load a manifest from path and return its resolved repository policy.

    Raises:
        ValueError: The schema, relative paths, tiers or references are invalid.
        OSError: The manifest cannot be read.
        KeyError: A required manifest field is absent.
    """
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != 1:
        raise ValueError(f"Unsupported test-map schema: {path}")
    areas, tests = document["areas"], document["tests"]
    for name, area in areas.items():
        for source in area["sources"]:
            _relative(source)
        for consumer in area["consumers"]:
            if consumer not in areas:
                raise ValueError(f"Unknown consumer {consumer} in {name}")
    for name, entry in tests.items():
        _relative(name)
        for tier in [entry["tier"], *entry.get("overrides", {}).values()]:
            if tier not in TIERS:
                raise ValueError(f"Unknown tier {tier} in {name}")
        if not entry["areas"] or set(entry["areas"]) - areas.keys():
            raise ValueError(f"Unknown or empty area in {name}")
    return Policy(
        (path.parent / document["repository"]).resolve(),
        tuple(_relative(root) for root in document["roots"]),
        areas,
        tests,
    )


def audit(policy: Policy) -> None:
    """Check policy against files in its registered roots, without running tests.

    Raises:
        ValueError: A file is missing/unclassified or an override is stale.
        OSError: A test file cannot be read.
        SyntaxError: An overridden test file cannot be parsed.
    """
    found = {
        file.relative_to(policy.root).as_posix()
        for root in policy.roots
        for file in (policy.root / root).rglob("test_*.py")
        if "__pycache__" not in file.parts
    }
    if found != policy.tests.keys():
        raise ValueError(
            f"Unclassified tests: {sorted(found - policy.tests.keys())}; "
            f"stale entries: {sorted(policy.tests.keys() - found)}"
        )
    for name, entry in policy.tests.items():
        overrides = set(entry.get("overrides", {}))
        if not overrides:
            continue
        tree = ast.parse((policy.root / name).read_text(encoding="utf-8-sig"))
        functions: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.add(node.name)
            elif isinstance(node, ast.ClassDef):
                functions.update(
                    f"{node.name}::{child.name}"
                    for child in node.body
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                )
        if overrides - functions:
            raise ValueError(
                f"Stale overrides in {name}: {sorted(overrides - functions)}"
            )


def resolve_tier(policy: Policy, path: str, key: str, declared: Iterable[str]) -> str:
    """Return the tier for a relative path, node key and declared tier markers.

    Function overrides and declared markers must agree; either takes precedence
    over the file default. Parameter suffixes in key do not affect overrides.

    Raises:
        ValueError: The file is unclassified or its tiers conflict.
    """
    if path not in policy.tests:
        raise ValueError(f"Unclassified test: {path}::{key}")
    entry = policy.tests[path]
    override = entry.get("overrides", {}).get(key.split("[", 1)[0])
    explicit = set(declared)
    if override:
        explicit.add(override)
    if len(explicit) > 1 or explicit - set(TIERS):
        raise ValueError(f"conflicting tiers for {path}::{key}: {sorted(explicit)}")
    return next(iter(explicit), entry["tier"])


def _importers(policy: Policy, changed: str) -> set[str]:
    files = {
        path.relative_to(policy.root).as_posix(): path
        for root in policy.roots
        for path in (policy.root / root).rglob("*.py")
        if "__pycache__" not in path.parts
    }
    reverse: dict[str, set[str]] = {}
    for name, path in files.items():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.add(module)
                imports.update(
                    f"{module}.{alias.name}".strip(".") for alias in node.names
                )
        for dependency in files:
            dotted = dependency.removesuffix(".py").replace("/", ".")
            # Basename matching is conservative for pytest's sibling helper imports.
            if dotted in imports or PurePosixPath(dependency).stem in imports:
                reverse.setdefault(dependency, set()).add(name)
    affected, pending = {changed}, [changed]
    while pending:
        for importer in reverse.get(pending.pop(), set()) - affected:
            affected.add(importer)
            pending.append(importer)
    return affected & policy.tests.keys()


def select(
    policy: Policy, *, changed: Iterable[str] = (), areas: Iterable[str] = ()
) -> Selection:
    """Return tests for changed relative paths or areas and their consumers.

    Args:
        policy: Audited repository inventory and ownership graph.
        changed: Repository-relative source, test/helper, or documentation paths.
        areas: Explicit area names, independent of changed paths.

    Raises:
        ValueError: An area or runtime path is unknown, or a path is external.
        OSError: A test/helper dependency cannot be read.
        SyntaxError: A test/helper dependency cannot be parsed.
    """
    reasons = {area: "explicit area" for area in areas}
    if reasons.keys() - policy.areas.keys():
        raise ValueError(
            f"Unknown areas: {sorted(reasons.keys() - policy.areas.keys())}"
        )
    direct_files: set[str] = set()
    documentation: set[str] = set()
    for value in changed:
        path = _relative(value)
        matches: list[tuple[int, str]] = []
        descendants: set[str] = set()
        for area, entry in policy.areas.items():
            for source in entry["sources"]:
                prefix = source.rstrip("/")
                if path == prefix or (
                    source.endswith("/") and path.startswith(prefix + "/")
                ):
                    matches.append((len(prefix), area))
                if prefix.startswith(path + "/"):
                    descendants.add(area)
        if matches or descendants:
            longest = max((length for length, _ in matches), default=0)
            for area in descendants | {
                area for length, area in matches if length == longest
            }:
                reasons[area] = f"changed {path}"
        elif any(path == root or path.startswith(root + "/") for root in policy.roots):
            helpers = _importers(policy, path)
            if path.endswith(".py") and helpers:
                direct_files.update(helpers)
            else:
                raise ValueError(f"Unmapped test/helper change: {path}")
        elif path.endswith(".md"):
            documentation.add(path)
        else:
            raise ValueError(f"Unmapped change: {path}; update tests/test-map.json")
    pending = list(sorted(reasons))
    while pending:
        area = pending.pop()
        for consumer in policy.areas[area]["consumers"]:
            if consumer not in reasons:
                reasons[consumer] = f"consumer of {area}"
                pending.append(consumer)
    files = direct_files | {
        name
        for name, entry in policy.tests.items()
        if set(entry["areas"]) & reasons.keys()
    }
    return Selection(
        tuple(sorted(reasons)),
        tuple(sorted(files)),
        reasons,
        tuple(sorted(documentation)),
    )
