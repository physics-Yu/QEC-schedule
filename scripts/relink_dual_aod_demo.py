"""Link frozen CNOT and factory actions into a dual-AOD schedule preview.

No circuit lowering, native compilation, placement, routing, batch selection,
runtime replay or token minting. The branch is the explicitly frozen fake
scenario from the accepted source run. Old event times remain immutable.
"""
from pathlib import Path
from copy import deepcopy
import argparse, base64, gzip, hashlib, json, shutil, sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from na_pipeline.runtime.compilation_guard import CompilationGuard
from build_component_gallery import read, write
from extend_frame_gallery import packed


def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def variable(p, name):
    s=Path(p).read_text(encoding='utf-8')
    return json.JSONDecoder().raw_decode(s.split('window.'+name+'=',1)[1])[0]


def putvar(p, name, value):
    p.write_text('window.'+name+'='+json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+';',encoding='utf-8')


def module_actions(w, m):
    return [a for a in w['atom_program']['actions'] if a['id'].startswith(m['instance_id']+'/')]


def link_pair(data, magic):
    """Preserve both pulse batches. Independent capture; magic pulse first.

    Data remains at its original home during the first pulse. Its outbound
    overlaps magic's return. The data pulse waits for the magic leaf to finish.
    No trajectory is split, stretched or changed; waits are between actions.
    All offsets below are relative to the start of their respective leaves.
    """
    ds=min(a['t_start_us'] for a in data); ms=min(a['t_start_us'] for a in magic)
    dc=next(a for a in data if a['payload'].get('name')=='CZ')
    mc=next(a for a in magic if a['payload'].get('name')=='CZ')
    first=min(a['t_start_us'] for a in data if a['kind']=='move')-ds
    pre_end=max(a['t_end_us']-ds for a in data if a['t_start_us']-ds<first)
    assert pre_end <= mc['t_start_us']-ms, 'CAPTURE_MUST_FINISH_BEFORE_GLOBAL_PULSE'
    outbound_wait=max(0,mc['t_end_us']-ms-first)
    magic_end=max(a['t_end_us'] for a in magic)-ms
    pulse_wait=max(0,magic_end-(dc['t_start_us']-ds+outbound_wait))
    offsets={}
    for a in data:
        offset=-ds
        if a['t_start_us']-ds >= first:offset+=outbound_wait
        if a['t_start_us'] >= dc['t_start_us']:offset+=pulse_wait
        offsets[a['id']]=offset
    end=max(a['t_end_us']+offsets[a['id']] for a in data)
    return offsets,max(end,magic_end),dict(outbound_wait_us=outbound_wait,
        data_pulse_wait_us=pulse_wait,magic_ready_us=magic_end,data_ready_us=end,
        reason='independent_AOD_capture_and_transport_with_global_CZ_barrier')


def check_resources(actions):
    calendars={}
    for a in actions:
        for r in a['resources']:
            calendars.setdefault(r,[]).append((a['t_start_us'],a['t_end_us'],a['id']))
    for r, spans in calendars.items():
        previous=None
        for span in sorted(spans):
            if previous and span[0] < previous[1]-1e-8:
                raise ValueError(('RESOURCE_OVERLAP',r,previous,span))
            if not previous or span[1]>previous[1]:previous=span


def overlap_intervals(actions):
    groups={g:[] for g in ('data','magic')}
    for a in actions:
        if a['kind']=='move':groups[a['payload']['aod_group']].append(a)
    found=[]
    for d in groups['data']:
        for m in groups['magic']:
            start=max(d['t_start_us'],m['t_start_us']);end=min(d['t_end_us'],m['t_end_us'])
            if start<end:found.append(dict(start_us=start,end_us=end,data=d['id'],magic=m['id']))
    return found


def active_overlap_us(actions):
    spans=[]
    for g in ('data','magic'):
        spans.append([(a['t_start_us'],a['t_end_us']) for a in actions
            if a['kind'] in ('pickup','move','drop') and a['payload'].get('aod_group')==g])
    intersections=sorted((max(a,c),min(b,d)) for a,b in spans[0] for c,d in spans[1] if max(a,c)<min(b,d))
    total=0.;stop=-1.
    for start,end in intersections:
        total+=max(0,end-max(start,stop));stop=max(stop,end)
    return total


