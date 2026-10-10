"""Exact controlled 2*x mod 15: compose frozen gates, producers and T ports.

All state/events/tokens are new. Production uses four compatible instances of
the complete qualified F0 path; no preloaded magic input or periodic token.
"""
from pathlib import Path
from copy import deepcopy
from collections import defaultdict,Counter
import gzip,json,sys,time,hashlib,math,cmath
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
from run_processor_injection_demo import Plan,read,write,atom,LIB,LAYOUT,TIMINGS
from na_pipeline.frontend.program import _multiplier_template,_op
from na_pipeline.validation.semantic_frontend import operator_matrix
from na_pipeline.runtime.compilation_guard import CompilationGuard

OUT=ROOT/'artifacts/deliveries/compact-modmul-20261009'
TEMPLATE=ROOT/'artifacts/qualification/compact-modmul-20261009/producer-template.json.gz'


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    path.write_bytes(gzip.compress(raw,compresslevel=1,mtime=0) if path.suffix=='.gz' else raw)


def program():
    template=_multiplier_template(2);formal=template['formal_qubits'];ops=[n['op'] for n in template['body']]
    u=operator_matrix(ops,formal);truth=[];err=0.
    for c in range(32):
        ctrl=c&1;x=c>>1;y=x if not ctrl or x==15 else 2*x%15;row=(y<<1)|ctrl
        err=max(err,max(abs(u[r][c]-int(r==row)) for r in range(32)))
        truth.append(dict(control=ctrl,x=x,y=y))
    assert err<1e-12
    mapping=dict(ctrl='q0',w0='q8',w1='q9',w2='q10',w3='q11')
    prefix=[dict(id=f'prepare:H{i}',gate='H',operands=[f'q{i}'],stage='prepare') for i in range(8)]
    prefix.append(dict(id='prepare:X8',gate='X',operands=['q8'],stage='prepare'))
    circuit=prefix+[dict(id='mul2:'+o['id'],gate=o['params']['name'],operands=[mapping[q] for q in o['qubits']],stage=o['id'].split('/')[0],source_ids=o['source_ids']) for o in ops]
    return dict(schema_version='CompactShorPrefix/1',N=15,a=2,registers=dict(phase=[f'q{i}' for i in range(8)],work=[f'q{i}' for i in range(8,12)],idle=[f'q{i}' for i in range(12,17)]),
        operations=circuit,arithmetic_template=template,truth_table=truth,operator_max_error=err,
        arithmetic_gate_counts=dict(Counter(o['params']['name'] for o in ops)),full_shor=False,quantum_state_simulated=False)


