"""Prepare reusable call recipes and execute the complete unchanged Shor DAG."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT), str(ROOT/'scripts')]
from na_pipeline.frontend.logical_dag import build_logical_dag
from na_pipeline.qec import physical_resource_requirements, build_factory15to1_protocol
from na_pipeline.device import canonical_surface17_device, build_preinitialized_state, validate_preinitialized_state
from na_pipeline.runtime.component_recipe import ComponentRecipeLibrary
from na_pipeline.runtime.component_pipeline import ComponentPipeline
from na_pipeline.runtime import LogicalGateLibrary
from na_pipeline.runtime.pipeline import save_artifact
from na_pipeline.runtime.compilation_guard import CompilationGuard, UnexpectedCompilation
from na_pipeline.backend.enola_kernel import StrategyError


def build_world():
    logical = build_logical_dag()
    req = physical_resource_requirements(logical)
    device = canonical_surface17_device()
    patches = {p: {k: d[k] for k in ('aod_group', 'basis', 'value')} for p, d in req['patches'].items()}
    # Preserve the regular factory shape. Four idle algorithm patches extend
    # the same row; every spectator remains in the actual complete world.
    order = list(patches)
    placements = {p: {'anchor_um': [100.*i, 900.], 'orientation': 'x_vertical_z_horizontal'} for i,p in enumerate(order)}
    singles = req['nonpatch_atoms']
    inventory = {'schema_version': 'initial-resource-inventory/0.1', 'artifact_id': 'basic-shor-inventory',
        'provenance': {'producer': 'R0-basic-component-pipeline', 'fixture': False, 'source_refs': [logical['artifact_id']]},
        'patch_roles': {p: {'role': d['role'], 'pool_id': req['factory_id'] if d['role']=='factory' else 'algorithm', 'slot_id':p}
                        for p,d in req['patches'].items()},
        'nonpatch_atoms': {'atom:'+q['physical_qubit_id']: {'qubit_id':q['physical_qubit_id'], 'trap_id':'slm:'+q['physical_qubit_id'],
            'position_um':[100.*len(patches)+10.*i,980.], 'aod_group':q['aod_group'], 'role':q['role'],
            'pool_id':req['factory_id'], 'slot_id':q['slot_id'], 'basis':q['basis'], 'value':q['value']}
            for i,q in enumerate(singles)}}
    initial = build_preinitialized_state(device, patches, placements,
        placement_ref={'artifact_id':'basic-shor-canonical-layout', 'producer':'R0', 'fixture':False}, resource_inventory=inventory)
    errors = validate_preinitialized_state(initial,device)
    if errors: raise ValueError(errors)
    return {'schema_version':'basic-shor-world/0.1', 'logical_dag':logical, 'requirements':req,
            'device':device, 'initial_state':initial, 'placement_policy':'canonical_regular_baseline_no_search',
            'sampled':False, 'quantum_state_simulated':False}


def copy_modules(sources, destination):
    from na_pipeline.backend.compiled_modules import native_compiler_sources
    from na_pipeline.backend.enola_kernel import digest
    destination.mkdir(parents=True,exist_ok=True)
    files = {};origins={};lookup_conflicts=[]
    for source in sources or []:
        if not Path(source).is_dir(): raise ValueError('MODULE_IMPORT_SOURCE_MISSING: '+str(source))
        for p in sorted(Path(source).glob('*.json')):
            raw=p.read_bytes()
            target=destination/p.name
            if target.exists() and target.read_bytes()!=raw:
                if p.name.startswith('frontier-') and not p.name.startswith('frontier-proof-'):
                    lookup_conflicts.append({'name':p.name,'ignored_source':str(source)});continue
                raise ValueError('IMMUTABLE_MODULE_IMPORT_COLLISION: '+p.name)
            (destination/p.name).write_bytes(raw)
            files[p.name]=hashlib.sha256(raw).hexdigest()
            origins[p.name]=str(source)
    save_artifact(destination.parent/'module-import.json', {'sources':[str(s) for s in sources or []], 'files':files,'origins':origins,'lookup_conflicts':lookup_conflicts,
        'native_compiler_hash':digest(native_compiler_sources()), 'scope':'immutable bytes; normal lookup/bind must still qualify each use'})


def run_phase(world, out, library, *, max_steps=None):
    out.mkdir(parents=True,exist_ok=True)
    cp = out/'checkpoint.json.gz'
    if cp.exists():
        driver = ComponentPipeline.restore(world,out,json.loads(gzip.decompress(cp.read_bytes())),compiler=library)
    else:
        driver = ComponentPipeline(world,out,phase_bits=[0,1,0,0,0,0,0,0],compiler=library)
    started = time.perf_counter(); steps=0
    guard=CompilationGuard(on_violation=lambda details:save_artifact(out/'compilation-violation.json.gz',details))
    try:
        with guard:
            while not driver.scheduler.snapshot()['complete']:
                with guard.scope(window=driver.window_count,phase=out.name,
                                 factory_stage=driver.factory.stage_id if driver.factory else None):
                    try:result=driver.step()
                    except StrategyError as exc:
                        if exc.code in {'MODULE_DEPENDENCY_MISSING','COMPONENT_NOT_REGISTERED'}:
                            guard.missing_dependency(exc)
                        raise
                steps+=1
                if steps%5==0 or result['kind']=='factory_begin':
                    print(json.dumps({'phase':out.name,'step':steps,'windows':driver.window_count,
                          'terminal_nodes':sum(s['status'] in ('completed','skipped') for s in driver.scheduler.states.values()),
                          'factory_stage':driver.factory.stage_id if driver.factory else None,
                          'time_us':driver.session.now_us,'recipe_builds':library.stats['recipe_build_count'],
                          'leaf_builds':library.stats['module_stats']['leaf_compile_count'],
                          'compilation_guard':'reuse_only',
                          'elapsed_seconds':round(time.perf_counter()-started,3)}),flush=True)
                if max_steps and steps>=max_steps: break
    except (Exception,UnexpectedCompilation):
        # Persist the committed prefix and live controller. Nothing after the
        # failed prepare is submitted; no automatic restart/materialization.
        save_artifact(cp,driver.checkpoint())
        save_artifact(out/'stopped-summary.json',driver.status())
        raise
    finally:
        save_artifact(out/'compilation-guard.json',guard.receipt())
        save_artifact(out/'compiler-stats.json',library.stats)
    save_artifact(out/'event-trace.json.gz', driver.session.export_trace())
    save_artifact(out/'summary.json',driver.status())
    return driver


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True)
    p.add_argument('--module-source',type=Path,action='append');p.add_argument('--component-source',type=Path);p.add_argument('--schedule-source',type=Path);p.add_argument('--probe-steps',type=int)
    p.add_argument('--mode',choices=('prepare','execute','all'),default='all')
    p.add_argument('--compiler-interface',choices=('gate-ports','legacy'),default='gate-ports')
    a=p.parse_args()
    out=a.out;out.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    try:
        world=build_world();save_artifact(out/'world.json.gz',world,immutable=True)
        recipes=out/'recipes'
        if not (recipes/'module-import.json').exists():copy_modules(a.module_source,recipes/'modules')
        if a.compiler_interface=='legacy' and a.schedule_source and not (recipes/'schedules/index.json').exists():
            target=recipes/'schedules';target.mkdir(parents=True,exist_ok=True)
            for name in ('index.json','import.json'):
                raw=(a.schedule_source/name).read_bytes();(target/name).write_bytes(raw)
            save_artifact(target/'transfer.json',{'source':str(a.schedule_source),
                'index_sha256':hashlib.sha256((target/'index.json').read_bytes()).hexdigest(),'compiled_again':False})
        if a.compiler_interface=='legacy' and a.component_source and not (recipes/'schedules/index.json').exists():
            from basic_shor_schedules import import_schedules
            import_schedules(a.component_source,recipes/'schedules')
        budget={'max_operations':100000,'max_wall_seconds':3600}
        def library_for(build_missing):
            if a.compiler_interface=='legacy':return ComponentRecipeLibrary(world['device'],recipes,build_missing=build_missing,budget=budget)
            source=a.component_source or ROOT/'artifacts/demos/joint-factory-repaired-20261008'
            library=LogicalGateLibrary(world['device'],connection_directory=recipes/'modules',budget=budget,allow_connection_planning=build_missing)
            library.import_directory(source)
            return library
        if a.mode in ('prepare','all'):
            library=library_for(False)
            driver=run_phase(world,out/'prepare',library,max_steps=a.probe_steps)
            save_artifact(out/'prepare-stats.json',library.stats)
            if a.probe_steps:
                save_artifact(out/'status.json',{'status':'probe_completed','full_shor_executed':False,'summary':driver.status()});return
            assert driver.scheduler.snapshot()['complete']
            del driver,library
        if a.mode in ('execute','all'):
            library=library_for(False)
            driver=run_phase(world,out/'execute',library)
            assert driver.scheduler.snapshot()['complete']
            # First-use static linking is allowed; no native plan/search runs.
            for k in (('recipe_build_count','strategy_compile_count') if a.compiler_interface=='legacy' else ('strategy_compile_count',)):
                assert library.stats[k]==0,(k,library.stats[k])
            for k in ('leaf_compile_count','placement_search_count','routing_search_count'):
                assert library.stats['module_stats'][k]==0
            save_artifact(out/'execution-stats.json',library.stats)
        save_artifact(out/'status.json',{'status':'execution_complete_validation_pending',
            'full_source_path_complete':True,'full_program_passed':False,'mode':a.mode,
            'wall_seconds':time.perf_counter()-started,'user_visual_acceptance':'pending'})
    except (Exception,UnexpectedCompilation) as error:
        save_artifact(out/'status.json',{'status':'stopped_unexpected_compilation' if isinstance(error,UnexpectedCompilation) else 'failed_incomplete','error':str(error),
            'details':getattr(error,'details',None),'traceback':traceback.format_exc(),'wall_seconds':time.perf_counter()-started})
        raise


if __name__=='__main__': main()
