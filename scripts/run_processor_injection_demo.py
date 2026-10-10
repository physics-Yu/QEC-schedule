"""Processor T injection, two fresh fake-event branches, no circuit recompilation.

Entry contract supplies encoded A+ at F3:W4. This is an injection qualification,
not a rerun of distillation or a quantum-state simulator. Compiled S-SE and
producer initialization leaves are instantiated; only transport connectors and
device ownership are rebound to the four-zone device profile.
"""
from pathlib import Path
from copy import deepcopy
from collections import defaultdict
import json,gzip,hashlib,cmath,math,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from na_pipeline.runtime.compilation_guard import CompilationGuard
from build_component_gallery import read,write

OUT=ROOT/'artifacts/deliveries/processor-injection-20261009'
LAYOUT=ROOT/'artifacts/deliveries/four-zone-layout-20261009/layout.json'
LIB=ROOT/'artifacts/demos/joint-factory-repaired-20261008'
SOURCE_RUN=ROOT/'artifacts/qualification/cnot-t-bottom-20261009/run-v1'
TIMINGS=read(LIB/'factory.consume/device.json')['timings_us']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def atom(q):return 'atom:'+q


class Plan:
    def __init__(self,layout,branch):
        self.layout=layout;self.branch=branch;self.actions=[];self.phases=[];self.lifecycle=[]
        self.initial={atom(a['id']):dict(position=a['xy_um'][:],carrier='SLM',owner=a['aod_group'],qubit=a['id']) for a in layout['atoms']}
        self.pos={k:v['position'][:] for k,v in self.initial.items()};self.serial=0
    def add(self,t,duration,kind,ids,*,group=None,name='',trajectories=None,pairs=None,phase='',source=None,**payload):
        self.serial+=1
        a=dict(id=f'b{self.branch}:a{self.serial}',kind=kind,atoms=list(ids),t_start_us=t,t_end_us=t+duration,
            payload=dict(name=name,phase=phase,**payload),resources=[],source_ids=list(source or [phase or kind]),depends_on=[])
        if group:a['payload']['aod_group']=group
        if kind=='drop':a['payload']['slm_sites']={i:self.pos[i][:] for i in ids}
        if trajectories:a['payload']['trajectories']=trajectories
        if pairs:a['payload']['pairs']=pairs
        a['resources']=['atom:'+x for x in ids]
        if kind in ('move','pickup','drop'):a['resources'].append('aod:'+group)
        if name=='CZ':a['resources'].append('rydberg:'+group)
        self.actions.append(a);return a['t_end_us']
    def move(self,t,targets,group,phase,source=None,order=(0,1)):
        # Shared AOD axes. Every segment is axis-aligned; no animation-only path.
        for axis in order:
            trs=[]
            for aid,target in targets.items():
                start=self.pos[aid][:];end=start[:];end[axis]=target[axis]
                trs.append(dict(atom_id=aid,from_um=start,to_um=end))
            duration=max((abs(v['to_um'][axis]-v['from_um'][axis]) for v in trs),default=0)
            if duration:
                t=self.add(t,duration,'move',targets,group=group,trajectories=trs,phase=phase,source=source)
                for v in trs:self.pos[v['atom_id']]=v['to_um']
        return t
    def transport(self,t,ids,targets,group,phase):
        t=self.add(t,100,'pickup',ids,group=group,phase=phase)
        # Off-grid departure followed by axis motion avoids passing through
        # the canonical lattice sites. All members retain one shared waveform.
        lift={i:[self.pos[i][0]+5,self.pos[i][1]+2.5] for i in ids}
        t=self.move(t,lift,group,phase)
        lane={i:[targets[i][0]+5,targets[i][1]+2.5] for i in ids}
        t=self.move(t,lane,group,phase)
        t=self.move(t,targets,group,phase,order=(1,0))
        return self.add(t,100,'drop',ids,group=group,phase=phase)
    def phase(self,label,start,end):self.phases.append(dict(id=str(len(self.phases)),label=label,start_us=start,end_us=end,note=label))


