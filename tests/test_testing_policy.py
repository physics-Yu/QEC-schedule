"""Regression for test files omitted by the inventory audit before 6bbe046."""

from pathlib import Path

import pytest

from tools.testing.policy import Policy, audit


def test_audit_detects_unclassified_files_before_a_narrow_run(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "new_test.py").write_text("def test_case(): pass\n")

    with pytest.raises(ValueError, match="tests/new_test.py"):
        audit(Policy(tmp_path, ("tests",), {}, {}))
