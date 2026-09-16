"""Compile and independently replay the complete ordered Studio QEC demo."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import json,time
from pathlib import Path
from neutral_atom_app.visualization.studio_config import demo_input
from neutral_atom_app.visualization.workbench import build_inputs,initialize_input,recording_payload
from neutral_atom_app.control import configured_strategy
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.visualization.viewer import write_html
from neutral_atom_experiments.surface_qec import summarize
from neutral_atom_env.replay.serializer import primitive

import argparse
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default='artifacts/ordered-workbench-qec')
out=Path(parser.parse_args().output);out.mkdir(parents=True,exist_ok=True)
v,c,p,m=build_inputs(demo_input('ordered-qec-ghz2'));env=NeutralAtomEnv(initialize_input(v,c,p,m))
initial=env.snapshot();rec=VisualRecorder(env.state);plans=[];submit=env.submit
(out/'input.json').write_text(json.dumps(v,ensure_ascii=False),encoding='utf-8')
def capture(plan):
    submit(plan);plans.append(plan)
    print(json.dumps({'plans':len(plans),'completed':env.state.metrics()['completed_gate_count']}),flush=True)
env.submit=capture;start=time.perf_counter()
r=configured_strategy(v).run(env,on_event=lambda s,e:rec.observe(s,e))
report={'status':r.status,'metrics':env.state.metrics(),'compile_seconds':time.perf_counter()-start,'quantum':summarize(env.state),'diagnostics':primitive(r.diagnostics)}
recording=recording_payload(rec,v)
write_html(recording,out/'animation.html')
(out/'recording.json').write_text(json.dumps(recording,ensure_ascii=False),encoding='utf-8')
(out/'checkpoint.json').write_text(env.snapshot(),encoding='utf-8')
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
assert r.status=='completed',report
assert report['quantum']['verified_logical_ghz2'] and report['quantum']['measurement_protocol_complete']
replay=NeutralAtomEnv.restore(initial);start=time.perf_counter()
for i,plan in enumerate(plans):
    replay.submit(plan);replay.run()
    if i%10==0:print(json.dumps({'replayed':i+1,'total':len(plans)}),flush=True)
report.update(replay_equal=replay.snapshot()==env.snapshot(),replay_seconds=time.perf_counter()-start,plans=len(plans))
assert report['replay_equal']
(out/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(out/'decisions.json').write_text(json.dumps(primitive(r.decision_log),ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
