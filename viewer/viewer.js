"use strict";
// The light shell follows the shared Enola/QEC motion viewer. The data adapter
// remains specific to this project's AtomProgram/EventTrace contract.
const DATA=JSON.parse(document.getElementById('payload').textContent), PLAN=DATA.atom_program, TRACE=DATA.display_trace||DATA.trace;
const $=id=>document.getElementById(id), NS='http://www.w3.org/2000/svg';
const actions=[...PLAN.actions].sort((a,b)=>a.t_start_us-b.t_start_us||a.t_end_us-b.t_end_us);
const eventMap=new Map((TRACE?.events||[]).map(e=>[e.action_id,e]));
const included=a=>!TRACE||eventMap.get(a.id)?.status==='completed';
const start=actions.reduce((v,a)=>Math.min(v,a.t_start_us),0);
const end=Object.values(TRACE?.results||{}).reduce((v,r)=>Math.max(v,r.ready_us),actions.reduce((v,a)=>Math.max(v,a.t_end_us),start));
const boundaries=[...new Set([start,end,...actions.flatMap(a=>[a.t_start_us,a.t_end_us]),...Object.values(TRACE?.results||{}).map(r=>r.ready_us)])].sort((a,b)=>a-b);
const calls=DATA.strategy_context?.calls||[], callButtons=[];
const fmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:3}), clone=x=>JSON.parse(JSON.stringify(x));
const shortAtom=id=>id.replace(/^atom:/,'');
const kinds={move:'移动',pickup:'装载',drop:'卸载',gate:'门操作',measure:'测量',reset:'复位',wait:'等待'};
const actionName=a=>a.kind==='gate'?(a.payload.name||'门操作'):(kinds[a.kind]||a.kind);
const callName=c=>({prepare:'制备',syndrome_round:'综合征',SE:'综合征',logical_cx:'逻辑 CX',CX:'逻辑 CX',CZ:'逻辑 CZ'}[c.operation]||c.operation)+' · '+(c.operands?.control?`${c.operands.control} → ${c.operands.target}`:Object.values(c.operands||{}).join(' / '));
const colors={idle:'#5865b6',move:'#df943e',gate:'#d65368',grid:'#dfe5ed',text:'#25334b',muted:'#8190a3'};
let current=start,selected=null,selectedAtom=null,page=0,atomPage=0,playing=false,lastFrame=null;
let frameState=null,frameActions=[],frameByAtom=new Map(),drag=null,suppressClick=false;
function node(tag,attrs={},text){const e=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function button(text,fn,cls){const b=el('button',text,cls);b.onclick=fn;return b;}
function stateAt(t){
 const state=new Map(PLAN.initial_state.atoms.map(a=>[a.atom_id,clone(a)]));
 for(const a of actions){
  if(a.t_start_us>t||!included(a))continue;
  const p=a.payload;
  if(a.kind==='move'){
   const f=a.t_end_us===a.t_start_us?1:Math.min(1,Math.max(0,(t-a.t_start_us)/(a.t_end_us-a.t_start_us)));
   for(const tr of p.trajectories){const atom=state.get(tr.atom_id);atom.position_um=tr.from_um.map((v,i)=>v+(tr.to_um[i]-v)*f);atom.row_id=tr.row_id;atom.column_id=tr.column_id;}
  }
  if(a.t_end_us<=t&&(a.kind==='pickup'||a.kind==='drop'))for(const b of p.bindings||a.atoms.map(id=>({atom_id:id,...p}))){
   const atom=state.get(b.atom_id);atom.carrier=a.kind==='pickup'?'AOD':'SLM';atom.trap_id=b.to_trap_id;
   atom.row_id=a.kind==='pickup'?b.row_id:null;atom.column_id=a.kind==='pickup'?b.column_id:null;atom.aod_group=b.aod_group||p.aod_group||atom.aod_group;
  }
 }
 return state;
}
function active(a){return included(a)&&a.t_start_us<=current&&(current<a.t_end_us||(a.t_start_us===a.t_end_us&&current===a.t_start_us));}
const allPositions=[...PLAN.initial_state.atoms.map(a=>a.position_um),...(PLAN.initial_state.slm_traps||[]).map(t=>t.position_um),...actions.filter(a=>a.kind==='move').flatMap(a=>a.payload.trajectories.flatMap(t=>[t.from_um,t.to_um]))];
const zones={...(DATA.device?.zones||{})};
if(DATA.device?.grouped_profile?.initialization_zone)zones.initialization=DATA.device.grouped_profile.initialization_zone;
function bounds(points){return points.reduce((b,p)=>[Math.min(b[0],p[0]),Math.max(b[1],p[0]),Math.min(b[2],p[1]),Math.max(b[3],p[1])],[Infinity,-Infinity,Infinity,-Infinity]);}
const world=bounds(allPositions.length?allPositions:[[0,0]]);
for(const z of Object.values(zones)){
 for(const v of z.x_range_um||[])if(Number.isFinite(v)){world[0]=Math.min(world[0],v);world[1]=Math.max(world[1],v);}
 for(const v of z.y_range_um||[])if(Number.isFinite(v)){world[2]=Math.min(world[2],v);world[3]=Math.max(world[3],v);}
}
// A single isotropic transform preserves the actual geometry. No broken axes.
const width=1000,height=650,margin=58;
const scale=Math.min((width-2*margin)/(world[1]-world[0]+30),(height-2*margin)/(world[3]-world[2]+25));
const px=x=>width/2+(x-(world[0]+world[1])/2)*scale;
const py=y=>height/2+((world[2]+world[3])/2-y)*scale;
const ux=x=>(x-width/2)/scale+(world[0]+world[1])/2;
const uy=y=>(height/2-y)/scale+(world[2]+world[3])/2;
let zoom=1,viewCenter=[width/2,height/2];
function viewport(){return {x:viewCenter[0]-width/zoom/2,y:viewCenter[1]-height/zoom/2,w:width/zoom,h:height/zoom};}
function applyViewport(){const v=viewport();$('scene').setAttribute('viewBox',`${v.x} ${v.y} ${v.w} ${v.h}`);}
function fitPoints(points){if(!points.length)return;const b=bounds(points);viewCenter=[px((b[0]+b[1])/2),py((b[2]+b[3])/2)];zoom=Math.max(.5,Math.min(14,Math.min((width-140)/((b[1]-b[0]+18)*scale),(height-140)/((b[3]-b[2]+18)*scale))));renderScene();}
function fitActive(){const points=frameActions.flatMap(a=>[...a.atoms.map(id=>frameState.get(id).position_um),...(a.kind==='move'?a.payload.trajectories.flatMap(tr=>[tr.from_um,tr.to_um]):[])]);fitPoints(points.length?points:[...frameState.values()].map(a=>a.position_um));}
function actionColor(a){return !a?colors.idle:['move','pickup','drop'].includes(a.kind)?colors.move:['gate','measure','reset'].includes(a.kind)?colors.gate:colors.idle;}
function gridStep(span){const v=span/9,p=Math.pow(10,Math.floor(Math.log10(Math.max(v,.0001))));return [1,2,5,10].find(n=>n*p>=v)*p;}
function renderScene(){
 const svg=$('scene');svg.replaceChildren();applyViewport();
 svg.setAttribute('class',$('labels').value==='all'?'all-labels':$('labels').value==='none'?'no-labels':'focus-labels');
 const v=viewport(),font=12/zoom,stroke=1/zoom;
 const left=ux(v.x+40/zoom),right=ux(v.x+v.w-25/zoom),top=uy(v.y+25/zoom),bottom=uy(v.y+v.h-50/zoom);
 if($('showZones').checked)for(const[id,z]of Object.entries(zones)){
  if(!z.x_range_um||!z.y_range_um)continue;
  const l=Math.max(left,z.x_range_um[0]??left),r=Math.min(right,z.x_range_um[1]??right),lo=Math.max(bottom,z.y_range_um[0]??bottom),hi=Math.min(top,z.y_range_um[1]??top);
  if(r<=l||hi<=lo)continue;
  svg.append(node('rect',{x:px(l),y:py(hi),width:(r-l)*scale,height:(hi-lo)*scale,fill:id==='measurement'?'#eaf3ef':id==='initialization'?'#eef2f7':'#f0edf8','data-layer':'zone'}));
  svg.append(node('text',{x:px(l)+9/zoom,y:py(hi)+16/zoom,fill:colors.muted,'font-size':font},({storage_entanglement:'01  存储 / 纠缠区',measurement:'02  测量区',initialization:'00  初始化区'})[id]||id));
 }
 if($('showGrid').checked){
  const step=gridStep(Math.max(right-left,top-bottom));
  for(let x=Math.ceil(left/step)*step;x<=right;x+=step){svg.append(node('line',{x1:px(x),x2:px(x),y1:py(top),y2:py(bottom),stroke:colors.grid,'stroke-width':stroke*.6}));svg.append(node('text',{x:px(x),y:py(bottom)+18/zoom,'text-anchor':'middle',fill:colors.muted,'font-size':font*.8},fmt(x)));}
  for(let y=Math.ceil(bottom/step)*step;y<=top;y+=step){svg.append(node('line',{x1:px(left),x2:px(right),y1:py(y),y2:py(y),stroke:colors.grid,'stroke-width':stroke*.6}));svg.append(node('text',{x:px(left)-7/zoom,y:py(y)+3/zoom,'text-anchor':'end',fill:colors.muted,'font-size':font*.8},fmt(y)));}
  svg.append(node('text',{x:px(right),y:py(bottom)+34/zoom,fill:colors.muted,'font-size':font*.85,'text-anchor':'end'},'x / μm'));
  svg.append(node('text',{x:px(left)-20/zoom,y:py(top)-7/zoom,fill:colors.muted,'font-size':font*.85},'y / μm'));
 }
 const declaredTraps=DATA.session_context?Array.from(new Map(DATA.session_context.trap_declarations.filter(d=>d.at_us<=current).flatMap(d=>d.traps).map(t=>[t.trap_id,t])).values()):(PLAN.initial_state.slm_traps||[]);
 if($('showTraps').checked)for(const trap of declaredTraps){const [x,y]=trap.position_um;svg.append(node('circle',{cx:px(x),cy:py(y),r:1.6*scale,fill:'none',stroke:'#a5afbf','stroke-width':.35*scale,'data-layer':'trap'}));}
 if($('showAxes').checked){
  const axes=new Map();for(const atom of frameState.values())if(atom.carrier==='AOD'){
   if(atom.row_id!=null)axes.set(atom.aod_group+'/r/'+atom.row_id,{vertical:false,v:atom.position_um[1]});
   if(atom.column_id!=null)axes.set(atom.aod_group+'/c/'+atom.column_id,{vertical:true,v:atom.position_um[0]});
  }
  for(const axis of axes.values())svg.append(node('line',{...(axis.vertical?{x1:px(axis.v),x2:px(axis.v),y1:py(top),y2:py(bottom)}:{x1:px(left),x2:px(right),y1:py(axis.v),y2:py(axis.v)}),stroke:'#cab183','stroke-width':stroke*.8,'stroke-dasharray':`${3/zoom} ${5/zoom}`,opacity:.65,'data-layer':'axis'}));
 }
 for(const a of frameActions){
  if(a.kind==='move'&&$('showPaths').checked)for(const tr of a.payload.trajectories)svg.append(node('line',{x1:px(tr.from_um[0]),y1:py(tr.from_um[1]),x2:px(tr.to_um[0]),y2:py(tr.to_um[1]),stroke:colors.move,'stroke-dasharray':`${4/zoom} ${4/zoom}`,'stroke-width':stroke*1.2,opacity:.7,'data-layer':'path'}));
  if(a.kind==='gate'&&a.payload.name==='CZ'&&$('showEffects').checked)for(const pair of a.payload.pairs||[]){const p=frameState.get(pair[0]).position_um,q=frameState.get(pair[1]).position_um;const line=node('line',{x1:px(p[0]),y1:py(p[1]),x2:px(q[0]),y2:py(q[1]),stroke:colors.gate,'stroke-width':.7*scale,'stroke-linecap':'round','data-layer':'cz'});line.append(node('title',{},`CZ · ${pair.join(' ↔ ')}`));svg.append(line);}
 }
 for(const atom of frameState.values()){
  const[x,y]=atom.position_um,cx=px(x),cy=py(y),a=frameByAtom.get(atom.atom_id),color=actionColor(a),r=.95*scale;
  const g=node('g',{class:'atom'+(selectedAtom===atom.atom_id?' selected':''),'data-atom-id':atom.atom_id});
  // Larger transparent hit area leaves the physical-scale drawing uncluttered.
  g.append(node('circle',{cx,cy,r:Math.max(r*2.4,8/zoom),fill:'transparent'}));
  if((a&&$('showEffects').checked)||selectedAtom===atom.atom_id)g.append(node('circle',{cx,cy,r:2.15*scale,fill:'none',stroke:color,'stroke-width':.4*scale,opacity:.65}));
  g.append(atom.carrier==='AOD'?node('path',{d:`M ${cx} ${cy-r*1.3} L ${cx+r*1.3} ${cy} L ${cx} ${cy+r*1.3} L ${cx-r*1.3} ${cy} Z`,fill:color}):node('circle',{cx,cy,r,fill:color}));
  g.append(node('text',{x:cx+4/zoom+r,y:cy-r-3/zoom,fill:colors.text,'font-size':font,class:'atom-label'},shortAtom(atom.atom_id)));
  g.append(node('title',{},`${atom.atom_id} · ${atom.carrier} · (${fmt(x)}, ${fmt(y)}) μm${a?' · '+actionName(a):''}`));
  g.addEventListener('click',()=>{if(!suppressClick)selectAtom(atom.atom_id);});svg.append(g);
 }
}
function selectAtom(id){selectedAtom=id;renderScene();renderAtoms();}
function renderAtoms(){
 const q=$('atomSearch').value.toLowerCase(),atoms=[...frameState.values()].filter(a=>[a.atom_id,a.qubit_id].join(' ').toLowerCase().includes(q));
 const pages=Math.max(1,Math.ceil(atoms.length/6));atomPage=Math.max(0,Math.min(atomPage,pages-1));$('atomList').replaceChildren();
 for(const atom of atoms.slice(atomPage*6,atomPage*6+6)){
  const a=frameByAtom.get(atom.atom_id),b=button('',()=>selectAtom(atom.atom_id),'atom-row'),icon=el('i',undefined,'symbol '+(atom.carrier==='AOD'?'diamond':'circle'));
  icon.style.background=actionColor(a);b.setAttribute('aria-pressed',selectedAtom===atom.atom_id?'true':'false');b.title=atom.atom_id;
  b.append(icon,el('b',shortAtom(atom.atom_id)),el('span',atom.carrier+' · '+(a?actionName(a):'空闲')));$('atomList').append(b);
 }
 if(!atoms.length)$('atomList').append(el('p','没有匹配的原子','muted'));
 $('atomPage').textContent=`${atoms.length} 原子 · ${atomPage+1}/${pages}`;$('atomPrev').disabled=atomPage===0;$('atomNext').disabled=atomPage===pages-1;
 if(!selectedAtom)return;const atom=frameState.get(selectedAtom),a=frameByAtom.get(selectedAtom),detail=$('atomDetail');detail.replaceChildren();detail.append(el('b',atom.atom_id));
 const dl=el('dl');for(const[label,value]of [['量子位',atom.qubit_id||'未声明'],['位置',atom.position_um.map(fmt).join(', ')+' μm'],['载体',atom.carrier],['操作',a?actionName(a):'空闲']])dl.append(el('dt',label),el('dd',value));detail.append(dl);
 if(a)detail.append(button('查看当前操作',()=>selectAction(a)));
 const raw=el('details');raw.append(el('summary','完整载体 / 阱 / 行列身份'),el('pre',JSON.stringify(atom,null,2)));detail.append(raw);
}
function renderCurrent(){
 const currentCalls=calls.filter(c=>c.start_us<=current&&current<c.end_us),counts=new Map();
 for(const a of frameActions){const key=actionName(a);counts.set(key,(counts.get(key)||0)+1);}
 const description=[...counts].map(([name,n])=>`${name} × ${n}`).join(' · ');
 const heading=currentCalls.map(callName).join(' / ')||(current>=end?'回放结束':'原子动作回放');
 $('operationTitle').textContent=heading;$('currentOperation').textContent=description||'此刻无活动动作';
 $('activeLabel').textContent=description?`${description} · ${frameByAtom.size} 个原子参与`:'沿同一模型时间轴查看事件与结果';
 $('currentSummary').textContent=`${frameActions.length} 个活动动作 · ${frameByAtom.size} 个参与原子`;
 const a=frameActions[0],progress=a?(a.t_end_us===a.t_start_us?100:(current-a.t_start_us)/(a.t_end_us-a.t_start_us)*100):current>=end?100:0;
 $('operationProgress').textContent=a?`${Math.round(progress)}%`:'—';$('operationFill').style.width=progress+'%';
 $('currentActions').replaceChildren();for(const item of frameActions.slice(0,4))$('currentActions').append(button(`${actionName(item)} · ${item.atoms.length} 原子`,()=>selectAction(item)));
 for(const {c,b}of callButtons)b.setAttribute('aria-current',currentCalls.includes(c)?'true':'false');
}
function renderResults(){
 const box=$('results');box.replaceChildren();const all=Object.entries(TRACE?.results||{}),ready=all.filter(([_,r])=>r.ready_us<=current);
 $('resultCount').textContent=`${ready.length} / ${all.length} ready`;
 for(const[id,r]of ready)box.append(el('span',`${id} = ${r.value} · fake · ready ${fmt(r.ready_us)}`,'result'));
 if(!ready.length)box.append(el('span',TRACE?'此刻尚无 ready 结果':'计划模式：没有运行结果','muted'));
}
function setTime(t){
 if(!Number.isFinite(Number(t)))return;
 current=Math.min(end,Math.max(start,Number(t)));$('time').value=current;$('timeLabel').textContent=fmt(current);
 $('readout').textContent=`${fmt(current)} / ${fmt(end)} μs`;$('progressLabel').textContent=`全程 ${fmt((end-start)/1000)} ms · ${fmt((current-start)/(end-start||1)*100)}%`;
 frameState=stateAt(current);frameActions=actions.filter(active);frameByAtom=new Map();for(const a of frameActions)for(const id of a.atoms)frameByAtom.set(id,a);
 renderScene();renderAtoms();renderCurrent();renderResults();
}
function selectAction(a){
 if(!a)return;selected=a.id;playing=false;playState();$('operationsPanel').open=true;
 $('selectionHint').textContent='原始 action 与同次事件；source_ids 可搜索';
 $('detail').textContent=JSON.stringify({action:a,event:TRACE?eventMap.get(a.id):'无事件：compile_plan'},null,2);
 setTime(a.t_start_us);renderTable();
}
function renderTable(){
 const q=$('search').value.toLowerCase(),filtered=actions.filter(a=>JSON.stringify([a.id,a.source_ids,a.atoms,a.kind,a.payload.name,a.payload.group_id]).toLowerCase().includes(q));
 const pages=Math.max(1,Math.ceil(filtered.length/60));page=Math.max(0,Math.min(page,pages-1));const body=$('actions');body.replaceChildren();
 for(const a of filtered.slice(page*60,(page+1)*60)){
  const tr=el('tr',undefined,'actionrow'+(a.id===selected?' selected':''));
  tr.append(el('td',`${fmt(a.t_start_us)} – ${fmt(a.t_end_us)}`),el('td',actionName(a)),el('td',a.atoms.length>3?`${a.atoms.slice(0,3).map(shortAtom).join(', ')} … 共 ${a.atoms.length} 个`:a.atoms.map(shortAtom).join(', ')));
  const src=el('td'),sources=el('div',a.source_ids.join(' · '),'source-preview');sources.title=a.source_ids.join(' · ');src.append(sources,el('div',a.id,'secondary'));tr.append(src,el('td',TRACE?eventMap.get(a.id)?.status:'计划'));tr.addEventListener('click',()=>selectAction(a));body.append(tr);
 }
 $('pageLabel').textContent=`${filtered.length} 条 · ${page+1} / ${pages}`;$('pagePrev').disabled=page===0;$('pageNext').disabled=page===pages-1;
}
function playState(){
 $('play').textContent=playing?'暂停':'播放';$('playbackStatus').textContent=playing?'正在回放 · 拖动时间轴或逐事件查看':current>=end?'回放结束 · 可回到起点或逐事件查看':'已暂停 · 点击播放，或拖动时间轴查看过程';lastFrame=null;
}
function noteMode(){$('modeNote').textContent=$('playMode').value==='keyframe'?'逐事件演示：相邻事件边界之间展示 0.6 秒（1×）；区间内按原轨迹插值。演示时长不计入模型时间。':'全程 30 秒（1×）：按模型时间等比例回放，短门可用“下一 CZ”单独查看。';}
function boundaryIndex(t){let lo=0,hi=boundaries.length;while(lo<hi){const mid=(lo+hi)>>1;if(boundaries[mid]<=t)lo=mid+1;else hi=mid;}return Math.min(Math.max(0,lo-1),Math.max(0,boundaries.length-2));}
function advance(t,screenSeconds,mode,speed){
 if(mode==='uniform')return Math.min(end,t+screenSeconds*(end-start)/30*speed);
 if(boundaries.length<2||t>=end)return end;
 let i=boundaryIndex(t),progress=(t-boundaries[i])/(boundaries[i+1]-boundaries[i])+screenSeconds*speed/.6;
 while(progress>=1&&i<boundaries.length-2){progress--;i++;}
 return Math.min(end,boundaries[i]+Math.min(1,progress)*(boundaries[i+1]-boundaries[i]));
}
function tick(stamp){if(playing){if(lastFrame!==null){setTime(advance(current,Math.min(.1,(stamp-lastFrame)/1000),$('playMode').value,Number($('speed').value)));if(current>=end){playing=false;playState();}}lastFrame=stamp;}requestAnimationFrame(tick);}
function jump(t){playing=false;setTime(t);playState();}
function jumpKind(kind){const a=actions.find(a=>a.t_start_us>current&&included(a)&&(kind==='CZ'?a.kind==='gate'&&a.payload.name==='CZ':a.kind===kind));if(a){jump(a.t_start_us);fitActive();}else{playing=false;playState();$('playbackStatus').textContent=kind==='CZ'?'后续没有 CZ 动作':'后续没有测量动作';}}
$('time').min=start;$('time').max=end;$('seekTime').max=end;
$('time').addEventListener('input',e=>jump(e.target.value));$('search').addEventListener('input',()=>{page=0;renderTable();});
$('atomSearch').addEventListener('input',()=>{atomPage=0;renderAtoms();});$('atomPrev').onclick=()=>{atomPage--;renderAtoms();};$('atomNext').onclick=()=>{atomPage++;renderAtoms();};
$('pagePrev').onclick=()=>{page--;renderTable();};$('pageNext').onclick=()=>{page++;renderTable();};
$('prev').onclick=()=>jump([...boundaries].reverse().find(t=>t<current)??start);$('next').onclick=()=>jump(boundaries.find(t=>t>current)??end);
$('nextGate').onclick=()=>jumpKind('CZ');$('nextMeasure').onclick=()=>jumpKind('measure');$('toStart').onclick=()=>jump(start);$('toEnd').onclick=()=>jump(end);
$('seek').onclick=()=>{const t=Number($('seekTime').value);if($('seekTime').value!==''&&Number.isFinite(t))jump(t);};
$('play').onclick=()=>{playing=!playing;if(playing&&current>=end)setTime(start);playState();};$('playMode').addEventListener('change',()=>{lastFrame=null;noteMode();});
for(const id of ['showZones','showGrid','showTraps','showAxes','showPaths','showEffects','labels'])$(id).addEventListener('change',renderScene);
$('fitAll').onclick=()=>{zoom=1;viewCenter=[width/2,height/2];renderScene();};$('fitAtoms').onclick=()=>fitPoints([...frameState.values()].map(a=>a.position_um));$('fitActive').onclick=fitActive;
$('zoomIn').onclick=()=>{zoom=Math.min(14,zoom*1.4);renderScene();};$('zoomOut').onclick=()=>{zoom=Math.max(.5,zoom/1.4);renderScene();};
// Pointer coordinates use the SVG screen transform, including letterboxing.
function svgPoint(e){const p=$('scene').createSVGPoint();p.x=e.clientX;p.y=e.clientY;return p.matrixTransform($('scene').getScreenCTM().inverse());}
$('scene').addEventListener('wheel',e=>{if(!e.ctrlKey)return;e.preventDefault();const p=svgPoint(e),old=zoom;zoom=Math.max(.5,Math.min(14,zoom*Math.exp(-e.deltaY*.002)));viewCenter=[p.x+(viewCenter[0]-p.x)*old/zoom,p.y+(viewCenter[1]-p.y)*old/zoom];renderScene();},{passive:false});
$('scene').addEventListener('pointerdown',e=>{if(e.button!==0)return;const m=$('scene').getScreenCTM();drag={x:e.clientX,y:e.clientY,center:[...viewCenter],scale:m.a,moved:false,pointer:e.pointerId};suppressClick=false;});
$('scene').addEventListener('pointermove',e=>{if(!drag||drag.pointer!==e.pointerId)return;if(Math.hypot(e.clientX-drag.x,e.clientY-drag.y)>4){drag.moved=true;suppressClick=true;$('scene').setPointerCapture(e.pointerId);}if(drag.moved){viewCenter=[drag.center[0]-(e.clientX-drag.x)/drag.scale,drag.center[1]-(e.clientY-drag.y)/drag.scale];renderScene();}});
function endDrag(e){if(drag?.pointer===e.pointerId){if($('scene').hasPointerCapture(e.pointerId))$('scene').releasePointerCapture(e.pointerId);drag=null;}}
$('scene').addEventListener('pointerup',endDrag);$('scene').addEventListener('pointercancel',endDrag);
$('scene').addEventListener('keydown',e=>{if(e.code==='Space'){e.preventDefault();$('play').onclick();}if(e.code==='ArrowLeft'){e.preventDefault();$('prev').onclick();}if(e.code==='ArrowRight'){e.preventDefault();$('next').onclick();}});
// Evidence stays complete, below the motion workspace.
$('subtitle').textContent=`${PLAN.initial_state.atoms.length} 个原子 · ${calls.length?calls.length+' 个逻辑调用 · ':''}${actions.length} 个动作 · ${TRACE?'无丢失 fake 场景':'编译计划'}`;
$('subtitle').title=PLAN.artifact_id;$('modeBadge').textContent=TRACE?'FAKE · 无量子采样':'COMPILE PLAN · 未运行';
$('evidenceNote').textContent=TRACE?'FAKE 场景 · 无量子采样 · 未模拟量子态 · 未执行硬件。':'编译计划 · 未运行 · 未模拟量子态 · 未执行硬件。';
if(DATA.session_context){$('modeBadge').textContent='FAKE · 连续窗口';$('subtitle').textContent+=` · ${DATA.session_context.window_count} 个已提交窗口`;$('evidenceNote').textContent+=` 本页为 ${DATA.session_context.window_count} 个原始窗口的只读显示投影，未生成新的执行计划。`;}
$('fixtureBadge').textContent=DATA.fixture?'FIXTURE · 查看器自测':'真实生产模块工件';
$('backendBadge').textContent=DATA.strategy_context?Array.from(new Set(calls.map(c=>c.backend_used))).join(' / '):(PLAN.provenance.backend_used||'后端未声明');
$('actionCount').textContent=actions.length+' 个动作';$('callCount').textContent=calls.length+' 次调用';$('groupCount').textContent=(DATA.group_projection||[]).length+' 组';$('callsPanel').hidden=!calls.length;
for(const[cIndex,c]of calls.entries()){const b=button('',()=>jump(c.start_us),'call-card');b.append(el('strong',`${String(cIndex+1).padStart(2,'0')}  ${callName(c)}`),el('span',`${fmt(c.start_us)} – ${fmt(c.end_us)} μs`));b.title=c.call_id;callButtons.push({c,b});$('calls').append(b);}
for(const[label,value]of [['物理载体',PLAN.initial_state.atoms.length],['原子动作',actions.length],['统一时长 μs',fmt(end-start)],['已执行 / 跳过',TRACE?`${TRACE.events.filter(e=>e.status==='completed').length} / ${TRACE.events.filter(e=>e.status==='skipped').length}`:'未运行']]){const b=el('div',undefined,'stat');b.append(el('b',value),el('span',label));$('stats').append(b);}
const report=DATA.report,validationText=report?(report.passed?'R6 报告 passed':report.scoped_pass?'R6 限定检查通过；仍有未验证项':'R6 检查失败 / 未完成'):'未提供独立验证报告';
$('validationSummary').textContent=validationText;$('validation').append(el('b',validationText,report?.passed?'good':'warn'));
if(report)$('validation').append(el('pre',JSON.stringify({scope:report.scope,failures:report.failures,unverified:report.unverified,out_of_scope:report.out_of_scope},null,2)));
$('illumination').textContent=TRACE?JSON.stringify(TRACE.illumination_counts,null,2):'计划模式：没有运行累计值';
for(const[key,r]of Object.entries(DATA.receipts)){const box=el('div');box.append(el('b',key+' / '+r.name),el('br'),el('code','byte '+r.byte_sha256),el('br'),el('code','canonical '+r.canonical_sha256));$('hashes').append(box);}
for(const[i,group]of (DATA.group_projection||[]).entries()){
 const box=el('details'),summary=el('summary',`${String(i+1).padStart(2,'0')} · ${group.purpose==='patch_initialization_transport'?'初始化运输':group.purpose} · ${group.members.length} 原子`);box.append(summary);
 box.append(el('p',group.group_id,'muted'));
 const spans=['readout_start_span_us','readout_end_span_us','result_ready_span_us'].map((key,i)=>['读出开始跨度','读出结束跨度','结果 ready 跨度'][i]+': '+(group[key]===null?'不适用':fmt(group[key])+' μs')).join(' · ');box.append(el('p',spans));
 box.append(button('查看本组动作',()=>{$('search').value=group.group_id;page=0;$('operationsPanel').open=true;renderTable();}));
 const table=el('table'),head=el('tr');for(const s of ['原子 / 结果 ID','读出开始','读出结束','ready'])head.append(el('th',s));table.append(head);
 for(const m of group.measurements){const row=el('tr');row.append(el('td',m.atoms.join(', ')+' / '+m.result_id),el('td',fmt(m.t_start_us)),el('td',fmt(m.t_end_us)),el('td',fmt(m.ready_us)));row.onclick=()=>selectAction(actions.find(a=>a.id===m.action_id));table.append(row);}
 const wrap=el('div',undefined,'tablewrap');wrap.append(table);box.append(wrap,el('p',`实际 move 动作 ${group.move_action_ids.length}；不将运动片段数视作运输批次数。`,'muted'));
 box.append(el('pre',JSON.stringify({members:group.members,explicit_wait_actions:group.wait_actions,split_reasons:group.split_reasons.length?group.split_reasons:'未报告',reported_metrics:group.reported_metrics??'未报告',runtime_metrics:group.runtime_metrics??'未报告'},null,2)));$('groups').append(box);
}
if(!(DATA.group_projection||[]).length)$('groups').textContent='本工件未声明 group_id；不推断分组或同步资格。';
if(DATA.strategy_context)$('strategyInfo').append(el('pre',JSON.stringify(DATA.strategy_context,null,2)));
noteMode();renderTable();setTime(start);if(DATA.device?.entry_mode==='preinitialized')fitPoints([...frameState.values()].map(a=>a.position_um));requestAnimationFrame(tick);
window.naViewer={stateAt,data:DATA,get currentTime(){return current;},setTime,advance,selectAtom,get viewport(){return {...viewport(),zoom};}};
