"""Source float storage and ordered accumulation boundaries."""

from nadit_physical_compiler.placement.scoring import _Node, _Search


def test_group_cost_accumulates_after_lookahead_instead_of_before_it() -> None:
    node = _Node(max_distances=(1.0, 1.0), lookahead_cost=16777216.0)
    assert _Search.cost(node) == 16777216.0
