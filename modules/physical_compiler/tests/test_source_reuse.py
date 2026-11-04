"""Separate the original endpoint-priority policy from complete shared edges."""

from reuse_support import _circuit

from nadit_physical_compiler.reuse import MatchingReuseAnalyzer, SourceReuseAnalyzer


def test_original_and_complete_edge_reuse_are_explicitly_different_policies() -> None:
    circuit = _circuit(((0, 1), (2, 3)), ((0, 2), (1, 3)))
    assert SourceReuseAnalyzer().analyze(*circuit) == (0,)
    assert MatchingReuseAnalyzer().analyze(*circuit) == (1, 2)
