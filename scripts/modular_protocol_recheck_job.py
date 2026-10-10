"""Resume only downstream protocol verification using qualified static leaves."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
import argparse,json,sys,tarfile,subprocess,time
import shutil
from contextlib import ExitStack
from unittest.mock import patch
from hashlib import sha256

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import save
from component_protocol_job import execute


def observed_execute(name,out,resume=False):
    targets=('na_pipeline.backend.compiled_modules.compile_physical_dag',
             'na_pipeline.backend.physical_dag.compile_operation_window',
             'na_pipeline.backend.enola_kernel.EnolaKernel.__init__',
             'na_pipeline.backend.enola_scheduler.EnolaReadyScheduler.__init__',
             'na_pipeline.backend.enola_kernel.group_route')
    calls={key:0 for key in targets}
    def forbidden(key):
        def call(*args,**kwargs):
            calls[key]+=1
            raise AssertionError('TOP_LEVEL_NATIVE_COMPILATION_ENTRY_CALLED: '+key)
        return call
    with ExitStack() as stack:
        for target in targets:stack.enter_context(patch(target,side_effect=forbidden(target)))
        result=execute(name,out,resume=resume)
    evidence={'schema_version':'NativeCompilerEntryGuard/0.1','method':'intercept actual compile/window/kernel/scheduler/router entrypoints; any invocation fails the protocol immediately',
              'call_counts':calls,'zero_native_calls':not any(calls.values()),'per_function_profiling':False,
              'instrument_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest()}
    save(Path(out)/name/'raw-search-observation.json',evidence)
    if any(calls.values()):
        raise ValueError('COMPOSITE_TRIGGERED_NATIVE_SEARCH')
    return result


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--module-bundle',required=True)
    ap.add_argument('--resume-manifest');ap.add_argument('--workers',type=int,default=2);a=ap.parse_args()
    out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True);store=out/'compiled-modules';store.mkdir(exist_ok=True)
    with tarfile.open(ROOT/a.module_bundle) as archive:
        if any(Path(m.name).name!=m.name or not m.name.endswith('.json') for m in archive.getmembers()):
            raise ValueError('MODULE_ARCHIVE_PATH_INVALID')
        archive.extractall(store,filter='data')
    if a.resume_manifest:
        manifest=json.loads((ROOT/a.resume_manifest).read_bytes());source=Path(manifest['source_project']).resolve()
        if not source.is_relative_to(Path('/home/yyq/na-platform-simulation/R7/T704')):
            raise ValueError('RESUME_SOURCE_PROJECT_SCOPE')
        for item in manifest['files']:
            original=(source/item['source_path']).resolve();target=(out/'protocols'/item['protocol_path']).resolve()
            if not original.is_relative_to(source) or not target.is_relative_to((out/'protocols').resolve()):
                raise ValueError('RESUME_PATH_ESCAPE')
            if sha256(original.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('RESUME_SOURCE_BYTES_CHANGED')
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,target)
            if sha256(target.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('RESUME_COPY_BYTES_CHANGED')
        save(out/'resume-input-receipt.json',{'source_project':str(source),'file_count':len(manifest['files']),
                                            'manifest_hash':sha256((ROOT/a.resume_manifest).read_bytes()).hexdigest(),'all_bytes_verified':True})
    started=time.perf_counter()
    # Regression specifically covers independent relative-window audit after a
    # prior committed H/SE, in addition to continuous absolute-session binding.
    test=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests/backend','-p','test_compiled_modules.py','-v'],
                        cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    (out/'module-recheck-tests.log').write_text(test.stdout+test.stderr,encoding='utf-8')
    results=[]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(observed_execute,n,str(out/'protocols'),bool(a.resume_manifest)) for n in ('T','TDG','REJECT_RETRY')]):
            results.append(f.result());save(out/'status.json',{'status':'running','protocols':results})
    passed=test.returncode==0 and all(r['status']=='passed' for r in results)
    save(out/'status.json',{'status':'passed' if passed else 'incomplete','checks_exit_code':test.returncode,'protocols':results,
                          'wall_seconds':time.perf_counter()-started,'upstream_recompiled':False,'user_visual_acceptance':'pending'})
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
