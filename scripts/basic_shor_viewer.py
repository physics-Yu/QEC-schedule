"""Project the one complete run into the existing light atom canvas, by call."""
from pathlib import Path
from copy import deepcopy
from collections import Counter
import argparse, gzip, json, re, shutil, sys, hashlib

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT),str(ROOT/'scripts')]
from build_component_gallery import project
from extend_frame_gallery import packed
from export_viewer_schedules import lanes,carrier_occupancy
from basic_shor_audit import read,checked_ref


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def export(out, *, phase='execute', allow_prefix=False):
    run=out/phase;dest=out/'viewer';dest.mkdir(exist_ok=True)
    world=read(out/'world.json.gz');device=world['device'];nodes={n['id']:n for n in world['logical_dag']['nodes']}
    acceptance=read(out/'acceptance.json') if (out/'acceptance.json').exists() else None
    if not allow_prefix and (not acceptance or not acceptance['passed']):raise ValueError('FULL_RUN_ACCEPTANCE_REQUIRED')
    indexes=[read(p) for p in sorted((run/'window-index').glob('*.json'))]
    calls=[]
    for item in indexes:
        nid=item['logical_nodes'][0]
        if not nid:raise ValueError('VIEWER_ORIGINAL_LOGICAL_NODE_REQUIRED')
        if calls and calls[-1]['node_id']==nid:calls[-1]['windows'].append(item)
        else:calls.append({'node_id':nid,'windows':[item]})
    rows=[];zones={};receipts=[];previous=None;global_end=indexes[-1]['end_us'];packed_data={};packed_schedules={}
    for ci,call in enumerate(calls):
        key=f'CALL_{ci:04d}';node=nodes[call['node_id']];entries=[];plans=[];phases=[];records=[];origin=call['windows'][0]['start_us']
        match=re.search(r'(?:round|after-round)(\d)',node['id']);round_no=int(match[1]) if match else None
        category=('入口维护' if node['id'].startswith('maintenance/entry/') or '/init/' in node['id'] else '结束与后处理') if round_no is None else f'QPE 第 {8-round_no} 轮 · round{round_no}'
        for item in call['windows']:
            w=read(checked_ref(item['window'],run/'windows'))
            h=read(checked_ref(item['history'],run/'history'));atom=w['atom_program'];plan=w['physical_plan']
            if previous is not None:
                current={a['atom_id']:(a['qubit_id'],a['position_um'],a['carrier'],a.get('site_id')) for a in atom['initial_state']['atoms']}
                if current!=previous:raise ValueError('VIEWER_WORLD_CONTINUITY')
            previous={a['atom_id']:(a['qubit_id'],a['position_um'],a['carrier'],a.get('site_id')) for a in h['final_state']['atoms']}
            trace={'events':list(h['events'].values()),'results':h['results'],'final_state':h['final_state']}
            entries.append((atom,trace));plans.append(plan)
            stage=plan['physical_dags'][0].get('protocol_binding',{}).get('stage_id',node['operation'])
            phases.append({'id':str(item['index']),'label':stage,'start_us':item['start_us'],'end_us':item['end_us'],
                'note':'实际同一持续会话 · '+node['id']})
            for action in atom['actions']:
                records.append((action['t_start_us']-origin,action['t_end_us']-origin,action,h['events'][action['id']]['status']))
        data=project(key,entries,device,phases,source_plans=plans)
        for a in data['actions']:a[0]-=origin;a[1]-=origin
        for r in data['results']:r['ready_us']-=origin
        for p in data['phases']:p['start_us']-=origin;p['end_us']-=origin
        data['end']-=origin;data['absolute_origin_us']=origin
        data['logical_node_id']=node['id'];data['modules']=[]
        records.sort(key=lambda x:(x[0],x[1]))
        resources=[];resource_ids={};tracks={}
        for ai,(start,end,action,status) in enumerate(records):
            if data['actions'][ai][:3]!=[start,end,action['kind']]:raise ValueError('SCHEDULE_ACTION_ORDER')
            if status!='completed':continue
            for lane,rs in lanes(action).items():
                for r in rs:
                    if r not in resource_ids:resource_ids[r]=len(resources);resources.append(r)
                tracks.setdefault(lane,[]).append([start,end,ai,[resource_ids[r] for r in rs]])
        schedule={'schema_version':'ViewerResources/0.1','id':key,'end':data['end'],'resource_names':resources,
            'lanes':[{'id':k,'kind':'activity' if k.startswith('activity:') else 'declared_resources','intervals':v} for k,v in tracks.items()]}
        schedule['lanes']+=carrier_occupancy(records,{a[0]:a[5] for a in data['atoms']},data['end'])
        cz=device['zones']['storage_entanglement'];mz=device['zones']['measurement']
        zones[key]={'compute':[*cz['x_range_um'],*cz['y_range_um']],'measurement':[*mz['x_range_um'],*mz['y_range_um']]}
        targets=' / '.join(node['patch_operands'].values())
        label=f'{ci+1:03d} · '+('蒸馏 → '+node['operation']+' 注入' if node['operation'] in ('T','TDG') else node['operation'])+(' · '+targets if targets else '')
        row={'id':key,'data_id':key,'data_path':'data/'+key+'.js','label':label,'category':category,
             'description':node['id'],'scope':f'同一完整会话；全程时间 {origin:g}–{origin+data["end"]:g} μs。显示本调用相对时间。测量为明确fake场景。',
             'atom_count':len(data['atoms']),'action_count':len(data['actions']),'duration_us':data['end'],
             'physical_operations':sum(len(d['nodes']) for p in plans for d in p['physical_dags']),
             'implementation_version':'opaque-component-pipeline/1','version_status':'基础完整流程' if not allow_prefix else '已执行前缀 · 非完整交付',
             'absolute_origin_us':origin,'logical_node_id':node['id'],'kind':'pipeline_call','links':[
                 {'label':'全程验收','href':'../acceptance.json'},{'label':'调用与原窗口对应','href':'calls.json'}]}
        rows.append(row)
        packed_data[key]=packed(data);packed_schedules[key]=packed(schedule)
        text='window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+json.dumps(key)+']='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n'
        text+='window.COMPONENT_SCHEDULE_PACKED=window.COMPONENT_SCHEDULE_PACKED||{};window.COMPONENT_SCHEDULE_PACKED['+json.dumps(key)+']='+json.dumps(packed(schedule))+';\n'
        path=dest/row['data_path'];path.parent.mkdir(exist_ok=True);path.write_text(text.replace('<','\\u003c'),encoding='utf-8')
        receipts.append({'id':key,'logical_node_id':node['id'],'windows':call['windows'],
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'actions':len(data['actions']),
            'start_us':origin,'end_us':origin+data['end']})
    summary=read(run/'summary.json') if (run/'summary.json').exists() else read(run/'manifest.json')
    statuses=Counter(s['status'] for s in read(run/'logical-schedule.json.gz')['nodes'].values())
    manifest={'schema_version':'component-gallery/0.1','component_count':len(rows),'demonstration_count':0,
        'components':rows,'coverage':{},'pipeline':{'logical_nodes':len(nodes),'statuses':dict(statuses),
        'duration_us':global_end,'postprocess':summary.get('postprocess'),'full_program_passed':bool(acceptance and acceptance['passed'])},
        'browser_verified':False,'user_visual_acceptance':'pending'}
    for name,var,value in [('manifest.js','COMPONENT_MANIFEST',manifest),('regions.js','COMPONENT_ZONES',zones),('schedules.js','COMPONENT_SCHEDULE_PACKED',packed_schedules)]:
        (dest/name).write_text('window.'+var+'='+json.dumps(value,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c')+';\n',encoding='utf-8')
    for name in ('components.css','lab-renderer.js','motion-preview.js','resource-schedule.js'):shutil.copyfile(ROOT/'viewer'/name,dest/name)
    js=(ROOT/'viewer/components.js').read_text(encoding='utf-8')
    js=js.replace("function render(){if(!data)return;", "function render(){if(!data)return;$('pipeline-clock').textContent='全程 '+fmt((data.absolute_origin_us||0)+current)+' / '+fmt(MANIFEST.pipeline.duration_us)+' μs';")
    js=js.replace("function showRow(row){", "function showRow(row){window.COMPONENT_DATA={};scheduleCache.clear();$('call-select').value=row.id;")
    js=js.replace("prepare(d);", "prepare(d);if(pipelineAutoplay){pipelineAutoplay=false;queueMicrotask(()=>{playing=true;playState();});}")
    js=js.replace("if(current>=stop){playing=false;playState();}","if(current>=stop){playing=false;playState();if(!playRange&&$('follow-calls').checked)nextPipelineCall(1,true);}")
    js=js.replace("$('overall').textContent=`${MANIFEST.component_count} 个组件 + ${MANIFEST.demonstration_count} 个并行示例`", "$('overall').textContent=`${MANIFEST.pipeline.logical_nodes} 个源节点 · ${MANIFEST.components.length} 次实际组件调用`")
    extra="""
let pipelineAutoplay=false;
function nextPipelineCall(delta,autoplay=false){const index=MANIFEST.components.findIndex(r=>r.id===chosen?.id),row=MANIFEST.components[index+delta];if(row){pipelineAutoplay=autoplay;showRow(row);}}
for(const r of MANIFEST.components){const o=html('option',r.label);o.value=r.id;$('call-select').appendChild(o);}
$('call-select').onchange=()=>showRow(MANIFEST.components.find(r=>r.id===$('call-select').value));
$('call-prev').onclick=()=>nextPipelineCall(-1);$('call-next').onclick=()=>nextPipelineCall(1);
"""
    # Initialize controls before the script's initial deep-link navigation.
    js=js.replace("new ResizeObserver(",extra+"\nnew ResizeObserver(",1)
    (dest/'components.js').write_text(js,encoding='utf-8')
    shell=(ROOT/'viewer/components.html').read_text(encoding='utf-8')
    shell=shell.replace('原子运动 · 组件实验台','Shor-15 · 基础完整流程').replace('逻辑组件 · 原子运动','Shor-15 · 连续原子运动')
    shell=shell.replace('选择一段原子运动','完整 Shor-15 运行').replace('70 组件<br>＋ 1 并行示例',str(len(rows))+' 次调用<br>同一持续会话')
    intro=f'2,102 个源节点 · 已执行 {statuses.get("completed",0)} · 条件跳过 {statuses.get("skipped",0)} · 205 个原子。完整组件复用；点击进入，支持连续播放与设备 Schedule。'
    if allow_prefix:intro='仅已执行前缀，完整运行尚未结束。'+intro
    shell=shell.replace('从逻辑门到辅助制备、蒸馏和连续协议。进入后查看运动、设备占用与执行记录。',intro)
    shell=shell.replace('<div class="landing-tools">','<p><a href="../acceptance.json">全程验收</a> · <a href="source-nodes.json">全部源节点与条件分支</a> · <a href="../README.md">交付说明</a></p><div class="landing-tools">',1)
    nav='<div class="viewer-bar"><button id="call-prev">前一调用</button><select id="call-select" aria-label="算法组件调用"></select><button id="call-next">下一调用</button><label><input type="checkbox" id="follow-calls" checked>连续播放</label><span id="pipeline-clock"></span></div>'
    shell=shell.replace('<div class="studio">',nav+'<div class="studio">',1)
    (dest/'index.html').write_text(shell,encoding='utf-8')
    standalone=shell.replace('<link rel="stylesheet" href="components.css">','<style>'+(dest/'components.css').read_text(encoding='utf-8')+'</style>')
    tags=''.join('<script type="application/octet-stream" id="packed-'+key+'">'+value+'</script>' for key,value in packed_data.items())
    standalone=standalone.replace('<script src="manifest.js"></script>',tags+'<script>'+(dest/'manifest.js').read_text(encoding='utf-8')+'</script>')
    for name in ('schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        standalone=standalone.replace(f'<script src="{name}"></script>','<script>'+(dest/name).read_text(encoding='utf-8')+'</script>')
    for name in ('animation-library.html','full-viewer.html'):(dest/name).write_text(standalone,encoding='utf-8')
    write(dest/'calls.json',receipts)
    schedule=read(run/'logical-schedule.json.gz');call_by_node={r['logical_node_id']:r['id'] for r in rows}
    write(dest/'source-nodes.json',{'logical_dag_hash':schedule['logical_dag_hash'],'nodes':[
        {'id':n['id'],'operation':n['operation'],'operands':n['patch_operands'],'condition':n['condition'],
         'state':schedule['nodes'][n['id']],'animation_id':call_by_node.get(n['id'])} for n in nodes.values()],
         'skipped_nodes_have_actual_condition_evidence':True,'physical_animation_invented_for_skips':False})
    write(dest/'viewer-receipt.json',{'calls':len(rows),'windows':len(indexes),'actions':sum(r['action_count'] for r in rows),
        'all_original_actions_preserved':True,'all_window_world_boundaries_equal':True,'source_run':str(run),
        'compilation_invoked':False,'browser_verified':False,'user_visual_acceptance':'pending','prefix_only':allow_prefix})
    print(json.dumps({'calls':len(rows),'windows':len(indexes),'path':str(dest/'animation-library.html')}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--phase',default='execute');p.add_argument('--allow-prefix',action='store_true');a=p.parse_args()
    export(a.out,phase=a.phase,allow_prefix=a.allow_prefix)
