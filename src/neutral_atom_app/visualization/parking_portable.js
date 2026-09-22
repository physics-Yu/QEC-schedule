(()=>{'use strict';
const $=id=>document.getElementById(id),copy=v=>JSON.parse(JSON.stringify(v));
const keys=['rows','columns','aod_rows','aod_columns','spacing_um','epsilon_x_um','epsilon_y_um','shift_x_um','shift_y_um'];
const E=window.ParkingTemplate,A=window.ParkingRecording;
let draft=E.normalize(JSON.parse($('demo-input').textContent)),viewer,result,paint='2',drawing=false,busy=false,revision=0,dirty=false;let undo=[],lastDraft=copy(draft);
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path){if(path==='/api/default')return E.preset();if(path==='/api/examples/compatible')return E.preset('compatible');if(path==='/api/examples/small')return E.preset('intro');throw Error('Unsupported local preset');}
function mount(plan){viewer?.destroy();viewer=window.NeutralAtomViewer.mount($('viewer'),A.recording(plan),A.options(plan));}
function render(){
 for(const k of keys)$(k).value=draft[k];$('strategy').value=draft.strategy;
 const pitch=44,pad=40,width=(draft.columns-1)*pitch+2*pad,height=(draft.rows-1)*pitch+2*pad;
 $('board').style.width=(Number($('board-zoom').value)||1)*100+'%';
 $('board').style.maxWidth=(Number($('board-zoom').value)||1)*620+'px';
 let html=`<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" aria-label="SLM 格点图">`,n=0,t=0;
 for(let c=0;c<draft.columns;c++)html+=`<text class="axis-label" x="${pad+c*pitch}" y="${height-6}">${c*draft.spacing_um}</text>`;
 for(let r=draft.rows-1;r>=0;r--){
  const y=pad+(draft.rows-1-r)*pitch;
  html+=`<text class="axis-label" x="12" y="${y+3}">${r*draft.spacing_um}</text>`;
  for(let c=0;c<draft.columns;c++){
   const kind=draft.cells[r][c],id='Q'+String(r*draft.columns+c).padStart(3,'0'),x=pad+c*pitch;
   const label=`SLM (${c*draft.spacing_um}, ${r*draft.spacing_um}) μm · ${kind===2?'待移动 '+id:kind===1?'固定 '+id:'空位'}`;
   n+=kind>0;t+=kind===2;
   html+=`<g class="site" data-r="${r}" data-c="${c}" data-kind="${kind}" data-label="${label}" tabindex="0" role="button" aria-label="${label}"><title>${label}</title><circle class="hit" cx="${x}" cy="${y}" r="20"/><circle class="focus-ring" cx="${x}" cy="${y}" r="14"/><circle class="marker" cx="${x}" cy="${y}" r="${kind?7:8}"/>${$('show-ids').checked&&kind?`<text class="site-label" x="${x}" y="${y+21}">${id}</text>`:''}</g>`;
  }
 }
 $('board').innerHTML=html+'</svg>';
 $('counts').textContent=`${draft.rows} × ${draft.columns} 格点 · ${n} 个原子 · ${t} 个待移动 · ${n-t} 个固定 · 外部固定 ${(draft.obstacles||[]).length}`;
 $('transport-note').textContent=`源 patch 宽 ${(draft.columns-1)*draft.spacing_um} μm；集体 X 位移至少需 ${(draft.columns-1)*draft.spacing_um+10} μm。`;
 const rows=draft.cells.filter(r=>r.includes(2)).length,cols=Array.from({length:draft.columns},(_,c)=>draft.cells.some(r=>r[c]===2)).filter(Boolean).length;
 const capacity=draft.aod_rows*draft.aod_columns;
 $('mapping').textContent=`当前目标需要 ${rows} 行 × ${cols} 列；已配置 ${draft.aod_rows} × ${draft.aod_columns} = ${capacity} 个交点（上限 128）。`;
 $('mapping').style.color=capacity>128||rows>draft.aod_rows||cols>draft.aod_columns?'#b43239':'';
 $('shift_x_um').min=(draft.columns-1)*draft.spacing_um+10;
}
function edited(){undo.push(lastDraft);if(undo.length>30)undo.shift();lastDraft=copy(draft);dirty=true;revision++;viewer?.pause();render();$('failure').hidden=true;$('status').textContent='草稿已修改；下方保留上次生成的动作。请手动生成以更新回放。';}
for(const k of keys)$(k).onchange=()=>{if(busy)return;const v=Number($(k).value);if(!Number.isFinite(v)){render();return;}
 if(['rows','columns','aod_rows','aod_columns'].includes(k)&&(!Number.isInteger(v)||v<1||v>16)){render();return;}
 draft[k]=v;if(k==='rows'||k==='columns'){draft.cells=Array.from({length:draft.rows},(_,r)=>Array.from({length:draft.columns},(_,c)=>draft.cells[r]?.[c]??0));}
 edited();};
$('strategy').onchange=()=>{if(!busy){draft.strategy=$('strategy').value;edited();}};
$('paint-tools').onclick=e=>{const b=e.target.closest('[data-paint]');if(b){paint=b.dataset.paint;for(const el of $('paint-tools').querySelectorAll('button'))el.setAttribute('aria-pressed',String(el===b));}};
function paintSite(e){if(busy)return;const b=e.target.closest('[data-r]');if(!b)return;const r=Number(b.dataset.r),c=Number(b.dataset.c);const old=draft.cells[r][c],next=paint==='toggle'?(old===2?1:old===1?2:0):Number(paint);if(next===old)return;draft.cells[r][c]=next;edited();}
$('board').onpointerdown=e=>{e.preventDefault?.();drawing=true;paintSite(e);};$('board').onpointerover=e=>{const b=e.target.closest('[data-r]');if(b)$('site-detail').textContent=b.dataset.label;if(drawing&&paint!=='toggle')paintSite(e);};document.addEventListener('pointerup',()=>drawing=false);document.addEventListener('pointercancel',()=>drawing=false);
$('board').onclick=e=>{if(e.detail===0)paintSite(e);};
$('board').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();paintSite(e);}};
$('show-ids').onchange=render;$('board-zoom').onchange=render;
$('fit-capacity').onclick=()=>{if(busy)return;draft.aod_rows=Math.max(1,draft.cells.filter(r=>r.includes(2)).length);draft.aod_columns=Math.max(1,Array.from({length:draft.columns},(_,c)=>draft.cells.some(r=>r[c]===2)).filter(Boolean).length);edited();};
$('fit-transport').onclick=()=>{if(busy)return;draft.shift_x_um=(draft.columns-1)*draft.spacing_um+50;draft.shift_y_um=40;edited();};
$('compatible-example').onclick=async()=>{if(busy)return;draft=await api('/api/examples/compatible');edited();};
$('small-example').onclick=async()=>{if(busy)return;draft=await api('/api/examples/small');edited();};
$('example').onclick=async()=>{if(busy)return;draft=await api('/api/default');edited();};
for(const [id,fn]of [['checker',(r,c)=>(r+c)%2?1:2],['all-target',()=>2],['clear',()=>0]])$(id).onclick=()=>{if(busy)return;draft.cells=draft.cells.map((row,r)=>row.map((_,c)=>fn(r,c)));edited();};
function accept(plan,elapsed){result=plan;dirty=false;lastDraft=copy(draft);mount(plan);
 const a=plan.analysis;$('compatibility-report').textContent=`最少兼容抓取：按行 ${a.row.batches} 批，按列 ${a.column.batches} 批；当前实际 ${plan.groups.length} 批，采用${plan.selectedAxis==='row'?'逐行':'逐列'}。无目标行 ${a.row.skipped.join(', ')||'无'}；无目标列 ${a.column.skipped.join(', ')||'无'}。空位不限，固定原子禁止对齐。`;
 $('status').textContent=`已生成 ${plan.operations.length} 个标准动作${elapsed===null?'（内置示例）':'，用时 '+elapsed.toFixed(2)+' ms'}。下方使用原工作台格点回放；目标保留 AOD 承载。`;
 $('metrics').innerHTML=[['拾取时间',plan.pickupEnd.toFixed(2)+' μs'],['集体运输',(plan.duration-plan.pickupEnd).toFixed(2)+' μs'],['拾取批次',plan.groups.length],['目标 / 固定',plan.metrics.targets+' / '+plan.metrics.fixed],['模型原子总路程',plan.metrics.totalDistance.toFixed(2)+' μm']].map(([k,v])=>`<span>${k}<br><strong>${v}</strong></span>`).join('');
 let carried=[];$('steps').innerHTML=plan.groups.map(g=>{carried.push(...g.ids);return `<tr><td>${g.axis==='row'?'行':'列'} ${(g.sources||[g.source]).join(', ')}</td><td>${g.ids.join(', ')}</td><td>${carried.length}</td><td><button data-time="${g.end}">${g.end.toFixed(2)}</button></td></tr>`;}).join('');
 for(const id of ['pickup-end','transport-start','export-replay'])$(id).disabled=false;
}
function construct(){const start=performance.now();try{const next=E.compile(draft);draft=copy(next.input);$('failure').hidden=true;render();accept(next,performance.now()-start);return true;}catch(e){$('status').textContent='未生成新动作；下方保留上次结果。';$('failure').hidden=false;$('failure-message').textContent=(e.code||'INPUT')+' · '+e.message;$('failure-detail').textContent='请调整参数或图案。这是标准模板的适用范围检查，不代表其他路线不可行。';$('failure').focus();return false;}}
$('compile').onclick=construct;
$('undo').onclick=()=>{if(!undo.length)return;draft=undo.pop();lastDraft=copy(draft);dirty=true;viewer?.pause();render();$('status').textContent='已撤销编辑，请重新生成。';};
$('steps').onclick=e=>{const b=e.target.closest('[data-time]');if(b)viewer?.setTime(Number(b.dataset.time));};
$('pickup-end').onclick=()=>viewer?.setTime(result.pickupEnd);
$('transport-start').onclick=()=>viewer?.setTime(Math.min(result.duration,result.pickupEnd+.001));
$('failure-close').onclick=()=>$('failure').hidden=true;
function download(name,body,type){const url=URL.createObjectURL(new Blob([body],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export-input').onclick=()=>download('parking-input.json',JSON.stringify({schema:'parking-lab/v1',input:draft},null,2),'application/json');
$('import-input').onclick=()=>$('input-file').click();
$('input-file').onchange=async()=>{try{const file=$('input-file').files[0];if(!file)return;if(file.size>1000000)throw Error('输入文件超过1 MB');draft=E.normalize(JSON.parse(await file.text()));edited();}catch(e){$('status').textContent='导入失败：'+e.message;}finally{$('input-file').value='';}};
$('export-replay').onclick=()=>{if(dirty&&!construct())return;viewer?.pause();const root=document.documentElement.cloneNode(true),safe=v=>JSON.stringify(v).replace(/</g,'\\u003c');root.querySelector('#demo-input').textContent=safe(draft);root.querySelector('#demo-plan').textContent=safe(result);root.querySelector('#viewer').innerHTML='';download('QEC-Parking-'+draft.rows+'x'+draft.columns+'.html','<!doctype html>\n'+root.outerHTML,'text/html;charset=utf-8');$('status').textContent='已下载当前配置与完整工作台，接收者可离线继续编辑、生成和播放。';};
render();const embedded=JSON.parse($('demo-plan').textContent);if(JSON.stringify(embedded.input)===JSON.stringify(draft))accept(embedded,null);else construct();
window.ParkingLab={getDraft:()=>copy(draft),getPlan:()=>copy(result),isDirty:()=>dirty,getViewer:()=>viewer,getTime:()=>viewer.getStatus().time_us};
})();
