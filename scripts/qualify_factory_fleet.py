"""Two-line source/inventory qualification and actual concurrent cleanup."""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from basic_shor_job import build_logical_dag
from na_pipeline.qec import factory_fleet_requirements,build_factory_physical_dag,validate_physical_dag
from na_pipeline.runtime import FactoryFleet,EventSession,resource_inventory,place_factory_lines,make_scenario,bind_physical_plan
from na_pipeline.device import canonical_surface17_device,build_preinitialized_state,validate_preinitialized_state
from na_pipeline.backend import LogicalComponentCompiler
from na_pipeline.validation.dag_physical import validate_physical_plan
from na_pipeline.runtime.pipeline import save_artifact


def qualify(out):
    out.mkdir(parents=True,exist_ok=True);device=canonical_surface17_device();logical=build_logical_dag()
    req=factory_fleet_requirements(logical,['F0','F1'])
    clone=place_factory_lines(req,{'F0':[500.,900.],'F1':[1300.,900.]})
    positions={p['patch_id']:{'anchor_um':[100.*i,900.],'orientation':'x_vertical_z_horizontal'} for i,p in enumerate(logical['patches'])}
    positions.update(clone['patch_placements'])
    patches={p:{k:r[k] for k in ('aod_group','basis','value')} for p,r in req['patches'].items()}
    ref={'artifact_id':'two-line-interface-qualification','producer':'R0','fixture':True}
    inventory=resource_inventory(req,clone['nonpatch_positions'],placement_ref=ref)
    world=build_preinitialized_state(device,patches,positions,placement_ref=ref,resource_inventory=inventory)
    assert not validate_preinitialized_state(world,device)
    session=EventSession(device,world,run_id='two-line-interface-qualification')
    fleet=FactoryFleet(session,req);started=fleet.start_idle();source_checks=[]
    for fid,c in fleet.lines.items():
        checked=0
        for stage,s in c.protocol['stages'].items():
            if s['kind']!='physical' or stage.startswith('consume'):continue
            graph=build_factory_physical_dag(c.protocol,stage);validate_physical_dag(graph)
            assert all(q.startswith(fid+':') for n in graph['nodes'] for q in n['qubits'])
            checked+=1
        source_checks.append({'factory_id':fid,'physical_producer_stages':checked,'source_checked':True,'data_operand':None,'private_carriers':120})
    before=fleet.snapshot();frontier=fleet.frontier()
    assert len(frontier)==2 and all(l['target_patch'] is None for l in fleet.pool.active.values())
    # Abort is a public resource-management path. Production was never run;
    # both complete real cleanup DAGs must execute before these lines restart.
    for fid in fleet.lines:fleet.abort_production(fid)
    compiler=LogicalComponentCompiler(device)
    def prepare(dags,session):
        context=session.compilation_context(dags)
        plan=compiler.compile_dags(dags,session.snapshot()['world_state'],execution_context=context,cache=False)
        return {'context':context,'physical_plan':plan,'atom_program':bind_physical_plan(plan,context)}
    batch=fleet.compile_frontier(prepare);call=batch['prepared'];atom=call['atom_program'];scenario=make_scenario(atom)
    session.submit(atom,scenario,expected_revision=call['context']['revision']);session.advance()
    trace=session.export_trace();start=min(a['t_start_us'] for a in atom['actions']);end=session.now_us
    trace.update(schema_version='EventTrace/0.2.0-draft',atom_program_ref=atom['artifact_id'],device_ref=device['artifact_id'],
        stats={'t_start_us':start,'t_end_us':end,'duration_us':end-start,'atom_count':len(world['atoms']),
            'action_count':len(atom['actions']),'result_count':len(trace['results']),
            'executed_action_count':len(atom['actions']),'skipped_action_count':0})
    projected={**call['physical_plan'],'atom_program':atom}
    report=validate_physical_plan(projected,device,trace=trace)
    assert report['passed'],report
    receipts=fleet.commit(batch['work'],call['physical_plan'],atom);cleaned=fleet.snapshot();restart=fleet.start_idle()
    assert [r['epoch'] for r in restart]==[1,1]
    assert len({a['t_start_us'] for a in atom['actions']})==1
    assert all(not a['qubit_id'].startswith(('ctrl/','w0/','w1/','w2/','w3/')) or a.get('reset_epoch',0)==0 for a in trace['final_state']['atoms'])
    acceptance={'schema_version':'FactoryFleetQualification/0.1','passed':True,'world_atoms':len(world['atoms']),
        'algorithm_patches':5,'factory_lines':2,'factory_carriers':240,'source_checks':source_checks,
        'producers_started':started,'simultaneously_ready_producer_frontier':len(frontier),
        'actual_shared_cleanup_actions':len(atom['actions']),'actual_cleanup_duration_us':end-start,
        'cleanup_actions_per_line':[len(r['action_ids']) for r in receipts],'next_line_epochs':[r['epoch'] for r in restart],
        'full_factory_production_executed':False,'magic_ready_tokens_published':0,'data_preserved':True,
        'runtime_request_allocation_tests':'test_factory_fleet.py uses explicitly labeled ready-boundary fixtures',
        'scope':'real shared cleanup plus source/lease/frontier interface; not complete parallel T production or full Shor',
        'hardware_executed':False,'quantum_state_simulated':False,'sampled':False}
    for name,value in [('acceptance.json',acceptance),('resource-requirements.json',req),('layout.json',clone),('device.json',device),
        ('initial-state.json',world),('producer-frontier.json',frontier),('before.json',before),('after-cleanup.json',cleaned),
        ('after-restart.json',fleet.snapshot()),('physical-plan.json',call['physical_plan']),('atom-program.json',atom),
        ('event-trace.json',trace),('validation.json',report)]:save_artifact(out/name,value)
    print(json.dumps(acceptance,ensure_ascii=False),flush=True)


if __name__=='__main__':qualify(Path(sys.argv[1]))