class Composer(Plan):
    def __init__(self,layout,producer):
        super().__init__(layout,'modmul');self.producer=producer;self.calls=[];self.prod=[];self.tokens=[];self.calls_by_id={};self.result_ready={}
        self.at={v['qubit']:k for k,v in self.initial.items()};self.site={v:k for k,v in self.at.items()};self.home={v['qubit']:v['position'][:] for v in self.initial.values()}
        self.native={name:read(LIB/name/'atom-program.json') for name in ('H','factory.consume_correction','factory.consume_correction_tdg')}
        self.template_refs={};self.cohort=-1;self.free_tokens=[];self.magic_free=0.;self.current_call=None
    def add(self,*args,**kwargs):
        if self.current_call:kwargs.setdefault('source',[self.current_call])
        end=super().add(*args,**kwargs);self.actions[-1]['payload']['logical_call']=self.current_call
        return end
    def ids(self,patch):return [self.at[patch+'/'+s] for s in [f'd{i}' for i in range(9)]+[f'x{i}' for i in range(4)]+[f'z{i}' for i in range(4)]]
    def classical_release(self,a):
        q=a['payload'];lat=TIMINGS['result_latency'] if a['kind']=='measure' else 0
        for bit in q.get('writes',[]):self.result_ready[bit]=a['t_end_us']+lat
    def bind_local(self,name,patch,t):
        raw=self.native[name];initial={a['atom_id']:a for a in raw['initial_state']['atoms']}
        prefix='atom:block/' if name=='H' else 'atom:live_data/'
        delta=[self.pos[self.at[patch+'/d0']][i]-initial[prefix+'d0']['position_um'][i] for i in (0,1)]
        ids={prefix+s:self.at[patch+'/'+s] for s in [f'd{i}' for i in range(9)]+[f'x{i}' for i in range(4)]+[f'z{i}' for i in range(4)]}
        def point(x):return [x[0]+delta[0],1100+x[1]-1030 if name!='H' and x[1]>=1020 else x[1]+delta[1]]
        batches=defaultdict(list)
        for a in raw['actions']:batches[(a['t_start_us'],a['t_end_us'])].append(a)
        old_end=0
        for (lo,hi),actions in sorted(batches.items()):
            t+=max(0,lo-old_end);ends=[]
            for a in actions:
                q=a['payload'];kind=a['kind'];owned=[ids[x] for x in a['atoms'] if x in ids]
                if q.get('name')=='CZ':owned=list(dict.fromkeys(ids[x] for pair in q['pairs'] for x in pair))
                ref=dict(component=name,action_id=a['id'],logical_call=self.current_call,patch=patch)
                if kind=='move':
                    before=len(self.actions);end=self.move(t,{ids[v['atom_id']]:point(v['to_um']) for v in q['trajectories']},'data',name)
                    for generated in self.actions[before:]:generated['payload']['native_ref']=ref
                elif kind=='rebind':
                    bindings=[dict(atom_id=ids[b['atom_id']],from_site_id=self.site[ids[b['atom_id']]],to_site_id=patch+'/'+b['to_site_id'].rsplit('/',1)[1]) for b in q['site_bindings']]
                    end=self.add(t,hi-lo,'rebind',owned,group='data',phase='H · 原子位置置换',site_bindings=bindings,native_ref=ref)
                    for b in bindings:self.site[b['atom_id']]=b['to_site_id'];self.at[b['to_site_id']]=b['atom_id']
                else:
                    writes=[self.current_call+':'+r for r in q.get('writes',[])]
                    end=self.add(t,hi-lo,kind,owned,group='data',name=q.get('name',''),pairs=[[ids[x] for x in v] for v in q.get('pairs',[])] or None,
                        phase='H · 物理 H 与搬运' if name=='H' else '条件 '+('S-SE' if name.endswith('correction') else 'S†-SE'),writes=writes,measurement_value=0,native_ref=ref)
                    self.classical_release(self.actions[-1])
                ends.append(end)
            t=max(ends);old_end=hi
        return t
    def cx(self,control,target,t):
        ds=[self.at[f'{control}/d{i}'] for i in range(9)];ts=[self.at[f'{target}/d{i}'] for i in range(9)];home={i:self.pos[i][:] for i in ds}
        t=self.add(t,1,'gate',ts,group='data',name='H',phase='CNOT · 目标基变换')
        t=self.add(t,100,'pickup',ds,group='data',phase='CNOT 配对')
        t=self.move(t,{i:[self.pos[i][0]+5,self.pos[i][1]+2.5] for i in ds},'data','CNOT 配对')
        t=self.move(t,{d:[self.pos[a][0]+2,self.pos[a][1]] for d,a in zip(ds,ts)},'data','CNOT 配对')
        t=self.add(t,1,'gate',ds+ts,group='data',name='CZ',pairs=[list(v) for v in zip(ds,ts)],phase='CNOT · 9 对原生 CZ')
        self.calls_by_id[self.current_call]['coupling_action']=self.actions[-1]['id']
        t=self.add(t,1,'gate',ts,group='data',name='H',phase='CNOT · 目标基变换')
        t=self.move(t,{i:[self.pos[i][0]+5,self.pos[i][1]+2.5] for i in ds},'data','CNOT 返回')
        t=self.move(t,{i:[home[i][0]+5,home[i][1]+2.5] for i in ds},'data','CNOT 返回')
        t=self.move(t,home,'data','CNOT 返回',order=(1,0))
        return self.add(t,100,'drop',ds,group='data',phase='CNOT 返回')
    def produce(self,t):
        assert not self.free_tokens
        self.cohort+=1;e=self.cohort;start=max(t,self.magic_free);t=start;saved=self.current_call;self.current_call=None
        def key(f,s):return f'cohort{e}:F{f}:'+s
        def aid(f,s):return s.replace('atom:F0:',f'atom:F{f}:',1)
        def point(f,x):return [x[0]+1600,1100+(x[1]-1030)+110*f] if x[1]>=1020 else [x[0]+800,x[1]-70+110*f]
        acceptance={};source_count=0;stage_spans=[]
        for stage in self.producer['stages']:
            began=t
            for leaf in stage['leaves']:
                batches=defaultdict(list)
                for a in leaf['actions']:batches[(a['start'],a['end'])].append(a)
                old_end=min(a['start'] for a in leaf['actions'])
                for (lo,hi),batch in sorted(batches.items()):
                    t+=max(0,lo-old_end);ends=[]
                    for a in batch:
                        q=a['payload'];kind=a['kind'];owned=[aid(f,x) for f in range(4) for x in a['atoms']]
                        reads=[key(f,r) for f in range(4) for r in q.get('reads',[])];writes=[key(f,r) for f in range(4) for r in q.get('writes',[])]
                        if reads:t=max(t,max(self.result_ready[r]+TIMINGS['feedback_latency'] for r in reads))
                        ref=leaf['module_hash']+'/'+a['id'];self.template_refs[ref]=dict(stage=stage['stage'],module_hash=leaf['module_hash'],action=a)
                        condition=[dict(bit=key(f,a['condition']['bit']),equals=a['condition']['equals']) for f in range(4)] if a['condition'] else []
                        extra=dict(native_ref=ref,cohort=e,factories=['F0','F1','F2','F3'],conditions=condition,reads=reads,writes=writes)
                        source_count+=1
                        if kind=='move':
                            targets={aid(f,v['atom_id']):point(f,v['to_um']) for f in range(4) for v in q['trajectories']};before=len(self.actions)
                            returning=any(self.pos[i][0]>=1500 and dest[1]<438 for i,dest in targets.items())
                            end=self.move(t,targets,'magic',f'工厂 e{e} · '+stage['stage'],order=(1,0) if returning else (0,1))
                            for generated in self.actions[before:]:generated['payload'].update(native_ref=ref,cohort=e,factories=extra['factories'])
                        elif kind=='classical':
                            op=q.get('operation',q.get('params',{}).get('operation'))
                            groups=[dict(reads=[key(f,r) for r in q.get('reads',[])],writes=[key(f,r) for r in q.get('writes',[])]) for f in range(4)]
                            end=self.add(t,hi-lo,kind,[],phase=f'工厂 e{e} · '+stage['stage'],operation=op,result_groups=groups,**extra)
                            if op=='all_zero':acceptance={f'F{f}':groups[f]['writes'][0] for f in range(4)}
                            self.classical_release(self.actions[-1])
                        else:
                            end=self.add(t,hi-lo,kind,owned,group='magic',name=q.get('name',''),pairs=[[aid(f,x) for x in pair] for f in range(4) for pair in q.get('pairs',[])] or None,
                                phase=f'工厂 e{e} · '+stage['stage'],measurement_value=0,**extra)
                            self.classical_release(self.actions[-1])
                        ends.append(end)
                    t=max(ends);old_end=hi
            stage_spans.append(dict(stage=stage['stage'],start_us=began,end_us=t))
        assert set(acceptance)=={'F0','F1','F2','F3'}
        for f in range(4):
            token=dict(id=f'cohort{e}:F{f}:Aplus',factory=f'F{f}',epoch=e,ready_us=t,accepted_result=acceptance[f'F{f}'],carrier_ids=self.ids(f'F{f}:W4'))
            self.tokens.append(token);self.free_tokens.append(token);self.lifecycle.append(dict(time_us=t,event='output_ready',**token))
        self.prod.append(dict(epoch=e,start_us=start,end_us=t,source_actions=source_count,stages=stage_spans));self.magic_free=t;self.current_call=saved
        print('producer cohort',e,'ready',round(t,1),'actions',len(self.actions),flush=True)
    def inject(self,patch,gate,t,m):
        if not self.free_tokens:self.produce(t)
        token=self.free_tokens.pop(0);fid=token['factory'];requested=t;t=max(t,token['ready_us'],self.magic_free)
        self.lifecycle.append(dict(time_us=t,event='reserve',token_id=token['id'],request=self.current_call,target=patch))
        D=self.ids(patch);A=token['carrier_ids'];dh={i:self.pos[i][:] for i in D};ah={i:self.pos[i][:] for i in A}
        anchor=self.home[patch+'/d0'];dp={i:[self.pos[i][0]+920-anchor[0],self.pos[i][1]+670-anchor[1]] for i in D}
        ar=self.home[fid+':W4/d0'];ap={i:[self.pos[i][0]+1200-ar[0],self.pos[i][1]+670-ar[1]] for i in A}
        td=self.transport(t,D,dp,'data','T · D 搬入 Processor');ta=self.transport(t,A,ap,'magic','T · W4 搬入 Processor');t=max(td,ta)
        self.add(t,0,'handoff',A,group='data',phase='T · 控制权交接',owner_from='magic',owner_to='data')
        # Source CNOT uses the current code-site map, including earlier H transport.
        t=self.cx(patch,fid+':W4',t)
        aa=[self.at[f'{fid}:W4/d{i}'] for i in range(9)];mz={i:[ap[i][0],1100+ap[i][1]-670] for i in aa}
        t=self.transport(t,aa,mz,'data','T · 魔态读出');bits=[]
        for i,carrier in enumerate(aa):
            bit=self.current_call+f':z{i}';bits.append(bit)
            self.add(t,TIMINGS['measure'],'measure',[carrier],group='data',phase='T · 魔态读出',writes=[bit],measurement_value=m if i==0 else 0);self.classical_release(self.actions[-1])
        t+=TIMINGS['measure']+TIMINGS['result_latency']+TIMINGS['feedback_latency'];result=self.current_call+':logical_m'
        t=self.add(t,1,'classical',[],phase='T · 逻辑反馈',reads=bits[:3],writes=[result],operation='xor');self.classical_release(self.actions[-1]);t+=1
        self.lifecycle.append(dict(time_us=t,event='consume',token_id=token['id'],request=self.current_call,result=result,gate=gate,target=patch,carrier_ids=A))
        t=self.add(t,10,'reset',aa,group='data',phase='T · 输出清理');t=self.transport(t,aa,{i:ap[i] for i in aa},'data','T · 魔态返回停车位');t=self.add(t,10,'reset',A[9:],group='data',phase='T · 输出清理')
        corr=('factory.consume_correction' if gate=='T' else 'factory.consume_correction_tdg') if (m==1 if gate=='T' else m==0) else None
        cs=t
        if corr:t=self.bind_local(corr,patch,t)
        t=self.transport(t,D,dh,'data','T · D 返回 Compute');data_done=t
        self.add(t,0,'handoff',A,group='magic',phase='T · 控制权归还',owner_from='data',owner_to='magic');t=self.transport(t,A,ah,'magic','T · W4 归还工厂')
        all_factory=[i for slot in ('W0','W1','W2','W3','W4','M') for i in self.ids(fid+':'+slot)]
        t=self.add(t,10,'reset',all_factory,group='magic',phase='工厂消费后清理')
        self.lifecycle.append(dict(time_us=t,event='cleaned',token_id=token['id'],factory=fid,epoch=token['epoch']));self.magic_free=t
        self.calls_by_id[self.current_call].update(token=token['id'],factory=fid,measurement_bit=result,scenario_m=m,correction=corr,
            correction_start_us=cs,data_completed_us=data_done,requested_us=requested,ready_wait_us=max(0,token['ready_us']-requested))
        return t


