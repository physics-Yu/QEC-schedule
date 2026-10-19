"""R6 real R1/R2/R4 entry, full logical source and observed patch-placement slice."""
from hashlib import sha256
from pathlib import Path
import gzip,json,sys,time,traceback

from na_pipeline.device import preinitialized_device
from na_pipeline.frontend import build_logical_dag,build_patch_dag_example
from na_pipeline.backend import place_patches
from na_pipeline.validation import validate_logical_dag_source,validate_patch_placement,validate_preinitialized_entry
from na_pipeline.validation.dag_core import DAGAudit,inspect_graph
from na_pipeline.validation.dag_observer import EnolaStageObserver

root=Path(__file__).resolve().parents[2]; out=root/'knowledge/roles/R6/evidence/T605'; out.mkdir(parents=True,exist_ok=True)
def write(name,value): (out/name).write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))


def main():
    started=time.perf_counter(); paths=list(root.glob('src/na_pipeline/**/*.py'))
    source_before={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in paths}
    try:
        device=preinitialized_device(); pin=json.loads((root/'third_party/enola/pin.json').read_bytes())
        dag=build_logical_dag(); report=validate_logical_dag_source(dag)
        write('logical-source-report.json',report)
        print(json.dumps({'stage':'full_logical_source','passed':report['passed'],'failures':report['failures'][:4],'unverified':report['unverified'],'metrics':report['metrics']},ensure_ascii=False),flush=True)
        example=build_patch_dag_example(); scratch=DAGAudit('projection',{}); graph=inspect_graph(scratch,example['nodes'],example['edges']); levels={}
        for nid in graph.order: levels[nid]=max((levels[p]+1 for p in graph.predecessors[nid]),default=0)
        patches={p['patch_id']:{'aod_group':'data','basis':p['initial_state']['logical_basis'],'value':p['initial_state']['logical_value']} for p in example['patches']}
        roles={'CX':('control','target'),'CZ':('left','right')}
        interactions=[{'node_id':n['id'],'patch_operands':[n['patch_operands'][r] for r in roles[n['operation']]],'layer':levels[n['id']]} for n in example['nodes'] if n['operation'] in roles]
        placements=[]; observations=[]; placement_reports=[]
        for seed in (0,7):
            with EnolaStageObserver(root/pin['source_root']) as watcher:
                placement=place_patches(patches,interactions,device,seed=seed,budget={'max_wall_seconds':180.})
            observed=watcher.evidence()
            checked=validate_patch_placement(placement,device,example,observation=observed,pin=pin)
            entry=validate_preinitialized_entry(placement['initial_state'],device)
            placements.append(placement); observations.append(observed); placement_reports.append(checked)
            write(f'placement-{seed}-report.json',checked); write(f'entry-{seed}-report.json',entry)
            print(json.dumps({'stage':'placement','seed':seed,'passed':checked['passed'],'entry_passed':entry['passed'],'failures':checked['failures'][:5],'unverified':checked['unverified'],'metrics':checked['metrics']},ensure_ascii=False),flush=True)
        bundle={'device':device,'logical_dag':dag,'example_dag':example,'placements':placements,'observations':observations,'pin':pin}
        with gzip.open(out/'frontend-placement-inputs.json.gz','wb') as target: target.write(json.dumps(bundle,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
        after={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in paths}
        summary={'scope':'real_R1_R2_R4_static_frontend_and_patch_placement_only','full_program_passed':False,'logical_source_passed':report['passed'],'placement_passed':all(r['passed'] for r in placement_reports),'seconds':time.perf_counter()-started,'python':sys.version,'executable':sys.executable,'fixture':False,'source_before':source_before,'source_after':after,'changed_files':[p for p in source_before if source_before[p]!=after[p]],'input_sha256':sha256((out/'frontend-placement-inputs.json.gz').read_bytes()).hexdigest(),'pending':['R3 PhysicalDAG and semantic operation summaries','R4 physical DAG compile and D02/D03 motion examples','R5 ready-set/session integration','factory/T lifecycle','all-eight-round physical Shor and same-artifact postprocessing'],'quantum_state_simulated':False,'hardware_executed':False}
        write('frontend-placement-summary.json',summary)
        return 0 if summary['placement_passed'] and not report['failures'] else 1
    except Exception as exc:
        failure={'status':'incomplete','error':str(exc),'traceback':traceback.format_exc(),'seconds':time.perf_counter()-started,'no_fallback_used':True}
        write('frontend-placement-failure.json',failure); print(json.dumps(failure,ensure_ascii=False),flush=True); return 1


if __name__=='__main__': raise SystemExit(main())
