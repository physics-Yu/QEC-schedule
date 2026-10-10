"""T044 repair inputs through the existing single persistent dispatcher."""
from argparse import Namespace
from pathlib import Path
import hashlib
import json
from server_pipeline_job import dispatch

ROOT = Path(__file__).resolve().parents[1]


def main():
    old_inventory = ROOT/'scripts/outputs/T704/server/20261008T074911655280Z-t044-joint-factory-frontier-v3/source-inventory.json'
    paths = {ROOT/p for p in json.loads(old_inventory.read_bytes())
             if not p.startswith('scripts/outputs/')}
    # Add new fixtures explicitly; an old inventory is only a list of input
    # paths, never a way to reuse old source hashes or compilation results.
    paths.update(p for p in (ROOT/'tests').rglob('*') if p.is_file() and p.suffix in ('.py', '.json'))
    paths.update(ROOT/f'artifacts/demos/frame-cnot-cohorts-20261008/protocols/{n}/summary.json'
                 for n in ('T', 'TDG', 'REJECT_RETRY'))
    spec = {
        'schema_version': 'r7-server-job/0.2',
        'name': 't044-joint-factory-committed-batch',
        'purpose_id': 't044-joint-factory-rebuild',
        'stage_kind': 'factory_t',
        'argv': ['{python}', 'scripts/joint_factory_job.py', '--out',
                 'artifacts/demos/joint-factory-repaired-20261008'],
        'budget': {'wall_seconds': 9000, 'memory_gib': 48, 'parallelism': 4, 'search_expansions': 20000},
        'budget_rationale': 'Cold full65+pairedSE,T/TDG/reject,7frames,4parallel examples; fix committed12-pair leaf11+1 regression. 11 focused tests passed with full137-atom fixture, physical H-CZ-H and original open-frontier policy. Prior full job2819s; budget9000s48GiB4workers, leaf1800s/beam192/assignment20k. Same100us pickup/drop and3 SE rounds; no cache migration, source truncation, fullShor or heartbeat. Final strict joint and CNOT audits required.',
        'output_roots': ['artifacts/demos/joint-factory-repaired-20261008'],
    }
    target = ROOT/'scripts/outputs/T704/joint-factory-repair-spec.json'
    target.write_bytes((json.dumps(spec, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    selected = sorted(paths)
    manifest = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in selected}
    (target.parent/'joint-repair-inputs.json').write_bytes((json.dumps(manifest, indent=2)+'\n').encode())
    dispatch(Namespace(spec=target, input=selected))


if __name__ == '__main__':
    main()