def compose():
    OUT.mkdir(parents=True,exist_ok=True);prog=program();save(OUT/'program.json',prog)
    layout=read(LAYOUT);producer=read(TEMPLATE);p=Composer(layout,producer);p.produce(0);t=0.;nth=0
    for op in prog['operations']:
        p.current_call=op['id'];call=dict(**op,start_us=t);p.calls.append(call);p.calls_by_id[op['id']]=call;start=t
        name=op['gate'];qs=op['operands']
        if name=='H':t=p.bind_local('H',qs[0],t)
        elif name=='X':t=p.add(t,1,'gate',[p.at[qs[0]+f'/d{i}'] for i in (0,3,6)],group='data',name='X',phase='Shor · 工作寄存器置 1')
        elif name=='CX':t=p.cx(*qs,t)
        elif name in ('T','TDG'):
            t=p.inject(qs[0],name,t,nth%2);nth+=1
        else:raise ValueError(name)
        call['end_us']=t;p.phase(op['id']+' · '+name+' '+','.join(qs),start,t)
        if not p.free_tokens and nth<21:
            p.current_call=None;p.produce(t)
        print(op['id'],name,round(t,1),flush=True)
    assert nth==21 and len(p.tokens)==24
    p.actions.sort(key=lambda a:(a['t_start_us'],a['t_end_us'],a['id']))
    value=dict(schema_version='CompactModmulPlan/1',program=prog,layout=layout,initial=p.initial,actions=p.actions,
        phases=p.phases,calls=p.calls,production=p.prod,lifecycle=sorted(p.lifecycle,key=lambda e:e['time_us']),
        tokens=p.tokens,final_sites=p.site,site_positions=p.home,end_us=t,
        template_projection_sha256=hashlib.sha256(TEMPLATE.read_bytes()).hexdigest(),template_refs=p.template_refs,
        gate_source_hashes={name:hashlib.sha256((LIB/name/'atom-program.json').read_bytes()).hexdigest() for name in p.native},
        quantum_state_simulated=False,hardware_executed=False,fake_scenario='producer readouts zero; T readouts alternating 0/1')
    save(OUT/'plan.json.gz',value);print('COMPOSED',len(p.actions),t,flush=True)
    return value


