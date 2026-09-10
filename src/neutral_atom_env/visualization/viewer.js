// Dependency-free, container-scoped atom motion viewer. Source generated with a shared shell.
(function(scope){
'use strict';
const SHELL=__SHELL_JSON__;
const mounted=new WeakMap();
function upperBound(items,value,key){let lo=0,hi=items.length;while(lo<hi){const mid=(lo+hi)>>>1;if(items[mid][key]<=value)lo=mid+1;else hi=mid}return lo}
function decodeFrames(data){
 if(data.format!=='neutral-atom-view/1')throw new Error('Unsupported visualization format');
 const checkpoints=new Map(),cache=new Map(),working=new Map();
 data.frames.forEach((frame,i)=>{for(const a of frame.atom_updates)working.set(a.id,a);if(i%64===0)checkpoints.set(i,new Map(working))});
 function sceneAt(i){
   if(cache.has(i))return cache.get(i);
   const start=Math.floor(i/64)*64,atoms=new Map(checkpoints.get(start));
   for(let j=start+1;j<=i;j++)for(const a of data.frames[j].atom_updates)atoms.set(a.id,a);
   const scene={...data.scene,atoms:[...atoms.values()]};cache.set(i,scene);if(cache.size>4)cache.delete(cache.keys().next().value);return scene;
 }
 return data.frames.map((f,i)=>({...f,get scene(){return sceneAt(i)}}));
}
function summaryMarkup(summary,operations){
 if(!summary)return '';
 const esc=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const m=summary.metrics,format=v=>v==null?'未完成':Number(v).toLocaleString('en-US',{maximumFractionDigits:2});
 const metrics=[['总耗时',summary.wall_time_us,'μs'],['逻辑完成',m.logical_completion_elapsed_us,'μs'],['完成门数',m.completed_gate_count,''],['AOD 路程',m.total_aod_distance_um,'μm'],['原子总路程',m.total_atom_distance_um,'μm'],['装载次数',m.aod_load_count,'']];
 const cards=metrics.map(([name,value,unit])=>`<div><small>${name}</small><div style="font-size:21px">${format(value)} <small>${unit}</small></div></div>`).join('');
 const start=summary.window_start_us,end=summary.window_end_us,span=end-start||1;
 const X=t=>150+700*(t-start)/span;
 const rows=summary.categories.map((r,i)=>`<rect x="150" y="${78+i*40}" width="700" height="40" fill="${i%2?'#f7f9fc':'#fff'}"/><text x="4" y="${103+i*40}">${esc(r.label)}</text><text x="1085" y="${103+i*40}" text-anchor="end">${format(r.duration_us)} μs · ${(r.fraction*100).toFixed(2)}%</text>`).join('');
 const ticks=Array.from({length:6},(_,i)=>{const time=start+(end-start)*i/5,x=X(time);return `<line x1="${x}" x2="${x}" y1="72" y2="358" stroke="#e6eaf1"/><text x="${x}" y="63" text-anchor="middle" fill="#78869c">${format(time)}</text>`}).join('');
 const intervals=summary.schedule||operations;
 const bars=intervals.map(interval=>{
   const i=summary.categories.findIndex(r=>r.key===interval.category);if(i<0)return '';
   const r=summary.categories[i],x=X(interval.start),actualWidth=X(interval.end)-x;
   const candidate=operations[upperBound(operations,interval.start,'start')-1];
   const op=candidate&&interval.start<candidate.end?candidate:null;
   const label=`${op?.gate_id||''} ${r.label} · ${format(interval.start)}–${format(interval.end)} μs · ${(interval.end-interval.start).toFixed(3)} μs${op?' · '+op.label:''}`;
   return `<g><rect class="schedule-segment" data-start="${interval.start}" data-end="${interval.end}" data-category="${interval.category}" x="${x}" y="${88+i*40}" width="${Math.max(actualWidth,2)}" height="20" fill="${r.color}" stroke="white" stroke-width=".5" role="button" tabindex="0" aria-label="${esc(label)}"><title>${esc(label)}</title></rect>${interval.category==='pulse'&&op?`<text x="${x}" y="${85+i*40}" text-anchor="middle" fill="${r.color}" font-size="10">${esc(op.gate_id)}</text>`:''}</g>`;
 }).join('');
 return `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:16px;margin:18px 0">${cards}</div><div style="overflow-x:auto"><svg id="schedule" viewBox="0 0 1100 375" style="display:block;width:100%;min-width:780px;font:13px system-ui;fill:#25334b" role="group" aria-label="操作时序表，横轴为真实仿真时间"><text x="4" y="26" font-weight="600">操作类别</text><text x="150" y="26" font-weight="600">操作时序 / μs →</text><text x="1085" y="26" text-anchor="end" font-weight="600">累计时间 · 占比</text>${rows}${ticks}${bars}<line id="schedule-playhead" x1="150" x2="150" y1="72" y2="358" stroke="#25334b" stroke-width="1.3" stroke-dasharray="4 3" pointer-events="none"/></svg></div><p id="schedule-current" class="muted"></p><p class="muted">横轴始终为真实仿真时间；同类操作按发生时间分段排列。点击色块跳转，悬停查看起止时间；短脉冲最小显示为 2 px 标记，真实时长不变。虚线与运动回放同步，右列保留累计占用。</p>`;
}
function mount(container,recording){
if(!recording?.frames?.length)throw new Error('Visualization requires at least one recorded frame');
mounted.get(container)?.destroy();

const data=recording, frames=decodeFrames(data), theme=data.theme;
const root=container.shadowRoot||container.attachShadow({mode:'open'});
root.innerHTML=SHELL;
const $=id=>root.getElementById(id), canvas=$('canvas'), ctx=canvas.getContext('2d');
const TRAP_RADIUS=7;
const view={zoom:1,panX:0,panY:0}, ui={time:data.start_time||0,mode:'keyframe',playing:false,selected:null,hover:null};
let width=0,height=0,last=null,hits=[],drag=null,current=null,disposed=false,raf=null;
let atomPage=0,stagePage=-1,atomQuery="",visibleAtoms=[],visibleOperations=[];
const ATOM_PAGE=32,STAGE_PAGE=12;
const names={idle:'空闲',moving:'移动',gating:'门操作',measuring:'测量',lost:'丢失'};
const statuses={blocked:'依赖未满足',failed:'失败',pending:'等待',ready:'就绪',reserved:'已预约',running:'执行中',completed:'已完成'};
const labels={'Joint load in SZ':'SZ 联合装载','Joint transport to EZ':'共同运输至 EZ','Park operand in EZ SLM':'目标原子转交 EZ 的 SLM','Local approach to parked operand':'局部靠近静态目标','Restore joint transport configuration':'恢复共同运输构型','Recapture parked operand':'从 SLM 重新接回目标','Joint return to SZ':'共同返回 SZ','Joint offload in SZ':'SZ 联合卸载','Depart source':'脱离源 trap','Approach offload':'接近卸载 trap','Corridor transport':'格间通道运输','Return corridor':'沿通道返回','Idle':'等待 / 空闲','Load':'装载','Escape':'脱离 SLM','Lateral alignment':'横向对齐','Transport to interaction':'前往作用位','CZ pulse':'CZ 作用','Reconfigure axes':'阵列伸缩','Return / approach':'返回 / 接近','Offload':'卸载','Empty reposition to source':'空载前往源原子','Empty return to initial pose':'空载返回起始位'};
const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Presentation time is a monotone mapping of simulation time, never a state edit.
const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
const smooth=u=>u*u*(3-2*u);
const US_PER_MS=.025; // Physical proportion: 1x = 25 simulation microseconds / screen second.
let presentationEnd=0;
const timelineOperations=[];
let cursor=data.start_time||0;
for(const op of data.operations){if(op.start>cursor)timelineOperations.push({index:-1,kind:'idle',label:'Idle',start:cursor,end:op.start,captured:[]});timelineOperations.push(op);cursor=op.end}
if(cursor<data.duration)timelineOperations.push({index:-1,kind:'idle',label:'Idle',start:cursor,end:data.duration,captured:[]});
const segments=timelineOperations.map(op=>{
    const milliseconds=['aod_load','aod_recapture'].includes(op.kind)?1800:['aod_offload','aod_park'].includes(op.kind)?1600:
        op.kind==='entangling_pulse'?1800:clamp((op.end-op.start)/US_PER_MS,800,2200);
    const segment={...op,displayStart:presentationEnd,displayEnd:presentationEnd+milliseconds};
    presentationEnd=segment.displayEnd;
    return segment;
});
function operationAt(time){const i=upperBound(segments,time,'start')-1;const op=segments[i];return op&&time<op.end?op:null}
function displayAt(time){
    const op=operationAt(time);
    if(!op)return time>=data.duration?presentationEnd:0;
    return op.displayStart+(time-op.start)/(op.end-op.start)*(op.displayEnd-op.displayStart);
}
function simulationAt(milliseconds){
    const t=clamp(milliseconds,0,presentationEnd);
    const op=segments[upperBound(segments,t,'displayEnd')];
    return op?op.start+(t-op.displayStart)/(op.displayEnd-op.displayStart)*(op.end-op.start):data.duration;
}
function transferAt(time){
    const op=operationAt(time);
    if(!op||!['aod_load','aod_offload','aod_park','aod_recapture'].includes(op.kind))return null;
    const progress=clamp((time-op.start)/(op.end-op.start),0,1);
    return {op,progress,mobileMix:['aod_load','aod_recapture'].includes(op.kind)?smooth(progress):1-smooth(progress),ids:op.captured};
}
function sample(time){
    const f=frames[Math.max(0,upperBound(frames,time+1e-8,'time')-1)];
    let columns=[...f.axes.x_um],rows=[...f.axes.y_um];
    if(f.movement){
        let u=clamp((time-f.movement.start)/f.movement.duration,0,1);
        if(f.movement.profile==='cubic')u=smooth(u);
        columns=columns.map((x,i)=>x+u*(f.movement.target_axes.x_um[i]-x));
        rows=rows.map((y,i)=>y+u*(f.movement.target_axes.y_um[i]-y));
    }
    const pose={x_um:columns[0],y_um:rows[0]};
    const atoms=f.scene.atoms.map(a=>({...a,position:a.holder.holder_type==='mobile'?{
        x_um:columns[a.holder.holder_id.column],y_um:rows[a.holder.holder_id.row]}:a.position}));
    return {f,pose,columns,rows,atoms};
}
function projection(){const b=frames[0].scene.bounds,base=Math.min((width-110)/(b.upper.x_um-b.lower.x_um),(height-100)/(b.upper.y_um-b.lower.y_um)),scale=base*view.zoom;return {scale,X:x=>width/2+view.panX+(x-(b.lower.x_um+b.upper.x_um)/2)*scale,Y:y=>height/2+view.panY-(y-(b.lower.y_um+b.upper.y_um)/2)*scale}}
function circle(x,y,r,fill,stroke,lw=1){ctx.beginPath();ctx.arc(x,y,r,0,2*Math.PI);if(fill){ctx.fillStyle=fill;ctx.fill()}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=lw;ctx.stroke()}}
function line(x,y,xx,yy,color,lw=1){ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(xx,yy);ctx.strokeStyle=color;ctx.lineWidth=lw;ctx.stroke()}
function atomColor(a){return a.activity==='moving'?theme.moving_color:['gating','measuring'].includes(a.activity)?theme.active_color:theme.static_color}
// Transitional marker only. sample() and the inspector retain committed holder truth.
function atomMarker(x,y,mobileMix,color){
    if(mobileMix===0){circle(x,y,4.5,color,'white',1);return}
    if(mobileMix===1){ctx.beginPath();ctx.moveTo(x,y-5);ctx.lineTo(x+5,y);ctx.lineTo(x,y+5);ctx.lineTo(x-5,y);ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=1;ctx.stroke();return}
    ctx.beginPath();
    for(let i=0;i<64;i++){
        const angle=i*Math.PI/32,c=Math.cos(angle),s=Math.sin(angle);
        const radius=4.5*(1-mobileMix)+5/(Math.abs(c)+Math.abs(s))*mobileMix;
        if(i===0)ctx.moveTo(x+radius*c,y+radius*s);else ctx.lineTo(x+radius*c,y+radius*s);
    }
    ctx.closePath();ctx.fillStyle=color;ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=1;ctx.stroke();
}
function transferEffect(x,y,transfer){
    const u=transfer.progress,envelope=Math.sin(Math.PI*u);
    const radius=['aod_load','aod_recapture'].includes(transfer.op.kind)?24-14*smooth(u):10+14*smooth(u);
    ctx.save();ctx.globalAlpha=.85*envelope;ctx.strokeStyle=theme.moving_color;ctx.lineWidth=2;
    for(let i=0;i<4;i++){
        const angle=i*Math.PI/2+Math.PI/4;
        ctx.beginPath();ctx.arc(x,y,radius,angle-.23,angle+.23);ctx.stroke();
    }
    ctx.restore();
}
function gateEffect(pair,op,X,Y){
    const u=op?clamp((ui.time-op.start)/(op.end-op.start),0,1):0;
    const wave=.5+.5*Math.sin(u*Math.PI*6),[a,b]=pair;
    ctx.save();ctx.globalAlpha=.12+.12*wave;
    line(X(a.x_um),Y(a.y_um),X(b.x_um),Y(b.y_um),theme.active_color,9);
    ctx.globalAlpha=.7;ctx.strokeStyle=theme.active_color;ctx.lineWidth=1.7;
    for(const p of pair){ctx.beginPath();ctx.arc(X(p.x_um),Y(p.y_um),12,-Math.PI/2,-Math.PI/2+2*Math.PI*u);ctx.stroke()}
    ctx.restore();
}
function draw(){if(!width||!height)return;current=sample(ui.time);const {f,pose,columns,rows,atoms}=current,{X,Y,scale}=projection(),scene=f.scene,b=scene.bounds;
ctx.clearRect(0,0,width,height);ctx.font='10px system-ui';ctx.textAlign='left';ctx.textBaseline='alphabetic';
if($('zones').checked)scene.zones.forEach((z,i)=>{ctx.fillStyle=theme.zone_colors[i%theme.zone_colors.length];ctx.fillRect(X(z.bounds.lower.x_um),Y(z.bounds.upper.y_um),(z.bounds.upper.x_um-z.bounds.lower.x_um)*scale,(z.bounds.upper.y_um-z.bounds.lower.y_um)*scale)});
if($('grid').checked){for(const x of scene.grid_x)line(X(x),Y(b.upper.y_um),X(x),Y(b.lower.y_um),theme.grid_color,.6);for(const y of scene.grid_y)line(X(b.lower.x_um),Y(y),X(b.upper.x_um),Y(y),theme.grid_color,.6);for(const p of scene.candidates)circle(X(p.x_um),Y(p.y_um),1.4,theme.muted_color);ctx.fillStyle=theme.muted_color;ctx.textAlign='center';let lastX=-Infinity;for(const x of scene.grid_x){if(X(x)-lastX>=32){ctx.fillText(x,X(x),Y(b.lower.y_um)+18);lastX=X(x)}}ctx.textAlign='right';let lastY=Infinity;for(const y of scene.grid_y){if(lastY-Y(y)>=18){ctx.fillText(y,X(b.lower.x_um)-10,Y(y)+3);lastY=Y(y)}}}
ctx.textAlign='left';if($('zones').checked)scene.zones.forEach((z,i)=>{const text=['01  STORAGE','02  ENTANGLEMENT','03  MEASUREMENT'][i]||z.id;const x=X(z.bounds.lower.x_um)+9,y=Y(z.bounds.upper.y_um)+17;ctx.fillStyle='rgba(250,251,253,.92)';ctx.fillRect(x-4,y-11,126,16);ctx.fillStyle=theme.muted_color;ctx.fillText(text,x,y)});
const routePlan=(data.plans||[]).find(p=>p.id===f.plan_id)||(data.plans||[])[0];
const routeAtom=ui.selected||(routePlan?.requested.find(q=>routePlan.paths[q]));
const route=routePlan?.paths[routeAtom]||[];
$('route-caption').textContent=routePlan?`${routePlan.gate_id} · planner: ${routePlan.planner_id} · ${routeAtom||'—'} 去程 ${Math.max(0,route.length-1)} 段 · 序号为途经点 · SLM 边界半径 ${scene.slm_clearance_um} μm`:'当前记录无物理运输计划';
if($('clearance').checked){ctx.setLineDash([3,3]);for(const trap of scene.traps){if(trap.enabled)circle(X(trap.position.x_um),Y(trap.position.y_um),(scene.slm_clearance_um||0)*scale,null,'#6d829a99',1)}ctx.setLineDash([])}
if($('planned-path').checked&&route.length){ctx.setLineDash([5,5]);for(let i=1;i<route.length;i++)line(X(route[i-1].x_um),Y(route[i-1].y_um),X(route[i].x_um),Y(route[i].y_um),'#bd7d3599',1.6);ctx.setLineDash([]);for(let i=0;i<route.length;i++){const p=route[i];circle(X(p.x_um),Y(p.y_um),3,'#fafbfd','#bd7d35',1);ctx.fillStyle='#966326';ctx.fillText(String(i),X(p.x_um)+(i%2?-16:10),Y(p.y_um)+(i%2?19:-9))}}
if($('trails').checked&&ui.selected){const a=atoms.find(a=>a.id===ui.selected),end=upperBound(frames,ui.time,'time'),step=Math.max(1,Math.ceil(end/128)),samples=[];for(let i=0;i<end;i+=step){const p=sample(frames[i].time).atoms.find(a=>a.id===ui.selected)?.position;if(p)samples.push(p)}if(a?.position)samples.push(a.position);ctx.setLineDash([3,4]);for(let i=1;i<samples.length;i++)line(X(samples[i-1].x_um),Y(samples[i-1].y_um),X(samples[i].x_um),Y(samples[i].y_um),'#a6b1c5',1);ctx.setLineDash([])}
if($('slm').checked)for(const trap of scene.traps){const x=X(trap.position.x_um),y=Y(trap.position.y_um);circle(x,y,TRAP_RADIUS,null,theme.muted_color,1.4);if(!trap.enabled){line(x-4,y-4,x+4,y+4,theme.failure_color);line(x-4,y+4,x+4,y-4,theme.failure_color)}}
if($('aod').checked){for(let row=0;row<f.aod.rows;row++)for(let column=0;column<f.aod.columns;column++){const x=X(columns[column]),y=Y(rows[row]);circle(x,y,TRAP_RADIUS,null,theme.moving_color,1.4)}}
const op=operationAt(ui.time),transfer=$('effects').checked?transferAt(ui.time):null;
if(f.gate_status==='running'){const pair=f.requested.map(id=>atoms.find(a=>a.id===id)?.position);if(pair.length===2&&pair.every(Boolean)){if($('effects').checked)gateEffect(pair,op,X,Y);line(X(pair[0].x_um),Y(pair[0].y_um),X(pair[1].x_um),Y(pair[1].y_um),theme.active_color,2);const distance=Math.hypot(pair[0].x_um-pair[1].x_um,pair[0].y_um-pair[1].y_um);ctx.textAlign='center';ctx.fillStyle=theme.active_color;ctx.fillText(distance.toFixed(2)+' μm',(X(pair[0].x_um)+X(pair[1].x_um))/2,Math.min(Y(pair[0].y_um),Y(pair[1].y_um))-19);ctx.textAlign='left'}}
hits=[];for(const a of atoms){if(!a.position)continue;const x=X(a.position.x_um),y=Y(a.position.y_um),mobile=a.holder.holder_type==='mobile',color=atomColor(a);hits.push({id:a.id,x,y});if(ui.selected===a.id)circle(x,y,16,null,'#5364bc80',1.3);else if(ui.hover===a.id)circle(x,y,16,null,'#5364bc40',1);const handingOver=transfer?.ids.includes(a.id);if(handingOver)transferEffect(x,y,transfer);atomMarker(x,y,handingOver?transfer.mobileMix:(mobile?1:0),color);if($('labels').value==='all'||($('labels').value==='focus'&&(ui.selected===a.id||ui.hover===a.id))){ctx.font='600 10px system-ui';const w=ctx.measureText(a.id).width;ctx.fillStyle='#fafbfdf0';ctx.fillRect(x-w/2-3,y+17,w+6,14);ctx.fillStyle=theme.text_color;ctx.textAlign='center';ctx.fillText(a.id,x,y+28);ctx.textAlign='left';ctx.font='10px system-ui'}}
ctx.fillStyle=theme.muted_color;ctx.font='10px system-ui';ctx.textAlign='center';ctx.fillText('x / μm',X((b.lower.x_um+b.upper.x_um)/2),Y(b.lower.y_um)+36);ctx.save();ctx.translate(X(b.lower.x_um)-36,Y((b.lower.y_um+b.upper.y_um)/2));ctx.rotate(-Math.PI/2);ctx.fillText('y / μm',0,0);ctx.restore();ctx.textAlign='left';updatePanel()}
function updatePanel(){const {f,atoms}=current,op=operationAt(ui.time),transfer=transferAt(ui.time);
const flags=['zones','grid','slm','aod','planned-path','trails','effects','clearance'];
$('display-summary').textContent=flags.filter(id=>$(id).checked).length+' / '+flags.length+' 图层开启';
const gaps=[...current.columns.slice(1).map((x,i)=>x-current.columns[i]),...current.rows.slice(1).map((y,i)=>y-current.rows[i])];
const minGap=gaps.length?Math.min(...gaps):null,limit=data.scene.aod_minimum_spacing_um??1.01;
$('spacing-readout').textContent='AOD trap 当前最小中心距：'+(minGap==null?'单 trap，无邻居':minGap.toFixed(3)+' μm')+'；硬约束 > '+limit+' μm（包括空 trap）。SLM 中心排斥边界半径：'+data.scene.slm_clearance_um+' μm。';
if(data.summary){const s=data.summary,x=150+700*clamp((ui.time-s.window_start_us)/(s.wall_time_us||1),0,1);$('schedule-playhead').setAttribute('x1',x);$('schedule-playhead').setAttribute('x2',x);$('schedule-current').textContent=`当前 ${ui.time.toFixed(2)} μs`+(op?` · ${op.gate_id||''} ${labels[op.label]||op.label} · ${op.start.toFixed(2)}–${op.end.toFixed(2)} μs`:' · 记录结束')}
$('clock').textContent=ui.time.toFixed(2);$('version').textContent='STATE v'+String(f.version).padStart(2,'0');$('gate').textContent=f.gate_label;$('status').textContent=statuses[f.gate_status]||f.gate_status;$('frontier').textContent='READY '+f.ready_count+': '+(f.ready_frontier.join(', ')||'—')+(f.ready_count>20?' …':'');$('gate-states').textContent=Object.entries(f.gate_counts).map(([status,count])=>(statuses[status]||status)+' '+count).join(' · ');$('event').textContent=op?(labels[op.label]||op.label):'周期完成';$('readout').textContent=ui.time.toFixed(2)+' / '+data.duration.toFixed(2)+' μs';$('slider').value=ui.mode==='keyframe'?displayAt(ui.time):ui.time;$('play').textContent=ui.playing?'暂停':'播放';$('previous').disabled=ui.time<=(data.start_time||0);$('next').disabled=ui.time>=data.duration;if(op&&op.index>=0&&Math.floor(op.index/STAGE_PAGE)!==stagePage)renderStages(Math.floor(op.index/STAGE_PAGE));for(const o of visibleOperations)$('stage-'+o.index).setAttribute('aria-current',String(op?.index===o.index));
const progress=op?clamp((ui.time-op.start)/(op.end-op.start),0,1):1;
$('operation-title').textContent=op?(transfer?(['aod_load','aod_recapture'].includes(op.kind)?'SLM → AOD · 原位抓取':'AOD → SLM · 原位释放'):op.kind==='entangling_pulse'?f.gate_label:(labels[op.label]||op.label)):'记录结束 · 已显示全部已提交状态';
$('operation-caption').textContent=transfer?transfer.ids.join(' / ')+' · 交接预览；承载在操作结束时提交':op?.kind==='idle'?'无设备操作 · 原子位置保持不变':op?.kind==='entangling_pulse'?'真实脉冲 '+(op.end-op.start).toFixed(2)+' μs · 红色连线表示作用对':op?(atoms.some(a=>a.holder.holder_type==='mobile')?(data.backend==='row_column'?'行列联动 · 同步三次轨迹 · 保持行列顺序':'刚性平移 · 所有已捕获原子同步移动'):'空载平移 · 原子保持 SLM 承载'):'所有时间与物理指标来自原始事件';
if(op?.transfer_phase)$('operation-caption').textContent+=(op.transfer_phase==='depart'?' · 仅允许离开自身源 trap':' · 仅允许接近自身卸载 trap');
$('operation-progress').textContent=Math.round(progress*100)+'%';
$('operation-fill').style.width=(progress*100)+'%';
$('operation-fill').style.background=op?.kind==='entangling_pulse'?theme.active_color:theme.moving_color;
$('readout').textContent=ui.mode==='keyframe'?'演示 '+(displayAt(ui.time)/1000).toFixed(2)+' / '+(presentationEnd/1000).toFixed(2)+' s · 仿真 '+ui.time.toFixed(2)+' μs':ui.time.toFixed(2)+' / '+data.duration.toFixed(2)+' μs';
$('mode-note').textContent=ui.mode==='keyframe'?'关键帧演示：装载 1.8 s · 卸载 1.6 s · 短门 1.8 s（1×）；阶段内按原轨迹推进。展示时长不计入物理指标。':'真实时间比例：1× = 25 μs 仿真 / 1 s 屏幕时间，所有操作统一缩放；0.3 μs 门约显示 12 ms。';
for(const a of atoms.filter(a=>visibleAtoms.includes(a.id))){const row=$('atom-'+a.id);row.setAttribute('aria-pressed',String(ui.selected===a.id));row.querySelector('.symbol').style.background=atomColor(a);row.querySelector('.symbol').className='symbol '+(a.holder.holder_type==='mobile'?'diamond':'circle');row.querySelector('.atom-state').textContent=(a.holder.holder_type==='mobile'?'AOD':'SLM')+' · '+(names[a.activity]||a.activity)}
const a=atoms.find(a=>a.id===ui.selected);if(a){const h=a.holder,holder=h.holder_type==='mobile'?`AOD · row ${h.holder_id.row}, col ${h.holder_id.column}`:`SLM · ${h.holder_id}`;const partner=f.requested.includes(a.id)?f.requested.filter(id=>id!==a.id).join(', '):'无（附带 / 旁观原子）';const active=transfer?.ids.includes(a.id)?(['aod_load','aod_recapture'].includes(op.kind)?'装载中（交接预览）':'卸载中（交接预览）'):a.activity==='gating'||a.activity==='measuring'?f.gate_label:a.holder.holder_type==='mobile'&&op?(labels[op.label]||op.label):'空闲';$('details').innerHTML='<dl>'+[['原子',a.id],['坐标',a.position?`${a.position.x_um.toFixed(2)}, ${a.position.y_um.toFixed(2)} μm`:'—'],['承载',holder],['当前操作',active],['目标伙伴',partner]].map(([k,v])=>`<dt>${escapeHTML(k)}</dt><dd>${escapeHTML(v)}</dd>`).join('')+'</dl>'}else $('details').textContent='点击画布或列表中的原子，查看位置、承载 trap 和当前操作。'}
function seek(time){if(!Number.isFinite(time))throw new Error('Simulation time must be finite');ui.playing=false;last=null;ui.time=Math.max(data.start_time||0,Math.min(data.duration,time));draw()}
function resize(){const rect=canvas.getBoundingClientRect();width=rect.width;height=rect.height;const dpr=window.devicePixelRatio||1;canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);draw()}
function zoom(factor,x=width/2,y=height/2){const next=Math.max(.65,Math.min(8,view.zoom*factor)),ratio=next/view.zoom;view.panX=x-width/2-(x-width/2-view.panX)*ratio;view.panY=y-height/2-(y-height/2-view.panY)*ratio;view.zoom=next;draw()}
function point(e){const r=canvas.getBoundingClientRect();return {x:e.clientX-r.left,y:e.clientY-r.top}}
function hit(p){let id=null,best=15;for(const h of hits){const d=Math.hypot(h.x-p.x,h.y-p.y);if(d<best){id=h.id;best=d}}return id}
function configureTimeline(){
    $('slider').min=ui.mode==='keyframe'?0:(data.start_time||0);$('slider').max=ui.mode==='keyframe'?presentationEnd:data.duration;
    $('slider').step='any';
    $('slider').setAttribute('aria-label',ui.mode==='keyframe'?'关键帧演示进度':'仿真时间');
    for(const visible of visibleOperations){const op=segments.find(s=>s.index===visible.index);const duration=$('stage-'+op.index).querySelector('em');duration.textContent=ui.mode==='keyframe'?((op.displayEnd-op.displayStart)/1000).toFixed(1)+' s 演示（1×）':''}
}
$('mode').onchange=()=>{ui.mode=$('mode').value;ui.playing=false;last=null;configureTimeline();draw()};
$('slider').oninput=()=>{const t=Number($('slider').value);seek(ui.mode==='keyframe'?simulationAt(t):t)};$('play').onclick=()=>{if(ui.time>=data.duration)ui.time=data.start_time||0;ui.playing=!ui.playing;last=null;draw()};$('reset').onclick=()=>seek(data.start_time||0);$('pulse').disabled=!frames.some(f=>f.gate_status==='running');$('pulse').onclick=()=>{const pulse=frames.find(f=>f.time>ui.time+1e-8&&f.gate_status==='running')||frames.find(f=>f.gate_status==='running');if(pulse)seek(pulse.time)};$('previous').onclick=()=>seek([...frames].reverse().find(f=>f.time<ui.time-1e-8)?.time??0);$('next').onclick=()=>seek(frames.find(f=>f.time>ui.time+1e-8)?.time??data.duration);for(const id of ['labels','grid','slm','aod','trails','effects','planned-path','clearance','zones'])$(id).onchange=draw;
$('fit').onclick=()=>{Object.assign(view,{zoom:1,panX:0,panY:0});draw()};$('zoomin').onclick=()=>zoom(1.3);$('zoomout').onclick=()=>zoom(1/1.3);
canvas.addEventListener('wheel',e=>{e.preventDefault();const p=point(e);zoom(Math.exp(-e.deltaY*.001),p.x,p.y)},{passive:false});
canvas.addEventListener('pointerdown',e=>{if(e.button!==0)return;const p=point(e);drag={...p,startX:p.x,startY:p.y,moved:false};canvas.setPointerCapture(e.pointerId);canvas.classList.add('dragging')});
canvas.addEventListener('pointermove',e=>{const p=point(e);if(drag){const moved=Math.hypot(p.x-drag.startX,p.y-drag.startY)>4;if(drag.moved||moved){view.panX+=p.x-drag.x;view.panY+=p.y-drag.y;drag.moved=true;ui.hover=null}drag.x=p.x;drag.y=p.y;draw()}else{const id=hit(p);if(id!==ui.hover){ui.hover=id;draw()}}});
canvas.addEventListener('pointerup',e=>{if(!drag)return;if(!drag.moved)ui.selected=hit(point(e));drag=null;canvas.classList.remove('dragging');canvas.releasePointerCapture(e.pointerId);draw()});canvas.addEventListener('pointercancel',()=>{drag=null;canvas.classList.remove('dragging')});canvas.addEventListener('pointerleave',()=>{ui.hover=null;draw()});
function renderAtoms(){
 const all=frames[0].scene.atoms.filter(a=>a.id.toLowerCase().includes(atomQuery));
 atomPage=Math.max(0,Math.min(atomPage,Math.ceil(all.length/ATOM_PAGE)-1));
 const list=all.slice(atomPage*ATOM_PAGE,(atomPage+1)*ATOM_PAGE);visibleAtoms=list.map(a=>a.id);
 $('atoms').innerHTML=list.map(a=>`<button class="atom-row" id="atom-${escapeHTML(a.id)}" aria-pressed="false"><i class="symbol circle"></i><strong>${escapeHTML(a.id)}</strong><span class="atom-state"></span></button>`).join('');
 for(const a of list)$('atom-'+a.id).onclick=()=>{ui.selected=a.id;draw()};
 $('atoms-page').textContent=`${all.length} 原子 · ${atomPage+1}/${Math.max(1,Math.ceil(all.length/ATOM_PAGE))}`;
 $('atoms-prev').disabled=atomPage===0;$('atoms-next').disabled=(atomPage+1)*ATOM_PAGE>=all.length;
}
function renderStages(page){
 stagePage=Math.max(0,Math.min(page,Math.ceil(data.operations.length/STAGE_PAGE)-1));
 visibleOperations=data.operations.slice(stagePage*STAGE_PAGE,(stagePage+1)*STAGE_PAGE);
 $('stages').innerHTML=visibleOperations.map(o=>`<button id="stage-${o.index}" class="stage" data-kind="${o.kind}" aria-current="false"><strong>${o.index+1} · ${escapeHTML(o.gate_id)} · ${escapeHTML(labels[o.label]||o.label)}</strong><span>${o.start.toFixed(1)}–${o.end.toFixed(1)} μs</span><em></em></button>`).join('');
 for(const op of visibleOperations)$('stage-'+op.index).onclick=()=>seek(op.start);
 $('stages-page').textContent=`${data.operations.length} 操作 · ${stagePage+1}/${Math.max(1,Math.ceil(data.operations.length/STAGE_PAGE))}`;
 $('stages-prev').disabled=stagePage===0;$('stages-next').disabled=(stagePage+1)*STAGE_PAGE>=data.operations.length;
 configureTimeline();
}
$('atom-search').oninput=()=>{atomQuery=$('atom-search').value.trim().toLowerCase();atomPage=0;renderAtoms();draw()};
$('atoms-prev').onclick=()=>{atomPage--;renderAtoms();draw()};$('atoms-next').onclick=()=>{atomPage++;renderAtoms();draw()};
$('stages-prev').onclick=()=>renderStages(stagePage-1);$('stages-next').onclick=()=>renderStages(stagePage+1);
renderAtoms();renderStages(0);
$('summary').innerHTML=summaryMarkup(data.summary,data.operations);
if(data.summary){
 const activate=e=>{const value=e.target.getAttribute?.('data-start');if(value!=null){seek(Number(value));return true}return false};
 $('schedule').onclick=activate;
 $('schedule').onkeydown=e=>{if((e.key==='Enter'||e.key===' ')&&activate(e))e.preventDefault()};
}
// Hidden tabs pause; a resumed tab must not jump over the short gate.
const visibility=()=>{if(document.hidden){ui.playing=false;last=null;draw()}};document.addEventListener('visibilitychange',visibility);
function tick(now){
    if(disposed)return;
    if(ui.playing&&last!==null){
        const elapsed=Math.max(0,now-last)*Number($('speed').value);
        ui.time=ui.mode==='keyframe'?simulationAt(displayAt(ui.time)+elapsed):Math.min(data.duration,ui.time+elapsed*US_PER_MS);
        if(ui.time>=data.duration)ui.playing=false;
        draw();
    }
    last=now;raf=requestAnimationFrame(tick);
}
$('backend-caption').textContent=data.backend==='row_column'?'ROW / COLUMN AOD · 行列伸缩与平移 · 返回并卸载':data.operations.some(op=>op.kind==='aod_park')?'RIGID AOD · SZ 同运 → EZ 局部交接 → CZ → 恢复构型并同返':'RIGID AOD · 刚性平移 · 静态伙伴配对 · 返回并卸载';
$('motion-note').textContent=data.backend==='row_column'?'按行列坐标与三次轨迹采样；采用配置的峰值速度/加速度/段内 jerk 限制，未模拟光场、加热与损失。':'轨迹按移动事件线性插值，未模拟加速度与加热。';
const observer=new ResizeObserver(resize);observer.observe($('viewport'));resize();raf=requestAnimationFrame(tick);

const api={setTime:seek,selectAtom(id){ui.selected=id;draw()},
 play(){ui.playing=true;last=null},pause(){ui.playing=false;last=null;draw()},
 getStatus(){return {time_us:ui.time,selected_atom:ui.selected,playing:ui.playing,visible_atom_rows:visibleAtoms.length,visible_operation_rows:visibleOperations.length}},
 destroy(){disposed=true;cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('visibilitychange',visibility);root.innerHTML='';mounted.delete(container)},
 debug:{data,frames,ui,view,seek,sample,displayAt,simulationAt,operationAt,transferAt,tick,renderStages,draw,projection,
        get presentationEnd(){return presentationEnd},get current(){return current},get hits(){return hits}}};
mounted.set(container,api);return api;

}
scope.NeutralAtomViewer={mount};
})(typeof window!=="undefined"?window:globalThis);
