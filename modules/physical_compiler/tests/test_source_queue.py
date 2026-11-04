"""Compare queue removals against executed original C++ heap operations."""

import json
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[1] / "reference"

EXPECTED = json.loads((REFERENCE / "queue_expected.json").read_text(encoding="utf-8"))


def test_original_equal_priority_order_is_not_fifo() -> None:
    # Executed from the pinned BoundedPriorityQueue, not inferred from Python.
    assert EXPECTED["cases"]["equal_priorities"]["popped"] == [
        [1, 0],
        [1, 3],
        [1, 2],
        [1, 1],
    ]
