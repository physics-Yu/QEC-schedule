"""Lightweight attribution only: inspect existing route records, no geometry rerun."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import gzip,json,time

from na_pipeline.validation.dag_factory import candidate_motion_witness

root=Path(__file__).resolve().parents[2];out=root/'knowledge/roles/R6/evidence/T605';started=time.perf_counter()
report_path=out/'factory-stage-validation-v1/report.json';report=json.loads(report_path.read_bytes())
path=root/'scripts/outputs/T704/server/20261006T152602272401Z-r4-factory-first-stage-205/result/examples/atom/t405/factory-stage-v1/physical-plan.json.gz'
with gzip.open(path,'rt',encoding='utf-8') as f:plan=json.load(f)
actions={a['id']:a for a in plan['atom_program']['actions']};failures=Counter(f['source_id'] for f in report['failures'] if f['code']=='ENOLA_ROUTE_MOTION_UNUSED');records=[];all_classes=Counter();still_bad=[]
for route in plan['enola']['route_decisions']:
    for index in route['selected_indices']:
        candidate=route['candidates'][index];witness=candidate_motion_witness(candidate,[actions[aid] for aid in route['action_ids']],actions[route['pulse_action_id']])
        all_classes[witness.get('classification',witness.get('reason'))]+=1
        if not witness['passed']:still_bad.append({'source_id':candidate['op_id'],'witness':witness})
        if candidate['op_id'] in failures:records.append({'source_id':candidate['op_id'],'original_candidate':candidate,'route_action_ids':route['action_ids'],'witness':witness})
assert Counter(r['source_id'] for r in records)==failures
result={'schema_version':'R6RouteFailureAttribution/0.1','scope':'original 25 candidate-to-motion matching failures only; original report and inputs unchanged','original_report_sha256':sha256(report_path.read_bytes()).hexdigest(),'physical_plan_byte_sha256':sha256(path.read_bytes()).hexdigest(),'original_failures':sum(failures.values()),'records':records,'all_selected_candidate_classes':dict(all_classes),'remaining_candidate_mapping_failures':still_bad,'seconds':time.perf_counter()-started,'recompiled':False,'search_calls':0,'full_stage_report_refreshed':False,'router_original_return_provenance':'unverified','full_program_passed':False}
(out/'factory-route-v1-attribution.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
print(json.dumps({k:v for k,v in result.items() if k!='records'},ensure_ascii=False))