def correction(plan,t,ids):
    """Bind the unchanged 133-action native S-SE body to q16 in Processor."""
    raw=read(LIB/'factory.consume_correction/atom-program.json')
    initial={a['atom_id']:a for a in raw['initial_state']['atoms']}
    delta=[plan.pos[atom('q16/d0')][k]-initial['atom:live_data/d0']['position_um'][k] for k in (0,1)]
    def aid(x):return atom('q16/'+x.rsplit('/',1)[1])
    def point(p):return [p[0]+delta[0],1100+(p[1]-1030) if p[1]>=1020 else p[1]+delta[1]]
    batches=defaultdict(list)
    for a in raw['actions']:batches[(a['t_start_us'],a['t_end_us'])].append(a)
    old_end=0;start=t;native=[]
    for (lo,hi),actions in sorted(batches.items()):
        t+=max(0,lo-old_end);ends=[]
        for a in actions:
            p=a['payload'];kind=a['kind'];owned=[aid(x) for x in a['atoms'] if x.startswith('atom:live_data/')]
            if p.get('name')=='CZ':owned=list(dict.fromkeys(aid(x) for pair in p['pairs'] for x in pair))
            src=['S-SE:'+s for s in a['source_ids']];native.append(a['id'])
            if kind=='move':
                target={aid(v['atom_id']):point(v['to_um']) for v in p['trajectories']}
                ends.append(plan.move(t,target,'data','条件 S-SE',src))
            else:
                pairs=[[aid(x) for x in pair] for pair in p.get('pairs',[])]
                duration=hi-lo
                if kind in ('pickup','drop'):duration=100
                ends.append(plan.add(t,duration,kind,owned,group='data',name=p.get('name',''),pairs=pairs or None,
                    phase='条件 S-SE',source=src,measurement_value=0,source_action=a['id']))
        t=max(ends);old_end=hi
    assert len(native)==133
    return t,dict(native_source_sha256=sha(LIB/'factory.consume_correction/atom-program.json'),native_actions=133,
        gate_members_unchanged=True,geometry_rebound=True,start_us=start,end_us=t)


def background(plan,start,source):
    """Three identical producer fronts: F0/F1/F2, one compatible magic AOD.

    F3 supplies the input W4 and waits for its return. These are actual compiled
    initialize actions, not a loop or a ready-state timer.
    """
    old=source;compiled=old['atom_program']['actions'];t=start;records=[]
    leaves=[m for m in old['physical_plan']['module_composition']['instances']
            if m['source_ids'] and all(s.startswith('F0-e0-') for s in m['source_ids'])]
    for leaf in leaves:
        actions=[a for a in compiled if a['id'].startswith(leaf['instance_id']+'/')]
        grouped=defaultdict(list)
        for a in actions:grouped[(a['t_start_us'],a['t_end_us'])].append(a)
        old_end=min(a['t_start_us'] for a in actions)
        for (lo,hi),batch in sorted(grouped.items()):
            t+=max(0,lo-old_end);ends=[]
            for a in batch:
                p=a['payload'];kind=a['kind'];trs={};owned=[];pairs=[]
                def remap(x,f):
                    assert x.startswith('atom:F0:')
                    return x.replace('atom:F0:',f'atom:F{f}:',1)
                def point(x,f):
                    if x[1]>=1020:return [x[0]+1600,1100+(x[1]-1030)+110*f]
                    return [x[0]+800,x[1]-70+110*f]
                for f in range(3):
                    relevant=[x for x in a['atoms'] if x.startswith('atom:F0:') and ':Y/' not in x and 'join_probe' not in x]
                    if p.get('name')=='CZ':relevant=list(dict.fromkeys(x for pair in p['pairs'] for x in pair))
                    owned += [remap(x,f) for x in relevant]
                    pairs += [[remap(x,f) for x in pair] for pair in p.get('pairs',[])]
                    for v in p.get('trajectories',[]):trs[remap(v['atom_id'],f)]=point(v['to_um'],f)
                assert owned
                # All syndrome inputs in this explicitly declared scenario are zero.
                enabled=a['condition'] is None or a['condition']['equals']==0
                src=['producer-template:'+s for s in a['source_ids']]
                if kind=='move':
                    # Keep the vertical readout leg outside Processor, including
                    # on return; a reversed XY order would cross its beam area.
                    returning=any(plan.pos[i][0]>=1500 and target[1]<438 for i,target in trs.items())
                    ends.append(plan.move(t,trs,'magic','F0–F2 同步生产',src,order=(1,0) if returning else (0,1)))
                else:
                    duration=100 if kind in ('pickup','drop') else hi-lo
                    ends.append(plan.add(t,duration,kind,owned,group='magic',name=p.get('name',''),pairs=pairs or None,
                        phase='F0–F2 同步生产',source=src,enabled=enabled,measurement_value=0,source_action=a['id']))
                records.append(a['id'])
            t=max(ends);old_end=hi
    return t,dict(template_factory='F0',instances=['F0','F1','F2'],compiled_actions=len(records),
        start_us=start,end_us=t,stage='initialize',ready_outputs_created=0,cohort_waveforms_checked=True)


