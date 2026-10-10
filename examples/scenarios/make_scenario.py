"""Write every fake return explicitly for an existing AtomProgram."""

import argparse
import json
from pathlib import Path

from na_pipeline.runtime import make_scenario


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atom_program", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--value", type=int, choices=(0, 1), default=0)
    parser.add_argument("--overrides", type=Path, help="JSON object of result_id to bit or full fake record")
    args = parser.parse_args()
    program = json.loads(args.atom_program.read_text(encoding="utf-8"))
    overrides = json.loads(args.overrides.read_text(encoding="utf-8")) if args.overrides else None
    scenario = make_scenario(program, value=args.value, overrides=overrides)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(scenario, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))
    print(json.dumps({"path": str(args.output.resolve()), "result_count": len(scenario["results"]), "origin": "fake", "sampled": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
