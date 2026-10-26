"""Apply audited test tiers before pytest performs marker deselection."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from .policy import DEFAULT_MAP, TIERS, audit, load_policy, resolve_tier

STATE: pytest.StashKey[dict[str, Any]] = pytest.StashKey()


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register manifest, profile, and machine-readable report options."""
    group = parser.getgroup("NADiT test policy")
    group.addoption("--test-map", default=str(DEFAULT_MAP))
    group.addoption("--test-tier", choices=("fast", "check", "full"), default=None)
    group.addoption("--test-report", default=None)


def pytest_configure(config: pytest.Config) -> None:
    """Register tiers and audit the full inventory before a scoped collection."""
    for tier, description in zip(
        TIERS,
        (
            "unit/constraint checks",
            "small integration checks",
            "expensive/reference experiments",
        ),
        strict=True,
    ):
        config.addinivalue_line("markers", f"{tier}: {description}")
    profile = config.getoption("test_tier")
    if profile and config.option.markexpr:
        raise pytest.UsageError("Use either --test-tier or -m, not both")
    if not config.option.markexpr:
        config.option.markexpr = {
            "fast": "fast",
            "full": "",
            "check": "not bench",
            None: "not bench",
        }[profile]
    try:
        policy = load_policy(Path(config.getoption("test_map")))
        audit(policy)
    except (ValueError, KeyError, OSError) as error:
        raise pytest.UsageError(str(error)) from error
    config.stash[STATE] = {
        "policy": policy,
        "nodes": {},
        "selected": set(),
        "outcomes": {},
        "duration": 0.0,
    }
    config.pluginmanager.register(OutcomeRecorder(config), "nadit-test-outcomes")


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> Generator[None, Any, Any]:
    """Validate every collected item before built-in -m filtering can hide errors."""
    state = config.stash[STATE]
    policy = state["policy"]
    for item in items:
        try:
            path = item.path.resolve().relative_to(policy.root).as_posix()
            key = item.nodeid.split("::", 1)[1]
            declared = tuple(
                mark.name for mark in item.iter_markers() if mark.name in TIERS
            )
            tier = resolve_tier(policy, path, key, declared)
        except ValueError as error:
            raise pytest.UsageError(str(error)) from error
        if tier not in declared:
            item.add_marker(getattr(pytest.mark, tier))
        state["nodes"][item.nodeid] = tier
    result = yield
    state["selected"] = {item.nodeid for item in items}
    return result


class OutcomeRecorder:
    """Collect outcomes across setup, call and teardown, preserving failures."""

    def __init__(self, config: pytest.Config) -> None:
        self.state = config.stash[STATE]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        """Record failures even if setup/teardown fails outside the call phase."""
        outcomes = self.state["outcomes"]
        self.state["duration"] += report.duration
        if report.failed:
            outcomes[report.nodeid] = "failed"
        elif report.skipped and outcomes.get(report.nodeid) != "failed":
            outcomes[report.nodeid] = "skipped"
        elif report.when == "call" and report.passed and report.nodeid not in outcomes:
            outcomes[report.nodeid] = "passed"


def _report(config: pytest.Config) -> dict[str, Any]:
    state = config.stash[STATE]
    tiers = {}
    for tier in TIERS:
        nodes = {node for node, value in state["nodes"].items() if value == tier}
        counts = Counter(state["outcomes"].get(node, "not_run") for node in nodes)
        tiers[tier] = {
            "collected": len(nodes),
            "selected": len(nodes & state["selected"]),
            **{key: counts[key] for key in ("passed", "failed", "skipped", "not_run")},
        }
    return {
        "tiers": tiers,
        "test_seconds": state["duration"],
        "scope": "collected files only",
    }


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write an optional outcome report including the actual pytest exit status."""
    path = session.config.getoption("test_report")
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {**_report(session.config), "exitstatus": int(exitstatus)}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """Display tier outcomes without treating deselection as a passing check."""
    terminalreporter.write_sep("-", "NADiT tiers (collected files only)")
    for tier, counts in _report(terminalreporter.config)["tiers"].items():
        terminalreporter.write_line(
            f"{tier}: " + ", ".join(f"{key}={value}" for key, value in counts.items())
        )
