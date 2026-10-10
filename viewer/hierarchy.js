"use strict";
const H=JSON.parse(document.getElementById('hierarchyPayload').textContent),V=H.values,D=V.logical_dag,P=V.patch_placement,S=V.initial_state;
const $=id=>document.getElementById(id),NS='http://www.w3.org/2000/svg';
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;}
function svg(tag,attrs={},text){const e=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;return e;}
const fmt=n=>Number(n).toLocaleString('en-US',{maximumFractionDigits:2}),nodes=new Map(D.nodes.map(n=>[n.id,n]));
const parents=new Map(D.nodes.map(n=>[n.id,new Set()])),children=new Map(D.nodes.map(n=>[n.id,new Set()]));
for(const e of D.edges){parents.get(e.target).add(e.source);children.get(e.source).add(e.target);}
const todo=D.nodes.filter(n=>!parents.get(n.id).size).map(n=>n.id),depth=new Map(todo.map(id=>[id,0])),left=new Map([...parents].map(([id,p])=>[id,p.size]));
for(const id of todo)for(const child of children.get(id)){depth.set(child,Math.max(depth.get(child)||0,depth.get(id)+1));left.set(child,left.get(child)-1);if(left.get(child)===0)todo.push(child);}
if(todo.length!==D.nodes.length)throw Error('Logical DAG cycle or missing node');
let first=0,selected=null,selectedPatch=null;const maxDepth=Math.max(0,...depth.values()),byDepth=new Map();
for(const id of todo){const d=depth.get(id);if(!byDepth.has(d))byDepth.set(d,[]);byDepth.get(d).push(id);}
const pairLabel=n=>Object.values(n.patch_operands).join(n.operation==='CX'?' → ':' · ');
function switchView(view){$('hLogicalStage').hidden=view!=='logical';$('hPlacementStage').hidden=view!=='placement';$('hPhysicalStage').hidden=view!=='physical';for(const[id,name]of [['hLogical','logical'],['hPlacement','placement'],['hPhysical','physical']])$(id).setAttribute('aria-pressed',view===name?'true':'false');}
function selectNode(id){const n=nodes.get(id);if(!n)return;selected=id;physicalFirst=0;first=Math.floor(depth.get(id)/8)*8;switchView('logical');drawDag();$('hSelection').replaceChildren(el('b',n.operation+' · '+pairLabel(n)),el('p',n.id,'muted'),el('p',`依赖层 ${depth.get(id)} · ${parents.get(id).size} 个前驱 · ${children.get(id).size} 个后继`),el('p',n.condition?'条件：'+JSON.stringify(n.condition):'无经典条件','muted'));if(V.physical_dag_bundle){const b=el('button','查看物理模板');b.onclick=()=>{switchView('physical');drawPhysical();};$('hSelection').append(b);}$('hRaw').textContent=JSON.stringify(n,null,2);}
function drawDag(){
 first=Math.max(0,Math.min(first,Math.floor(maxDepth/8)*8));$('hDepthInput').value=first;
 const out=$('hDag');out.replaceChildren();const shown=[];for(let d=first;d<first+8;d++)shown.push(...(byDepth.get(d)||[]));
 const rows=Math.max(1,...Array.from({length:8},(_,i)=>(byDepth.get(first+i)||[]).length));const height=Math.max(450,90+rows*83);out.setAttribute('viewBox',`0 0 1120 ${height}`);
 const positions=new Map();for(let d=first;d<first+8;d++){out.append(svg('text',{x:78+(d-first)*139,y:26,fill:'#8190a3','font-size':11,'text-anchor':'middle'},'依赖层 '+d));(byDepth.get(d)||[]).forEach((id,i)=>positions.set(id,[22+(d-first)*139,55+i*83]));}
 for(const e of D.edges){const a=positions.get(e.source),b=positions.get(e.target);if(!a||!b)continue;const chosen=selected===e.source||selected===e.target;out.append(svg('path',{d:`M ${a[0]+112} ${a[1]+23} C ${a[0]+132} ${a[1]+23}, ${b[0]-20} ${b[1]+23}, ${b[0]} ${b[1]+23}`,fill:'none',stroke:e.kind==='classical_ready'?'#df943e':e.kind==='quantum'?'#8a96cd':'#c8d0dd','stroke-width':chosen?2:1,opacity:selected&&!chosen?.28:.85,'stroke-dasharray':e.kind==='classical_ready'?'4 4':'none'}));}
 for(const[id,[x,y]]of positions){const n=nodes.get(id),g=svg('g',{class:'node-card'+(selected===id?' selected':''),'data-node-id':id});g.append(svg('rect',{x,y,width:112,height:49,rx:8,fill:'#fff',stroke:'#dce2ed'}),svg('text',{x:x+10,y:y+19,fill:'#25334b','font-size':12,'font-weight':600},n.operation),svg('text',{x:x+10,y:y+37,fill:'#748198','font-size':10},pairLabel(n)||'经典处理'));
  const external=[...parents.get(id)].filter(p=>!positions.has(p)).length;if(external)g.append(svg('text',{x:x+4,y:y+64,fill:'#748198','font-size':9},`另有 ${external} 个窗口外前驱`));g.append(svg('title',{},id));g.addEventListener('click',()=>selectNode(id));out.append(g);
 }
 $('hDepthRange').textContent=`${first}–${Math.min(first+7,maxDepth)} / ${maxDepth} · 本窗 ${shown.length} 节点`;$('hPrev').disabled=first===0;$('hNext').disabled=first+8>maxDepth;
}
const placements=Object.entries(P.placements),extent=V.device.patch_geometry.cell_extent_um;
function selectPatch(id){selectedPatch=id;switchView('placement');drawMap();const p=P.placements[id],atoms=S.atoms.filter(a=>a.patch_id===id);$('hSelection').replaceChildren(el('b',id+' · t = 0'),el('p',`锚点 (${p.anchor_um.map(fmt).join(', ')}) μm`),el('p',`${atoms.length} 个初始载体 · ${p.orientation}`,'muted'));$('hRaw').textContent=JSON.stringify({placement:p,patch:S.patches[id]||S.patches.find?.(x=>x.logical_id===id),atoms},null,2);}
function selectCarrier(atom){switchView('placement');$('hSelection').replaceChildren(el('b',atom.atom_id),el('p',`(${atom.position_um.map(fmt).join(', ')}) μm · ${atom.carrier}`),el('p',atom.patch_id?'所属 patch：'+atom.patch_id:'独立非 patch 载体','muted'));$('hRaw').textContent=JSON.stringify(atom,null,2);}
function drawMap(){
 const out=$('hMap');out.replaceChildren();out.setAttribute('viewBox','0 0 1000 570');
 const all=placements.flatMap(([_,p])=>[p.anchor_um,[p.anchor_um[0]+extent[0],p.anchor_um[1]+extent[1]]]).concat(S.atoms.map(a=>a.position_um)),xmin=Math.min(...all.map(p=>p[0]))-12,xmax=Math.max(...all.map(p=>p[0]))+12,ymin=Math.min(...all.map(p=>p[1]))-12,ymax=Math.max(...all.map(p=>p[1]))+12;
 const scale=Math.min(880/(xmax-xmin),440/(ymax-ymin)),x=v=>500+(v-(xmin+xmax)/2)*scale,y=v=>295- (v-(ymin+ymax)/2)*scale;
 for(let value=Math.ceil(xmin/20)*20;value<=xmax;value+=20){out.append(svg('line',{x1:x(value),x2:x(value),y1:y(ymax),y2:y(ymin),stroke:'#e2e7ef','stroke-width':.6}),svg('text',{x:x(value),y:y(ymin)+17,'text-anchor':'middle',fill:'#8190a3','font-size':10},fmt(value)));}
 for(let value=Math.ceil(ymin/20)*20;value<=ymax;value+=20){out.append(svg('line',{x1:x(xmin),x2:x(xmax),y1:y(value),y2:y(value),stroke:'#e2e7ef','stroke-width':.6}),svg('text',{x:x(xmin)-7,y:y(value)+3,'text-anchor':'end',fill:'#8190a3','font-size':10},fmt(value)));}
 for(const edge of D.patch_interaction_graph?.edges||[]){const a=P.placements[edge.patches[0]].anchor_um,b=P.placements[edge.patches[1]].anchor_um;out.append(svg('line',{x1:x(a[0]+extent[0]/2),y1:y(a[1]+extent[1]/2),x2:x(b[0]+extent[0]/2),y2:y(b[1]+extent[1]/2),stroke:'#b9c2dd','stroke-dasharray':'5 5','stroke-width':1.2}));}
 for(const[id,p]of placements){const[a,b]=p.anchor_um,g=svg('g',{class:'node-card','data-patch-id':id}),role=V.resource_requirements?.patches[id]?.role;g.append(svg('rect',{x:x(a),y:y(b+extent[1]),width:extent[0]*scale,height:extent[1]*scale,rx:4,fill:selectedPatch===id?'#ebeefa':role==='factory'?'#eaf3ef':'#f0edf8','fill-opacity':.85,stroke:selectedPatch===id?'#5865b6':'#c9d3d1','stroke-width':1.2}),svg('text',{x:x(a)+8,y:y(b+extent[1])+18,fill:'#5865b6','font-size':12,'font-weight':650},id));g.addEventListener('click',()=>selectPatch(id));out.append(g);}
 for(const a of S.atoms){const color=selectedPatch&&a.patch_id!==selectedPatch?'#aab2c7':a.patch_id?'#5865b6':'#df943e',g=svg('g',{'data-atom-id':a.atom_id});g.append(svg('circle',{cx:x(a.position_um[0]),cy:y(a.position_um[1]),r:1.3*scale,fill:'none',stroke:'#a4adc0','stroke-width':.4}),svg('circle',{cx:x(a.position_um[0]),cy:y(a.position_um[1]),r:.65*scale,fill:color}),svg('title',{},`${a.atom_id} · (${a.position_um.join(', ')}) μm`));if(!a.patch_id)g.append(svg('text',{x:x(a.position_um[0])+8,y:y(a.position_um[1])-8,fill:'#9b753d','font-size':11},'独立探针'));g.addEventListener('click',()=>selectCarrier(a));out.append(g);}
 out.append(svg('text',{x:x(xmax),y:y(ymin)+37,fill:'#8190a3','font-size':11,'text-anchor':'end'},'x / μm'),svg('text',{x:x(xmin)-20,y:y(ymax)-8,fill:'#8190a3','font-size':11},'y / μm'));
}
let physicalFirst=0;
function drawPhysical(){
 const out=$('hPhysicalDag');out.replaceChildren();out.setAttribute('viewBox','0 0 1120 450');
 const bundle=V.physical_dag_bundle;if(!bundle)return;
 const id=selected||D.nodes[0].id,instance=bundle.instances[id],spec=bundle.specifications[instance.spec_ref],graph=spec.physical_dag;
 $('hPhysicalTitle').textContent=`${spec.operation} · ${id}`;$('hPhysicalNote').textContent='共享模板及逻辑实例映射，未生成运行结果。';
 $('hRaw').textContent=JSON.stringify({instance,specification:spec},null,2);
 if(!graph){out.append(svg('text',{x:40,y:80,fill:'#5865b6','font-size':20},'自适应工厂协议'),svg('text',{x:40,y:117,fill:'#748198','font-size':13},'该节点需要真实生产、判定、清理与消费；尚未提供执行路径。'));$('hPhysicalRange').textContent='工厂 stage 按 ready 结果展开';$('hPhysicalPrev').disabled=true;$('hPhysicalNext').disabled=true;return;}
 const ns=new Map(graph.nodes.map(n=>[n.id,n])),ps=new Map(graph.nodes.map(n=>[n.id,new Set()])),cs=new Map(graph.nodes.map(n=>[n.id,new Set()]));
 for(const e of graph.edges){ps.get(e.target).add(e.source);cs.get(e.source).add(e.target);}
 const q=graph.nodes.filter(n=>!ps.get(n.id).size).map(n=>n.id),dep=new Map(q.map(id=>[id,0])),rem=new Map([...ps].map(([id,p])=>[id,p.size]));
 for(const id of q)for(const child of cs.get(id)){dep.set(child,Math.max(dep.get(child)||0,dep.get(id)+1));rem.set(child,rem.get(child)-1);if(!rem.get(child))q.push(child);}
 if(q.length!==graph.nodes.length)throw Error('Physical DAG cycle');
 const max=Math.max(0,...dep.values()),layers=new Map();for(const id of q){const d=dep.get(id);if(!layers.has(d))layers.set(d,[]);layers.get(d).push(id);}
 physicalFirst=Math.max(0,Math.min(physicalFirst,Math.floor(max/8)*8));
 const count=Math.max(1,...Array.from({length:8},(_,i)=>(layers.get(physicalFirst+i)||[]).length)),height=Math.max(450,80+count*72);out.setAttribute('viewBox',`0 0 1120 ${height}`);out.style.height=Math.min(height,1100)+'px';
 const pos=new Map();for(let d=physicalFirst;d<physicalFirst+8;d++){out.append(svg('text',{x:78+(d-physicalFirst)*139,y:25,fill:'#8190a3','font-size':11,'text-anchor':'middle'},'依赖层 '+d));(layers.get(d)||[]).forEach((id,i)=>pos.set(id,[22+(d-physicalFirst)*139,50+i*72]));}
 for(const e of graph.edges){const a=pos.get(e.source),b=pos.get(e.target);if(a&&b)out.append(svg('path',{d:`M ${a[0]+112} ${a[1]+23} C ${a[0]+127} ${a[1]+23}, ${b[0]-15} ${b[1]+23}, ${b[0]} ${b[1]+23}`,fill:'none',stroke:e.kind==='classical_ready'?'#df943e':'#b5bfd8','stroke-width':1,'stroke-dasharray':e.kind==='classical_ready'?'4 4':'none'}));}
 for(const[id,[x,y]]of pos){const n=ns.get(id),label=n.kind==='gate'?n.params.name:n.kind,g=svg('g',{class:'node-card','data-physical-id':id});g.append(svg('rect',{x,y,width:112,height:49,rx:8,fill:'#fff',stroke:'#dce2ed'}),svg('text',{x:x+9,y:y+19,fill:'#25334b','font-size':12,'font-weight':600},label),svg('text',{x:x+9,y:y+37,fill:'#748198','font-size':9},n.qubits.join(' · ').slice(0,18)),svg('title',{},id));g.addEventListener('click',()=>{$('hSelection').replaceChildren(el('b',label),el('p',id,'muted'),el('p',n.qubits.join(' · ')));$('hRaw').textContent=JSON.stringify({physical_node:n,logical_instance:instance},null,2);});out.append(g);}
 $('hPhysicalRange').textContent=`${physicalFirst}–${Math.min(physicalFirst+7,max)} / ${max} · 模板共 ${graph.nodes.length} 操作`;$('hPhysicalPrev').disabled=physicalFirst===0;$('hPhysicalNext').disabled=physicalFirst+8>max;
}
function search(){const q=$('hQuery').value.trim().toLowerCase(),box=$('hMatches');box.replaceChildren();if(!q)return;const found=D.nodes.filter(n=>JSON.stringify([n.id,n.operation,n.patch_operands,n.source_ids]).toLowerCase().includes(q));box.append(el('p',`${found.length} 个匹配 · 显示前 20 个`,'muted'));for(const n of found.slice(0,20)){const b=el('button',`${n.operation} · ${n.id}`);b.onclick=()=>selectNode(n.id);box.append(b);}}
$('hLogical').onclick=()=>switchView('logical');$('hPlacement').onclick=()=>switchView('placement');$('hPrev').onclick=()=>{first-=8;drawDag();};$('hNext').onclick=()=>{first+=8;drawDag();};$('hGo').onclick=()=>{const v=Number($('hDepthInput').value);if(Number.isFinite(v)){first=Math.floor(Math.max(0,v)/8)*8;drawDag();}};$('hQuery').addEventListener('input',search);
$('hPhysical').disabled=!V.physical_dag_bundle;$('hPhysical').onclick=()=>{switchView('physical');drawPhysical();};$('hPhysicalPrev').onclick=()=>{physicalFirst-=8;drawPhysical();};$('hPhysicalNext').onclick=()=>{physicalFirst+=8;drawPhysical();};
$('hSubtitle').textContent=`${D.patches.length} 个算法 patch · ${D.nodes.length} 个逻辑节点 · ${D.rounds?.length||0} 个相位轮次`;
$('hCount').textContent=`${S.atoms.length} 个已定位原子${V.resource_requirements?' / '+V.resource_requirements.physical_qubit_count+' 个需求载体':''}`;$('hNodeTotal').textContent=fmt(D.nodes.length)+' 节点';$('hCounts').textContent=`${D.edges.length} 条依赖 · ${maxDepth+1} 个依赖层`;
$('hScope').textContent=H.atom_view?'已提供原子计划，可打开对应回放。':'当前为完整逻辑源图与初始布局；实际物理调度和动作尚未接入。';
if(V.resource_requirements&&S.atoms.length<V.resource_requirements.physical_qubit_count)$('hScope').textContent+=` 完整资源世界另有 ${V.resource_requirements.physical_qubit_count-S.atoms.length} 个需求载体尚未定位。`;
$('hBaseline').textContent=fmt(P.cost.baseline);$('hCandidate').textContent=fmt(P.cost.candidate);$('hSearchStats').textContent=`seed ${P.search.seed} · ${fmt(P.search.moves)} 次搜索移动 · ${fmt(P.search.wall_seconds)} 秒`;
for(const[name,ready]of [['逻辑源图',true],['Enola 初始布局',true],['物理 DAG 模板',!!V.physical_dag_bundle],['逻辑调度',!!V.logical_schedule],['原子动作',!!V.atom],['事件运行',!!V.trace]])$('hPipeline').append(el('span',`${ready?'●':'○'} ${name}${ready?'':' · 待接入'}`,ready?'complete':'pending'));
if(H.atom_view){$('hLink').hidden=false;$('hLink').href=encodeURIComponent(H.atom_view.name);}
$('hEvidence').textContent=JSON.stringify({scope:H.display_scope,source_program_ref:D.source_program_ref,entry:D.entry,producer_schemas:Object.fromEntries(Object.entries(V).map(([k,v])=>[k,v.schema_version])),receipt:H.receipt,enola:P.enola,search:P.search,user_visual_acceptance:'pending'},null,2);
drawDag();drawMap();window.naHierarchy={data:H,depth,selectNode,selectPatch,get firstDepth(){return first;}};
