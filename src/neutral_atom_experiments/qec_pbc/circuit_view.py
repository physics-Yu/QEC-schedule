"""Self-contained inspection of every lowered physical gate and recorded time.

This view reads execution evidence; the horizontal circuit axis is gate order,
not elapsed time. Missing execution fields remain explicitly unknown.
"""
import json
from pathlib import Path


def write_circuit_view(output_path, compiled, gate_schedule, evidence):
    """Write an offline physical circuit diagram and searchable full gate table.

    ``gate_schedule`` contains native gate fields and observed
    ``start_us/end_us/applied``. Partial schedules are allowed; unscheduled gates
    remain in the view with no invented execution time or application status.
    """
    definition = compiled.to_dict() if hasattr(compiled, 'to_dict') else dict(compiled)
    native_ids = {gate['id'] for gate in definition['gates']}
    schedule = [dict(row) for row in gate_schedule]
    ids = [row['id'] for row in schedule]
    if len(set(ids)) != len(ids) or not set(ids) <= native_ids:
        raise ValueError('Schedule IDs must be distinct gates of this compiled circuit')
    for row in schedule:
        if row.get('applied') is not None and type(row['applied']) is not bool:
            raise ValueError('Applied status must be a boolean or unknown')
        start, end = row.get('start_us'), row.get('end_us')
        if ((start is not None and (type(start) not in (int, float) or start < 0)) or
                (end is not None and (type(end) not in (int, float) or end < 0)) or
                start is not None and end is not None and end < start):
            raise ValueError('Recorded gate times must be nonnegative and ordered')
    payload = {'compiled': definition, 'gate_schedule': schedule, 'evidence': evidence}
    # HTML parses script endings even in JSON script blocks. Escape literal HTML
    # delimiters and JS line separators before placing untrusted IDs in the page.
    serialized = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
    serialized = (serialized.replace('&', '\\u0026').replace('<', '\\u003c')
                  .replace('>', '\\u003e').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_HTML.replace('__PAYLOAD__', serialized), encoding='utf-8')
    return destination


