"""Project complete compact-modmul events into the established atom viewer."""
from pathlib import Path
import json,sys,shutil
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from run_compact_modmul_demo import OUT,read,save
from extend_frame_gallery import packed
from export_viewer_schedules import lanes


def export():
    p=read(OUT/'plan.json.gz');trace=read(OUT/'trace.json.gz');accept=read(OUT/'acceptance.json');assert accept['passed']
    viewer=OUT/'viewer';(viewer/'data').mkdir(parents=True,exist_ok=True)
    ids={a:i for i,a in enumerate(p['initial'])};atoms=[[a,v['qubit'],*v['position'],v['carrier'],v['owner'],v['qubit']] for a,v in p['initial'].items()]
    em={e['action_id']:e for e in trace['events']};actions=[];sources=[];source_index={};ownership=[];intervals={};occ={};loaded={}
    for ai,a in enumerate(p['actions']):
        q=a['payload'];label=q.get('logical_call') or ('factory e'+str(q.get('cohort',''))+' '+q['phase']);idx=source_index.get(label)
        if idx is None:idx=len(sources);sources.append(label);source_index[label]=idx
        actions.append([a['t_start_us'],a['t_end_us'],a['kind'],[ids[x] for x in a['atoms']],
            [[ids[v['atom_id']],*v['from_um'],*v['to_um']] for v in q.get('trajectories',[])],
            [[ids[x] for x in pair] for pair in q.get('pairs',[])],q.get('name',''),em[a['id']]['status'],[idx],
            [[ids[b['atom_id']],b['from_site_id'],b['to_site_id']] for b in q.get('site_bindings',[])],q.get('aod_group','')])
        if a['kind']=='handoff':ownership.append(dict(time_us=a['t_start_us'],atoms=[ids[x] for x in a['atoms']],owner=q['owner_to']))
        if em[a['id']]['status']!='completed':continue
        for lane in lanes(a):intervals.setdefault(lane,[]).append([a['t_start_us'],a['t_end_us'],ai,[]])
        if a['kind']=='pickup':
            for x in a['atoms']:loaded[x]=(a['t_end_us'],ai,q['aod_group'])
        if a['kind']=='drop':
            for x in a['atoms']:
                start,i,g=loaded.pop(x);occ.setdefault('occupancy:aod:'+g,set()).add((start,a['t_end_us'],i))
    assert not loaded
    key='MODMUL_2_15';phases=[]
    for i,c in enumerate(p['calls']):
        title=('初始准备' if c['stage']=='prepare' else '受控交换 '+str(int(c['stage'][-1])+1))+' · '+c['gate']+' '+','.join(c['operands'])
        phases.append(dict(id=str(i),label=f'{i+1:02d} · '+title,start_us=c['start_us'],end_us=c['end_us'],
            note=('等待本轮工厂输出；' if c.get('ready_wait_us',0)>0 else '')+'完整逻辑调用'))
    d=dict(id=key,atoms=atoms,actions=actions,sources=sources,source_meta=[None]*len(sources),results=[dict(id=k,**v) for k,v in trace['results'].items()],
        end=p['end_us'],phases=phases,patches=[[z['id'],z['anchor_um'][0]+40,z['anchor_um'][1]-10] for z in p['layout']['patches']],
        bounds=[40,2240,-100,1500],layout_bounds=[40,1500,-100,1050],full_bounds=[40,2240,-100,1500],measurement=[None,None,1020,1480],readout_capacity=None,
        raw_action_count=len(actions),fake_scenario=True,layout=p['layout'],modules=[],ownership_events=ownership,
        logical_calls=p['calls'],production=p['production'],token_events=trace['lifecycle'],tokens=p['tokens'],truth_table=p['program']['truth_table'],
        final_sites=trace['final_sites'],operator_max_error=p['program']['operator_max_error'])
    save(viewer/'data.json',d)
    (viewer/f'data/{key}.js').write_text('window.COMPONENT_DATA=window.COMPONENT_DATA||{};window.COMPONENT_DATA['+json.dumps(key)+']='+json.dumps(d,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    schedule=dict(schema_version='ViewerResources/0.1',id=key,end=d['end'],resource_names=[],
        lanes=[dict(id=k,kind='activity' if k.startswith('activity:') else 'declared_resources',intervals=v) for k,v in intervals.items()]+
        [dict(id=k,kind='carrier_occupancy',intervals=[[a,b,i,[]] for a,b,i in sorted(v)]) for k,v in occ.items()])
    row=dict(id=key,data_id=key,data_path=f'data/{key}.js',label='Shor-15 初始准备 + 受控 ×2 mod 15',category='精确模乘电路',
        description='9 个准备门 + 51 个模乘门；21 次 T/T† 注入，四工厂并行生产 24 份输出。',
        scope='完整受控模乘算符通过32输入验证。所有测量为显式fake场景，未模拟量子态或执行硬件；不包括后续模乘和逆QFT。',
        atom_count=697,action_count=len(actions),executed_action_count=sum(e['status']=='completed' for e in trace['events']),physical_operations=60,duration_us=d['end'],
        kind='physical',implementation_version='compact-modmul/1',version_status='算术与新事件检查通过',
        links=[dict(label='完整逻辑电路与真值表',href='../program.json'),dict(label='验收报告',href='../acceptance.json'),dict(label='范围与复现',href='../README.md')])
    for name,var,value in [('manifest.js','COMPONENT_MANIFEST',dict(schema_version='component-gallery/0.1',component_count=1,demonstration_count=0,components=[row],coverage={})),
        ('schedules.js','COMPONENT_SCHEDULE_PACKED',{key:packed(schedule)}),('regions.js','COMPONENT_ZONES',{key:{'compute':[80,650,438,1000],'measurement':[None,None,1020,1480]}})]:
        (viewer/name).write_text('window.'+var+'='+json.dumps(value,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    # Reuse the four-zone renderer and its current no-residue optical layer.
    for name in ('components.css','lab-renderer.js','resource-schedule.js','motion-preview.js'):
        shutil.copyfile(ROOT/'artifacts/deliveries/processor-injection-20261009/viewer'/name,viewer/name)
    js=(ROOT/'viewer/components.js').read_text(encoding='utf-8')
    js=js.replace("'物理操作'","'逻辑操作'")
    js=js.replace('`${MANIFEST.component_count} 个组件 + ${MANIFEST.demonstration_count} 个并行示例`',"'697 原子 · 60 逻辑门 · 21 次 T/T†'")
    js=js.replace("return{id:a[0],qubit:a[1],site,x,y,carrier}","let owner=a[5];for(const e of data.ownership_events||[])if(e.time_us<=t&&e.atoms.includes(i))owner=e.owner;return{id:a[0],qubit:a[1],site,x,y,carrier,owner}")
    js=js.replace('${data.atoms[selectedAtom][5]} AOD','${a.owner} AOD')
    js=js.replace('function render(){if(!data)return;','function render(){if(!data)return;renderAlgorithm();')
    js=js.replace("compute zone 红色表示共同照明","红色仅表示正在发光的对应区域")
    js=js.replace("const n=a[6]||names[a[2]]||a[2]","const n=a[6]==='H'?'物理 H':a[6]||names[a[2]]||a[2]")
    js=js.replace("'此历史工件没有本轮模块化验收记录'","'原生组件编译 0；复用已编译 H、S-SE 与完整生产路径，绑定当前运输接口'")
    js=js.replace("'模块引用只保存编译动作；测量值、token及epoch来自本次事件会话。'","'工厂生产与消费均为新事件；不复用旧token。H使用实际原子置换并更新code-site映射。'")
    extra="""
function renderAlgorithm(){const t=current,c=data.logical_calls.find(c=>c.start_us<=t&&t<c.end_us),done=data.logical_calls.filter(c=>c.end_us<=t).length;
 $('logic-progress').textContent=done+' / 60 个逻辑操作完成'+(c?'\\n当前：'+c.gate+' '+c.operands.join(' → '):'');
 const ev=data.token_events.filter(e=>e.time_us<=t),produced=ev.filter(e=>e.event==='output_ready').length,consumed=ev.filter(e=>e.event==='consume').length;
 $('magic-stock').textContent='生产 '+produced+' · 消费 '+consumed+' / 21 · 未消费 '+(produced-consumed)+'\\n'+(c?.ready_wait_us&&t<c.start_us+c.ready_wait_us?'当前 T 请求等待工厂就绪':'同载体预约、注入、清理与归还');
 const prod=data.production.find(p=>p.start_us<=t&&t<p.end_us);let text=prod?'F0–F3 并行生产 · epoch '+prod.epoch+'\\n'+(prod.stages.find(s=>s.start_us<=t&&t<s.end_us)?.stage||'阶段交接'):'四厂库存 / 消费交接阶段';
 $('factory-progress').textContent=text;
}
function overview(){if(!data)return;data.bounds=data.full_bounds.slice();view={zoom:1,x:0,y:0};playRange=null;$('mode').value='physical';$('timebase').value='100000';$('speed').value='1';configureClock();setTime(0);playing=true;playState();}
$('overview').onclick=overview;
$('detail-call').onclick=()=>{if(!data)return;const p=data.phases.find(p=>p.id===$('phase').value);if(!p)return;const c=data.logical_calls[Number(p.id)];playRange={start_us:c.start_us+(c.ready_wait_us||0),end_us:c.end_us};$('mode').value='keyframe';$('speed').value='4';configureClock();setTime(playRange.start_us);playing=true;playState();};
$('layout-view').onclick=()=>{if(data){data.bounds=data.layout_bounds.slice();view={zoom:1,x:0,y:0};render();}};
$('processor-view').onclick=()=>{if(data){data.bounds=[760,1460,420,1020];view={zoom:1,x:0,y:0};render();}};
$('full-view').onclick=()=>{if(data){data.bounds=data.full_bounds.slice();view={zoom:1,x:0,y:0};render();}};
function truth(){const x=Number($('arith-x').value),c=Number($('arith-c').value),y=!c||x===15?x:2*x%15;$('arith-result').textContent='|'+c+','+x+'⟩ → |'+c+','+y+'⟩（算符验证，非测量输出）';}
for(let i=0;i<16;i++){const o=html('option',String(i));o.value=String(i);$('arith-x').appendChild(o);}$('arith-x').value='7';$('arith-c').onchange=truth;$('arith-x').onchange=truth;truth();
"""
    js=js.replace('new ResizeObserver(',extra+'\nnew ResizeObserver(',1)
    (viewer/'components.js').write_text(js,encoding='utf-8')
    shell=(ROOT/'viewer/components.html').read_text(encoding='utf-8')
    shell=shell.replace('原子运动 · 组件实验台','Shor-15 · 精确受控模乘').replace('逻辑组件 · 原子运动','Shor-15 · 受控 ×2 mod 15')
    shell=shell.replace('选择一段原子运动','初始准备 → 完整受控模乘').replace('70 组件<br>＋ 1 并行示例','60 个逻辑门<br>21 次魔态消费')
    shell=shell.replace('从逻辑门到辅助制备、蒸馏和连续协议。进入后查看运动、设备占用与执行记录。','保留17个data码块。前8个相位比特做H、工作寄存器置1，再执行3个精确受控交换。四厂同步生产六轮；全部门、反馈与资源记录可逐步查看。')
    shell=shell.replace('<div class="view-tools">','<div class="view-tools"><button id="layout-view">四区布局</button><button id="processor-view">Processor 放大</button><button id="full-view">含测量区</button>')
    panel='<section class="panel" style="padding:14px"><strong>逻辑电路与工厂</strong><p id="logic-progress" style="white-space:pre-line"></p><p id="magic-stock" style="white-space:pre-line"></p><p id="factory-progress" style="white-space:pre-line"></p><button id="overview">播放全程概览（约24秒）</button><button id="detail-call">详看所选逻辑门</button><p class="muted">概览保留全部时间；详看跳过该门前的资源等待。</p></section><section class="panel" style="padding:14px"><strong>算术语义 · 全32输入已验证</strong><p>控制 q0；工作 q8（低位）至 q11（高位）</p><label>c <select id="arith-c"><option value="0">0</option><option value="1" selected>1</option></select></label> <label>x <select id="arith-x"></select></label><p id="arith-result"></p></section>'
    shell=shell.replace('<section class="transport panel"',panel+'<section class="transport panel"',1)
    shell=shell.replace('<option value="1000000">','<option value="100000">100 ms / 秒（概览）</option><option value="1000000">')
    shell=shell.replace('<option value="xy" selected>','<option value="xy">').replace('<option value="original">','<option value="original" selected>')
    shell=shell.replace('value="2.8" step="0.2"','value="4" step="0.2"').replace('>2.8 μm<','>4 μm<')
    (viewer/'index.html').write_text(shell,encoding='utf-8')
    # A single portable compressed artifact is also available for offline viewing.
    standalone=shell.replace('<link rel="stylesheet" href="components.css">','<style>'+(viewer/'components.css').read_text(encoding='utf-8')+'</style>')
    standalone=standalone.replace('<script src="manifest.js"></script>','<script type="application/octet-stream" id="packed-'+key+'">'+packed(d)+'</script><script src="manifest.js"></script>')
    for name in ('manifest.js','schedules.js','regions.js','motion-preview.js','resource-schedule.js','lab-renderer.js','components.js'):
        standalone=standalone.replace('<script src="'+name+'"></script>','<script>'+(viewer/name).read_text(encoding='utf-8')+'</script>')
    (viewer/'animation-library.html').write_text(standalone,encoding='utf-8');(viewer/'full-viewer.html').write_text(standalone,encoding='utf-8')
    save(OUT/'viewer-export.json',dict(passed=True,actions=len(actions),atoms=697,logical_calls=len(p['calls']),complete_trace_projected=True))
    print('exported',len(actions),'actions',flush=True)


if __name__=='__main__':export()
