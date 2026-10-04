"""Generate complete ideal d=3 encoded Shor15 native branches and evidence."""
import argparse
import json
from pathlib import Path
import numpy as np
from neutral_atom_experiments.qec_pbc.encoded_shor_native import execute_encoded_native, load_cached_shor


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cached-source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rounds',type=int,default=1)
    parser.add_argument('--seed',type=int,default=7)
    parser.add_argument('--max-attempts',type=int,default=4)
    args=parser.parse_args()
    synthesized,program,provenance=load_cached_shor(args.cached_source)
    initial=np.zeros(1<<len(program.wires),complex);initial[0]=1
    summary=execute_encoded_native(program,initial,args.output,rounds=args.rounds,seed=args.seed,
        terminal_wires=program.wires[:8],external_global_phase_radians=synthesized.global_phase_radians,
        synthesized=synthesized,max_attempts=args.max_attempts,source_provenance=provenance,
        on_progress=lambda value:print(json.dumps(value),flush=True))
    print(json.dumps(summary,indent=2),flush=True)
    return 0 if summary['success'] else 2


if __name__=='__main__':
    raise SystemExit(main())
