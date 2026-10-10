"""Compile and execute complete adaptive component examples in one live world."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor,as_completed
from copy import deepcopy
import argparse,gzip,json,sys,time,traceback,hashlib,shutil
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import fixture_world,save
from na_pipeline.device import canonical_surface17_device
from na_pipeline.qec import build_factory15to1_protocol,physical_resource_requirements
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.runtime import EventSession,FiniteResourcePool,FactoryExecution,bind_physical_plan,make_scenario,run
from na_pipeline.validation.dag_physical import validate_physical_plan

def savegz(path,value):
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    temporary=Path(str(path)+'.tmp');temporary.write_bytes(gzip.compress(raw,mtime=0));temporary.replace(path)

def execute(name,out,resume=False):
    folder=Path(out)/name;folder.mkdir(parents=True,exist_ok=True);started=time.perf_counter()
    try:
        gate='TDG' if name=='TDG' else 'T';device=canonical_surface17_device()
        requirements=physical_resource_requirements({'patches':[{'patch_id':'live_data','initial_state':{'logical_basis':'Z','logical_value':0}}]})
        protocol=build_factory15to1_protocol(gate=gate);world=fixture_world(protocol['qubits'],device)
        if resume and (folder/'checkpoint.json.gz').is_file():
            controller=FactoryExecution.restore(device,json.loads(gzip.decompress((folder/'checkpoint.json.gz').read_bytes())))
            pool,session=controller.pool,controller.session
            phases=json.loads((folder/'checkpoint-progress.json').read_bytes())['phases']
            latest=json.loads((folder/'progress.json').read_bytes())['phases']
            if latest[:len(phases)]!=phases or len(controller.receipts)!=len(phases):
                raise ValueError('CHECKPOINT_PHASE_LIST_MISMATCH')
            if phases and abs(phases[-1]['end_us']-session.now_us)>1e-8:
                raise ValueError('CHECKPOINT_CLOCK_MISMATCH')
            recovery=folder/'recovery-before-resume';recovery.mkdir(exist_ok=True)
            for phase in latest[len(phases):]:
                source=folder/phase['artifact']
                if source.is_file():shutil.copyfile(source,recovery/source.name)
            save(folder/'resume-receipt.json',{'same_session':True,'run_id':session.run_id,'epoch':controller.protocol['epoch'],
                'checkpoint_phase_count':len(phases),'previous_completed_phase_count':len(latest),'resume_stage':controller.stage_id,
                'time_us':session.now_us,'checkpoint_byte_sha256':hashlib.sha256((folder/'checkpoint.json.gz').read_bytes()).hexdigest(),
                'preserved_suffix_artifacts':[p['artifact'] for p in latest[len(phases):]],'compiled_modules_rebuilt':False})
        else:
            session=EventSession(device,world,run_id='T044-canonical-'+name);pool=FiniteResourcePool(requirements,world)
            controller=FactoryExecution(protocol,pool,session,owner='gallery-'+name+'-epoch0');phases=[]
        save(folder/'device.json',device);save(folder/'initial-state.json',world)
        save(folder/'protocol.json',protocol);save(folder/'requirements.json',requirements)
        compiler=LogicalComponentCompiler(device,budget={'max_operations':100000,'max_wall_seconds':3600},module_directory=Path(out).parent/'compiled-modules')
        retry_started=name=='REJECT_RETRY' and controller.protocol['epoch']>0
        while True:
            if retry_started and phases and phases[-1]['epoch']==controller.protocol['epoch'] and phases[-1]['stage_id']=='initialize':break
            if controller.terminal:
                if name!='REJECT_RETRY' or retry_started:break
                if controller.terminal!='rejected' or controller.token is not None or pool.active:raise ValueError('REJECTION_DID_NOT_RELEASE_WITHOUT_TOKEN')
                protocol=build_factory15to1_protocol(gate='T',epoch=pool.next_epoch,request_id='retry_request')
                controller=FactoryExecution(protocol,pool,session,owner='gallery-retry-epoch1');retry_started=True
                save(folder/'retry-protocol.json',protocol)
            stage=controller.protocol['stages'][controller.stage_id];sid=controller.stage_id;epoch=controller.protocol['epoch']
            if stage['kind']=='lifecycle':
                controller.advance_lifecycle();continue
            status={'status':'running','component_id':name,'stage_id':sid,'epoch':epoch,'completed_stages':len(phases),'time_us':session.now_us,'phases':phases}
            save(folder/'status.json',status)
            print(json.dumps({k:v for k,v in status.items() if k!='phases'}),flush=True)
            graph=controller.next_graph();context=session.compilation_context(graph);start=session.now_us
            # All dependencies must have been built by the upstream component
            # job. T/T-dagger are pure downstream composition and execution.
            plan=compiler.compose_recipe(graph,session.snapshot()['world_state'],execution_context=context)
            atom=bind_physical_plan(plan,context)
            # Deterministic input scenario exercises S corrections; terminal checks
            # are explicitly configured to accept, or one bit rejects the candidate.
            value=0 if name=='REJECT_RETRY' or sid=='terminal_checks' or (gate=='TDG' and sid=='consume') else 1
            overrides={}
            if name=='REJECT_RETRY' and epoch==0 and sid=='terminal_checks':
                overrides[controller.protocol['acceptance_checks'][0]['result_ids'][0]]=1
            scenario=make_scenario(atom,value=value,overrides=overrides)
            # Independent bounded-window geometry/source/trace audit, in addition
            # to the continuous EventSession below. This audit is scoped per stage.
            local_scenario=make_scenario(plan['atom_program'],value=value,overrides=overrides)
            local_trace=run(plan['atom_program'],local_scenario,device)
            report=validate_physical_plan(plan,device,trace=local_trace)
            if not report['passed'] or report['failures'] or report['unverified']:raise ValueError({'validation':report})
            controller.validate_submission(plan,atom);session.submit(atom,scenario,expected_revision=context['revision']);session.advance()
            receipt=controller.commit_stage(plan,atom)
            aidset={a['id'] for a in atom['actions']}
            stage_trace={'schema_version':'component-stage-trace/0.1','execution_kind':'fake_event_run','sampled':False,
                         'events':[deepcopy(session.events[a]) for a in aidset],
                         'results':{r:deepcopy(session.results[r]) for r in graph['result_producers']},'run_id':session.run_id,
                         'final_state':session.state.export(session.now_us)}
            key=f'e{epoch}-{sid}'
            savegz(folder/(key+'.json.gz'),{'physical_plan':plan,'atom_program':atom,'scenario':scenario,'trace':stage_trace,'validation':report,'receipt':receipt})
            phases.append({'id':key,'stage_id':sid,'epoch':epoch,'start_us':start,'end_us':session.now_us,
                           'actions':len(atom['actions']),'physical_operations':len(graph['nodes']),'artifact':key+'.json.gz','validation_passed':True,
                           'module_count':len(plan['module_composition']['instances']),'module_hashes':list(dict.fromkeys(i['module_hash'] for i in plan['module_composition']['instances'])),
                           'module_stats':compiler.modules.stats})
            save(folder/'progress.json',{'phases':phases,'controller':controller.snapshot()})
            if len(phases)%8==0 or controller.terminal or retry_started:
                savegz(folder/'checkpoint.json.gz',controller.checkpoint())
                save(folder/'checkpoint-progress.json',{'phases':phases})
            if retry_started:break
        if name!='REJECT_RETRY' and (controller.terminal!='consumed' or controller.token['status']!='consumed' or pool.active):
            raise ValueError('FULL_PROTOCOL_DID_NOT_CONSUME_AND_RELEASE')
        # All no-loss identities are compared, not just participating live data.
        assert {a['qubit_id']:a['atom_id'] for a in world['atoms']}=={a['qubit_id']:a['atom_id'] for a in session.state.atoms.values()}
        save(folder/'controller.json',controller.snapshot());save(folder/'pool.json',pool.snapshot())
        summary={'status':'passed','component_id':name,'continuous_session':True,'physical_stage_count':len(phases),
                 'physical_operations':sum(p['physical_operations'] for p in phases),'action_count':sum(p['actions'] for p in phases),
                 'duration_us':session.now_us,'atom_count':len(world['atoms']),'phases':phases,'wall_seconds':time.perf_counter()-started,
                 'outcome':controller.terminal if name!='REJECT_RETRY' else 'rejected_cleaned_and_new_epoch_initialized',
                 'all_stage_checks_passed':True,'fake_scenario':True,'quantum_state_simulated':False,'hardware_executed':False,
                 'full_shor_executed':False,'user_visual_acceptance':'pending','module_stats':compiler.modules.stats,
                 'implementation_version':'neutral-modular/1','whole_stage_fallback':False}
        if any(compiler.modules.stats[k] for k in ('leaf_compile_count','placement_search_count','routing_search_count')):
            raise ValueError('TOP_LEVEL_PROTOCOL_RECOMPILED_LEAF')
        if any(p.get('module_stats',{}).get(k,0) for p in phases for k in ('leaf_compile_count','placement_search_count','routing_search_count')):
            raise ValueError('RESTORED_PREFIX_RECOMPILED_LEAF')
        summary['module_stats_current_process']=compiler.modules.stats
        summary['module_stats']={'leaf_compile_count':0,'placement_search_count':0,'routing_search_count':0,'connector_compile_count':0,
                                'bind_count':sum(p['module_count'] for p in phases),'cache_hit_count':sum(p['module_count'] for p in phases),
                                'composition_count':len(phases),'aggregation':'committed phase records including the restored prefix'}
        save(folder/'summary.json',summary);save(folder/'status.json',summary);return summary
    except Exception as e:
        error={'status':'failed','component_id':name,'error':str(e),'details':getattr(e,'details',None),'traceback':traceback.format_exc(),'wall_seconds':time.perf_counter()-started}
        save(folder/'status.json',error);print(json.dumps(error),flush=True);return error

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',default='artifacts/demos/logical-components-20261007/protocols');ap.add_argument('--workers',type=int,default=2)
    ap.add_argument('--components',nargs='*',default=['T','TDG','REJECT_RETRY']);ap.add_argument('--resume',action='store_true');a=ap.parse_args()
    out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True);results=[]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for f in as_completed([pool.submit(execute,n,str(out),a.resume) for n in a.components]):
            results.append(f.result());save(out/'status.json',{'results':results,'total':len(a.components)})
    if any(r['status']!='passed' for r in results):raise SystemExit(1)
if __name__=='__main__':main()
