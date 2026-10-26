"""Run explicit test scopes without additional pytest dependencies."""

from __future__ import annotations

import argparse
import json

from .policy import DEFAULT_MAP, audit, load_policy, select


def main() -> int:
    """Parse scope, print its reasons, and return pytest's unmodified exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile", choices=("fast", "check", "full"), nargs="?", default="fast"
    )
    parser.add_argument("--changed", nargs="+", default=[])
    parser.add_argument("--area", action="append", default=[])
    parser.add_argument("--plan", action="store_true")
    parser.add_argument("--list-areas", action="store_true")
    args = parser.parse_args()
    try:
        policy = load_policy(DEFAULT_MAP)
        audit(policy)
        if args.list_areas:
            print(json.dumps(policy.areas, indent=2))
            return 0
        if args.profile == "fast" and not (args.changed or args.area):
            parser.error("fast requires --changed or --area")
        selection = select(policy, changed=args.changed, areas=args.area)
        scoped = bool(args.changed or args.area)
        files = selection.files if scoped else tuple(sorted(policy.tests))
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(
        json.dumps(
            {
                "profile": args.profile,
                "areas": selection.reasons,
                "files": files,
                "documentation": selection.documentation,
            },
            indent=2,
        ),
        flush=True,
    )
    if not args.plan and not files and selection.areas:
        parser.error("Selected runtime areas have no tests; this is not verification")
    if args.plan or not files:
        return 0
    import pytest

    return int(
        pytest.main(
            [
                "-c",
                str(policy.root / "pytest.ini"),
                "--test-tier",
                args.profile,
                "--durations=20",
                "--test-report",
                str(policy.root / ".pytest_cache/test-report.json"),
                "-q",
                *(str(policy.root / file) for file in files),
            ]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
