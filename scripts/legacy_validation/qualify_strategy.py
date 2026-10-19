"""R6 independent T604 production-path observation and artifact capture.

Uses public R1/R2/R3/R4/R5 APIs. Output lives only in the R6 ownership directory.
No source patching, fallback backend, or ideal execution stand-in is used.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import gzip,json,sys,time,traceback
from importlib.metadata import version
from pathlib import Path

from na_pipeline.device import grouped_device,group_layout
from na_pipeline.frontend import build_t000_program,iter_encoded_calls
from na_pipeline.qec import build_logical_primitive
from na_pipeline.backend import StrategyLibrary
from na_pipeline.runtime import LogicalBlockController,make_scenario
from na_pipeline.validation import validate_strategy,validate_strategy_run
from na_pipeline.validation.strategy_observer import EnolaCallObserver

root=Path(__file__).resolve().parents[2]
out=root/'knowledge/roles/R6/evidence/T604'; out.mkdir(parents=True,exist_ok=True)
def write(name,value):
    (out/name).write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))

def world_for(device,blocks):
    world={'atoms':[],'slm_traps':[],'aod_rows':[],'aod_columns':[],'time_us':0.}
    for index,block in enumerate(blocks):
        lid=block['logical_id']
        for profile in ('patch_initialization','patch_home','ancilla_readout'):
            layout=group_layout(device,profile,offset_um=(100.*index,0.))
            for slot,definition in layout['slots'].items():
                atom_id=f'atom:{lid}/{slot}'; trap_id=f'site:{lid}:{profile}:{slot}'
                world['slm_traps'].append({'trap_id':trap_id,'position_um':definition['position_um'],'zone_id':layout['zone_id'],'occupant':atom_id if profile=='patch_initialization' else None})
                if profile=='patch_initialization': world['atoms'].append({'atom_id':atom_id,'qubit_id':f'{lid}/{slot}','position_um':definition['position_um'],'carrier':'SLM','trap_id':trap_id,'aod_group':'data','row_id':None,'column_id':None})
    return world


def main():
    pin=json.loads((root/'third_party/enola/pin.json').read_text(encoding='utf-8'))
    source=root/pin['source_root']/'enola/router/router_mis.py'
    device=grouped_device(); encoded=build_t000_program(rounds=3)
    lib=StrategyLibrary(device); strategies={}; observations={}; static_reports={}; stages=[]
    sources=[*root.glob('src/na_pipeline/**/*.py'),Path(__file__).resolve()]
    source_before={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in sources}
    started=time.perf_counter(); phase='compile'
    try:
        for operation,params in [('prepare',{'state':'+'}),('prepare',{'state':'0'}),('syndrome_round',{}),('logical_cx',{})]:
            t=time.perf_counter(); physical=build_logical_primitive(operation,params=params)
            with EnolaCallObserver(source) as observer: strategy=lib.get_or_compile(physical)
            key=strategy['strategy_hash']; strategies[strategy['strategy_id']]=strategy; observations[key]=observer.evidence()
            stages.append({'stage':f'compile:{operation}:{params}','seconds':time.perf_counter()-t,'upstream_calls':len(observer.records)})
            print(json.dumps(stages[-1]),flush=True)
        evidence={'pin':pin,'observations':observations,'binding_observations':{}}
        phase='static_validation'
        for strategy in strategies.values():
            r=validate_strategy(strategy,device,enola_evidence=evidence); static_reports[strategy['strategy_id']]=r
            print(json.dumps({'stage':'static','operation':strategy['body']['strategy_contract']['operation'],'passed':r['passed'],'failure_codes':dict(Counter(f['code'] for f in r['failures']))},ensure_ascii=False),flush=True)
        phase='controller_binding'
        world=world_for(device,encoded['blocks'])
        class ObservedController(LogicalBlockController):
            # Instrument the public boundary; the producer schedules/binds the
            # original encoded program and owns every returned action/alias.
            def queue_call(self,*args,**kwargs):
                call_started=time.perf_counter()
                with EnolaCallObserver(source) as observer:
                    instance=super().queue_call(*args,**kwargs)
                cid=instance['call_id']; evidence['binding_observations'][cid]=observer.evidence()
                stages.append({'stage':'bind','call_id':cid,'seconds':time.perf_counter()-call_started,'start_us':instance['start_us'],'end_us':instance['end_us'],'composition_retries':len(instance['composition_retries']),'upstream_calls':len(observer.records)})
                print(json.dumps(stages[-1]),flush=True)
                return instance
        controller=ObservedController(device,world,run_id='R6-T604-T000',strategy_library=lib,binding_retry_budget=4096)
        slots=list(device['grouped_profile']['layouts']['patch_home']['slots'])
        for index,block in enumerate(encoded['blocks']):
            lid=block['logical_id']; controller.register_block(lid,qubits={slot:f'{lid}/{slot}' for slot in slots},data_slots=[f'd{i}' for i in range(9)],code_profile=block['code_profile'],layout_profile=block['layout_profile_ref'],offset_um=(100.*index,0.))
        controller.queue_encoded_program(encoded)
        phase='runtime'
        t=time.perf_counter()
        scenario=make_scenario(controller.pending_program(),value=1)
        run=controller.execute_pending(scenario)
        stages.append({'stage':'runtime','seconds':time.perf_counter()-t})
        phase='run_validation'
        t=time.perf_counter()
        report=validate_strategy_run(run,device,strategies=strategies,enola_evidence=evidence)
        stages.append({'stage':'run_validation','seconds':time.perf_counter()-t})
        bundle={'device':device,'strategies':strategies,'enola_evidence':evidence,'run':run,'scenario':scenario,'static_reports':static_reports,'run_report':report}
        with gzip.open(out/'inputs.json.gz','wb') as saved: saved.write(json.dumps(bundle,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8'))
        write('run-report.json',report)
        for index,r in enumerate(static_reports.values()): write(f'strategy-report-{index}.json',r)
        source_after={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in sources}
        summary={'status':'completed_checks','passed':report['passed'],'static_passed':all(r['passed'] for r in static_reports.values()),'seconds':time.perf_counter()-started,'stages':stages,'failure_codes':dict(Counter(f['code'] for f in report['failures'])),'unverified':report['unverified'],'instance_count':len(run['instances']),'library_stats':lib.stats,'input_archive_sha256':sha256((out/'inputs.json.gz').read_bytes()).hexdigest(),'python':sys.version,'executable':sys.executable,'dependencies':{n:version(n) for n in ('networkx','numpy','rustworkx')},'source_before':source_before,'source_after':source_after,'source_unchanged':source_before==source_after,'changed_source_files':[p for p in source_before if source_before[p]!=source_after[p]],'controller_entrypoint':'queue_encoded_program','binding_retry_budget':4096,'fixture':False,'quantum_state_simulated':False,'hardware_executed':False}
        write('summary.json',summary); print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
        return 0 if report['passed'] else 1
    except Exception as exc:
        failure={'status':'incomplete','phase':phase,'error_type':type(exc).__name__,'error':str(exc),'seconds':time.perf_counter()-started,'stages':stages,'traceback':traceback.format_exc(),'fixture':False,'no_fallback_used':True}
        write('failure.json',failure)
        partial={'device':device,'strategies':strategies,'observations':observations,'static_reports':static_reports}
        with gzip.open(out/'partial-inputs.json.gz','wb') as saved: saved.write(json.dumps(partial,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        print(json.dumps(failure,ensure_ascii=False,indent=2),flush=True)
        return 1


if __name__=='__main__': raise SystemExit(main())