def validate_endpoints_and_pulses(actions, initial):
    """Endpoint/carrier replay and local spatial-bin CZ illumination audit.

    This is NOT the runtime and does not create measurements, tokens or epochs.
    No continuous all-pairs collision qualification is claimed.
    """
    import math
    positions={a['atom_id']:list(a['position_um']) for a in initial}
    carriers={a['atom_id']:a['carrier'] for a in initial}
    endpoints=[];moves=0;pulses=0
    for a in actions:
        if a['kind']=='move':
            endpoints.append((a['t_start_us'],1,a));endpoints.append((a['t_end_us'],0,a))
        elif a['kind'] in ('pickup','drop'):
            endpoints.append((a['t_end_us'],0,a))
        elif a['payload'].get('name')=='CZ':endpoints.append((a['t_start_us'],2,a))
    active=set()
    for _,edge,a in sorted(endpoints,key=lambda x:(x[0],x[1],x[2]['id'])):
        if a['kind']=='move':
            if edge:
                for t in a['payload']['trajectories']:
                    assert positions[t['atom_id']]==t['from_um'],('AB_DISCONTINUITY',a['id'])
                    assert carriers[t['atom_id']]=='AOD'
                active.add(a['id']);moves+=1
            else:
                for t in a['payload']['trajectories']:positions[t['atom_id']]=t['to_um']
                active.remove(a['id'])
        elif a['kind'] in ('pickup','drop'):
            old,new=('SLM','AOD') if a['kind']=='pickup' else ('AOD','SLM')
            for atom in a['atoms']:
                assert carriers[atom]==old
                carriers[atom]=new
        else:
            assert not active,('MOVE_DURING_GLOBAL_CZ',a['id'])
            expected={tuple(sorted(p)) for p in a['payload']['pairs']}
            bins={};actual=set()
            for aid,(x,y) in positions.items():
                if not 0 <= y <= 1000:continue
                cell=(math.floor(x/3),math.floor(y/3))
                for dx in (-1,0,1):
                    for dy in (-1,0,1):
                        for bid in bins.get((cell[0]+dx,cell[1]+dy),[]):
                            bx,by=positions[bid];dist=math.hypot(x-bx,y-by)
                            if dist<=2+1e-7:actual.add(tuple(sorted((aid,bid))))
                bins.setdefault(cell,[]).append(aid)
            assert actual==expected,('CZ_PAIR_SET_CHANGED',a['id'],actual^expected)
            pulses+=1
    return dict(endpoint_moves=moves,global_pulses_checked=pulses,final_positions=positions,final_carriers=carriers)


def schedule_from_compact(d):
    tracks={};occupancy={};loaded={}
    for i,a in enumerate(d['actions']):
        if a[7]!='completed':continue
        lane='activity:'+a[2]
        if a[2] in ('move','pickup','drop'):
            groups={d['atoms'][k][5] for k in a[3]}
            assert len(groups)==1
            lane='aod:'+next(iter(groups))
        elif a[6]=='CZ':lane='rydberg:global'
        elif a[2]=='measure':lane='readout:array'
        elif a[2]=='gate':lane='activity:1q'
        tracks.setdefault(lane,[]).append([a[0],a[1],i,[]])
        if a[2]=='pickup':
            for atom in a[3]:loaded[atom]=(a[1],i)
        if a[2]=='drop':
            for atom in a[3]:
                start,idx=loaded.pop(atom)
                occupancy.setdefault('occupancy:aod:'+d['atoms'][atom][5],set()).add((start,a[1],idx))
    assert not loaded
    return dict(schema_version='ViewerResources/0.1',id=d['id'],end=d['end'],resource_names=[],
        lanes=[dict(id=k,kind='activity' if k.startswith('activity:') else 'declared_resources',intervals=v) for k,v in tracks.items()]+
        [dict(id=k,kind='carrier_occupancy',intervals=[[a,b,i,[]] for a,b,i in sorted(v)]) for k,v in occupancy.items()])


