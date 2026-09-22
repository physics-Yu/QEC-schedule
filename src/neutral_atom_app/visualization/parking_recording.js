/* Presentation adapter only: constructive parking plan -> shared viewer /2.
   This is a model timeline, not a forged Executor audit or checkpoint. */
(function(root){'use strict';
const point=(x,y)=>({x_um:x,y_um:y});
function recording(plan){
 const spec=plan.input,targets=plan.atoms.filter(a=>a.target).map(a=>a.id),traps=[];
 for(let r=0;r<spec.rows;r++)for(let c=0;c<spec.columns;c++)traps.push({id:`S${r}_${c}`,position:point(c*spec.spacing_um,r*spec.spacing_um),grid:{x:c,y:r},enabled:true});
 const axes=s=>({x_um:[...s.x],y_um:[...s.y]});
 const atom=(a,s,moving)=>{const cell=s.loaded[a.id];return {id:a.id,position:cell?point(s.x[cell.c],s.y[cell.r]):point(a.x,a.y),holder:cell?{holder_type:'mobile',holder_id:{aod_id:'AOD_0',row:cell.r,column:cell.c}}:{holder_type:'static',holder_id:`S${a.r}_${a.c}`},measured:false,activity:cell&&moving?'moving':'idle'};};
 const operations=plan.operations.map(o=>{
  const carried=Object.keys(o.before.loaded),moved=carried.filter(id=>{const c=o.before.loaded[id];return o.before.x[c.c]!==o.after.x[c.c]||o.before.y[c.r]!==o.after.y[c.r];});
  return {index:o.index,kind:o.type==='move'?'aod_move':o.type==='switch'?'trap_switch':carried.length?'aod_recapture':'aod_load',label:o.label,description:o.description,start:o.start,end:o.end,
   category:o.type==='load'?'load':o.type==='switch'?'switch':carried.length?'transport':'empty',captured:o.ids||carried,qubit_ids:[],gate_ids:[],intended_pairs:[],applied:true,resources:['AOD_0'],
   moving_count:moved.length,moving_atom_ids:moved,source_axes:axes(o.before),target_axes:axes(o.after),enabled_rows:o.before.rows,enabled_columns:o.before.cols,planner_id:'parking-template/v1',task_id:'parking',task_phase:'transport',mode:o.stage==='transport'?'translation':'axis_deformation'};
 });
 function frame(s,t,o,index){
  const vacated=new Set(plan.atoms.filter(a=>s.loaded[a.id]).map(a=>`S${a.r}_${a.c}`));
  const masks=Object.fromEntries(traps.map(t=>[t.id,!vacated.has(t.id)]));
  return {time:t,version:index,axes:axes(s),aod:{rows:spec.aod_rows,columns:spec.aod_columns,spacing_um:spec.spacing_um,pose:point(s.x[0],s.y[0]),enabled_rows:[...(o?.type==='load'?o.after.rows:s.rows)],enabled_columns:[...(o?.type==='load'?o.after.cols:s.cols)],is_moving:o?.type==='move'},
   atom_updates:plan.atoms.map(a=>atom(a,s,o?.type==='move')),slm_enabled:masks,
   movement:o?.type==='move'?{start:o.start,duration:o.duration,profile:'cubic',target_axes:axes(o.after)}:null,
   label:o?.label||'标准模板终态',plan_id:'parking-template',requested:targets,active_operations:o?[o.index]:[],transfer:null,
   gate_label:'Parking · 无门操作',gate_status:'idle',gate_counts:{},gate_statuses:{},active_gate_ids:[],ready_count:0,ready_frontier:[],measurement_results:{},quantum_tracking:false};
 }
 const frames=plan.operations.map((o,i)=>frame(o.before,o.start,o,i));frames.push(frame(plan.finalState,plan.duration,null,frames.length));
 const width=(spec.columns-1)*spec.spacing_um,height=(spec.rows-1)*spec.spacing_um;
 const bounds={lower:point(-20,-20),upper:point(Math.max(width+20,...plan.finalState.x)+20,Math.max(height+20,...plan.finalState.y)+20)};
 const grid_x=[],grid_y=[],candidates=[];for(let x=-20;x<=bounds.upper.x_um;x+=5)grid_x.push(x);for(let y=-20;y<=bounds.upper.y_um;y+=5)grid_y.push(y);for(const x of grid_x)for(const y of grid_y)candidates.push(point(x,y));
 const paths={};for(const a of plan.atoms)if(a.target){const points=[point(a.x,a.y)];for(const o of plan.operations){const b=atom(a,o.after,false).position,p=points.at(-1);if(p.x_um!==b.x_um||p.y_um!==b.y_um)points.push(b);}paths[a.id]=points;}
 return {format:'neutral-atom-view/2',provenance:{kind:'constructive-template',full_environment_audit:false},start_time:0,duration:plan.duration,backend:'row_column_orthogonal',requested:targets,captured:targets,gate_label:'Parking',
  theme:{background:'#fafbfd',grid_color:'#dbe2e9',muted_color:'#8190a3',moving_color:'#e89438',static_color:'#5364bc',active_color:'#d95360',text_color:'#25334b',zone_colors:['#eef3f5','#f0edf8','#eaf3ef']},
  scene:{bounds,grid_x,grid_y,candidates,traps,spacing_um:5,slm_clearance_um:1,aod_minimum_spacing_um:1.01,zones:[{id:'STORAGE',zone_type:'storage',bounds}]},
  frames,operations,plans:[{id:'parking-template',planner_id:'parking-template/v1',task_id:'标准 parking 方法',requested:targets,paths}],summary:null,atom_statistics:null,atom_statistics_unavailable:'本页为标准模板方法演示，未运行完整环境统计审计。'};
}
function options(plan){return {compact:true,dashedEmptySlm:true,atomColors:Object.fromEntries(plan.atoms.map(a=>[a.id,a.target?'#db4b50':'#3879c7'])),modelCaption:'隔离规则 patch · 标准模板运动学演示，非完整环境审计'};}
const api={recording,options};if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.ParkingRecording=api;
})(globalThis);