_HTML = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QEC / PBC 完整物理电路</title><style>
:root{color-scheme:light;--ink:#142b41;--muted:#576d80;--line:#d6e0e8;--blue:#1763a6}
*{box-sizing:border-box}body{margin:0;background:#f3f6f8;color:var(--ink);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:1500px;margin:auto;padding:28px 24px}h1{font-size:26px;margin:0 0 7px}h2{font-size:19px;margin:0 0 10px}
p{margin:7px 0}.muted{color:var(--muted)}.card{background:white;border:1px solid var(--line);border-radius:12px;padding:18px;margin:18px 0}
.stats{display:flex;flex-wrap:wrap;gap:12px;margin:16px 0}.stat{min-width:145px;background:white;border:1px solid var(--line);border-radius:10px;padding:10px 15px}
.stat b{display:block;font-size:23px}.stat span{color:var(--muted);font-size:12px}.toolbar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:12px 0}
label{display:flex;gap:7px;align-items:center}input,select,button{font:inherit;border:1px solid #b7c9d7;border-radius:6px;background:white;padding:7px 9px;color:var(--ink)}
#search{width:min(440px,95vw)}button{cursor:pointer}button:hover{background:#eef5fc}.diagram{overflow:auto;max-height:760px;border:1px solid var(--line);border-radius:7px;background:#fff}
.table-wrap{overflow:auto;max-height:660px;border:1px solid var(--line);border-radius:7px}table{border-collapse:collapse;width:100%;font-size:12px}
th,td{padding:9px 10px;border-bottom:1px solid #e1e8ee;text-align:left;vertical-align:top}th{position:sticky;top:0;background:#eaf1f6;z-index:1;white-space:nowrap}
td{min-width:90px}td:first-child{min-width:42px}td.id,td.deps,td.condition{font-family:ui-monospace,Consolas,monospace;word-break:break-all;min-width:180px;max-width:360px}
td.time{white-space:nowrap;min-width:96px;font-variant-numeric:tabular-nums}tr:hover{background:#f2f7fd}tr.selected{background:#dfedfa!important}
.badge{display:inline-block;border-radius:5px;padding:2px 7px;font-size:11px}.yes{background:#e4f2e9;color:#185c31}.skip{background:#fff0d9;color:#8a4b02}.unknown{background:#edf0f3;color:#5a6570}
#detail{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f9;border:1px solid var(--line);border-radius:7px;padding:12px;font:12px/1.65 ui-monospace,Consolas,monospace;min-height:65px}
.legend{display:flex;flex-wrap:wrap;gap:15px;font-size:12px;color:var(--muted)}.legend i{display:inline-block;width:13px;height:13px;vertical-align:middle;margin-right:5px;border:1px solid #4e8ab8;background:#e4f1fd}
footer{font-size:12px;color:var(--muted);margin:24px 0}svg text{font-family:ui-monospace,Consolas,monospace}svg .gate{cursor:pointer}svg .gate:hover{filter:drop-shadow(0 0 3px #2b79b8)}
@media(max-width:600px){main{padding:16px 10px}.card{padding:12px}h1{font-size:22px}.stat{min-width:125px}}
</style></head><body><main>
<h1>QEC / PBC 完整物理电路</h1><p id="program-name" class="muted"></p>
<div class="stats" id="stats"></div>
<div class="card"><h2>执行范围</h2><p id="scope"></p><p class="muted">此页展示编译后的完整物理门序列和执行记录。图中横轴是门序号；具体耗时见下方表格。空白执行字段显示“未记录”。本页不作全电路噪声容错或保真度结论。</p><p id="checks" class="muted"></p></div>
<section class="card"><h2>物理量子线路图</h2><p class="muted">每条线对应一个角色绑定的物理原子。点击任一门查看其依赖、条件和真实时刻；水平滚动可查看全部门。</p>
<div class="toolbar"><label>门间距 <input id="spacing" type="range" min="32" max="100" step="4" value="48"></label><label>定位门序号 <input id="gate-number" type="number" min="1" value="1" style="width:90px"></label><button id="jump">定位</button><span id="diagram-count" class="muted"></span></div>
<div class="legend"><span><i></i>已执行</span><span><i style="border-style:dashed;border-color:#a56c19;background:#fff2df"></i>条件不满足，跳过</span><span><i style="background:#edf0f3;border-color:#9ba7b2"></i>未记录</span><span>R = RESET　M = MEASURE　CZ = 两端圆点连线</span></div>
<div id="diagram" class="diagram"></div><p id="selection-label" class="muted">选择一个门以查看记录。</p><div id="detail"></div></section>
<section class="card"><h2>全部物理门及执行记录</h2><div class="toolbar">
<input id="search" type="search" placeholder="搜索门 ID、物理原子、角色、依赖或条件" aria-label="搜索物理门">
<label>门类型 <select id="gate-type"><option value="">全部</option></select></label>
<label>上游操作 <select id="operation"><option value="">全部</option></select></label>
<label>执行状态 <select id="execution"><option value="">全部</option><option value="yes">已执行</option><option value="skip">已跳过</option><option value="unknown">未记录</option></select></label>
<button id="clear">清除筛选</button><span id="table-count" class="muted"></span></div>
<div class="table-wrap"><table><thead><tr><th>序号</th><th>门 ID</th><th>类型 / 物理目标</th><th>上游操作 / 阶段</th><th>依赖</th><th>测量条件（AND）</th><th>开始 μs</th><th>结束 μs</th><th>时隙 μs</th><th>状态</th></tr></thead><tbody id="rows"></tbody></table></div></section>
<footer>离线独立页面；无网络请求。运输、装卸与尾部清理计入提供的总时间，但不伪装为量子门。</footer>
</main><script id="data" type="application/json">__PAYLOAD__</script><script>
'use strict';
const payload=JSON.parse(document.getElementById('data').textContent), compiled=payload.compiled, evidence=payload.evidence||{};
const schedule=new Map(payload.gate_schedule.map(g=>[g.id,g]));
const provenance=new Map((compiled.provenance||[]).map(p=>[p.gate_id,p]));
const bindings=Object.entries(compiled.bindings||{}), roles=new Map(bindings.map(([role,q])=>[q,role]));
const gates=compiled.gates.map((g,index)=>({...g,...schedule.get(g.id),index,provenance:provenance.get(g.id)||{}}));
const element=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=String(text);if(cls)node.className=cls;return node;};
const finite=n=>typeof n==='number'&&Number.isFinite(n), fmt=n=>finite(n)?n.toLocaleString('en-US',{minimumFractionDigits:3,maximumFractionDigits:3}):'未记录';
const state=g=>g.applied===true?'yes':g.applied===false?'skip':'unknown', status={yes:'已执行',skip:'已跳过',unknown:'未记录'};
const condition=g=>(g.condition||[]).map(c=>`${c[0]} = ${c[1]}`).join(' ∧ ')||'无';
const target=g=>(g.qubit_ids||[]).map(q=>`${q}${roles.has(q)?' ('+roles.get(q)+')':''}`).join(', ');
const summary=evidence.metrics||{};
document.getElementById('program-name').textContent=compiled.program?.name||'QEC / PBC physical circuit';
document.getElementById('scope').textContent=evidence.scope||compiled.claim||'以提供的编译与执行记录为准。';
const stats=[['物理门总数',gates.length],['CZ 数量',gates.filter(g=>g.gate_type==='CZ').length],['绑定角色',bindings.length],['测量门',gates.filter(g=>g.gate_type==='MEASURE').length],['已执行 / 跳过',`${gates.filter(g=>state(g)==='yes').length} / ${gates.filter(g=>state(g)==='skip').length}`],['总完成时间 μs',fmt(summary.simulation_time_us??summary.episode_wall_time_us)],['逻辑完成时间 μs',fmt(summary.logical_completion_elapsed_us)]];
for(const [label,value]of stats){const box=element('div',undefined,'stat');box.append(element('b',value),element('span',label));document.getElementById('stats').append(box);}
const audit=evidence.audit||{};document.getElementById('checks').textContent=`执行状态：${evidence.status||'未记录'}。验收：${Object.entries(audit).filter(([k,v])=>typeof v==='boolean').map(([k,v])=>`${k}=${v?'通过':'未通过'}`).join('；')||'见原始执行证据'}。`;
function addOptions(id,values){for(const value of [...new Set(values.filter(Boolean))].sort()){const option=element('option',value);option.value=value;document.getElementById(id).append(option);}}
addOptions('gate-type',gates.map(g=>g.gate_type));addOptions('operation',gates.map(g=>g.provenance.operation_id));
let selected=null;
function selectGate(g){selected=g.id;document.getElementById('selection-label').textContent=`门 ${g.index+1} / ${gates.length}：${g.id}`;
 document.getElementById('detail').textContent=JSON.stringify({id:g.id,gate_type:g.gate_type,physical_targets:g.qubit_ids,role_targets:(g.qubit_ids||[]).map(q=>roles.get(q)||null),operation_id:g.provenance.operation_id??null,phase:g.provenance.phase??null,depends_on:g.depends_on||[],condition:g.condition||[],start_us:g.start_us??null,end_us:g.end_us??null,slot_duration_us:finite(g.start_us)&&finite(g.end_us)?g.end_us-g.start_us:null,applied:g.applied??null},null,2);
 for(const row of document.querySelectorAll('#rows tr'))row.classList.toggle('selected',row.dataset.gateId===g.id);}
function renderTable(){const search=document.getElementById('search').value.toLowerCase(),type=document.getElementById('gate-type').value,op=document.getElementById('operation').value,execution=document.getElementById('execution').value;
 const visible=gates.filter(g=>(!type||g.gate_type===type)&&(!op||g.provenance.operation_id===op)&&(!execution||state(g)===execution)&&(!search||[g.id,g.gate_type,target(g),g.provenance.operation_id,g.provenance.phase,(g.depends_on||[]).join(' '),condition(g)].join(' ').toLowerCase().includes(search)));
 const fragment=document.createDocumentFragment();for(const g of visible){const row=element('tr');row.dataset.gateId=g.id;row.classList.toggle('selected',g.id===selected);row.addEventListener('click',()=>selectGate(g));
 const cells=[[g.index+1,''],[g.id,'id'],[g.gate_type+'\n'+target(g),''],[(g.provenance.operation_id||'未记录')+'\n'+(g.provenance.phase||''),'id'],[(g.depends_on||[]).join('\n')||'无','deps'],[condition(g),'condition'],[fmt(g.start_us),'time'],[fmt(g.end_us),'time'],[finite(g.start_us)&&finite(g.end_us)?fmt(g.end_us-g.start_us):'未记录','time']];
 for(const [text,cls]of cells){const td=element('td',text,cls);td.style.whiteSpace=cls==='time'?'nowrap':'pre-wrap';row.append(td);}const td=element('td');td.append(element('span',status[state(g)],'badge '+state(g)));row.append(td);fragment.append(row);}
 document.getElementById('rows').replaceChildren(fragment);document.getElementById('table-count').textContent=`显示 ${visible.length} / ${gates.length} 个门`;}
const NS='http://www.w3.org/2000/svg';function svgEl(tag,attrs,text){const node=document.createElementNS(NS,tag);for(const [key,value]of Object.entries(attrs||{}))node.setAttribute(key,String(value));if(text!==undefined)node.textContent=text;return node;}
let diagramSpacing=48;const LEFT=190,TOP=48,HEIGHT=35;
function renderDiagram(){diagramSpacing=Number(document.getElementById('spacing').value);const wireBindings=[...bindings];const seen=new Set(bindings.map(([,q])=>q));for(const g of gates)for(const q of g.qubit_ids||[])if(!seen.has(q)){wireBindings.push(['未绑定',q]);seen.add(q);}
 const wireMap=new Map(wireBindings.map(([,q],i)=>[q,TOP+i*HEIGHT]));const width=LEFT+(gates.length+1)*diagramSpacing,height=TOP+(wireBindings.length-1)*HEIGHT+40;const svg=svgEl('svg',{width,height,viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':`${wireBindings.length} 条物理量子线，${gates.length} 个门，横轴为门序号`});
 for(const [role,q]of wireBindings){const y=wireMap.get(q);svg.append(svgEl('line',{x1:LEFT-12,y1:y,x2:width-15,y2:y,stroke:'#b8c8d4','stroke-width':1}),svgEl('text',{x:10,y:y+4,'font-size':12,fill:'#314f66'},`${role} · ${q}`));}
 for(const g of gates){const x=LEFT+(g.index+.5)*diagramSpacing,group=svgEl('g',{'class':'gate','data-gate-id':g.id,tabindex:0,role:'button','aria-label':`门 ${g.index+1} ${g.id}`});const mode=state(g),stroke=mode==='skip'?'#a56c19':mode==='unknown'?'#8796a2':'#1763a6',fill=mode==='skip'?'#fff2df':mode==='unknown'?'#edf0f3':'#e4f1fd';group.append(svgEl('title',{},`${g.index+1}. ${g.id}\n${g.gate_type}: ${target(g)}\n${condition(g)}\n${fmt(g.start_us)} → ${fmt(g.end_us)} μs\n${status[mode]}`));
 if(g.index%10===0)svg.append(svgEl('text',{x,y:18,'text-anchor':'middle','font-size':10,fill:'#6d8294'},g.index+1));const ys=(g.qubit_ids||[]).map(q=>wireMap.get(q));
 if(g.gate_type==='CZ'&&ys.length===2){group.append(svgEl('line',{x1:x,y1:ys[0],x2:x,y2:ys[1],stroke,'stroke-width':2}));for(const y of ys)group.append(svgEl('circle',{cx:x,cy:y,r:4.5,fill:stroke}));}
 else for(const y of ys){const attrs={x:x-13,y:y-11,width:26,height:22,rx:3,stroke,fill,'stroke-width':1.3};if(mode==='skip')attrs['stroke-dasharray']='3 2';group.append(svgEl('rect',attrs),svgEl('text',{x,y:y+4,'text-anchor':'middle','font-size':11,fill:stroke},g.gate_type==='RESET'?'R':g.gate_type==='MEASURE'?'M':g.gate_type));}
 group.addEventListener('click',()=>selectGate(g));group.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectGate(g);}});svg.append(group);}
 document.getElementById('diagram').replaceChildren(svg);document.getElementById('diagram-count').textContent=`${wireBindings.length} 条线 · 全部 ${gates.length} 个门`;}
for(const id of ['search','gate-type','operation','execution'])document.getElementById(id).addEventListener(id==='search'?'input':'change',renderTable);
document.getElementById('clear').addEventListener('click',()=>{for(const id of ['search','gate-type','operation','execution'])document.getElementById(id).value='';renderTable();});
document.getElementById('spacing').addEventListener('input',renderDiagram);document.getElementById('gate-number').max=gates.length;
document.getElementById('jump').addEventListener('click',()=>{const index=Math.min(gates.length-1,Math.max(0,Number(document.getElementById('gate-number').value)-1));if(!gates[index])return;selectGate(gates[index]);document.getElementById('diagram').scrollLeft=Math.max(0,LEFT+(index+.5)*diagramSpacing-300);});
renderDiagram();renderTable();
</script></body></html>'''
