"""Bounded source compatibility and compile/bind timing audit; no full run."""
from pathlib import Path
from collections import Counter
from copy import deepcopy
from unittest.mock import patch
import argparse,cProfile,json,sys,time,hashlib,platform,pstats,io,ast

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from basic_shor_job import build_world
from na_pipeline.qec import build_physical_dag_bundle,materialize_physical_node,materialize_factory_protocol,build_factory_physical_dag
from na_pipeline.runtime import LogicalGateLibrary,EventSession
from na_pipeline.runtime.component_schedule import schedule_signature
from na_pipeline.backend.physical_strategy import PhysicalStrategyLibrary
from na_pipeline.backend.enola_kernel import digest


def save(out,name,value):
    (out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def audit(out,source,measure=True):
    out.mkdir(parents=True,exist_ok=True)
    timings={};started=time.perf_counter();world=build_world();timings['build_world']=time.perf_counter()-started
    started=time.perf_counter();bundle=build_physical_dag_bundle(world['logical_dag']);timings['logical_to_shared_physical_bundle']=time.perf_counter()-started
    connection_dir=out/('connections-'+str(time.time_ns()))
    lib=LogicalGateLibrary(world['device'],connection_directory=connection_dir,budget={'max_wall_seconds':120,'max_operations':100000})
    nodes=world['logical_dag']['nodes'];name_for=lambda n:{'MEASURE':'MEASURE_Z','RESET':'RESET_Z'}.get(n['operation'],n['operation'])
    needed={name_for(n) for n in nodes if n['operation'] not in ('T','TDG')}
    needed.update(p.name for p in source.iterdir() if p.name.startswith('factory.') and (p/'physical-plan.json').exists())
    started=time.perf_counter()
    for name in sorted(needed):lib.import_component(name,source/name)
    timings['import_qualified_templates']=time.perf_counter()-started
    print(json.dumps({'phase':'import','templates':len(needed),'timings':timings}),flush=True)
    checks=[];families={};graphs={};started=time.perf_counter()
    for n in nodes:
        if n['operation'] in ('T','TDG'):continue
        name=name_for(n);dag=materialize_physical_node(bundle,n['id'])
        key=schedule_signature([dag])[0];families.setdefault(name,set()).add(key)
        item={'node_id':n['id'],'operation':n['operation'],'component':name,'guarded':n['condition'] is not None,
              'signature':key,'template_signature':lib._get(name).signature}
        try:
            lib._get(name).bind_graph([dag]);item['compatible']=True
            if not dag['external_reads'] and dag['execution_guard'] is None:graphs.setdefault(name,dag)
        except Exception as e:item.update(compatible=False,error_code=getattr(e,'code',type(e).__name__),error=str(e))
        checks.append(item)
    timings['all_static_node_binding_checks']=time.perf_counter()-started
    factory=[];protocols={}
    for gate in ('T','TDG'):
        node=next(n for n in nodes if n['operation']==gate)
        started=time.perf_counter();protocol=materialize_factory_protocol(bundle,node['id'],epoch=0)
        timings['materialize_'+gate+'_protocol']=time.perf_counter()-started;protocols[gate]=protocol
        for stage_id,stage in protocol['stages'].items():
            if stage['kind']!='physical':continue
            name='factory.consume_correction_tdg' if gate=='TDG' and stage_id=='consume_correction' else 'factory.'+stage_id
            dag=build_factory_physical_dag(protocol,stage_id)
            item={'gate':gate,'stage':stage_id,'component':name,'target':protocol['data_block_id']}
            try:lib._get(name).bind_graph([dag]);item['compatible']=True
            except Exception as e:item.update(compatible=False,error_code=getattr(e,'code',type(e).__name__),error=str(e))
            factory.append(item)
            if gate=='T':graphs.setdefault(name,dag)
    compatibility={'logical_nodes':len(nodes),'operation_counts':dict(Counter(n['operation'] for n in nodes)),
        'static_total':len(checks),'static_compatible':sum(i['compatible'] for i in checks),
        'static_failures':dict(Counter((i['component']+':'+i['error_code']) for i in checks if not i['compatible'])),
        'unique_source_signatures':{k:len(v) for k,v in families.items()},
        'factory_stage_total':len(factory),'factory_stage_compatible':sum(i['compatible'] for i in factory),
        'factory_failures':[i for i in factory if not i['compatible']],'all_static_checks':checks,'factory_checks':factory}
    save(out,'source-compatibility.json',compatibility)
    print(json.dumps({k:v for k,v in compatibility.items() if k not in ('all_static_checks','factory_checks')},ensure_ascii=False),flush=True)
    driver_tree=ast.parse((ROOT/'src/na_pipeline/runtime/pipeline.py').read_text(encoding='utf-8'))
    defs={n.name:n for n in ast.walk(driver_tree) if isinstance(n,ast.FunctionDef)}
    calls=lambda name:{ast.unparse(n.func) for n in ast.walk(defs[name]) if isinstance(n,ast.Call)}
    gate_connected='self.compiler.prepare_dags' in calls('_plan')
    factory_connected='FactoryDataInterface' in calls('_factory_step')
    cli_tree=ast.parse((ROOT/'scripts/basic_shor_job.py').read_text(encoding='utf-8'))
    defaults=[k.value.value for n in ast.walk(cli_tree) if isinstance(n,ast.Call) and
        any(isinstance(a,ast.Constant) and a.value=='--compiler-interface' for a in n.args)
        for k in n.keywords if k.arg=='default' and isinstance(k.value,ast.Constant)]
    wiring={'driver_compiler':'LogicalGateLibrary' if defaults==['gate-ports'] else 'ComponentRecipeLibrary',
        'new_gate_api_connected':gate_connected,'new_factory_output_port_connected':factory_connected,
        'driver_old_protocol_methods':all(hasattr(PhysicalStrategyLibrary,n) for n in ('get_or_compile','bind')),
        'new_library_old_protocol_methods':{n:hasattr(lib,n) for n in ('get_or_compile','bind')},
        'checked_files':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in
            ['scripts/basic_shor_job.py','src/na_pipeline/runtime/pipeline.py','src/na_pipeline/runtime/component_pipeline.py','src/na_pipeline/runtime/component_recipe.py']}}
    save(out,'driver-wiring.json',wiring)
    performance=[]
    if measure:
        for name in ('CX','H','SE','S','factory.consume','factory.finish_04'):
            # This is preparation only. No actions are submitted and no ready
            # token is manufactured. Each cold/warm call sees the full205world.
            graph=graphs.get(name)
            if graph is None:performance.append({'component':name,'not_measured':'no compatible unguarded representative'});continue
            session=EventSession(world['device'],world['initial_state'],run_id='compile-only-audit:'+name)
            for mode in ('cold_connection','warm_connection'):
                before=lib.adapter.connections.stats;prof=cProfile.Profile();started=time.perf_counter()
                try:
                    with (patch('na_pipeline.backend.compiled_modules.module_graph',side_effect=AssertionError('internal graph recomposed')),
                          patch('na_pipeline.backend.frontier_store.select_frontier',side_effect=AssertionError('internal batch selection'))):
                        prof.enable();prepared=lib.prepare_dags(name,session,graph,allow_connection_planning=mode=='cold_connection');prof.disable()
                    row={'component':name,'mode':mode,'wall_seconds':time.perf_counter()-started,'passed':True,
                         'physical_ops':sum(len(d['nodes']) for d in prepared['physical_plan']['physical_dags']),
                         'native_actions':len(prepared['atom_program']['actions']),'world_atoms':len(world['initial_state']['atoms']),
                         'internal_modules':len(prepared['physical_plan']['module_composition']['dependency_graph']['modules']),
                         'receipt':prepared['physical_plan']['parametric_component_instance']}
                    buffer=io.StringIO();pstats.Stats(prof,stream=buffer).strip_dirs().sort_stats('cumulative').print_stats(22)
                    (out/(name+'-'+mode+'-profile.txt')).write_text(buffer.getvalue(),encoding='utf-8')
                except Exception as e:
                    prof.disable();row={'component':name,'mode':mode,'wall_seconds':time.perf_counter()-started,
                        'passed':False,'error':str(e),'error_code':getattr(e,'code',type(e).__name__)}
                after=lib.adapter.connections.stats
                row['counter_delta']={k:after[k]-before[k] for k in before}
                performance.append(row);save(out,'performance.json',performance);print(json.dumps(row,ensure_ascii=False),flush=True)
                if not row['passed']:break
    result={'schema_version':'ShorInterfaceAudit/0.1','scope':'N15 a2 d3 Surface17, compile interfaces only',
        'timings_seconds':timings,'python':sys.version,'platform':platform.platform(),
        'logical_nodes':len(nodes),'source_compatible_static':sum(i['compatible'] for i in checks),
        'static_total':len(checks),'factory_stage_compatible':sum(i['compatible'] for i in factory),
        'factory_stage_total':len(factory),'driver_wiring':wiring,'performance':performance,
        'full_shor_compiled':False,'factory_started':False,'new_server_job_dispatched':False,
        'measurement_kind':'cProfile-instrumented bounded local prepare_dags; not end-to-end wall-time prediction'}
    save(out,'audit.json',result)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--no-measure',action='store_true')
    a=p.parse_args();audit(a.out,a.source,measure=not a.no_measure)
