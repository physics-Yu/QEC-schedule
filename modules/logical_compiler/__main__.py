"""Source-checkout command line for logical translation."""

import argparse
import json
from pathlib import Path

from . import TranslationError, load_qasm


def main() -> int:
    """Translate one input file and emit JSON; return 2 for invalid input."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("qasm", type=Path)
    parser.add_argument("--code", required=True)
    parser.add_argument("--scheme", default="clifford_t")
    parser.add_argument("--error-budget", type=float, default=1e-6)
    parser.add_argument("--input-state", choices=("zero", "external"), default="zero")
    parser.add_argument("--max-operations", type=int, default=100_000)
    parser.add_argument("-o", "--output", type=Path)
    args = parser.parse_args()
    try:
        if args.output is not None and args.output.resolve() == args.qasm.resolve():
            raise TranslationError(
                "OUTPUT_COLLISION", "Output must not overwrite QASM input."
            )
        result = load_qasm(
            args.qasm,
            code=args.code,
            scheme=args.scheme,
            error_budget=args.error_budget,
            input_state=args.input_state,
            max_operations=args.max_operations,
        )
        text = json.dumps(result.to_dict(), indent=2, allow_nan=False)
        if args.output is not None:
            args.output.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    except (TranslationError, OSError, UnicodeError) as error:
        print(
            json.dumps(
                {
                    "status": "error",
                    "code": error.code
                    if isinstance(error, TranslationError)
                    else "INPUT_OUTPUT_ERROR",
                    "message": str(error),
                }
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