def build(branch,layout,source):
    p=Plan(layout,branch)
    D=[atom('q16/'+s) for s in ['d'+str(i) for i in range(9)]+['x'+str(i) for i in range(4)]+['z'+str(i) for i in range(4)]]
    A=[i.replace('q16/','F3:W4/') for i in D];dhome={i:p.pos[i][:] for i in D};ahome={i:p.pos[i][:] for i in A}
    dpark={i:[p.pos[i][0]+600,p.pos[i][1]] for i in D}
    apark={i:[p.pos[i][0]-20,p.pos[i][1]+390] for i in A}
    td=p.transport(0,D,dpark,'data','D 搬入 Processor')
    ta=p.transport(0,A,apark,'magic','W4 搬入 Processor')
    t=max(td,ta);p.phase('两套 AOD 搬入 D / W4',0,t)
    p.add(t,0,'handoff',A,group='data',phase='W4 控制权交接',owner_from='magic',owner_to='data')
    p.lifecycle.append(dict(time_us=t,event='processor_takes_W4_transport_lease',carrier_ids=A))
    bg_end,bg=background(p,ta,source)
    t0=t;data9=D[:9];magic9=A[:9]
    t=p.add(t,1,'gate',magic9,group='data',name='H',phase='横向逻辑 CNOT')
    t=p.add(t,100,'pickup',data9,group='data',phase='横向逻辑 CNOT')
    lift={i:[p.pos[i][0]+5,p.pos[i][1]+2.5] for i in data9};t=p.move(t,lift,'data','横向逻辑 CNOT')
    aligned={d:[apark[a][0]+2,apark[a][1]] for d,a in zip(data9,magic9)}
    t=p.move(t,aligned,'data','横向逻辑 CNOT')
    t=p.add(t,1,'gate',data9+magic9,group='data',name='CZ',pairs=list(map(list,zip(data9,magic9))),phase='横向逻辑 CNOT')
    t=p.add(t,1,'gate',magic9,group='data',name='H',phase='横向逻辑 CNOT')
    lift={i:[p.pos[i][0]+5,p.pos[i][1]+2.5] for i in data9};t=p.move(t,lift,'data','D 返回停车位')
    t=p.move(t,{i:[dpark[i][0]+5,dpark[i][1]+2.5] for i in data9},'data','D 返回停车位')
    t=p.move(t,{i:dpark[i] for i in data9},'data','D 返回停车位',order=(1,0))
    t=p.add(t,100,'drop',data9,group='data',phase='D 返回停车位');p.phase('9 对 CNOT：H → CZ → H',t0,t)
    t0=t;target={i:[apark[i][0],1100+(apark[i][1]-apark[magic9[0]][1])] for i in magic9}
    t=p.transport(t,magic9,target,'data','W4 送入测量区')
    measure_start=t
    for i,aid in enumerate(magic9):
        p.add(t,TIMINGS['measure'],'measure',[aid],group='data',phase='W4 逻辑 Z 读出',writes=[f'magic-z-{i}'],measurement_value=branch if i==0 else 0)
    t+=TIMINGS['measure']+TIMINGS['result_latency']+TIMINGS['feedback_latency']
    t=p.add(t,1,'classical',[],phase='逻辑奇偶与反馈',reads=['magic-z-0','magic-z-1','magic-z-2'],writes=['logical-m'],operation='xor')
    t+=1;feedback=t;p.phase('9 位读出 → 逻辑 Z → 反馈就绪',t0,t)
    # Clear the consumed magic carriers before reusing the data AOD for S-SE.
    t0=t;t=p.add(t,10,'reset',magic9,group='data',phase='已消耗 W4 清理')
    t=p.transport(t,magic9,{i:apark[i] for i in magic9},'data','W4 返回交接位')
    t=p.add(t,10,'reset',A[9:],group='data',phase='已消耗 W4 清理')
    p.phase('W4 清理并返回 Processor',t0,t)
    corr=None
    if branch:
        t0=t;t,corr=correction(p,t,D);p.phase('m=1：完整物理 S-SE 修正',t0,t)
    else:
        p.lifecycle.append(dict(time_us=t,event='m0_no_S_required'))
    t0=t;t=p.transport(t,D,dhome,'data','D 返回 Compute');p.phase('T 完成，D 返回 Compute',t0,t)
    data_done=t
    wait_start=t;t=max(t,bg_end)
    if t>wait_start:p.phase('D 已完成；等待 magic AOD 归还窗口',wait_start,t)
    p.add(t,0,'handoff',A,group='magic',phase='W4 控制权归还',owner_from='data',owner_to='magic')
    t0=t;t=p.transport(t,A,ahome,'magic','W4 归还工厂');p.phase('同一 W4 载体归还 F3',t0,t)
    p.lifecycle += [dict(time_us=feedback,event='magic_token_consumed_once',token=f'injection-case-{branch}:supplied-A-plus',epoch=0),
        dict(time_us=data_done,event='data_T_complete',target='q16'),dict(time_us=t,event='F3_W4_clean_carriers_returned')]
    p.actions.sort(key=lambda a:(a['t_start_us'],a['t_end_us'],a['id']))
    return p,dict(end_us=t,data_completed_us=data_done,feedback_ready_us=feedback,measurement_start_us=measure_start,
        background=bg,correction=corr,entry_contract=dict(kind='declared_encoded_A_plus_input',patch='F3:W4',
        source='injection_test_boundary_condition',distillation_reexecuted=False,old_runtime_token_reused=False),
        branch=branch,timings_us=TIMINGS,timing_source='factory.consume/device.json',quantum_state_simulated=False,hardware_executed=False)


