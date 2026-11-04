"""Compatibility CLI for nadit method retiming/v1 with optional stdout output."""

import argparse
import json
from pathlib import Path

from nadit_physical_compiler.methods import run_method
from nadit_physical_compiler.methods.retiming import (
    DURATION_TOLERANCE_US,
    KINDS,
    SCHEMA,
    TERM_TOLERANCE,
    TERMS,
    UnsupportedSchedule,
    accept,
    duration,
    evaluate,
    export,
    reference_timing,
)

__all__ = [
    "DURATION_TOLERANCE_US",
    "KINDS",
    "SCHEMA",
    "TERMS",
    "TERM_TOLERANCE",
    "UnsupportedSchedule",
    "accept",
    "duration",
    "evaluate",
    "export",
    "reference_timing",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--error-params", type=Path)
    args = parser.parse_args()
    if args.output and args.output.resolve() in {
        path.resolve() for path in (args.result, args.error_params) if path is not None
    }:
        parser.error("Output must differ from the result and parameter files.")
    document = json.loads(args.result.read_text(encoding="utf-8"))
    error = (
        json.loads(args.error_params.read_text(encoding="utf-8"))
        if args.error_params
        else {}
    )
    retiming = run_method("retiming/v1", document, error_params=error)
    text = json.dumps(retiming, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8", newline="\n")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
