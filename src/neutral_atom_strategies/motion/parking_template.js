/* Pure, dependency-free constructive planner for an isolated regular patch.
   Teaching model, not a replacement for NeutralAtomEnv's general validator. */
(function(root){'use strict';
const clone=v=>JSON.parse(JSON.stringify(v));
const MODEL=Object.freeze({version:'isolated-parking/v2',clearance:1,axisFloor:1.01,speed:.5,acceleration:.01,jerk:.001,loadUs:100,switchUs:1});
function fail(code,message){const e=new Error(message);e.code=code;throw e;}
function preset(name='mixed',seed=17){
 let r=10,c=10;if(name==='intro'){r=2;c=3;}
 let rng=seed>>>0;const random=()=>{rng=(Math.imul(rng,1664525)+1013904223)>>>0;return rng/4294967296;};
 const cells=Array.from({length:r},(_,y)=>Array.from({length:c},(_,x)=>{
  if(name==='intro')return [[2,2,1],[1,2,2]][y][x];
  if(name==='compatible'){if(y===9)return 1;if(y<5)return x>=5?1:x===y%4?2:0;return x<5?1:x===5+(y-5)%4?2:0;}
  if(name==='checker')return (y+x)%2?1:2;
  if(name==='sparse')return (x===y||x===(y+3)%c)?2:(x+y)%3===0?1:0;
  if(name==='random'){const q=random();return q<.4?2:q<.8?1:0;}
  return (3*y+2*x)%7<3?2:(y+x)%4===0?0:1;
 }));
 return {rows:r,columns:c,cells,aod_rows:r,aod_columns:c,spacing_um:10,epsilon_x_um:2.5,epsilon_y_um:2.5,
  shift_x_um:(c-1)*10+50,shift_y_um:name==='intro'?30:40,strategy:name==='compatible'?'pattern_optimal':'naive_rowwise',obstacles:[]};
}
function normalize(raw){
 const source=raw?.schema==='parking-lab/v1'?raw.input:raw;
 if(!source||typeof source!=='object'||Array.isArray(source))fail('INPUT','需要 Parking 输入对象。');
 const v=clone(source);
 if(!v||typeof v!=='object'||Array.isArray(v))fail('INPUT','需要 Parking 输入对象。');
 const allowed=new Set(Object.keys(preset()));
 for(const k of Object.keys(v))if(!allowed.has(k))fail('UNSUPPORTED',`本演示不支持输入字段：${k}`);
 for(const k of ['rows','columns','aod_rows','aod_columns'])if(!Number.isInteger(v[k])||v[k]<1||v[k]>16)fail('SIZE','SLM 和 AOD 每维需为 1–16。');
 if(v.aod_rows*v.aod_columns>128)fail('CAPACITY','AOD 总交点不能超过 128。');
 if(!Array.isArray(v.cells)||v.cells.length!==v.rows||v.cells.some(row=>!Array.isArray(row)||row.length!==v.columns||row.some(k=>![0,1,2].includes(k))))fail('MASK','格点必须是 0 空位、1 固定、2 目标组成的矩形。');
 for(const k of ['spacing_um','epsilon_x_um','epsilon_y_um','shift_x_um','shift_y_um'])if(typeof v[k]!=='number'||!Number.isFinite(v[k]))fail('NUMBER','长度参数必须是有限数值，单位 μm。');
 if(![5,10,15,20].includes(v.spacing_um))fail('GRID','源间距请选择 5、10、15 或 20 μm。');
 for(const e of [v.epsilon_x_um,v.epsilon_y_um])if(!(e>MODEL.clearance&&v.spacing_um-e>MODEL.axisFloor+1e-12))fail('GAP','停车偏移需 >1 μm，且源间距减去偏移需 >1.01 μm。');
 if(v.shift_x_um<(v.columns-1)*v.spacing_um+10||v.shift_x_um>500||v.shift_y_um<0||v.shift_y_um>300)fail('DESTINATION','目标区 X 位移需超过源宽度至少 10 μm（最多500）；Y 位移需在0–300 μm。');
 if(v.obstacles!==undefined&&(!Array.isArray(v.obstacles)||v.obstacles.length))fail('ISOLATION','快速模板仅支持隔离的规则 patch；外部障碍需要完整环境规划。');
 if(!['naive_rowwise','naive_columnwise','pattern_optimal'].includes(v.strategy))fail('STRATEGY','请选择朴素逐行、逐列或兼容批量优化。');
 v.obstacles=[];return v;
}
function compatibleGroups(cells,rowwise=true){
 if(!Array.isArray(cells)||!cells.length||cells.length>16||!Array.isArray(cells[0])||!cells[0].length||cells[0].length>16||cells.some(r=>!Array.isArray(r)||r.length!==cells[0].length||r.some(v=>![0,1,2].includes(v))))fail('GROUP_INPUT','兼容分析需要1–16行列的0/1/2矩形。');
 const lines=rowwise?cells:cells[0].map((_,c)=>cells.map(row=>row[c])),sources=lines.map((r,i)=>r.includes(2)?i:-1).filter(i=>i>=0),n=sources.length;
 const t=sources.map(i=>lines[i].reduce((m,v,c)=>v===2?m|(1<<c):m,0)),f=sources.map(i=>lines[i].reduce((m,v,c)=>v===1?m|(1<<c):m,0));
 const edges=t.map((_,i)=>sources.map((_,j)=>j).filter(j=>(t[i]&f[j])||(t[j]&f[i])));
 let colors=Array(n).fill(-1),nodes=0;
 function choose(){let best=-1,sat=-1,deg=-1;for(let i=0;i<n;i++)if(colors[i]<0){const k=new Set(edges[i].map(j=>colors[j]).filter(c=>c>=0)).size;if(k>sat||(k===sat&&edges[i].length>deg)){best=i;sat=k;deg=edges[i].length;}}return best;}
 for(let k=0;k<n;k++){const i=choose(),used=new Set(edges[i].map(j=>colors[j]));let c=0;while(used.has(c))c++;colors[i]=c;}
 let best=[...colors],count=n?Math.max(...best)+1:0;colors.fill(-1);
 function search(done,used){nodes++;if(used>=count)return;if(done===n){best=[...colors];count=used;return;}const i=choose(),blocked=new Set(edges[i].map(j=>colors[j]));for(let c=0;c<Math.min(used+1,count);c++)if(!blocked.has(c)){colors[i]=c;search(done+1,Math.max(used,c+1));}colors[i]=-1;}
 if(n)search(0,0);
 const groups=Array.from({length:count},(_,c)=>sources.filter((_,i)=>best[i]===c)).sort((a,b)=>a[0]-b[0]);
 return {groups,batches:count,exact:true,search_nodes:nodes,skipped:lines.map((_,i)=>i).filter(i=>!sources.includes(i))};
}
function analyze(cells){const row=compatibleGroups(cells,true),column=compatibleGroups(cells,false);return {row,column,selected_axis:row.batches<=column.batches?'row':'column',objective:'minimum captures; row first on ties; whole-line template only'};}
function compile(raw){
 const input=normalize(raw),d=input.spacing_um,ex=input.epsilon_x_um,ey=input.epsilon_y_um,atoms=[];
 const byRow=new Map(),byCol=new Map();
 for(let r=0;r<input.rows;r++)for(let c=0;c<input.columns;c++){
  const kind=input.cells[r][c];if(!kind)continue;
  const a={id:'Q'+String(r*input.columns+c).padStart(3,'0'),r,c,x:c*d,y:r*d,target:kind===2};atoms.push(a);
  if(a.target){if(!byRow.has(r))byRow.set(r,[]);byRow.get(r).push(a);if(!byCol.has(c))byCol.set(c,[]);byCol.get(c).push(a);}
 }
 const rs=[...byRow.keys()].sort((a,b)=>a-b),cs=[...byCol.keys()].sort((a,b)=>a-b);
 if(rs.length>input.aod_rows||cs.length>input.aod_columns)fail('AXIS_CAPACITY',`目标需要 ${rs.length} 行 × ${cs.length} 列，请增加 AOD 容量。`);
 const analysis=analyze(input.cells),rowwise=input.strategy==='pattern_optimal'?analysis.selected_axis==='row':input.strategy==='naive_rowwise';
 const selected= input.strategy==='pattern_optimal' ? analysis[rowwise?'row':'column'].groups : (rowwise?rs:cs).map(i=>[i]);
 const initial={x:Array.from({length:input.aod_columns},(_,i)=>i*d),y:Array.from({length:input.aod_rows},(_,i)=>i*d),
  rows:Array(input.aod_rows).fill(false),cols:Array(input.aod_columns).fill(false),loaded:{}};
 let state=clone(initial),time=0,totalDistance=0,sweeps=0;const operations=[],groups=[];
 function append(type,label,description,next,duration,extra={}){
  operations.push({index:operations.length,type,label,description,start:time,end:time+duration,duration,before:clone(state),after:clone(next),...extra});
  time+=duration;state=next;
 }
 function move(x,y,label,description,extra={}){
  const dx=Math.max(...x.map((v,i)=>Math.abs(v-state.x[i]))),dy=Math.max(...y.map((v,i)=>Math.abs(v-state.y[i])));
  if(dx===0&&dy===0)return;
  if(dx&&dy)fail('ORTHOGONAL','模板动作只能沿一个方向移动。');
  const distance=Math.max(dx,dy),duration=Math.max(1.5*distance/MODEL.speed,Math.sqrt(6*distance/MODEL.acceleration),Math.cbrt(12*distance/MODEL.jerk));
  const next={...clone(state),x:[...x],y:[...y]};let travel=0;
  for(const cell of Object.values(state.loaded))travel+=Math.hypot(x[cell.c]-state.x[cell.c],y[cell.r]-state.y[cell.r]);
  totalDistance+=travel;if(extra.stage==='park-x'||extra.stage==='park-y')sweeps++;
  append('move',label,description,next,duration,{axis:dx?'x':'y',distance,atomDistance:travel,...extra});
 }
 if(rs.length){
  const full=(indices,n)=>Array.from({length:n},(_,i)=>(i<indices.length?indices[i]:indices.at(-1)+i-indices.length+1)*d);
  const ax=full(cs,input.aod_columns),ay=full(rs,input.aod_rows),px=ax.map((x,i)=>x+(i<cs.length?ex:0)),py=ay.map((y,i)=>y+(i<rs.length?ey:0));
  const mapR=new Map(rs.map((r,i)=>[r,i])),mapC=new Map(cs.map((c,i)=>[c,i]));
  move(ax,state.y,'配置空 AOD · X','所有行列尚未形成活动交点；此时不拾取原子。',{stage:'setup'});
  move(state.x,ay,'配置空 AOD · Y','先配置有序行列的位置，再逐组开启。',{stage:'setup'});
  const mask=clone(state);if(rowwise)mask.cols=mask.cols.map((_,i)=>i<cs.length);else mask.rows=mask.rows.map((_,i)=>i<rs.length);
  append('switch','仅开启'+(rowwise?'列':'行')+'轴','只开启一个方向没有二维交点，因此尚未形成 AOD 陷阱。',mask,MODEL.switchUs,{stage:'setup'});
  for(const sources of selected){
   const targets=sources.flatMap(source=>(rowwise?byRow:byCol).get(source)).sort((a,b)=>a.id.localeCompare(b.id)),group=groups.length,source=sources[0],x=[...state.x],y=[...state.y];
   const cross=rowwise?cs:rs;
   cross.forEach((coordinate,i)=>{const values=sources.map(line=>rowwise?input.cells[line][coordinate]:input.cells[coordinate][line]);
    if(values.includes(2)&&values.includes(1))fail('GROUP_CONFLICT','兼容批次含固定原子冲突。');
    if(values.includes(2)){if(rowwise)x[i]=ax[i];else y[i]=ay[i];}
    else if(values.includes(1)){if(rowwise)x[i]=px[i];else y[i]=py[i];}
    // Empty intersections are wildcards: retain the present axis, never invent an atom.
   });
   move(x,y,'仅调整不匹配的'+(rowwise?'列':'行'),'目标需对齐，固定原子需避开；空位不约束，已经匹配的轴保持不动。',{stage:'align',group,source,sources});
   const next=clone(state);
   for(const a of targets){const r=mapR.get(a.r),c=mapC.get(a.c);next.rows[r]=next.cols[c]=true;next.loaded[a.id]={r,c};}
   append('load',(rowwise?'行 ':'列 ')+sources.join(', ')+' · 合计拾取 '+targets.length+' 个原子','一次开启本批兼容行列；空交点不抓原子，已载入轴保持开启。交接结束才改变承载。',next,MODEL.loadUs,{stage:'load',group,source,sources,ids:targets.map(a=>a.id)});
   if(rowwise){const yy=[...state.y];for(const r of sources)yy[mapR.get(r)]=py[mapR.get(r)];move(state.x,yy,'本批行 Y parking','只将新拾取行移入行间隙，保留已有列构型给下一批复用。',{stage:'park-y',group,source,sources});}
   else {const xx=[...state.x];for(const c of sources)xx[mapC.get(c)]=px[mapC.get(c)];move(xx,state.y,'本批列 X parking','只将新拾取列移入列间隙，保留已有行构型给下一批复用。',{stage:'park-x',group,source,sources});}
   groups.push({index:group,source,sources,axis:rowwise?'row':'column',ids:targets.map(a=>a.id),end:time});
  }
  // Normalize once after the last capture, not after every batch. Same terminal contract.
  move(px,state.y,'统一最终 X parking','全部目标已拾取，停止开启新行列；仅整理共同终态。',{stage:'finalize'});
  move(state.x,py,'统一最终 Y parking','保持与其他策略相同的最终停车构型。',{stage:'finalize'});
 }
 const pickupEnd=time,pickupState=clone(state),pickupDistance=totalDistance;
 if(rs.length){
  move(state.x.map(x=>x+input.shift_x_um),state.y,'集体搬运 · X','目标已全部载入。所有行列整体平移，固定原子留在原 SLM。',{stage:'transport'});
  move(state.x,state.y.map(y=>y+input.shift_y_um),'集体搬运 · Y','到达远处终点。保留 AOD 承载，不卸载，也不自动返回源 patch。',{stage:'transport'});
 }
 return {model:MODEL,input,analysis,selectedAxis:rowwise?'row':'column',atoms,initial,operations,groups,pickupEnd,pickupState,finalState:clone(state),duration:time,
  metrics:{targets:Object.keys(state.loaded).length,fixed:atoms.filter(a=>!a.target).length,empty:input.rows*input.columns-atoms.length,
   transferBatches:groups.length,parkingSegments:sweeps,pickupDistance,totalDistance},
  certificate:{kind:'isolated-regular-grid-template',gapX:d-ex,gapY:d-ey,externalObstacles:false,fullEnvironmentAudit:false}};
}
function sample(plan,t){
 const time=Math.max(0,Math.min(plan.duration,Number.isFinite(t)?t:0));
 const op=plan.operations.find(o=>time<o.end);
 let state=clone(op?op.before:plan.finalState),progress=op?(time-op.start)/op.duration:1;
 if(op?.type==='move'){const u=progress*progress*(3-2*progress);state.x=state.x.map((x,i)=>x+(op.after.x[i]-x)*u);state.y=state.y.map((y,i)=>y+(op.after.y[i]-y)*u);}
 if(op?.type==='load'){state.rows=[...op.after.rows];state.cols=[...op.after.cols];}
 const atoms=plan.atoms.map(a=>{const cell=state.loaded[a.id];return {...a,x:cell?state.x[cell.c]:a.x,y:cell?state.y[cell.r]:a.y,holder:cell?'AOD':'SLM',cell:cell||null};});
 return {time,state,atoms,op:op||null,progress,capturing:op?.type==='load'?op.ids:[]};
}
const api={MODEL,preset,normalize,compile,sample,compatibleGroups,analyze};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ParkingTemplate=api;
})(globalThis);