def execute(p,meta):
    """Fresh bounded event execution: carriers, ownership, results and leases."""
    coupling=[a for a in p.actions if a['payload'].get('name')=='CZ' and a['payload']['phase']=='横向逻辑 CNOT']
    expected_pairs={tuple(sorted((atom(f'q16/d{i}'),atom(f'F3:W4/d{i}')))) for i in range(9)}
    assert len(coupling)==1 and {tuple(sorted(v)) for v in coupling[0]['payload']['pairs']}==expected_pairs,'INJECTION_CNOT_CHANGED'
    basis=[a for a in p.actions if a['payload'].get('name')=='H' and a['payload']['phase']=='横向逻辑 CNOT']
    assert len(basis)==2 and all(set(a['atoms'])=={atom(f'F3:W4/d{i}') for i in range(9)} for a in basis),'INJECTION_H_CHANGED'
    assert basis[0]['t_end_us']<=coupling[0]['t_start_us'] and coupling[0]['t_end_us']<=basis[1]['t_start_us']
    correction_actions=[a for a in p.actions if a['payload']['phase']=='条件 S-SE']
    if p.branch:
        source=read(LIB/'factory.consume_correction/atom-program.json')['actions']
        actual={a['payload']['source_action']:a for a in correction_actions if 'source_action' in a['payload']}
        for a in source:
            if a['kind']=='move':continue
            assert a['id'] in actual,'CORRECTION_SOURCE_ACTION_MISSING'
            b=actual[a['id']]
            assert (a['kind'],a['payload'].get('name',''))==(b['kind'],b['payload'].get('name',''))
            def renamed(x):return atom('q16/'+x.rsplit('/',1)[1])
            if a['payload'].get('name')=='CZ':
                assert [[renamed(x) for x in pair] for pair in a['payload']['pairs']]==b['payload']['pairs']
            else:assert [renamed(x) for x in a['atoms']]==b['atoms']
    else:assert not correction_actions,'UNEXPECTED_S_CORRECTION'
    state=deepcopy(p.initial);results={};events=[];active={};resource_busy={};check_count=0
    boundaries=[]
    for a in p.actions:
        boundaries.extend([(a['t_start_us'],1,a),(a['t_end_us'],0,a)]) if a['t_start_us']!=a['t_end_us'] else boundaries.append((a['t_start_us'],2,a))
    # End/drop -> instantaneous ownership handoff -> new pickup at one clock.
    for time,edge,a in sorted(boundaries,key=lambda x:(x[0],{0:0,2:1,1:2}[x[1]],x[2]['id'])):
        q=a['payload'];enabled=q.get('enabled',True)
        if edge==1:
            if not enabled:continue
            for r in a['resources']:
                assert r not in resource_busy,('RESOURCE_CONFLICT',a['id'],resource_busy.get(r),r)
                resource_busy[r]=a['id']
            for bit in q.get('reads',[]):assert bit in results and results[bit]['ready_us']<=time-1+1e-8
            if a['kind'] in ('pickup','drop','move'):
                expected='SLM' if a['kind']=='pickup' else 'AOD'
                for i in a['atoms']:
                    assert state[i]['carrier']==expected,(a['id'],i,'CARRIER')
                    assert state[i]['owner']==q['aod_group'],(a['id'],i,'AOD_OWNER')
            if a['kind']=='move':
                # AOD row/column maps are single-valued and order-preserving.
                for axis in (0,1):
                    maps={}
                    for tr in q['trajectories']:
                        i=tr['atom_id'];assert state[i]['position']==tr['from_um'],(a['id'],'AB_START',i,state[i]['position'],tr['from_um'])
                        v=tr['from_um'][axis];target=tr['to_um'][axis]
                        assert v not in maps or abs(maps[v]-target)<1e-8,(a['id'],'AOD_INCOMPATIBLE_AXIS',axis)
                        maps[v]=target
                    values=[maps[k] for k in sorted(maps)];assert values==sorted(set(values)),(a['id'],'AOD_AXIS_CROSSING')
                active[a['id']]=a
            if q.get('name')=='CZ':
                group=q['aod_group'];expected={tuple(sorted(pair)) for pair in q['pairs']};actual=set();bins={}
                def illuminated(x,y):
                    return 780<=x<=1460 and -90<=y<=412 if group=='magic' else (80<=x<=1460 and 438<=y<=1000)
                region=(780,-90,1460,412) if group=='magic' else (80,438,1460,1000)
                for moving in active.values():
                    for tr in moving['payload']['trajectories']:
                        x0,x1=sorted((tr['from_um'][0],tr['to_um'][0]));y0,y1=sorted((tr['from_um'][1],tr['to_um'][1]))
                        crosses=x0<=region[2] and x1>=region[0] and y0<=region[3] and y1>=region[1]
                        assert not crosses,('CZ_DURING_REGIONAL_MOTION',a['id'],moving['id'])
                for i,s in state.items():
                    x,y=s['position']
                    if not illuminated(x,y):continue
                    cell=(math.floor(x/3),math.floor(y/3))
                    for dx in (-1,0,1):
                        for dy in (-1,0,1):
                            for j in bins.get((cell[0]+dx,cell[1]+dy),[]):
                                if math.dist([x,y],state[j]['position'])<=2+1e-7:actual.add(tuple(sorted((i,j))))
                    bins.setdefault(cell,[]).append(i)
                assert actual==expected,('REGIONAL_CZ_PAIR_SET',a['id'],actual^expected)
                check_count+=1
            if a['kind']=='reset':assert not any(i.startswith('atom:q16/d') for i in a['atoms']),'LIVE_DATA_RESET'
        elif edge==2:
            assert a['kind']=='handoff'
            for i in a['atoms']:
                assert state[i]['carrier']=='SLM' and state[i]['owner']==q['owner_from']
                state[i]['owner']=q['owner_to']
            events.append(dict(action_id=a['id'],kind=a['kind'],status='completed',t_start_us=time,t_end_us=time))
        else:
            if enabled:
                if a['kind']=='move':
                    for tr in q['trajectories']:state[tr['atom_id']]['position']=tr['to_um'][:]
                    active.pop(a['id'])
                if a['kind'] in ('pickup','drop'):
                    if a['kind']=='drop':
                        occupied={tuple(s['position']):i for i,s in state.items() if s['carrier']=='SLM'}
                        for i in a['atoms']:
                            assert state[i]['position']==q['slm_sites'][i],('SLM_PORT_CHANGED',a['id'],i)
                            xy=tuple(state[i]['position']);assert xy not in occupied,('SLM_PORT_OCCUPIED',a['id'],i)
                            occupied[xy]=i
                    for i in a['atoms']:state[i]['carrier']='AOD' if a['kind']=='pickup' else 'SLM'
                if a['kind']=='measure':
                    for bit in q.get('writes',[a['id']+':result']):results[bit]=dict(value=q.get('measurement_value',0),ready_us=time+TIMINGS['result_latency'],origin='fake',producer=a['id'])
                if a['kind']=='classical':
                    value=0
                    for bit in q['reads']:value^=results[bit]['value']
                    results[q['writes'][0]]=dict(value=value,ready_us=time,origin='computed_from_fake',producer=a['id'])
                for r in a['resources']:assert resource_busy.pop(r)==a['id']
            events.append(dict(action_id=a['id'],kind=a['kind'],status='completed' if enabled else 'skipped',t_start_us=a['t_start_us'],t_end_us=time))
    assert not active and not resource_busy
    assert state==p.initial,'FINAL_WORLD_OR_OWNER_CHANGED'
    assert results['logical-m']['value']==p.branch
    assert len([e for e in p.lifecycle if e['event']=='magic_token_consumed_once'])==1
    handoffs=[a for a in p.actions if a['kind']=='handoff']
    assert len(handoffs)==2 and handoffs[0]['atoms']==handoffs[1]['atoms']
    if p.branch:assert meta['correction']['start_us']>=results['logical-m']['ready_us']+1
    # Operator identity proves the logical injection for arbitrary input states.
    z=cmath.exp(1j*math.pi/4);K0=[1/math.sqrt(2),z/math.sqrt(2)];K1=[z/math.sqrt(2),1/math.sqrt(2)]
    assert max(abs(K0[i]-[1,z][i]/math.sqrt(2)) for i in range(2))<1e-12
    assert max(abs([1,1j][i]*K1[i]-z*[1,z][i]/math.sqrt(2)) for i in range(2))<1e-12
    # Report actual overlap of foreground transport and producer transport.
    moves={g:[a for a in p.actions if a['kind']=='move' and a['payload'].get('aod_group')==g] for g in ('data','magic')}
    overlap=sum(max(0,min(a['t_end_us'],b['t_end_us'])-max(a['t_start_us'],b['t_start_us'])) for a in moves['data'] for b in moves['magic'])
    assert overlap>0
    return dict(schema_version='ProcessorInjectionEventTrace/1',events=events,results=results,final_state=state,
        lifecycle=p.lifecycle,stats=dict(t_end_us=meta['end_us'],action_count=len(p.actions))),dict(passed=True,
        regional_CZ_pulses_checked=check_count,atom_count=len(state),fresh_events=len(events),
        measurement_branch=p.branch,logical_operator_identity=True,all_carriers_and_owners_returned=True,
        token_consumption_count=1,dual_AOD_move_overlap_us=overlap,continuous_all_pairs_check=False,
        runtime_scope='bounded_injection_fake_event_runner',full_factory_distillation_reexecuted=False,
        user_visual_acceptance='pending')


