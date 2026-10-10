"""Existing motion viewer adapter for the checked Processor injection events."""
from pathlib import Path
import json,shutil,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from run_processor_injection_demo import OUT,read,write
from extend_frame_gallery import packed
from export_viewer_schedules import lanes


def export():
    viewer=OUT/'viewer';(viewer/'data').mkdir(parents=True,exist_ok=True)
    rows=[];schedules={};zones={};data_packed={}
    for m in (0,1):
        p=read(OUT/f'branch-{m}-plan.json.gz');trace=read(OUT/f'branch-{m}-trace.json.gz');check=read(OUT/f'branch-{m}-checks.json')
        assert check['passed'];key=f'T_M{m}'
        ids={a:i for i,a in enumerate(p['initial'])};atoms=[[a,v['qubit'],*v['position'],v['carrier'],v['owner'],v['qubit']] for a,v in p['initial'].items()]
        em={e['action_id']:e for e in trace['events']};actions=[];sources=[];si={};intervals={};resource_names=[];ri={};ownership=[];loaded={};occ={}
        for ai,a in enumerate(p['actions']):
            q=a['payload'];sourceidx=[]
            for s in a['source_ids']:
                if s not in si:si[s]=len(sources);sources.append(s)
                sourceidx.append(si[s])
            actions.append([a['t_start_us'],a['t_end_us'],a['kind'],[ids[x] for x in a['atoms']],
                [[ids[t['atom_id']],*t['from_um'],*t['to_um']] for t in q.get('trajectories',[])],
                [[ids[x] for x in pair] for pair in q.get('pairs',[])],q.get('name',''),em[a['id']]['status'],sourceidx,[],q.get('aod_group','')])
            if a['kind']=='handoff':ownership.append(dict(time_us=a['t_start_us'],atoms=[ids[x] for x in a['atoms']],owner=q['owner_to']))
            if em[a['id']]['status']!='completed':continue
            for lane,resources in lanes(a).items():
                rr=[]
                for r in resources:
                    if r not in ri:ri[r]=len(resource_names);resource_names.append(r)
                    rr.append(ri[r])
                intervals.setdefault(lane,[]).append([a['t_start_us'],a['t_end_us'],ai,rr])
            if a['kind']=='pickup':
                for x in a['atoms']:loaded[x]=(a['t_end_us'],ai,q['aod_group'])
            if a['kind']=='drop':
                for x in a['atoms']:
                    begin,ix,g=loaded.pop(x);occ.setdefault('occupancy:aod:'+g,set()).add((begin,a['t_end_us'],ix))
        assert not loaded
        d=dict(id=key,atoms=atoms,actions=actions,sources=sources,source_meta=[None]*len(sources),
            results=[dict(id=k,**v) for k,v in trace['results'].items()],end=p['metadata']['end_us'],
            phases=p['phases'],patches=[[z['id'],z['anchor_um'][0]+40,z['anchor_um'][1]-10] for z in p['layout']['patches']],
            bounds=[40,2240,-100,1500],layout_bounds=[40,1500,-100,1050],full_bounds=[40,2240,-100,1500],
            measurement=[None,None,1020,1480],readout_capacity=None,raw_action_count=len(actions),fake_scenario=True,
            layout=p['layout'],modules=[],ownership_events=ownership,lifecycle=trace['lifecycle'],injection=p['metadata'])
        # The full frame includes peripheral readout lanes so no transport vanishes.
        data_packed[key]=packed(d)
        (viewer/f'data/{key}.js').write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+json.dumps(key)+']='+json.dumps(d,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
        schedule=dict(schema_version='ViewerResources/0.1',id=key,end=d['end'],resource_names=resource_names,
            lanes=[dict(id=k,kind='activity' if k.startswith('activity:') else 'declared_resources',intervals=v) for k,v in intervals.items()]+
            [dict(id=k,kind='carrier_occupancy',intervals=[[a,b,i,[]] for a,b,i in sorted(v)]) for k,v in occ.items()])
        schedules[key]=packed(schedule);zones[key]={'compute':[80,650,438,1000],'measurement':[None,None,1020,1480]}
        rows.append(dict(id=key,data_id=key,data_path=f'data/{key}.js',label=f'T 注入 · m={m}'+(' · 条件 S-SE' if m else ' · 无需修正'),
            category='Processor 完整注入',description='D / W4 搬入 → 9 对 CNOT → W4 读出 → '+('S-SE → ' if m else '')+'D 返回与 W4 归还',
            scope='输入端声明已编码 A+；测量为明确 fake 场景。新事件执行涵盖注入、控制权交接、读出反馈和归还；蒸馏未重跑。F0–F2 同步执行生产初始化。',
            atom_count=697,action_count=len(actions),executed_action_count=sum(e['status']=='completed' for e in trace['events']),
            physical_operations=len(actions),duration_us=d['end'],kind='physical',implementation_version='processor-injection/1',
            version_status='限定注入事件检查通过',links=[dict(label='分支检查报告',href=f'../branch-{m}-checks.json'),dict(label='输入与验证边界',href='../README.md')]))
    for name,var,value in [('manifest.js','COMPONENT_MANIFEST',dict(schema_version='component-gallery/0.1',components=rows,component_count=2,demonstration_count=0,coverage={},user_visual_acceptance='pending')),('schedules.js','COMPONENT_SCHEDULE_PACKED',schedules),('regions.js','COMPONENT_ZONES',zones)]:
        (viewer/name).write_text('window.'+var+'='+json.dumps(value,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    for name in ('components.css','motion-preview.js','resource-schedule.js'):shutil.copyfile(ROOT/'viewer'/name,viewer/name)
    resource=(viewer/'resource-schedule.js').read_text(encoding='utf-8').replace("'rydberg:global':'Rydberg · CZ'","'rydberg:data':'Rydberg · Processor / data','rydberg:magic':'Rydberg · magic'")
    (viewer/'resource-schedule.js').write_text(resource,encoding='utf-8')
    renderer=(ROOT/'viewer/lab-renderer.js').read_text(encoding='utf-8')
    renderer=renderer.replace("const key=d.atoms[i][5]","const key=a.owner||d.atoms[i][5]")
    renderer=renderer.replace("const z=model.regions[id]","if(d.layout&&id==='compute')continue;const z=model.regions[id]",1)
    overlay="""
 if(options.zones&&d.layout){for(const[id,label,color]of [['compute','Compute zone','#e7eef4'],['processor','Processor · T injection','#edf1f5'],['reloading','Reloading · reserve','#f2f3ef'],['magic','Magic factory zone','#edf2eb']]){
  const z=d.layout.regions[id],pulse=active.some(a=>a[6]==='CZ'&&a[5].some(pair=>pair.some(i=>{const p=state[i];return p.x>=z[0]&&p.x<=z[2]&&p.y>=z[1]&&p.y<=z[3];})));
  add('rect',{x:z[0],y:z[1],width:z[2]-z[0],height:z[3]-z[1],fill:pulse?'#edb6ad':color,stroke:'#ccd8df','stroke-width':.6,'data-zone':id,'data-cz-illumination':pulse?'active':'idle'});text(z[0]+6,z[3]-18,label,'#526a78',18);
 }for(const p of d.layout.patches)add('rect',{x:p.anchor_um[0],y:p.anchor_um[1],width:80,height:80,fill:'none',stroke:'#b8c7ce','stroke-width':.55});}
"""
    renderer=renderer.replace(' if(options.grid){',overlay+'\n if(options.grid){',1)
    (viewer/'lab-renderer.js').write_text(renderer,encoding='utf-8')
    js=(ROOT/'viewer/components.js').read_text(encoding='utf-8')
    js=js.replace('`${MANIFEST.component_count} 个组件 + ${MANIFEST.demonstration_count} 个并行示例`',"'697 原子 · 两个反馈分支 · 双 AOD'")
    js=js.replace("return{id:a[0],qubit:a[1],site,x,y,carrier}","let owner=a[5];for(const e of data.ownership_events||[])if(e.time_us<=t&&e.atoms.includes(i))owner=e.owner;return{id:a[0],qubit:a[1],site,x,y,carrier,owner}")
    js=js.replace("${data.atoms[selectedAtom][5]} AOD","${a.owner} AOD")
    js=js.replace("compute zone 红色表示共同照明","红色仅表示本次对应区域的 Rydberg 光")
    js=js.replace("const n=a[6]||names[a[2]]||a[2]","const n=a[6]==='H'?'物理 H':a[6]||names[a[2]]||a[2]")
    js=js.replace('function render(){if(!data)return;', 'function render(){if(!data)return;renderInjection();')
    js=js.replace("'此历史工件没有本轮模块化验收记录'","'复用 S-SE 与生产初始化原子动作；新构造四区运输和控制权交接'")
    js=js.replace("'模块引用只保存编译动作；测量值、token及epoch来自本次事件会话。'","'A+ 为注入测试的输入条件；没有复用旧 token。全部回放来自本次新事件。'")
    extra="""
function renderInjection(){const m=data.injection,t=current;let owner='magic';for(const e of data.ownership_events||[])if(e.time_us<=t)owner=e.owner;
 $('injection-status').textContent='场景 m='+m.branch+' · '+(t>=m.data_completed_us?'q16 的 T 完成':t>=m.feedback_ready_us?'反馈已就绪':'注入进行中')+'\\nW4 当前运输控制：'+owner+' AOD\\n'+(t>=m.end_us?'同一 W4 已归还 F3':t>=m.data_completed_us?'data 已返回，W4 等待归还':'同载体 W4 → Processor → 读出 / 清理');
 const bg=m.background;$('production-status').textContent=t<bg.start_us?'magic AOD 正在交付 F3:W4':t<bg.end_us?'F0 / F1 / F2 同步执行生产初始化\\nF3 等待已交付的 W4 归还':'F0 / F1 / F2 初始化完成（尚未蒸馏完毕）\\n'+(t>=m.end_us?'F3 的 W4 已归还':'magic AOD 可执行归还运输');
}
$('layout-view').onclick=()=>{if(data){data.bounds=data.layout_bounds.slice();view={zoom:1,x:0,y:0};render();}};
$('processor-view').onclick=()=>{if(data){data.bounds=[760,1460,420,1020];view={zoom:1,x:0,y:0};render();}};
$('full-view').onclick=()=>{if(data){data.bounds=data.full_bounds.slice();view={zoom:1,x:0,y:0};render();}};
"""
    js=js.replace('new ResizeObserver(',extra+'\nnew ResizeObserver(',1)
    (viewer/'components.js').write_text(js,encoding='utf-8')
    shell=(ROOT/'viewer/components.html').read_text(encoding='utf-8')
    shell=shell.replace('原子运动 · 组件实验台','Processor · 完整 T 注入').replace('逻辑组件 · 原子运动','Processor · T 注入与反馈')
    shell=shell.replace('选择一段原子运动','验证两个完整测量分支').replace('70 组件<br>＋ 1 并行示例','697 原子<br>两个反馈分支')
    shell=shell.replace('从逻辑门到辅助制备、蒸馏和连续协议。进入后查看运动、设备占用与执行记录。','从就绪 A+ 输入开始：搬入、控制权交接、9 对耦合、读出、条件 S-SE、返回与归还。F0–F2 同步执行生产初始化；此演示不重跑蒸馏。')
    shell=shell.replace('<div class="view-tools">','<div class="view-tools"><button id="layout-view">四区布局</button><button id="processor-view">Processor 放大</button><button id="full-view">含测量区</button>')
    shell=shell.replace('<section class="transport panel"','<section class="panel" style="padding:14px"><strong>注入与工厂</strong><p id="injection-status" style="white-space:pre-line"></p><p id="production-status" style="white-space:pre-line"></p></section><section class="transport panel"',1)
    shell=shell.replace('<option value="keyframe">','<option value="keyframe" selected>').replace('<option value="physical" selected>','<option value="physical">')
    shell=shell.replace('<option value="xy" selected>','<option value="xy">').replace('<option value="original">','<option value="original" selected>')
    shell=shell.replace('value="2.8" step="0.2"','value="4" step="0.2"').replace('>2.8 μm<','>4 μm<')
    with (viewer/'components.css').open('a',encoding='utf-8') as f:f.write('\n.canvas-stack{height:auto!important}.drawing{flex:0 0 auto!important;min-height:610px;height:auto!important}.drawing .viewport{min-height:520px}#scene{height:520px}\n')
    (viewer/'index.html').write_text(shell,encoding='utf-8')
    standalone=shell.replace('<link rel="stylesheet" href="components.css">','<style>'+(viewer/'components.css').read_text(encoding='utf-8')+'</style>')
    standalone=standalone.replace('<script src="manifest.js"></script>',''.join('<script type="application/octet-stream" id="packed-'+k+'">'+v+'</script>' for k,v in data_packed.items())+'<script src="manifest.js"></script>')
    for name in ('manifest.js','schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        standalone=standalone.replace('<script src="'+name+'"></script>','<script>'+(viewer/name).read_text(encoding='utf-8')+'</script>')
    (viewer/'full-viewer.html').write_text(standalone,encoding='utf-8');(viewer/'animation-library.html').write_text(standalone,encoding='utf-8')
    print(json.dumps(dict(exported=2,atoms=697,viewer=str(viewer))))


if __name__=='__main__':export()
