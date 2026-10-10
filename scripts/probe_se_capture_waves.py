"""Bounded read-only feasibility probe for loading a SE layer in two waves."""
from pathlib import Path
from itertools import combinations
import json,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from na_pipeline.backend.enola_kernel import EnolaKernel,capture_closure,group_route,StrategyError
from na_pipeline.backend.geometry import broadcast_pairs,in_zone

p=ROOT/'artifacts/demos/aod-held-cz-20261007/SE'
d=json.loads((p/'physical-dag.json').read_bytes());dev=json.loads((p/'device.json').read_bytes())
atoms=json.loads((p/'atom-program.json').read_bytes())['initial_state']['atoms']
world={x['atom_id']:x for x in atoms};qm={x.get('site_id',x['qubit_id']):x['atom_id'] for x in atoms}
k=EnolaKernel();zone={'bounds_um':[dev['zones']['storage_entanglement'][t] for t in ['x_range_um','y_range_um']]}
distance=dev['geometry']['gate_pair_distance_um'];reports=[]
for layer in (1,2):
 ops=[o for o in d['nodes'] if o.get('metadata',{}).get('syndrome_layer')==layer];domains=[]
 for o in ops:
  pair=[qm[q] for q in o['qubits']];cs=[]
  for mover in pair:
   fixed=world[next(q for q in pair if q!=mover)]['position_um'];start=world[mover]['position_um']
   for dx,dy in [(distance,0),(-distance,0),(0,distance),(0,-distance)]:
    goal=[fixed[0]+dx,fixed[1]+dy];trial=[dict(x,position_um=goal) if x['atom_id']==mover else x for x in atoms]
    if in_zone(goal,zone) and broadcast_pairs(trial,zone,distance,1e-7)==[sorted(pair)]:
     cs.append({'op_id':o['id'],'pair':pair,'mover':mover,'to_um':goal,'vector':[start[1],goal[1],start[0],goal[0]]})
  domains.append(cs)
 complete=[]
 def build(i,chosen):
  if i==len(domains):complete.append(chosen);return
  for c in domains[i]:
   if all(k.compatible(c['vector'],v['vector']) for v in chosen):build(i+1,chosen+[c])
 build(0,[]);tested=0;found=None;start=time.monotonic()
 for chosen in complete:
  if found:break
  goals={c['mover']:c['to_um'] for c in chosen};all_ids=set(goals)
  for size in (3,2,4,1,5):
   if found:break
   for part in combinations(chosen,size):
    tested+=1
    if time.monotonic()-start>60:raise RuntimeError('60_SECOND_PROBE_BUDGET')
    first={c['mover']:c['to_um'] for c in part};second=all_ids-set(first)
    if set(capture_closure(atoms,list(first))['captured_atoms'])!=set(first):continue
    try:path1,_=group_route(atoms,first,10.)
    except StrategyError:continue
    scene=[dict(x,position_um=first[x['atom_id']],carrier='AOD') if x['atom_id'] in first else dict(x) for x in atoms]
    # A second loading pulse enables the union of old and new axes.
    xs={x['position_um'][0] for x in scene if x['atom_id'] in all_ids};ys={x['position_um'][1] for x in scene if x['atom_id'] in all_ids}
    captured={x['atom_id'] for x in scene if x['carrier']=='SLM' and x['position_um'][0] in xs and x['position_um'][1] in ys}
    if captured!=second:continue
    try:path2,_=group_route(scene,goals,10.)
    except StrategyError:continue
    trial=[dict(x,position_um=goals[x['atom_id']]) if x['atom_id'] in goals else x for x in atoms]
    if sorted(broadcast_pairs(trial,zone,distance,1e-7))!=sorted(sorted(c['pair']) for c in chosen):continue
    found={'selected':chosen,'wave1':list(first),'wave2':sorted(second),'route1':path1,'route2':path2};break
 reports.append({'layer':layer,'single_capture_compatible_full_selections':len(complete),'two_capture_choices_tested':tested,'found':found,'seconds':time.monotonic()-start})
print(json.dumps(reports))
(ROOT/'knowledge/roles/R0/se-two-capture-probe-20261008.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
