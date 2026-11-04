"""Isolated Z3 worker; only the parent consumes the caller's measurement case."""

import sys
from pathlib import Path

from ..execution import FakeBackend
from .process import read_request, write_checkpoint
from .solver import solve


def main() -> None:
    """Persist validated incumbents before subsequent unrestricted queries."""
    work = Path(sys.argv[1])
    context, options, seed = read_request(work / "request.json")
    solved = solve(
        context,
        options,
        FakeBackend(),
        seed=seed,
        checkpoint=lambda candidate: write_checkpoint(
            work / "checkpoint.json", candidate
        ),
    )
    write_checkpoint(work / "answer.json", solved)


if __name__ == "__main__":
    main()