def run(source, baseline, out):
    out.mkdir(parents=True,exist_ok=True)
    viewer=out/'viewer';viewer.mkdir(exist_ok=True)
    inputs=list(sorted((source/'windows').glob('*.json.gz')))+list(sorted((baseline/'data').glob('*.js')))
    inputs += [baseline/n for n in ('manifest.js','fleet.js','acceptance.json')]
    hashes={str(p.relative_to(ROOT)):digest(p) for p in inputs}
    assert read(source/'acceptance.json')['passed']
    manifest=variable(baseline/'manifest.js','COMPONENT_MANIFEST');fleet=variable(baseline/'fleet.js','FACTORY_DEMO')
    windows=[read(source/f'windows/window-{i:04d}.json.gz') for i in range(3)]
    data_modules=[]
    for wi,w in enumerate(windows):
        for m in w['physical_plan']['module_composition']['instances']:
            if any(s.startswith('cnot-demo:') for s in m['source_ids']):
                acts=module_actions(w,m)
                data_modules.append((wi,m,acts))
    assert len(data_modules)==6
    magic_modules=[m for m in windows[0]['physical_plan']['module_composition']['instances']
        if m['kind']=='entangling_layer' and not any(s.startswith('cnot-demo:') for s in m['source_ids'])][:6]
    removed=[];edits=[];pairs=[];data_times={};data_ids=set()
    for (wi,dm,da),mm in zip(data_modules,magic_modules):
        start=min(a['t_start_us'] for a in da);end=max(a['t_end_us'] for a in da)
        removed.append((start,end));data_ids.update(a['id'] for a in da)
        ma=module_actions(windows[0],mm);ms=min(a['t_start_us'] for a in ma);me=max(a['t_end_us'] for a in ma)
        offsets,span,wait=link_pair(da,ma)
        edits.append((me,span-(me-ms)))
        pairs.append(dict(data_module=dm['instance_id'],magic_module=mm['instance_id'],magic_start_old=ms,
            module_hashes=[dm['module_hash'],mm['module_hash']],wait=wait,offsets=offsets,
            logical_id=dm['source_ids'][0].split('/op:')[0]))
    # Monotone magic-controller clock map: remove data-only blocks and insert
    # shared-resource waits after selected compiled factory leaves.
    def warp(t):
        return t-sum(max(0,min(t,e)-s) for s,e in removed if t>s)+sum(delta for at,delta in edits if t>=at-1e-8)
    for (_,dm,da),pair in zip(data_modules,pairs):
        origin=warp(pair['magic_start_old'])
        pair['start_us']=origin
        for a in da:
            shift=origin+pair['offsets'][a['id']]
            data_times[a['id']]=(a['t_start_us']+shift,a['t_end_us']+shift)
        pair['end_us']=max(data_times[a['id']][1] for a in da)
    # A factory action ending exactly at an insertion precedes that wait.
    def magic_times(a):
        duration=a['t_end_us']-a['t_start_us'];start=warp(a['t_start_us'])
        return start,start+duration
    raw_actions=[];original_by_id={};new_by_id={};native_mapping={}
    for wi,w in enumerate(windows):
        raw=sorted(w['atom_program']['actions'],key=lambda a:(a['t_start_us'],a['t_end_us']))
        native_mapping[wi]=raw
        for a in raw:
            original_by_id[a['id']]=a
            b=deepcopy(a);b['t_start_us'],b['t_end_us']=data_times.get(a['id'],magic_times(a))
            new_by_id[a['id']]=b
            if wi==0 or a['id'] in data_ids:raw_actions.append(b)
    # Only compiler-added scene barriers may change; native leaf dependencies
    # and logical wire order remain. Preserve them in the new plan explicitly.
    for a in raw_actions:
        a['depends_on']=[dep for dep in a['depends_on'] if dep.split('/action:')[0]==a['id'].split('/action:')[0]]
    for p in pairs:
        da=[a for a in raw_actions if a['id'].startswith(p['data_module']+'/')]
        ma=[a for a in raw_actions if a['id'].startswith(p['magic_module']+'/')]
        dc=next(a for a in da if a['payload'].get('name')=='CZ')
        mc=next(a for a in ma if a['payload'].get('name')=='CZ')
        first=min((a for a in da if a['kind']=='move'),key=lambda a:a['t_start_us'])
        first['depends_on'].append(mc['id'])
        dc['depends_on'] += [a['id'] for a in ma if a['t_end_us']==max(b['t_end_us'] for b in ma)]
    for a in raw_actions:
        assert all(new_by_id[dep]['t_end_us']<=a['t_start_us']+1e-8 for dep in a['depends_on'])
        original=original_by_id[a['id']]
        assert a['t_end_us']-a['t_start_us']==original['t_end_us']-original['t_start_us']
        assert a['payload']==original['payload'] and a['atoms']==original['atoms'] and a['source_ids']==original['source_ids']
    check_resources(raw_actions)
    check=validate_endpoints_and_pulses(raw_actions,windows[0]['atom_program']['initial_state']['atoms'])
    overlap=overlap_intervals(raw_actions);assert overlap
    for previous,current in zip(pairs,pairs[1:]):assert previous['end_us']<=current['start_us']+1e-8
    # Copy viewer assets only. All event receipts and runtime files stay at the
    # original run. The new directory holds a compiled scheduling projection.
    for path in baseline.iterdir():
        if path.is_file() and path.suffix in ('.js','.css','.html'):shutil.copyfile(path,viewer/path.name)
    (viewer/'data').mkdir(exist_ok=True)
    datasets={};old_datasets={}
    for row in manifest['components']:
        key=row['id'];old=variable(baseline/row['data_path'],'COMPONENT_DATA['+json.dumps(key)+']')
        old_datasets[key]=old;datasets[key]=deepcopy(old);datasets[key]['actions']=[]
    for wi,(key,old) in enumerate(old_datasets.items()):
        origin=old['absolute_origin_us'];d=datasets[key];new_origin=warp(origin)
        d['absolute_origin_us']=new_origin;d['end']=warp(origin+old['end'])-new_origin
        d['execution_kind']='frozen_fake_branch_schedule_preview';d['runtime_reexecuted']=False
        for phase in d['phases']:
            phase['start_us']=warp(origin+phase['start_us'])-new_origin;phase['end_us']=warp(origin+phase['end_us'])-new_origin
        for result in d['results']:result['ready_us']=warp(origin+result['ready_us'])-new_origin
        for ev in d.get('frame_events',[]):
            for field in ('time_us','start_us','end_us'):ev[field]=warp(origin+ev[field])-new_origin
        for ai,compact in enumerate(old['actions']):
            a=deepcopy(compact);target=d
            if wi<3:
                raw=native_mapping[wi][ai]
                assert [raw['t_start_us']-origin,raw['t_end_us']-origin,raw['kind']]==a[:3]
                times=data_times.get(raw['id'],magic_times(raw))
                if raw['id'] in data_ids:
                    target=datasets['WINDOW_0000']
                    indices=[]
                    for idx in a[8]:
                        sid=old['sources'][idx]
                        if sid not in target['sources']:
                            target['sources'].append(sid);target['source_meta'].append(old['source_meta'][idx])
                        indices.append(target['sources'].index(sid))
                    a[8]=indices
            else:
                start=warp(origin+a[0]);times=(start,start+a[1]-a[0])
            a[0],a[1]=[t-target['absolute_origin_us'] for t in times]
            target['actions'].append(a)
    schedules={};packed_data={}
    for row in manifest['components']:
        key=row['id'];d=datasets[key];d['actions'].sort(key=lambda a:(a[0],a[1]));d['raw_action_count']=len(d['actions'])
        row.update(duration_us=d['end'],absolute_origin_us=d['absolute_origin_us'],action_count=len(d['actions']),
            executed_action_count=0,scheduled_action_count=len(d['actions']),version_status='冻结动作重排 · 零电路重编译',
            scope='复用原运行的显式 fake 分支；本次为合并时间表，未重新执行运行时。')
        if key=='WINDOW_0000':row['label']='01 · 双 AOD 并行 · 三轮 CNOT + 工厂生产'
        elif key in ('WINDOW_0001','WINDOW_0002'):row['label']=f'{int(key[-4:])+1:02d} · 工厂继续生产 · data 等待 T'
        if key in ('WINDOW_0000','WINDOW_0001','WINDOW_0002'):
            for phase in d['phases']:phase['label']=row['label']
        schedules[key]=packed(schedule_from_compact(d));packed_data[key]=packed(d)
        putvar(viewer/row['data_path'],'COMPONENT_DATA['+json.dumps(key)+']',d)
        # Ensure the registry exists before the lazy-loaded data assignment.
        path=viewer/row['data_path'];path.write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};'+path.read_text(encoding='utf-8'),encoding='utf-8')
    manifest['highlights']=[dict(window='WINDOW_0000',label='双 AOD · 第'+str(i//2+1)+'轮 CNOT '+str(i%2+1),start_us=p['start_us'],end_us=p['end_us']) for i,p in enumerate(pairs)] + [
        dict(h, start_us=warp(old_datasets[h['window']]['absolute_origin_us']+h['start_us'])-datasets[h['window']]['absolute_origin_us'],
            end_us=warp(old_datasets[h['window']]['absolute_origin_us']+h['end_us'])-datasets[h['window']]['absolute_origin_us'])
        for h in manifest['highlights'] if 'T ' in h['label']]
    manifest['pipeline'].update(duration_us=warp(manifest['pipeline']['duration_us']),scoped_prefix_passed=False,schedule_link_passed=True)
    for stage in fleet['stages']:
        for f in ('start_us','end_us'):stage[f]=warp(stage[f])
    for event in fleet['fleet']['history']:
        if 'time_us' in event:event['time_us']=warp(event['time_us'])
        if 'receipt' in event:event['receipt']['end_us']=warp(event['receipt']['end_us'])
    for state in fleet['logical'].values():
        for field in ('completed_us','submitted_us'):
            if field in state:state[field]=warp(state[field])
    for p in pairs:fleet['logical'][p['logical_id']]['completed_us']=p['end_us']
    for req in fleet['requests']:
        for f in ('submitted_us','reserved_us','completed_us'):
            if req.get(f) is not None:req[f]=warp(req[f])
        req['submitted_us']=pairs[-1]['end_us']
        assert req['reserved_us']>=req['submitted_us']
    fleet['schedule_projection']=True
    putvar(viewer/'fleet.js','FACTORY_DEMO',fleet)
    putvar(viewer/'manifest.js','COMPONENT_MANIFEST',manifest)
    with (viewer/'manifest.js').open('a',encoding='utf-8') as f:f.write('\n'+(viewer/'fleet.js').read_text(encoding='utf-8'))
    putvar(viewer/'schedules.js','COMPONENT_SCHEDULE_PACKED',schedules)
    report=dict(schema_version='FrozenDualAODLink/0.1',passed=True,scope='compiled_schedule_and_animation_only',
        runtime_reexecuted=False,physical_executed=False,fake_branch_reused=True,new_tokens_minted=0,
        native_compilation_calls=0,placement_calls=0,routing_calls=0,batch_selection_calls=0,
        source_action_count=sum(len(d['actions']) for d in old_datasets.values()),
        linked_action_count=sum(len(d['actions']) for d in datasets.values()),atom_count=769,
        logical_requests=7,source_duration_us=952465.5,duration_us=manifest['pipeline']['duration_us'],
        dual_aod_move_overlap_us=sum(v['end_us']-v['start_us'] for v in overlap),overlaps=overlap,
        dual_aod_active_overlap_us=active_overlap_us(raw_actions),
        action_bodies_unchanged=True,cz_batches_unchanged=True,source_inputs_sha256=hashes,
        source_inputs_unchanged=all(digest(ROOT/p)==h for p,h in hashes.items()),
        checks={k:v for k,v in check.items() if not k.startswith('final_')},
        continuous_all_pairs_check=False,user_visual_acceptance='pending',pairs=pairs,
        limitations=['Fixed fake branch schedule projection; original execution receipts are not reissued.',
          'Four factory lines share the existing magic AOD; only data/magic concurrency is changed.'])
    assert report['source_inputs_unchanged'] and report['source_action_count']==report['linked_action_count']
    write(out/'schedule-link.json',report);write(viewer/'acceptance.json',report)
    write(viewer/'prefix.json',read(baseline/'prefix.json'))
    write(viewer/'calls.json',manifest['components'])
    (out/'linked-first-window.json.gz').write_bytes(gzip.compress(json.dumps(dict(actions=raw_actions,pairs=pairs),separators=(',',':')).encode(),compresslevel=1,mtime=0))
    # Live lane status distinguishes motion, transfer, and resource waiting.
    js=(viewer/'components.js').read_text(encoding='utf-8')
    js=js.replace('等待下一个实际事件','等待下一计划动作').replace('正在载入实际轨迹','正在载入合并时间表')
    js=js.replace('此历史工件没有本轮模块化验收记录','本次仅链接已有动作；电路编译 / 布局 / 路由调用均为 0')
    js=js.replace('模块引用只保存编译动作；测量值、token及epoch来自本次事件会话。','测量分支、token 与 epoch 引用原运行；本页只重新排程，没有签发新的执行回执。')
    js=js.replace('function render(){if(!data)return;', 'function render(){if(!data)return;renderDualAOD();')
    inspect_at=(overlap[0]['start_us']+overlap[0]['end_us'])/2
    js=js.replace('prepare(d);','prepare(d);if(inspectParallel){inspectParallel=false;storyIndex=-1;playRange=null;setTime('+str(inspect_at)+');playing=false;playState();}')
    js+='\nlet inspectParallel=false;document.getElementById("inspect-parallel").onclick=()=>{pendingHighlight=null;inspectParallel=true;showRow(MANIFEST.components[0]);};\n'
    js+='''\nfunction renderDualAOD(){
 const lines=[];for(const g of ['data','magic']){
  const active=data.actions.filter(a=>a[7]==='completed'&&a[0]<=current&&current<a[1]&&['move','pickup','drop'].includes(a[2])&&a[3].some(i=>data.atoms[i][5]===g));
  const kinds=[...new Set(active.map(a=>({move:'搬运',pickup:'SLM → AOD',drop:'AOD → SLM'})[a[2]]))];
  let waiting='等待共享资源 / 保持';const t=current+(data.absolute_origin_us||0),f=window.FACTORY_DEMO;
  if(g==='data'&&Object.entries(f.logical).filter(([id,s])=>id!=='cnot-demo:6'&&s.completed_us<=t).length===6){waiting=f.requests[0].completed_us<=t?'T 消费完成':f.requests[0].reserved_us<=t?'T 消费：等待下一动作':'三轮 CNOT 完成 · 等待 magic 就绪';}
  lines.push('AOD '+g+'：'+(kinds.join(' / ')||waiting));
 }document.getElementById('dual-aod-live').textContent=lines.join('\\n');
}\n'''
    (viewer/'components.js').write_text(js,encoding='utf-8')
    shell=(baseline/'index.html').read_text(encoding='utf-8')
    shell=shell.replace('三轮 CNOT → T 注入','双 AOD 并行 · CNOT → T 注入')
    shell=shell.replace('播放三轮 CNOT → T 注入（摘要）','播放双 AOD 并行 → T 注入')
    shell=shell.replace('<strong>工厂与 data</strong>', '<strong>工厂与 data</strong><pre id="dual-aod-live" style="line-height:1.8;color:#365c6a"></pre>')
    shell=shell.replace('<button id="view-layout">','<button id="inspect-parallel">定位双 AOD 同时搬运</button><button id="view-layout">')
    shell=shell.replace('摘要只跳过显示时间；下方保留全部工厂生产与资源 schedule。','双 AOD 使用同一合并时间表。保留全部原子动作和 CZ 批次；在共享激光与 T 就绪处等待。')
    shell=shell.replace('测量为显式 fake 场景。','本次为冻结 fake 分支的重新排程预览；没有重新编译电路或重演运行时。')
    shell=shell.replace('实际运行窗口','合并时间表窗口').replace('限定工程验收','时间表合并检查')
    (viewer/'index.html').write_text(shell,encoding='utf-8')
    standalone=shell.replace('<link rel="stylesheet" href="components.css">','<style>'+(viewer/'components.css').read_text(encoding='utf-8')+'</style>')
    standalone=standalone.replace('<script src="manifest.js"></script>',''.join('<script type="application/octet-stream" id="packed-'+k+'">'+v+'</script>' for k,v in packed_data.items())+'<script src="manifest.js"></script>')
    for name in ('fleet.js','manifest.js','schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        standalone=standalone.replace('<script src="'+name+'"></script>','<script>'+(viewer/name).read_text(encoding='utf-8')+'</script>')
    for name in ('animation-library.html','full-viewer.html'):(viewer/name).write_text(standalone,encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('passed','linked_action_count','duration_us','dual_aod_move_overlap_us','native_compilation_calls')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=ROOT/'artifacts/deliveries/dual-aod-linked-20261009')
    args=parser.parse_args()
    with CompilationGuard() as guard:
        run(ROOT/'artifacts/qualification/cnot-t-bottom-20261009/run-v1',ROOT/'artifacts/deliveries/cnot-t-bottom-20261009/viewer',args.out)
        write(args.out/'compilation-guard.json',guard.receipt())