def verify(plan):
    local_sources={}
    for name,expected_hash in plan['gate_source_hashes'].items():
        path=LIB/name/'atom-program.json';assert hashlib.sha256(path.read_bytes()).hexdigest()==expected_hash,'LOCAL_TEMPLATE_BYTES_CHANGED'
        local_sources[name]={a['id']:a for a in read(path)['actions']}
    assert [(c['id'],c['gate'],c['operands']) for c in plan['calls']]==[(o['id'],o['gate'],o['operands']) for o in plan['program']['operations']],'LOGICAL_SOURCE_CHANGED'
    call_by_id={c['id']:c for c in plan['calls']}
    factory_covered=defaultdict(set)
    for a in plan['actions']:
        q=a['payload'];ref=q.get('native_ref')
        if isinstance(ref,str):
            original=plan['template_refs'][ref]['action'];factory_covered[q['cohort']].add(ref)
            expected=[x.replace('atom:F0:',f'atom:F{f}:',1) for f in range(4) for x in original['atoms']]
            assert a['atoms']==expected,'FACTORY_TEMPLATE_OPERANDS_CHANGED'
            if a['kind']!='move':assert (a['kind'],q.get('name',''))==(original['kind'],original['payload'].get('name','')),'FACTORY_TEMPLATE_GATE_CHANGED'
    expected_refs=set(plan['template_refs'])
    assert set(factory_covered)==set(range(6)) and all(s==expected_refs for s in factory_covered.values()),'FACTORY_SOURCE_COVERAGE'
    state=deepcopy(plan['initial']);site={k:v['qubit'] for k,v in state.items()};results={};busy={};moving={};events=[];pulses=0
    tokens={};leases={};completed_calls=set();lifecycle=[];times=[]
    for a in plan['actions']:
        times.extend([(a['t_start_us'],3,a),(a['t_end_us'],0,a)]) if a['t_end_us']>a['t_start_us'] else times.append((a['t_start_us'],2,a))
    for e in plan['lifecycle']:times.append((e['time_us'],1,e))
    for t,edge,a in sorted(times,key=lambda x:(x[0],x[1])):
        if edge==1:
            kind=a['event'];tid=a.get('token_id',a.get('id'))
            if kind=='output_ready':
                assert tid not in tokens and results[a['accepted_result']]['value'] is True
                assert results[a['accepted_result']]['ready_us']<=t
                fid=a['factory'];assert fid not in leases
                tokens[tid]='ready';leases[fid]=tid
            elif kind=='reserve':assert tokens[tid]=='ready';tokens[tid]='reserved'
            elif kind=='consume':
                assert tokens[tid]=='reserved' and results[a['result']]['ready_us']+1<=t
                call=next(c for c in plan['calls'] if c['id']==a['request']);m=results[a['result']]['value']
                expected='factory.consume_correction' if a['gate']=='T' and m==1 else 'factory.consume_correction_tdg' if a['gate']=='TDG' and m==0 else None
                assert call['correction']==expected and call['scenario_m']==m
                assert a['carrier_ids']==next(tok['carrier_ids'] for tok in plan['tokens'] if tok['id']==tid)
                tokens[tid]='consumed'
            elif kind=='cleaned':assert tokens[tid]=='consumed';tokens[tid]='cleaned';assert leases.pop(a['factory'])==tid
            lifecycle.append(a);continue
        q=a['payload'];kind=a['kind']
        if edge==3:
            ref=q.get('native_ref')
            if isinstance(ref,dict) and kind not in ('move','rebind'):
                original=local_sources[ref['component']][ref['action_id']];bysite={v:k for k,v in site.items()}
                def bind(x):return bysite[ref['patch']+'/'+x.rsplit('/',1)[1]]
                assert (kind,q.get('name',''))==(original['kind'],original['payload'].get('name','')),'LOCAL_TEMPLATE_GATE_CHANGED'
                if q.get('name')=='CZ':assert q['pairs']==[[bind(x) for x in v] for v in original['payload']['pairs']],'LOCAL_TEMPLATE_CZ_BINDING'
                else:assert a['atoms']==[bind(x) for x in original['atoms']],'LOCAL_TEMPLATE_BINDING'
            for bit in q.get('reads',[]):assert bit in results and results[bit]['ready_us']+TIMINGS['feedback_latency']<=t+1e-8,('RESULT_NOT_READY',a['id'],bit)
            enabled=all(results[c['bit']]['value']==c['equals'] for c in q.get('conditions',[]));q['_enabled']=enabled
            if not enabled:continue
            for r in a['resources']:
                assert r not in busy,('RESOURCE_CONFLICT',a['id'],busy.get(r),r);busy[r]=a['id']
            if kind in ('pickup','drop','move'):
                for i in a['atoms']:
                    assert state[i]['owner']==q['aod_group'],('AOD_OWNER',a['id'],i)
                    assert state[i]['carrier']==('SLM' if kind=='pickup' else 'AOD'),('CARRIER',a['id'],i)
            if kind=='move':
                for axis in (0,1):
                    mapping={}
                    for tr in q['trajectories']:
                        assert state[tr['atom_id']]['position']==tr['from_um'],('AB_START',a['id'],tr['atom_id'])
                        x,y=tr['from_um'][axis],tr['to_um'][axis]
                        assert x not in mapping or abs(mapping[x]-y)<1e-7,('AOD_AXIS_INCOMPATIBLE',a['id']);mapping[x]=y
                    vals=[mapping[x] for x in sorted(mapping)];assert vals==sorted(set(vals)),('AOD_AXIS_CROSS',a['id'])
                moving[a['id']]=a
            if q.get('name')=='CZ':
                call=call_by_id.get(q.get('logical_call'))
                if call and call.get('coupling_action')==a['id']:
                    control=call['operands'][0];target=call['operands'][1] if call['gate']=='CX' else call['factory']+':W4'
                    bysite={v:k for k,v in site.items()};expected=[[bysite[f'{control}/d{i}'],bysite[f'{target}/d{i}']] for i in range(9)]
                    assert q['pairs']==expected,'LOGICAL_CNOT_BINDING_CHANGED'
                group=q['aod_group'];box=(780,-90,1460,412) if group=='magic' else (80,438,1460,1000)
                for move in moving.values():
                    for tr in move['payload']['trajectories']:
                        x0,x1=sorted((tr['from_um'][0],tr['to_um'][0]));y0,y1=sorted((tr['from_um'][1],tr['to_um'][1]))
                        assert not(x0<=box[2] and x1>=box[0] and y0<=box[3] and y1>=box[1]),('CZ_DURING_MOTION',a['id'],move['id'])
                bins={};actual=set()
                for i,s in state.items():
                    x,y=s['position']
                    if not(box[0]<=x<=box[2] and box[1]<=y<=box[3]):continue
                    cell=(math.floor(x/3),math.floor(y/3))
                    for dx in (-1,0,1):
                        for dy in (-1,0,1):
                            for j in bins.get((cell[0]+dx,cell[1]+dy),[]):
                                if math.dist([x,y],state[j]['position'])<=2+1e-7:actual.add(tuple(sorted((i,j))))
                    bins.setdefault(cell,[]).append(i)
                assert actual=={tuple(sorted(x)) for x in q['pairs']},('CZ_PAIR_SET',a['id'],list(actual^{tuple(sorted(x)) for x in q['pairs']})[:4]);pulses+=1
            if kind=='reset':assert not any(state[i]['qubit'].startswith('q') and '/d' in state[i]['qubit'] for i in a['atoms']),'DATA_RESET'
        elif edge==2:
            assert kind=='handoff'
            for i in a['atoms']:
                assert state[i]['carrier']=='SLM' and state[i]['owner']==q['owner_from']
                state[i]['owner']=q['owner_to']
            events.append(dict(action_id=a['id'],status='completed',t_start_us=t,t_end_us=t));continue
        else:
            enabled=q.pop('_enabled',True)
            if enabled:
                if kind=='move':
                    for tr in q['trajectories']:state[tr['atom_id']]['position']=tr['to_um'][:]
                    moving.pop(a['id'])
                elif kind in ('pickup','drop'):
                    if kind=='drop':
                        occupied={tuple(s['position']) for s in state.values() if s['carrier']=='SLM'}
                        for i in a['atoms']:
                            assert state[i]['position']==q['slm_sites'][i] and tuple(state[i]['position']) not in occupied,('SLM_OCCUPIED',a['id'],i)
                            occupied.add(tuple(state[i]['position']))
                    for i in a['atoms']:state[i]['carrier']='AOD' if kind=='pickup' else 'SLM'
                elif kind=='rebind':
                    for b in q['site_bindings']:
                        assert site[b['atom_id']]==b['from_site_id'] and state[b['atom_id']]['position']==plan['site_positions'][b['to_site_id']]
                        site[b['atom_id']]=b['to_site_id']
                elif kind=='measure':
                    for bit in q.get('writes',[]):results[bit]=dict(value=q.get('measurement_value',0),ready_us=t+TIMINGS['result_latency'],producer=a['id'],origin='fake')
                elif kind=='classical':
                    for group in q.get('result_groups',[dict(reads=q.get('reads',[]),writes=q.get('writes',[]))]):
                        values=[results[r]['value'] for r in group['reads']];op=q['operation']
                        if op=='xor':v=sum(values)%2
                        elif op=='all_zero':v=not any(values)
                        else:raise ValueError(('CLASSICAL_OPERATION',op))
                        for bit in group['writes']:results[bit]=dict(value=v,ready_us=t,producer=a['id'],origin='computed_from_fake')
                for r in a['resources']:assert busy.pop(r)==a['id']
            events.append(dict(action_id=a['id'],status='completed' if enabled else 'skipped',t_start_us=a['t_start_us'],t_end_us=t))
    assert not busy and not moving
    for i,s in state.items():
        assert s['position']==plan['site_positions'][site[i]],('FINAL_SITE',i)
        assert s['carrier']=='SLM' and s['owner']==plan['initial'][i]['owner']
    assert site==plan['final_sites'] and Counter(tokens.values())=={'cleaned':21,'ready':3}
    assert len(plan['calls'])==60 and len({a['id'] for a in plan['actions']})==len(plan['actions'])
    # Check every logical gate has its own physical invocation, not just a label.
    bycall=defaultdict(list)
    for a in plan['actions']:
        if a['payload'].get('logical_call'):bycall[a['payload']['logical_call']].append(a)
    for c in plan['calls']:
        aa=bycall[c['id']];assert aa
        if c['gate']=='H':assert sum(len(a['atoms']) for a in aa if a['payload'].get('name')=='H')==9 and sum(a['kind']=='rebind' for a in aa)==1
        elif c['gate'] in ('CX','T','TDG'):assert len(next(a for a in aa if a['id']==c['coupling_action'])['payload']['pairs'])==9
    report=dict(passed=True,scope='exact_arithmetic_and_composed_fake_events',logical_operations=60,modmul_operations=51,
        magic_outputs_produced=24,magic_outputs_consumed=21,remaining_ready=3,production_cohorts=6,
        atom_count=697,actions=len(events),regional_CZ_pulses=pulses,operator_max_error=plan['program']['operator_max_error'],
        native_local_gate_bindings_checked=True,factory_template_coverage_checked=True,
        end_us=plan['end_us'],native_circuit_compilation_calls=0,old_runtime_state_reused=False,
        all_carriers_at_current_code_sites=True,quantum_state_simulated=False,hardware_executed=False,
        continuous_all_pairs_geometry=False,user_visual_acceptance='pending')
    save(OUT/'trace.json.gz',dict(events=events,results=results,lifecycle=lifecycle,final_state=state,final_sites=site,tokens=tokens));save(OUT/'acceptance.json',report)
    print('VERIFIED',json.dumps(report),flush=True)


if __name__=='__main__':
    started=time.time()
    with CompilationGuard() as guard:
        plan=compose();verify(plan);save(OUT/'compilation-guard.json',guard.receipt())
    save(OUT/'completion.json',dict(completed=True,wall_seconds=time.time()-started))
