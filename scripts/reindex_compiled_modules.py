"""Qualify legacy identities after a linker-only change, without compilation.

The original frozen source bundle, every native-rule hash and the leaf-emission
AST must match. Changed leaf actions, dependencies or source signatures reject.
Original artifacts remain untouched; a proof links content-addressed copies.
"""
from pathlib import Path
import argparse
import json
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
from na_pipeline.backend.compiled_modules import emission_fingerprint,native_compiler_sources
from na_pipeline.backend.enola_kernel import digest


def reindex(source, destination, bundle):
    source,destination=Path(source),Path(destination);destination.mkdir(parents=True,exist_ok=True)
    with tarfile.open(bundle) as archive:
        members={m.name:m for m in archive.getmembers()}
        key=next(k for k in members if k.endswith('src/na_pipeline/backend/compiled_modules.py'))
        old_source=archive.extractfile(members[key]).read().decode('utf-8')
    current=native_compiler_sources();ast_hash=emission_fingerprint(old_source)
    if ast_hash!=current['backend/compiled_modules.py::template_emission']:
        raise ValueError('MODULE_EMISSION_CHANGED_RECOMPILE_REQUIRED')
    excluded={'backend/compiled_modules.py','backend/module_graph.py','backend/logical_components.py'}
    proofs=[]
    for path in sorted(source.glob('*.json')):
        artifact=json.loads(path.read_bytes());body=artifact['body']
        if artifact['schema_version']!='CompiledModule/0.1' or digest(body)!=artifact['hash']:
            raise ValueError('MODULE_BODY_CORRUPTED '+path.name)
        normalized={k:v for k,v in body['compiler_sources'].items() if k not in excluded}
        normalized['backend/compiled_modules.py::template_emission']=ast_hash
        if normalized!=current:raise ValueError('NATIVE_RULE_CHANGED_RECOMPILE_REQUIRED '+path.name)
        template_hash=digest(body['template'])
        previous=artifact['hash']
        body['identity']['compiler']=digest(current);body['key']=digest(body['identity'])
        body['identity_reindex']={'previous_artifact_hash':previous,'leaf_template_hash_unchanged':template_hash,
                                  'native_rules_and_emission_ast_unchanged':True,'search_count':0}
        artifact['hash']=digest(body)
        name=body['key']+'-'+artifact['hash']+'.json'
        (destination/name).write_text(json.dumps(artifact,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
        proofs.append({'source_file':path.name,'source_hash':previous,'output_file':name,'output_hash':artifact['hash'],'template_hash':template_hash})
    report={'schema_version':'ModuleIdentityReindex/0.1','native_sources':current,'emission_ast_sha256':ast_hash,
            'artifacts':proofs,'artifact_count':len(proofs),'leaf_compile_count':0,'placement_search_count':0,'routing_search_count':0,
            'original_files_modified':False,'qualification':'native code equivalence only; every bound world must still be checked'}
    (destination/'reindex-proof.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--destination',required=True);p.add_argument('--bundle',required=True);a=p.parse_args()
    report=reindex(a.source,a.destination,a.bundle);print(json.dumps({'reindexed':report['artifact_count'],'search_count':0}))
