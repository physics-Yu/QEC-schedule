(()=>{'use strict';
const $=id=>document.getElementById(id),copy=v=>JSON.parse(JSON.stringify(v));
const keys=['rows','columns','aod_rows','aod_columns','spacing_um','epsilon_x_um','epsilon_y_um','shift_x_um','shift_y_um'];
let draft,viewer,result,paint='2',drawing=false,busy=false,revision=0,timer;
const esc=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function api(path,value){const r=await fetch(path,value?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}:{});const v=await r.json();if(!r.ok)throw Error(v.error||r.statusText);return v;}
function mount(data){viewer?.destroy();const targets=new Set(data.requested||[]),atomColors=Object.fromEntries(data.frames[0].atom_updates.map(a=>[a.id,targets.has(a.id)?'#db4b50':'#3879c7']));viewer=window.NeutralAtomViewer.mount($('viewer'),data,{compact:true,atomColors,dashedEmptySlm:true});}
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
function edited(){revision++;render();$('failure').hidden=true;$('status').textContent=result?'草稿已修改；下方保留上次执行，需重新编译。':'初态可编辑；点击编译才执行拾取和运输。';clearTimeout(timer);if(!result)timer=setTimeout(updatePreview,250);}
async function updatePreview(){const rev=revision;try{const p=await api('/api/preview',copy(draft));if(rev===revision&&!result)mount(p.recording);}catch(e){if(rev===revision)$('status').textContent='初态检查：'+e.message;}}
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
function setBusy(value){busy=value;for(const el of document.querySelectorAll('input,select,#compile,#example,#checker,#all-target,#clear,#import-input,#small-example,#compatible-example,#fit-capacity,#fit-transport'))el.disabled=value;}
function showFailure(error){$('status').textContent='本次未完成。输入保留；没有发布新的成功动画。';$('failure').hidden=false;$('failure-message').textContent=(error.phase||'input')+' · '+error.code+'：'+error.message;$('failure-detail').textContent='这是指定固定构造或输入的失败，不是一般物理不可行证明。\n'+JSON.stringify(error,null,2);$('failure').focus();$('failure').scrollIntoView({behavior:'smooth',block:'center'});}
function accept(r){result=r;mount(r.recording);const p=r.pickup;
 const a=p.analysis;$('compatibility-report').textContent=a?`最少兼容抓取：按行 ${a.row.batches} 批，按列 ${a.column.batches} 批；当前实际 ${p.transfer_events} 批。无目标行列跳过，空位不限，固定原子禁止对齐。`:'';
 $('status').textContent='已完成：目标保持 AOD 承载，保护原子留在原 SLM；完整计划独立重放一致。';
 $('metrics').innerHTML=[['拾取耗时',p.duration_us.toFixed(2)+' μs'],['集体运输',r.transport_duration_us.toFixed(2)+' μs'],['转移批次',p.transfer_events],['parking 段',p.parking_sweeps],['拾取阶段原子总路程',p.movement_distance_um.toFixed(2)+' μm']].map(([k,v])=>`<span>${esc(k)}<br><strong>${esc(v)}</strong></span>`).join('');
 $('steps').innerHTML=p.steps.map(s=>`<tr><td>${s.axis==='row'?'行':'列'} ${(s.groups||[s.group]).join(', ')}</td><td>${s.picked.join(', ')}</td><td>${s.loaded.join(', ')}</td><td><button data-time="${s.end_us}">${s.end_us.toFixed(2)}</button></td></tr>`).join('');
 for(const id of ['pickup-end','transport-start','export-replay'])$(id).disabled=false;
}
$('compile').onclick=async()=>{if(busy)return;const input=copy(draft);setBusy(true);$('failure').hidden=true;const start=Date.now();
 try{const job=await api('/api/compile',input);let r;
 do{$('status').textContent='正在规划并验证全交点、连续路径和独立重放… '+((Date.now()-start)/1000).toFixed(1)+' s';await new Promise(resolve=>setTimeout(resolve,350));r=await api('/api/jobs/'+job.id);}while(r.status==='compiling');
 if(r.status!=='completed')showFailure(r.error);else{accept(r);history.replaceState(null,'','?job='+job.id);}}
 catch(e){showFailure({code:'REQUEST_ERROR',message:e.message,phase:'request'});}finally{setBusy(false);}};
$('steps').onclick=e=>{const b=e.target.closest('[data-time]');if(b)viewer?.setTime(Number(b.dataset.time));};
$('pickup-end').onclick=()=>viewer?.setTime(result.pickup.duration_us);
$('transport-start').onclick=()=>viewer?.setTime(Math.min(result.recording.duration,result.pickup.duration_us+.001));
$('failure-close').onclick=()=>$('failure').hidden=true;
function download(name,body,type){const url=URL.createObjectURL(new Blob([body],{type}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('export-input').onclick=()=>download('parking-input.json',JSON.stringify(draft,null,2),'application/json');
$('import-input').onclick=()=>$('input-file').click();$('input-file').onchange=async()=>{try{const f=$('input-file').files[0];if(!f)return;if(f.size>65535)throw Error('输入文件过大');const input=JSON.parse(await f.text());await api('/api/preview',input);draft=input;edited();}catch(e){showFailure({code:'INVALID_INPUT',message:e.message});}};
$('export-replay').onclick=async()=>{const bundle=await (await fetch('/atom-viewer.js')).text();download('parking-animation.html','<!doctype html><meta charset="utf-8"><div id="viewer"></div><script>'+bundle.replace(/<\/script/gi,'<\\/script')+'</'+'script><script>NeutralAtomViewer.mount(document.getElementById("viewer"),'+JSON.stringify(result.recording).replace(/</g,'\\u003c')+');</'+'script>','text/html');};
setBusy(true);
(async()=>{try{draft=await api('/api/default');const id=new URLSearchParams(location.search).get('job');if(id){const r=await api('/api/jobs/'+id);if(r.input)draft=r.input;render();if(r.status==='completed')accept(r);else showFailure(r.error||{code:'NOT_READY',message:'任务尚未完成'});}else{render();await updatePreview();$('status').textContent='初态已就绪；编辑目标后点击编译。';}}catch(e){showFailure({code:'LOAD_ERROR',message:e.message});}finally{setBusy(false);}})();
})();
