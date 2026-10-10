"""Unprofiled bounded component binding times, not an algorithm execution."""
from pathlib import Path
import json,sys,time,statistics
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from basic_shor_job import build_world
from na_pipeline.runtime import LogicalGateLibrary,EventSession


def main(out,source):
    world=build_world();store=out/('plain-connections-'+str(time.time_ns()))
    lib=LogicalGateLibrary(world['device'],connection_directory=store,budget={'max_operations':100000,'max_wall_seconds':120})
    cases=('CX','H','SE','S','factory.consume','factory.finish_04');rows=[]
    for name in cases:
        row=lib.import_component(name,source/name)
        operands={p:'w2' if p=='control' else 'w0' if p=='target' else 'ctrl' if p in ('block','live_data') else
                  p+':join_probe' if '$atom' in spec['sites'] else p for p,spec in row['operands'].items()}
        session=EventSession(world['device'],world['initial_state'],run_id='isolated-component-benchmark:'+name)
        graph=lib.source(name,operands=operands,invocation_id='bench-source:'+name)
        record={'component':name,'world_atoms':205,'warm_runs':[],'scope':'isolated static component at declared input; no Shor branch, event, token or factory execution'}
        for repetition in range(4):
            start=time.perf_counter()
            try:
                with (patch('na_pipeline.backend.compiled_modules.module_graph',side_effect=AssertionError('internal rebuild')),
                      patch('na_pipeline.backend.frontier_store.select_frontier',side_effect=AssertionError('batch search'))):
                    call=lib.prepare_dags(name,session,graph,allow_connection_planning=repetition==0)
                elapsed=time.perf_counter()-start
                receipt=call['physical_plan']['parametric_component_instance']
                if repetition:
                    assert all(receipt['connection_work'][k]==0 for k in ('legacy_fixed_fragment_materializations','placement_candidates','routing_calls'))
                    record['warm_runs'].append(elapsed)
                else:record.update(cold_seconds=elapsed,cold_connection_work=receipt['connection_work'],actions=len(call['atom_program']['actions']),modules=len(call['physical_plan']['module_composition']['instances']))
                print(json.dumps({'component':name,'run':repetition,'seconds':elapsed}),flush=True)
            except Exception as e:
                record.update(error=str(e),error_code=getattr(e,'code',type(e).__name__));print(json.dumps(record),flush=True);break
        if record['warm_runs']:record['warm_median_seconds']=statistics.median(record['warm_runs'])
        rows.append(record)
        (out/'unprofiled-performance.json').write_text(json.dumps({'schema_version':'BoundedComponentTiming/0.1','cProfile':False,
            'case_count':len(rows),'measurements':rows,'no_actions_submitted':True,'full_factory_started':False},ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main(Path(sys.argv[1]),Path(sys.argv[2]))