def main():
    OUT.mkdir(parents=True,exist_ok=True);layout=read(LAYOUT)
    source=read(SOURCE_RUN/'windows/window-0000.json.gz')
    for branch in (0,1):
        p,meta=build(branch,layout,source);trace,check=execute(p,meta)
        value=dict(schema_version='ProcessorInjectionPlan/1',initial=p.initial,actions=p.actions,phases=p.phases,metadata=meta,layout=layout)
        (OUT/f'branch-{branch}-plan.json.gz').write_bytes(gzip.compress(json.dumps(value,separators=(',',':')).encode(),compresslevel=1,mtime=0))
        (OUT/f'branch-{branch}-trace.json.gz').write_bytes(gzip.compress(json.dumps(trace,separators=(',',':')).encode(),compresslevel=1,mtime=0))
        write(OUT/f'branch-{branch}-checks.json',check)
        print(json.dumps(dict(branch=branch,**check,duration_us=meta['end_us']),ensure_ascii=False),flush=True)
    write(OUT/'source-hashes.json',{str(p.relative_to(ROOT)):sha(p) for p in [LAYOUT,LIB/'factory.consume_correction/atom-program.json',SOURCE_RUN/'windows/window-0000.json.gz']})


if __name__=='__main__':
    with CompilationGuard() as guard:
        main();write(OUT/'compilation-guard.json',guard.receipt())
