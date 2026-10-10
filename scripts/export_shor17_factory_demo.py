"""Display-only export of the checked four-factory run, using the existing UI."""
from pathlib import Path
import argparse
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from build_component_gallery import project, read, write
from extend_frame_gallery import packed
from export_viewer_schedules import lanes, carrier_occupancy


def export(run, out, *, allow_prefix=False):
    completed_paths=sorted((run/'fleet').glob('window-*.json.gz'))
    if not completed_paths:raise ValueError('NO_COMMITTED_WINDOWS')
    if allow_prefix:
        reports=[read(run/'validation'/(p.stem.removesuffix('.json')+'.json')) for p in completed_paths]
        if any(not r['physical']['passed'] or not r['binding']['passed'] for r in reports):
            raise ValueError('UNCHECKED_WINDOW_PREVIEW')
        acceptance={'passed':False,'scope':'debug_preview_of_checked_windows_only','full_prefix_acceptance':'pending',
                    'checked_windows':len(reports),'user_visual_acceptance':'pending'}
    else:
        acceptance = read(run/'acceptance.json')
        if not acceptance['passed']:raise ValueError('CHECKED_PREFIX_REQUIRED')
    out.mkdir(parents=True, exist_ok=True)
    device, layout, prefix = (read(run/n) for n in ('device.json', 'layout.json', 'prefix.json'))
    final = read(completed_paths[-1] if allow_prefix else run/'final-fleet.json.gz')
    rows, compressed, schedules, zones, stage_intervals = [], {}, {}, {}, []
    for i, path in enumerate([run/'windows'/p.name for p in completed_paths]):
        w = read(path)
        trace = read(run/'traces'/path.name)
        plan, atom = w['physical_plan'], w['atom_program']
        by_action={a['id']:a for a in atom['actions']}
        for work in w['fleet_work']:
            own={a for n in work['physical_dag']['nodes'] for a in atom['source_map'][n['id']]}
            stage_intervals.append({'factory_id':work['factory_id'],'epoch':work['epoch'],'stage_id':work['stage_id'],
                'start_us':min(by_action[a]['t_start_us'] for a in own),
                'end_us':max([by_action[a]['t_end_us'] for a in own]+[trace['results'][r]['ready_us'] for r in work['physical_dag']['result_producers']])})
        key = f'WINDOW_{i:04d}'
        origin = w['context']['time_us']
        stages = [r['factory_id']+' · '+r['stage_id'] for r in w['fleet_work']]
        logical = [o['operation']+' '+','.join(o['patches']) for o in w['logical_operations']]
        label = ' / '.join(logical) if logical else '四工厂生产'
        if any(r['stage_id'].startswith('consume') for r in w['fleet_work']):
            label = 'Magic → Data · 消费与其他工厂生产'
        phases = [{'id': str(i), 'label': label, 'start_us': origin, 'end_us': trace['stats']['t_end_us'],
                   'note': '; '.join(stages)}]
        d = project(key, [(atom, trace)], device, phases, source_plans=[plan])
        for action in d['actions']:
            action[0] -= origin
            action[1] -= origin
        for result in d['results']:
            result['ready_us'] -= origin
        for phase in d['phases']:
            phase['start_us'] -= origin
            phase['end_us'] -= origin
        d['end'] -= origin
        bounds=d['bounds']
        d.update(absolute_origin_us=origin, modules=[], layout=layout,
                 bounds=[min(-40,bounds[0]),max(1400,bounds[1]),min(400,bounds[2]),max(1240,bounds[3])], logical_node_id=key)
        event = {e['action_id']: e for e in trace['events']}
        records = sorted([(a['t_start_us']-origin, a['t_end_us']-origin, a, event[a['id']]['status'])
                          for a in atom['actions']], key=lambda a: (a[0], a[1]))
        resources, resource_ids, tracks = [], {}, {}
        for ai, (begin, end, action, status) in enumerate(records):
            if status != 'completed':
                continue
            for lane, rs in lanes(action).items():
                for r in rs:
                    if r not in resource_ids:
                        resource_ids[r] = len(resources)
                        resources.append(r)
                tracks.setdefault(lane, []).append([begin, end, ai, [resource_ids[r] for r in rs]])
        schedule = {'schema_version': 'ViewerResources/0.1', 'id': key, 'end': d['end'],
            'resource_names': resources, 'lanes': [{'id': k, 'kind': 'activity' if k.startswith('activity:') else 'declared_resources',
                'intervals': v} for k, v in tracks.items()]}
        schedule['lanes'] += carrier_occupancy(records, {a[0]: a[5] for a in d['atoms']}, d['end'])
        compressed[key], schedules[key] = packed(d), packed(schedule)
        zones[key] = {'compute': [None, None, 0, 1000], 'measurement': [None, None, 1020, 1220]}
        row = {'id': key, 'data_id': key, 'data_path': 'data/'+key+'.js', 'label': f'{i+1:02d} · '+label,
            'category': '工厂与 data 消费' if '消费' in label else '工厂与算法运行',
            'description': '; '.join(stages), 'scope': '同一769原子会话的实际动作和显式fake测量事件。',
            'atom_count': 769, 'action_count': len(d['actions']), 'duration_us': d['end'],
            'executed_action_count': sum(a[7]=='completed' for a in d['actions']),
            'physical_operations': sum(len(g['nodes']) for g in plan['physical_dags']),
            'implementation_version': 'shor17-prefix-fleet/1', 'version_status': '已执行窗口 · 小演示尚未完成' if allow_prefix else '小演示工程检查通过',
            'absolute_origin_us': origin, 'logical_node_id': key, 'kind': 'pipeline_call',
            'links': [{'label': '限定验收报告', 'href': 'acceptance.json'}, {'label': '16个原始操作', 'href': 'prefix.json'}]}
        rows.append(row)
        target = out/row['data_path']
        target.parent.mkdir(exist_ok=True)
        target.write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+
                          json.dumps(key)+']='+json.dumps(d, ensure_ascii=False, separators=(',', ':')).replace('<','\\u003c')+';', encoding='utf-8')
    manifest = {'schema_version': 'component-gallery/0.1', 'component_count': len(rows), 'demonstration_count': 0,
        'components': rows, 'coverage': {}, 'pipeline': {'logical_nodes': 16, 'duration_us': final['time_us'],
            'full_program_passed': False, 'scoped_prefix_passed': not allow_prefix},
        'browser_verified': False, 'user_visual_acceptance': 'pending'}
    history=[]
    for e in final['history']:
        row={k:v for k,v in e.items() if k in ('event','factory_id','time_us','epoch','target_patch','gate','request_id','token_id')}
        if 'receipt' in e:row['receipt']={k:e['receipt'][k] for k in ('stage_id','end_us')}
        history.append(row)
    logical_states = read(run/'checkpoint.json.gz')['logical_states'] if allow_prefix else read(run/'logical-states.json')
    extra_data = {'layout': layout, 'prefix': prefix, 'fleet': {'history':history},
                  'logical': {k:{a:b for a,b in v.items() if a!='actions'} for k,v in logical_states.items()},
                  'stages':stage_intervals,'requests':[{k:v for k,v in r.items() if k in ('request_id','gate','target_patch','submitted_us','reserved_us','completed_us','factory_id','token_id')} for r in final['requests'].values()]}
    values = [('manifest.js','COMPONENT_MANIFEST',manifest), ('regions.js','COMPONENT_ZONES',zones),
              ('schedules.js','COMPONENT_SCHEDULE_PACKED',schedules), ('fleet.js','FACTORY_DEMO',extra_data)]
    for name, variable, value in values:
        (out/name).write_text('window.'+variable+'='+json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<','\\u003c')+';', encoding='utf-8')
    # The established DOM harness loads manifest.js as the viewer entry.
    with (out/'manifest.js').open('a',encoding='utf-8') as stream:
        stream.write('\n'+(out/'fleet.js').read_text(encoding='utf-8'))
    for name in ('components.css', 'motion-preview.js', 'resource-schedule.js'):
        shutil.copyfile(ROOT/'viewer'/name, out/name)
    with (out/'components.css').open('a',encoding='utf-8') as stream:
        stream.write('\n:root{--data:#40586b;--xanc:#68a49b;--zanc:#8c9cbd;}\n.pipeline-nav{flex-wrap:wrap}.pipeline-nav button,.pipeline-nav label{white-space:nowrap;flex-shrink:0}#call-select{flex:1;min-width:100px;width:240px;max-width:100%}#pipeline-clock{font-size:11px}#fleet-live{padding:4px 0}.fleet-panel{padding:12px}#magic-demand{font-size:12px;color:#4d7160;white-space:pre-line}\n')
    renderer = (ROOT/'viewer/lab-renderer.js').read_text(encoding='utf-8')
    overlay = """
 if(options.zones&&d.layout){
  for(const [id,name,color]of [['compute','Compute zone','#e7eef4'],['magic','Magic factory zone','#edf2ef']]){
   const z=d.layout.regions[id];add('rect',{x:z[0],y:z[1],width:z[2]-z[0],height:z[3]-z[1],fill:active.some(a=>a[6]==='CZ')?'#edb6ad':color,stroke:'#ccd8df','stroke-width':.6,'data-layout-region':id});text(z[0]+6,z[3]+12,name,'#526a78',20);
  }
  for(const p of d.layout.patches)add('rect',{x:p.anchor_um[0],y:p.anchor_um[1],width:80,height:80,fill:'none',stroke:p.output_carrier?'#80a595':'#c3cfd8','stroke-width':.65,'data-patch':p.id});
  for(const f of d.layout.factories)text(f.bounds_um[0]-22,f.origin_um[1]+42,f.id,'#59796b',16);
 }
"""
    renderer = renderer.replace(' if(options.grid){', overlay+'\n if(options.grid){', 1)
    renderer = renderer.replace("const z=model.regions[id]", "if(d.layout&&id==='compute')continue;const z=model.regions[id]",1)
    (out/'lab-renderer.js').write_text(renderer, encoding='utf-8')
    js = (ROOT/'viewer/components.js').read_text(encoding='utf-8')
    js = js.replace('function render(){if(!data)return;', "function render(){if(!data)return;renderFleetAt((data.absolute_origin_us||0)+current);$('pipeline-clock').textContent='全程 '+fmt((data.absolute_origin_us||0)+current)+' / '+fmt(MANIFEST.pipeline.duration_us)+' μs';")
    js = js.replace('function showRow(row){', "function showRow(row){window.COMPONENT_DATA={};scheduleCache.clear();$('call-select').value=row.id;")
    js = js.replace('prepare(d);', 'prepare(d);if(pipelineAutoplay){pipelineAutoplay=false;queueMicrotask(()=>{playing=true;playState();});}')
    js = js.replace('if(current>=stop){playing=false;playState();}', "if(current>=stop){playing=false;playState();if(!playRange&&$('follow-calls').checked)nextPipelineCall(1,true);}")
    js = js.replace("$('overall').textContent=`${MANIFEST.component_count} 个组件 + ${MANIFEST.demonstration_count} 个并行示例`", "$('overall').textContent='17 码块 · 4 工厂 · 769 原子 · 16 逻辑操作'")
    js = js.replace("+' · 工程检查通过 · 视觉待验'", "+' · 当前窗口检查通过 · 视觉待验'")
    extra = """
let pipelineAutoplay=false;
function nextPipelineCall(delta,autoplay=false){const index=MANIFEST.components.findIndex(r=>r.id===chosen?.id),row=MANIFEST.components[index+delta];if(row){pipelineAutoplay=autoplay;showRow(row);}}
function renderFleetAt(t){
 const lines=[];
 for(const fid of ['F0','F1','F2','F3']){let state='待生产',epoch=0,target='';
  for(const e of window.FACTORY_DEMO.fleet.history){const when=e.time_us??e.receipt?.end_us;if(e.factory_id!==fid||when>t)continue;
   if(e.event==='production_started'){state='生产中';epoch=e.epoch;target='';}
   if(e.event==='output_ready')state='W4 库存就绪';
   if(e.event==='consumer_reserved'){state='供给 '+e.gate;target=' → '+e.target_patch;}
   if(e.event==='stage_committed'){state='已完成 '+e.receipt.stage_id;}
  }
  const active=window.FACTORY_DEMO.stages.find(s=>s.factory_id===fid&&s.start_us<=t&&t<s.end_us);
  if(active){state='执行 '+active.stage_id;epoch=active.epoch;}
  lines.push(fid+' · epoch '+epoch+' · '+state+target);
 }
 $('fleet-live').textContent=lines.join('\\n');
 const done=Object.values(window.FACTORY_DEMO.logical).filter(s=>s.completed_us<=t).length;
 $('logical-progress').textContent=done+' / 16 个原始逻辑操作完成';
 $('magic-demand').textContent=window.FACTORY_DEMO.requests.filter(r=>r.submitted_us<=t).map(r=>r.completed_us<=t?r.target_patch+' · '+r.gate+' 消费完成':r.reserved_us<=t?r.factory_id+':W4 → '+r.target_patch+' · '+r.gate+' 消费中':r.target_patch+' · 等待 '+r.gate+' 资源 ('+fmt((t-r.submitted_us)/1000)+' ms)').join('\\n');
}
for(const r of MANIFEST.components){const o=html('option',r.label);o.value=r.id;$('call-select').appendChild(o);}
$('call-select').onchange=()=>showRow(MANIFEST.components.find(r=>r.id===$('call-select').value));
$('call-prev').onclick=()=>nextPipelineCall(-1);$('call-next').onclick=()=>nextPipelineCall(1);
"""
    js = js.replace('new ResizeObserver(', extra+'\nnew ResizeObserver(', 1)
    (out/'components.js').write_text(js, encoding='utf-8')
    shell = (ROOT/'viewer/components.html').read_text(encoding='utf-8')
    shell = shell.replace('原子运动 · 组件实验台','Shor-17 · 四工厂交互演示').replace('逻辑组件 · 原子运动','四工厂 → Data · 16 个逻辑操作')
    shell = shell.replace('选择一段原子运动','工厂如何向 data 提供 magic').replace('70 组件<br>＋ 1 并行示例','17 个 data 码块<br>4 座右侧工厂')
    if allow_prefix:shell=shell.replace('工厂如何向 data 提供 magic','已提交动作预览 · 小演示尚未完成')
    shell = shell.replace('从逻辑门到辅助制备、蒸馏和连续协议。进入后查看运动、设备占用与执行记录。',
        '原 HRS Shor 电路前 16 个操作；769 个原子。展开实际蒸馏、W4 交接、T/T† 消费与清理。测量为显式 fake 场景，非量子采样。')
    shell = shell.replace('<div class="landing-tools">','<p><a href="acceptance.json">限定工程验收</a> · <a href="prefix.json">原电路前缀</a></p><div class="landing-tools">',1)
    nav = '<div class="viewer-bar pipeline-nav"><button id="call-prev">前一窗口</button><select id="call-select" aria-label="实际运行窗口"></select><button id="call-next">下一窗口</button><label><input type="checkbox" id="follow-calls" checked>连续播放</label><span id="pipeline-clock"></span></div>'
    shell = shell.replace('<div class="studio">',nav+'<div class="studio">',1)
    shell = shell.replace('<section class="transport panel"','<section class="panel fleet-panel"><strong>工厂与 data</strong><p id="logical-progress"></p><div id="magic-demand"></div><div id="fleet-live" style="white-space:pre-line;line-height:1.9"></div><p class="muted">周期由实际动作决定；200 ms 是布局容量估算。</p></section><section class="transport panel"',1)
    shell = shell.replace('value="2.8" step="0.2"','value="4" step="0.2"').replace('>2.8 μm<','>4 μm<')
    (out/'index.html').write_text(shell, encoding='utf-8')
    standalone = shell.replace('<link rel="stylesheet" href="components.css">','<style>'+(out/'components.css').read_text(encoding='utf-8')+'</style>')
    standalone = standalone.replace('<script src="manifest.js"></script>', ''.join('<script type="application/octet-stream" id="packed-'+k+'">'+v+'</script>' for k,v in compressed.items())+'<script src="manifest.js"></script>')
    for name in ('fleet.js','manifest.js','schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        standalone = standalone.replace('<script src="'+name+'"></script>','<script>'+(out/name).read_text(encoding='utf-8')+'</script>')
    (out/'animation-library.html').write_text(standalone, encoding='utf-8')
    (out/'full-viewer.html').write_text(standalone, encoding='utf-8')
    write(out/'acceptance.json', acceptance)
    write(out/'prefix.json', prefix)
    write(out/'calls.json', rows)
    print(json.dumps({'windows':len(rows),'out':str(out),'user_visual_acceptance':'pending'}), flush=True)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--run',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--allow-prefix',action='store_true')
    a=p.parse_args();export(a.run,a.out,allow_prefix=a.allow_prefix)
