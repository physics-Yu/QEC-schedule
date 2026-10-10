"""Actual live-frame continuation examples, including a full same-session T."""
from pathlib import Path
from copy import deepcopy
import argparse, gzip, json, shutil, sys, time, os, hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from component_gallery_job import fixture_world, save
from na_pipeline.device import canonical_surface17_device
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.qec import build_factory15to1_protocol, physical_resource_requirements
from na_pipeline.runtime import EventSession, LogicalFrameSession, FactoryExecution, FiniteResourcePool, bind_physical_plan, make_scenario, run
from na_pipeline.validation.dag_physical import validate_physical_plan


def run_case(key,sequence,out):
    started=time.perf_counter();device=canonical_surface17_device()
    store=out/'compiled-modules'
    if os.name=='nt':store=Path('\\\\?\\'+str(store.resolve()))
    compiler=LogicalComponentCompiler(device,module_directory=store,budget={'max_operations':100000,'max_wall_seconds':1800})
    protocol=build_factory15to1_protocol()
    if key=='H_THEN_T':qubits=protocol['qubits']
    else:
        names=('A','B') if key in ('H_THEN_CZ','CZ_THEN_CX_SE') else ('A',)
        qubits=[{'id':p+'/'+q,'aod_group':'data','role':'data' if q[0]=='d' else 'syndrome'}
                for p in names for q in [f'd{i}' for i in range(9)]+[f'{c}{i}' for c in 'xz' for i in range(4)]]
    world=fixture_world(qubits,device,orientations={'B':'canonical_rot90'} if key=='CZ_THEN_CX_SE' else None)
    session=EventSession(device,world,run_id='frame-preview-'+key)
    live=LogicalFrameSession(compiler,session);phases=[];controller_records=[]
    folder=out/key;folder.mkdir(parents=True,exist_ok=True)

    def adaptive(gate,data,session,compiler):
        requirements=physical_resource_requirements({'patches':[{'patch_id':data,'initial_state':{'logical_basis':'Z','logical_value':0}}]})
        pool=FiniteResourcePool(requirements,world)
        protocol=build_factory15to1_protocol(gate=gate,data_block_id=data)
        controller=FactoryExecution(protocol,pool,session,owner='frame-preview')
        while not controller.terminal:
            sid=controller.stage_id;stage=protocol['stages'][sid]
            if stage['kind']=='lifecycle':controller.advance_lifecycle();continue
            graph=controller.next_graph();start=session.now_us;current=session.snapshot()['world_state']
            compiler.build_dependencies(graph,current)
            context=session.compilation_context(graph)
            plan=compiler.compose_recipe(graph,current,execution_context=context)
            atom=bind_physical_plan(plan,context)
            value=0 if sid=='terminal_checks' else 1
            local_trace=run(plan['atom_program'],make_scenario(plan['atom_program'],value=value),device)
            report=validate_physical_plan(plan,device,trace=local_trace)
            if not report['passed'] or report['unverified']:raise ValueError(report)
            scenario=make_scenario(atom,value=value)
            controller.validate_submission(plan,atom);session.submit(atom,scenario,expected_revision=context['revision']);session.advance()
            receipt=controller.commit_stage(plan,atom)
            live.physical_plans.append({'component_id':'T:'+sid,'physical_plan':plan,'atom_program':atom,'scenario':scenario,'validation':report,'receipt':receipt})
            phases.append({'id':sid,'stage_id':sid,'start_us':start,'end_us':session.now_us,'label':'H→T · '+sid,'note':'同一帧与事件会话'})
            save(folder/'progress.json',{'stage_id':sid,'time_us':session.now_us,'phases':phases})
        if controller.terminal!='consumed' or controller.token['status']!='consumed' or pool.active:raise ValueError('FRAME_T_NOT_CONSUMED')
        controller_records.append(controller.snapshot())
        return {'run_id':session.run_id,'token_status':controller.token['status'],'end_us':session.now_us,
                'same_carrier':True,'protocol_id':protocol['artifact_id'],'stage_count':len(controller.receipts)}

    for gate,blocks in sequence:
        live.run_gate(gate,blocks,adaptive_runner=adaptive)
    entries=[];audits=[]
    for item in live.physical_plans:
        atom=item['atom_program'];plan=item['physical_plan']
        # Validate every ordinary prefix as well as the adaptive stages.
        report=item.get('validation')
        if report is None:
            local=run(plan['atom_program'],make_scenario(plan['atom_program']),device)
            report=validate_physical_plan(plan,device,trace=local)
        if not report['passed'] or report['unverified']:raise ValueError(report)
        aids={a['id'] for a in atom['actions']}
        trace={'events':[deepcopy(session.events[a]) for a in aids],
               'results':{r:deepcopy(record) for r,record in session.results.items() if record['action_id'] in aids},
               'final_state':session.state.export(session.now_us)}
        entries.append({'component_id':item['component_id'],'atom_program':atom,'trace':trace,'physical_plan':plan})
        audits.append({'component_id':item['component_id'],'passed':True,'actions':len(atom['actions'])})
    data={'device':device,'initial_state':world,'frame_context':live.snapshot(),'entries':entries,
          'phases':phases,'controller_records':controller_records,'audits':audits,
          'final_world':session.snapshot()['world_state']}
    raw=json.dumps(data,ensure_ascii=False,separators=(',',':')).encode()
    (folder/'frame-session.json.gz').write_bytes(gzip.compress(raw,mtime=0))
    summary={'id':key,'status':'passed','duration_us':session.now_us,'atom_count':len(world['atoms']),
             'action_count':sum(x['actions'] for x in audits),'control_events':len(live.events),
             'wall_seconds':time.perf_counter()-started,'module_stats':compiler.modules.stats,
             'frame_materialization_explicit':True,'user_visual_acceptance':'pending'}
    save(folder/'summary.json',summary);print(json.dumps(summary),flush=True)
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--module-source');p.add_argument('--module-manifest');p.add_argument('--small-only',action='store_true');a=p.parse_args()
    out=ROOT/a.out;out.mkdir(parents=True,exist_ok=True)
    if a.module_source:
        source=Path(a.module_source).resolve()
        if not source.is_relative_to(Path('/home/yyq/na-platform-simulation/R7/T704')):raise ValueError('MODULE_SOURCE_SCOPE')
        dest=out/'compiled-modules';dest.mkdir(exist_ok=True)
        manifest=json.loads((ROOT/a.module_manifest).read_bytes())
        if manifest['source']!=str(source):raise ValueError('MODULE_SOURCE_CHANGED')
        for name,sha in manifest['files'].items():
            if Path(name).name!=name:raise ValueError('MODULE_PATH_SCOPE')
            content=(source/name).read_bytes()
            if hashlib.sha256(content).hexdigest()!=sha:raise ValueError('MODULE_IMPORT_HASH')
            (dest/name).write_bytes(content)
        save(out/'module-import.json',manifest)
    cases=[('H_VIRTUAL',[('H',['A'])]),('H_THEN_H',[('H',['A']),('H',['A'])]),
           ('H_THEN_Z',[('H',['A']),('MEASURE_Z',['A'])]),('H_THEN_SE',[('H',['A']),('SE',['A'])]),
           ('H_THEN_CZ',[('H',['A']),('CZ',['A','B'])]),
           ('CZ_THEN_CX_SE',[('CZ',['A','B']),('CX',['A','B']),('SE',['B']),('MEASURE_Z',['B'])])]
    if not a.small_only:cases.append(('H_THEN_T',[('H',['live_data']),('T',['live_data'])]))
    results=[]
    for key,sequence in cases:
        results.append(run_case(key,sequence,out));save(out/'status.json',{'status':'running','components':results})
    save(out/'status.json',{'status':'passed','components':results,'full_shor_executed':False})


if __name__=='__main__':main()
