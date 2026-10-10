"""Freeze exact decision witnesses; repair only unresolved consumers, no routing."""
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
import argparse,gzip,hashlib,json,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from na_pipeline.backend.enola_kernel import digest
from na_pipeline.backend.compiled_modules import native_compiler_sources
from component_gallery_job import save


def read(p):
    b=p.read_bytes();return json.loads(gzip.decompress(b) if p.suffix=='.gz' else b)


def plans(out):
    for p in out.glob('*/physical-plan.json'):yield ('component',p.parent.name),p,read(p)
    for p in (out/'parallel-examples').glob('*/physical-plan.json'):yield ('parallel',p.parent.name),p,read(p)
    for name in ('T','TDG','REJECT_RETRY'):
        folder=out/'protocols'/name
        for row in read(folder/'summary.json')['phases']:
            p=folder/row['artifact'];yield ('protocol',name),p,read(p)['physical_plan']
    for p in (out/'frame-continuations').glob('*/frame-session.json.gz'):
        for e in read(p)['entries']:yield ('frame',p.parent.name),p,e['physical_plan']


def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',required=True);p.add_argument('--source',required=True);p.add_argument('--out',required=True);p.add_argument('--input-manifest',required=True);a=p.parse_args()
    parent=Path(a.parent).resolve();source=(parent/a.source).resolve();out=(ROOT/a.out).resolve()
    if not parent.is_relative_to('/home/yyq/na-platform-simulation/R7/T704') or not source.is_relative_to(parent/'artifacts/demos') or not out.is_relative_to(ROOT/'artifacts/demos'):raise ValueError('SEAL_SCOPE')
    worker=read(parent/'scripts/outputs/T704/worker-receipt.json')
    if worker['returncode']!=0 or not worker['source_snapshot_stable'] or not worker['input_snapshot_verified'] or read(source/'residency-and-frame-complete.json')['status']!='passed':raise ValueError('PARENT_NOT_COMPLETE')
    frozen=read(ROOT/a.input_manifest)
    if frozen['source']!=str(source):raise ValueError('INPUT_SOURCE_CHANGED')
    for name,sha in frozen['files'].items():
        f=(source/name).resolve()
        if not f.is_relative_to(source) or hashlib.sha256(f.read_bytes()).hexdigest()!=sha:raise ValueError('INPUT_CHANGED '+name)
    if out.exists():raise ValueError('DELIVERY_ALREADY_EXISTS')
    shutil.copytree(source,out,ignore=shutil.ignore_patterns('checkpoint*','*.tmp'))
    store=out/'compiled-modules';native=native_compiler_sources();proofs={};imports={};inputs={}
    # Include the frame variants in the root store so every displayed reference
    # remains inspectable from the one delivery entry point.
    for root in (source/'compiled-modules',source/'frame-continuations/compiled-modules'):
        for file in root.glob('*.json'):
            item=read(file);body=item.get('body')
            if not body or digest(body)!=item.get('hash'):raise ValueError('INPUT_BODY_HASH '+str(file))
            if item['schema_version']=='CompiledModule/0.1':
                if body['compiler_sources']!=native:raise ValueError('NATIVE_RULES_CHANGED '+file.name)
                target=store/file.name
                if target.exists() and read(target)!=item:raise ValueError('MODULE_COLLISION')
                if not target.exists():shutil.copyfile(file,target)
                imports[file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
            elif item['schema_version']=='JointFrontierDecision/0.1':
                if body['identity']['compiler_hash']!=digest(native):raise ValueError('FRONTIER_NATIVE_RULES_CHANGED')
                name='frontier-proof-'+item['hash']+'.json'
                (store/name).write_text(json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':')),encoding='utf-8')
                proofs[item['hash']]={'file':name,'source':str(file),'byte_sha256':hashlib.sha256((store/name).read_bytes()).hexdigest()}
                target=store/file.name
                if not target.exists():shutil.copyfile(file,target)
    def missing():
        bad={}
        for key,path,plan in plans(out):
            inputs[path.relative_to(out).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
            absent={f['decision_hash'] for f in plan['module_composition']['dependency_graph'].get('joint_frontiers',[]) if f['decision_hash'] not in proofs and not (store/('frontier-proof-'+f['decision_hash']+'.json')).is_file()}
            if absent:bad.setdefault(key,set()).update(absent)
        return bad
    gaps=missing();original_inputs=dict(inputs);repaired=[]
    targets=('na_pipeline.backend.compiled_modules.compile_physical_dag','na_pipeline.backend.physical_dag.compile_operation_window',
             'na_pipeline.backend.enola_kernel.EnolaKernel.__init__','na_pipeline.backend.enola_scheduler.EnolaReadyScheduler.__init__',
             'na_pipeline.backend.enola_kernel.group_route')
    calls={t:0 for t in targets}
    def forbidden(name):
        def f(*args,**kwargs):calls[name]+=1;raise AssertionError('SEAL_TRIGGERED_NATIVE_SEARCH '+name)
        return f
    with ExitStack() as stack:
        for t in targets:stack.enter_context(patch(t,side_effect=forbidden(t)))
        for (kind,name),hashes in gaps.items():
            if kind=='component':
                if name=='SE_PAIR':
                    from component_parallel_demo import build
                    build(out)
                else:
                    from component_gallery_job import compile_one
                    result=compile_one(name,out,1800)
                    if result['status']!='passed':raise ValueError(result)
            elif kind=='protocol':
                from modular_protocol_recheck_job import observed_execute
                result=observed_execute(name,str(out/'protocols'))
                if result['status']!='passed':raise ValueError(result)
            else:
                # These consumers were built sequentially. A missing witness is
                # unexpected; preserve all bytes rather than fabricating it.
                raise ValueError({'UNRESOLVED_SEQUENTIAL_CONSUMER':kind,'name':name,'hashes':sorted(hashes)})
            repaired.append({'kind':kind,'name':name,'unresolved_original_hashes':sorted(hashes),'native_search_calls':0})
    if missing():raise ValueError('UNRESOLVED_FRONTIER_PROOFS')
    status=read(out/'status.json')
    status['components']=[read(out/r['component_id']/'summary.json') for r in status['components']]
    status['protocols']=[read(out/'protocols'/r['component_id']/'summary.json') for r in status['protocols']]
    save(out/'status.json',status)
    tests=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/backend','-p','test_joint_frontier.py','-v'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    (out/'proof-storage-tests.log').write_text(tests.stdout+tests.stderr,encoding='utf-8')
    if tests.returncode:raise ValueError('PROOF_STORAGE_TEST_FAILED')
    # Index includes newly frozen receipts from any repaired source consumers.
    for file in store.glob('frontier-proof-*.json'):
        item=read(file);proofs[item['hash']]={'file':file.name,'byte_sha256':hashlib.sha256(file.read_bytes()).hexdigest()}
    from audit_cnot_cohorts import audit
    audit(out)
    receipt={'schema_version':'JointDeliveryProofSeal/0.1','status':'passed','parent_project':str(parent),'parent_worker_receipt':worker,
        'native_rule_hash':digest(native),'native_rule_sources':native,'imported_module_byte_sha256':imports,
        'original_consumer_byte_sha256':original_inputs,'final_consumer_byte_sha256':inputs,'repaired_consumers':repaired,'guard_calls':calls,
        'immutable_frontier_proofs':proofs,'original_parent_unchanged':True,'new_native_compilation':False,
        'proof_storage_tests_passed':True,'test_compilation_separate_from_delivery':True,'user_visual_acceptance':'pending'}
    receipt['input_manifest_sha256']=hashlib.sha256((ROOT/a.input_manifest).read_bytes()).hexdigest()
    save(out/'proof-seal.json',receipt)
    print(json.dumps({'status':'passed','proofs':len(proofs),'repaired_consumers':len(repaired),'native_calls':sum(calls.values())}),flush=True)

if __name__=='__main__':main()
