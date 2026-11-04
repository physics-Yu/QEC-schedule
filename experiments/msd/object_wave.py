"""Schedule a single homogeneous wave of caller-supplied logical component stages."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from modules.codes.contracts.parallel import ComponentPhase
from modules.logical_compiler.src.estimation.phases import (
    PhaseInvocation,
    schedule_phases,
)


def _stage(record: dict) -> ComponentPhase:
    fields = dict(record)
    for key in ("resources", "acquire", "release"):
        if key in fields:
            if not isinstance(fields[key], list):
                raise TypeError(f"stage {key} must be an array of resource names")
            fields[key] = tuple(fields[key])
    return ComponentPhase(**fields)


def main() -> None:
    """Read an array of phase invocations and print their schedule in microseconds."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, help="UTF-8 JSON array of PhaseInvocation records"
    )
    parser.add_argument("--timeout-seconds", type=float, default=5.0)
    args = parser.parse_args()
    with args.input.open(encoding="utf-8-sig") as stream:
        records = json.load(stream)
    if not isinstance(records, list):
        raise TypeError("the input must be an array of invocations")
    members = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("stages"), list):
            raise TypeError("each invocation must contain an array of stages")
        stages = tuple(_stage(stage) for stage in record["stages"])
        members.append(PhaseInvocation(**{**record, "stages": stages}))
    result = schedule_phases(tuple(members), timeout_seconds=args.timeout_seconds)
    print(json.dumps(asdict(result), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
