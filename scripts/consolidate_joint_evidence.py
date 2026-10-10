"""Make frame immutable witnesses inspectable at the shared gallery entry.

Copy bytes only. Do not replace lookup indices, reindex caches, change source
fingerprints, compile leaves or generate runtime results.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from na_pipeline.backend.enola_kernel import digest
from frozen_native_identity import frozen_native_sources


def consolidate(out, dispatch):
    sources = frozen_native_sources(dispatch); native_hash = digest(sources)
    target = out/'compiled-modules'; files = {}
    frame_store=(out/'frame-continuations/compiled-modules').resolve()
    if os.name=='nt':frame_store=Path('\\\\?\\'+str(frame_store))
    for p in sorted(frame_store.glob('*.json')):
        artifact = json.loads(p.read_bytes()); body = artifact['body']
        assert digest(body) == artifact['hash'], p
        if artifact['schema_version'] == 'JointFrontierDecision/0.1':
            assert p.name == 'frontier-proof-'+artifact['hash']+'.json', p
            assert body['identity']['compiler_hash'] == native_hash, p
        else:
            assert artifact['schema_version'] == 'CompiledModule/0.1', p
            assert body['compiler_sources'] == sources, p
        dest = target/p.name; content = p.read_bytes()
        if dest.exists():
            assert dest.read_bytes() == content, ('IMMUTABLE_EVIDENCE_COLLISION', p)
        else:
            dest.write_bytes(content)
        files[p.name] = hashlib.sha256(content).hexdigest()
    result = {'schema_version': 'FrameEvidenceConsolidation/0.1', 'passed': True,
              'native_hash': native_hash, 'copied_or_verified_bytes': files,
              'lookup_indices_replaced': False, 'compiled_or_retimed': False,
              'plans_or_events_modified': False}
    (out/'frame-evidence-consolidation.json').write_bytes((json.dumps(result, indent=2)+'\n').encode())
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True); p.add_argument('--dispatch', type=Path, required=True); args = p.parse_args()
    result = consolidate(args.out, args.dispatch)
    print(json.dumps({'passed': result['passed'], 'immutable_files': len(result['copied_or_verified_bytes'])}))
