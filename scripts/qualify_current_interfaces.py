"""Fresh contract regressions, source acceptance, then a guarded full attempt."""
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,time,unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from na_pipeline.runtime.pipeline import save_artifact


def test_group(group,out):
    started=time.perf_counter()
    # Independent process per group avoids same-name unittest import collisions.
    sys.path.insert(0,str(ROOT/'tests'/group))
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'/group))
    with (out/(group+'-tests.log')).open('w',encoding='utf-8') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    record={'group':group,'tests':result.testsRun,'passed':result.wasSuccessful(),
            'failures':[(str(t),v) for t,v in result.failures],
            'errors':[(str(t),v) for t,v in result.errors],
            'skipped':[(str(t),v) for t,v in result.skipped],
            'wall_seconds':time.perf_counter()-started}
    save_artifact(out/(group+'-tests.json'),record)
    print(json.dumps(record),flush=True)
    return 0 if result.wasSuccessful() and not result.skipped else 1


def prior_test_record(project,group,component_source):
    """Reuse only passed regressions with unchanged production/test inputs."""
    if group=='tooling':return None
    root=Path(project)
    p=root/'artifacts/qualification/shor-guard-20261009'/(group+'-tests.json')
    if not p.exists():return None
    record=json.loads(p.read_bytes())
    if not record['passed'] or record['skipped']:return None
    worker=json.loads((root/'scripts/outputs/T704/worker-receipt.json').read_bytes())
    if worker.get('source_snapshot_stable') is not True:raise ValueError('PREVIOUS_TEST_SOURCE_NOT_STABLE')
    argv=json.loads((root/'scripts/outputs/T704/job-spec.json').read_bytes())['argv']
    if argv[argv.index('--component-source')+1]!=str(component_source):raise ValueError('TEST_COMPONENT_PACKAGE_CHANGED')
    inventory=json.loads((root/'scripts/outputs/T704/source-inventory.json').read_bytes())
    checked={}
    # These groups import only production modules, each other's own group
    # helpers, and these fixed fixtures. No scripts/viewer authoring code is
    # imported by them. New tooling/backend cases always rerun below.
    for name,h in inventory.items():
        if name.startswith(('src/','configs/','third_party/','tests/'+group+'/','tests/fixtures/','knowledge/','examples/')) or name.endswith('/factory-stage-v1/input.json.gz'):
            if not (ROOT/name).exists() or hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=h:
                raise ValueError('TEST_INPUT_CHANGED: '+name)
            checked[name]=h
    current={p.relative_to(ROOT).as_posix() for p in (ROOT/'tests'/group).glob('*.py')}
    if not current<=inventory.keys():raise ValueError('NEW_TEST_NOT_EXECUTED')
    record['reused_qualification']={'project':str(root),'report_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
                                  'unchanged_inputs':checked,'runtime_state_reused':False}
    return record


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--test-group');p.add_argument('--component-source',type=Path)
    p.add_argument('--module-source',type=Path);p.add_argument('--attempt-shor',action='store_true')
    p.add_argument('--reuse-test-receipts-from',type=Path)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    if a.test_group:return test_group(a.test_group,a.out)
    # This symlink is a read-only package input for the existing public tests.
    package=ROOT/'artifacts/demos/joint-factory-repaired-20261008'
    if not package.exists():
        package.parent.mkdir(parents=True,exist_ok=True)
        package.symlink_to(a.component_source.resolve(),target_is_directory=True)
    groups=['runtime','qec','validation','backend','device','frontend','integration','tooling']
    result={'schema_version':'CurrentInterfaceAcceptance/0.1','status':'testing',
            'groups':[], 'full_shor_passed':False,'all_interfaces_end_to_end_accepted':False,
            'fleet_full_production_accepted':False,'sampled':False,
            'qualification_scope':'contract regressions plus exact frozen Shor source binding; full producer fleet still requires native qualified templates'}
    for group in groups:
        prior=prior_test_record(a.reuse_test_receipts_from,group,a.component_source) if a.reuse_test_receipts_from else None
        if prior:
            save_artifact(a.out/(group+'-tests.json'),prior)
            (a.out/(group+'-tests.log')).write_bytes((a.reuse_test_receipts_from/'artifacts/qualification/shor-guard-20261009'/(group+'-tests.log')).read_bytes())
            rc=0
        else:rc=subprocess.call([sys.executable,__file__,'--out',str(a.out),'--test-group',group],cwd=ROOT)
        record=json.loads((a.out/(group+'-tests.json')).read_bytes());result['groups'].append(record)
        save_artifact(a.out/'acceptance.json',result)
        if rc:
            result['status']='tests_failed_or_skipped';save_artifact(a.out/'acceptance.json',result);return 1
    command=[sys.executable,str(ROOT/'scripts/audit_shor_interfaces.py'),'--out',str(a.out/'source-audit'),
             '--source',str(a.component_source),'--no-measure']
    rc=subprocess.call(command,cwd=ROOT)
    if rc:return rc
    compatibility=json.loads((a.out/'source-audit/source-compatibility.json').read_bytes())
    if compatibility['static_compatible']!=compatibility['static_total'] or compatibility['factory_stage_compatible']!=compatibility['factory_stage_total']:
        raise ValueError('SHOR_SOURCE_INTERFACE_REJECTED')
    result.update(status='contract_regressions_passed',test_count=sum(r['tests'] for r in result['groups']),
                  static_source_checks=compatibility['static_compatible'],factory_source_checks=compatibility['factory_stage_compatible'])
    save_artifact(a.out/'acceptance.json',result)
    if a.attempt_shor:
        # New runtime state; reuse only immutable native bytes from prior work.
        command=[sys.executable,str(ROOT/'scripts/basic_shor_job.py'),'--out',str(a.out/'full-shor'),
                 '--mode','execute','--component-source',str(a.component_source)]
        if a.module_source:command+=['--module-source',str(a.module_source)]
        save_artifact(a.out/'full-attempt-command.json',{'argv':command,'auto_retry':False,
            'component_compilation_allowance':0,'input_nodes':2102,'factory_mode':'single_line_compatibility'})
        return subprocess.call(command,cwd=ROOT)
    return 0


if __name__=='__main__':raise SystemExit(main())
