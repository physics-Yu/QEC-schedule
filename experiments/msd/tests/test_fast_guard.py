"""No-atom evidence catches aliases and restores process-local profiling state."""

import sys
from types import FrameType, FunctionType
from typing import Any

import pytest
from nadit_physical_compiler.replay import replay as captured_replay_alias

from experiments.msd.fast_guard import AtomExecutionForbidden, no_atom_execution


def test_pure_execution_records_completed_zero_interceptions():
    previous = sys.getprofile()
    with no_atom_execution() as audit:
        assert sum(range(5)) == 10
        assert not audit.to_dict()["passed"]
    evidence = audit.to_dict()
    assert evidence["passed"] is True
    assert evidence["intercepted_call_count"] == 0
    assert evidence["intercepted_entrypoints"] == []
    assert "current_thread_only" in evidence["scope"]
    assert sys.getprofile() is previous


def test_captured_real_replay_alias_is_blocked_before_invalid_arguments_run():
    previous = sys.getprofile()
    with (
        pytest.raises(AtomExecutionForbidden, match="replay:replay"),
        no_atom_execution() as audit,
    ):
        captured_replay_alias(None, None, None)
    assert audit.intercepted_call_count == 1
    assert audit.intercepted_entrypoints == ["nadit_physical_compiler.replay:replay"]
    assert audit.to_dict()["passed"] is False
    assert sys.getprofile() is previous


def test_late_component_expansion_is_blocked_without_importing_components():
    def expand() -> None:
        raise AssertionError("body ran")

    with (
        pytest.raises(AtomExecutionForbidden, match="fixture_component:.*expand"),
        no_atom_execution(),
    ):
        alias = FunctionType(
            expand.__code__, {"__name__": "modules.codes.fixture_component"}
        )
        alias()


def test_previous_profiler_is_chained_and_restored_on_exception():
    previous = sys.getprofile()
    observed: list[str] = []

    def original(frame: FrameType, event: str, arg: Any) -> None:
        if event == "call" and frame.f_code.co_name == "pure":
            observed.append("pure")

    def pure() -> None:
        raise ValueError("expected application error")

    sys.setprofile(original)
    try:
        with (
            pytest.raises(ValueError, match="expected application error"),
            no_atom_execution() as audit,
        ):
            pure()
        assert observed == ["pure"]
        assert sys.getprofile() is original
        assert audit.completed is False
    finally:
        sys.setprofile(previous)


def test_nested_guard_is_rejected_and_outer_guard_remains_usable():
    with no_atom_execution() as audit:
        with (
            pytest.raises(RuntimeError, match="ALREADY_ACTIVE_ON_THREAD"),
            no_atom_execution(),
        ):
            pytest.fail("nested guard entered")
        assert sum((2, 3)) == 5
    assert audit.completed


def test_suppressed_interception_cannot_report_success():
    with (
        pytest.raises(AtomExecutionForbidden, match="WAS_SUPPRESSED"),
        no_atom_execution() as audit,
        pytest.raises(AtomExecutionForbidden),
    ):
        captured_replay_alias(None, None, None)
    assert audit.to_dict()["passed"] is False


def test_disabling_profiler_invalidates_acceptance():
    previous = sys.getprofile()
    with (
        pytest.raises(RuntimeError, match="PROFILER_CHANGED"),
        no_atom_execution() as audit,
    ):
        sys.setprofile(None)
    assert audit.to_dict()["passed"] is False
    assert sys.getprofile() is previous


def test_cached_allowed_calls_do_not_hide_late_forbidden_alias():
    def pure(value: int) -> int:
        return value + 1

    with (
        pytest.raises(AtomExecutionForbidden, match="replay:replay"),
        no_atom_execution() as audit,
    ):
        assert sum(pure(i) for i in range(1000)) == 500500
        captured_replay_alias(None, None, None)
    assert audit.intercepted_call_count == 1


def test_same_code_with_changed_module_globals_is_reclassified():
    def expand() -> int:
        return 7

    namespace = {"__name__": "safe_fixture"}
    alias = FunctionType(expand.__code__, namespace)
    with (
        pytest.raises(AtomExecutionForbidden, match="modules.codes.late_fixture"),
        no_atom_execution() as audit,
    ):
        assert [alias() for _ in range(10)] == [7] * 10
        namespace["__name__"] = "modules.codes.late_fixture"
        alias()
    assert audit.intercepted_call_count == 1


def test_classification_cache_is_fresh_in_repeated_guard_contexts():
    previous = sys.getprofile()
    audits = []
    for _ in range(2):
        with (
            pytest.raises(AtomExecutionForbidden, match="replay:replay"),
            no_atom_execution() as audit,
        ):
            captured_replay_alias(None, None, None)
        audits.append(audit)
        assert sys.getprofile() is previous
    assert audits[0] is not audits[1]
    assert [audit.intercepted_call_count for audit in audits] == [1, 1]
