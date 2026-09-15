/* Editor operates on physical DAG slots; it never assigns physical timing. */
let selectedGate = null;
const pageLayers = 8;
function render() {
  const columns = logicalColumns(spec.gates), total = Math.max(0,...columns)+1;
  offset = Math.max(0,Math.min(offset,total-1));
  const stageMap = new Map((spec.qec_protocol?.stages||[]).map(x=>[x.gate_id,x.stage]));
  const first = new Map();
  spec.gates.forEach((g,i)=>{const s=stageMap.get(g.id);if(s&&!first.has(s))first.set(s,columns[i]);});
  $('stage').innerHTML='<option value="0">线路起点</option>'+[...first].map(([s,i])=>`<option value="${i}">${esc(stageNames[s]||s)}</option>`).join('');
  const current=[...first.values()].filter(i=>i<=offset).sort((a,b)=>b-a)[0]||0;
  $('stage').value=String(current);
  const visible=spec.gates.map((g,i)=>({g,i,layer:columns[i]})).filter(x=>x.layer>=offset&&x.layer<offset+pageLayers);
  const used=new Set(visible.flatMap(x=>x.g.qubit_ids));
  const rows=Array.from({length:34},(_,i)=>'Q'+String(i).padStart(3,'0')).filter(q=>$('rowFilter').value==='all'||used.has(q));
  const rowY=q=>54+rows.indexOf(q)*34;
  // Parallel CZ links get separate subtracks within one logical layer, so a
  // group of disjoint pairs is not drawn as one apparently connected wire.
  let left=116;const layerX=new Map();
  for(let layer=offset;layer<Math.min(total,offset+pageLayers);layer++) {
    const pairs=visible.filter(x=>x.layer===layer&&x.g.gate_type==='CZ');
    const width=Math.max(86,38+pairs.length*18);
    layerX.set(layer,{left,width,pairs});left+=width;
  }
  let svg=`<svg xmlns="http://www.w3.org/2000/svg" width="${Math.max(700,left+16)}" height="${Math.max(110,rows.length*34+72)}" aria-label="物理线路逻辑层">`;
  for(const [layer,p]of layerX)svg+=`<text x="${p.left+p.width/2}" y="22" text-anchor="middle" fill="#6d8387" font-size="11">层 ${layer+1}</text>`;
  rows.forEach(q=>{const n=+q.slice(1),group=n<9?'A 数据':n<18?'B 数据':n<26?'A 辅助':'B 辅助',y=rowY(q);svg+=`<text x="8" y="${y+4}" font-size="11" fill="${n<18?'#356d68':'#986c38'}">${q} · ${group}</text><line x1="112" x2="${left}" y1="${y}" y2="${y}" stroke="#dce8e4"/>`;});
  visible.forEach(({g,layer})=>{
    const p=layerX.get(layer),pair=p.pairs.findIndex(x=>x.g.id===g.id);
    const x=pair<0?p.left+p.width/2:p.left+28+pair*18;
    const ys=g.qubit_ids.map(rowY),chosen=g.id===selectedGate;
    svg+=`<g data-gate="${esc(g.id)}" tabindex="0" role="button" aria-label="选择 ${esc(g.id+' '+g.gate_type+' '+g.qubit_ids.join(' '))}" style="cursor:pointer"><title>${esc(g.id+' · '+g.gate_type+' · '+g.qubit_ids.join(' / '))}</title>`;
    if(pair>=0) {
      svg+=`<line x1="${x}" x2="${x}" y1="${ys[0]}" y2="${ys[1]}" stroke="${chosen?'#d27928':'#499784'}" stroke-width="${chosen?3:1.5}"/>`;
      ys.forEach(y=>{svg+=`<circle cx="${x}" cy="${y}" r="6" fill="${chosen?'#d27928':'#338972'}" stroke="white" stroke-width="2"/>`;});
    } else ys.forEach(y=>{const label=(g.condition?.length?'◇':'')+(g.gate_type==='MEASURE'?'M':g.gate_type==='RESET'?'R':g.gate_type);svg+=`<rect x="${x-22}" y="${y-12}" width="44" height="24" rx="5" fill="${chosen?'#fde6c9':g.gate_type==='MEASURE'?'#fff0d6':'#eee9f8'}" stroke="${chosen?'#d27928':'#d8d8e5'}"/><text x="${x}" y="${y+4}" text-anchor="middle" font-size="11">${esc(label)}</text>`;});
    svg+='</g>';
  });
  $('circuit').innerHTML=svg+'</svg>';
  $('gateList').innerHTML=visible.map(({g,i})=>`<button data-gate="${esc(g.id)}" class="${g.id===selectedGate?'chosen':''}">${i+1} · ${esc(g.gate_type)} ${esc(g.qubit_ids.join(' / '))}${g.condition?.length?' ◇':''}</button>`).join('');
  $('page').textContent=spec.gates.length?`逻辑层 ${offset+1}–${Math.min(offset+pageLayers,total)} / ${total} · 本页 ${visible.length} 槽`:'空线路';
  $('prev').disabled=offset===0;$('next').disabled=offset+pageLayers>=total;
  $('json').value=JSON.stringify(spec.gates,null,2);
  $('summary').textContent=`34 原子 · ${spec.gates.length} 门与控制槽`;
  $('selection').textContent=selectedGate?`正在编辑 ${selectedGate}`:'点击图中的门或下方条目进行编辑';
  for(const id of ['saveGate','removeGate','insertGate'])$(id).disabled=!selectedGate;
}
function selectGate(id) {
  const g=spec.gates.find(x=>x.id===id);if(!g)return;
  selectedGate=id;$('kind').value=g.gate_type;$('qa').value=+g.qubit_ids[0].slice(1);
  $('qb').value=g.qubit_ids[1]?+g.qubit_ids[1].slice(1):1;
  $('second').hidden=g.gate_type!=='CZ';
  $('gateMeta').value=JSON.stringify({depends_on:g.depends_on||[],condition:g.condition||[]},null,2);
  render();
}
function formGate(original={}) {
  const qs=[+$('qa').value];if($('kind').value==='CZ')qs.push(+$('qb').value);
  if(qs.some(q=>!Number.isInteger(q)||q<0||q>33)||new Set(qs).size!==qs.length)throw Error('请选择不同的有效原子编号 0–33');
  const meta=JSON.parse($('gateMeta').value||'{}');
  if(!Array.isArray(meta.depends_on||[])||!Array.isArray(meta.condition||[]))throw Error('依赖和条件必须为数组');
  const gate={...original,gate_type:$('kind').value,qubit_ids:qs.map(q=>'Q'+String(q).padStart(3,'0'))};
  delete gate.u_parameters;
  for(const key of ['condition','depends_on']){delete gate[key];if(meta[key]?.length)gate[key]=meta[key];}
  return gate;
}
function markEdited(){render();$('status').textContent='草稿已修改。下方回放仍为上一次结果；点击线路区编译按钮更新。';}
function initEditor() {
  $('stage').onchange=()=>{offset=+$('stage').value;render();};
  $('load').onclick=()=>{selectedGate=null;load();};
  $('prev').onclick=()=>{offset=Math.max(0,offset-pageLayers);render();};
  $('next').onclick=()=>{offset+=pageLayers;render();};
  $('rowFilter').onchange=render;
  $('kind').onchange=()=>$('second').hidden=$('kind').value!=='CZ';
  $('clear').onclick=()=>{spec.gates=[];selectedGate=null;offset=0;markEdited();};
  for(const id of ['circuit','gateList']){
    $(id).onclick=e=>{const item=e.target.closest('[data-gate]');if(item)selectGate(item.dataset.gate);};
    $(id).onkeydown=e=>{if(e.key==='Enter'||e.key===' '){const item=e.target.closest('[data-gate]');if(item){e.preventDefault();selectGate(item.dataset.gate);}}};
  }
  $('removeGate').onclick=()=>{spec.gates=spec.gates.filter(g=>g.id!==selectedGate);selectedGate=null;markEdited();};
  $('saveGate').onclick=()=>{try{const i=spec.gates.findIndex(g=>g.id===selectedGate);spec.gates[i]=formGate(spec.gates[i]);markEdited();}catch(e){fail({message:e.message});}};
  function add(insert){try{let n=0;while(spec.gates.some(g=>g.id==='edit_'+n))n++;const g=formGate({id:'edit_'+n});const i=insert?spec.gates.findIndex(g=>g.id===selectedGate)+1:spec.gates.length;spec.gates.splice(i,0,g);selectedGate=g.id;offset=logicalColumns(spec.gates)[i];markEdited();}catch(e){fail({message:e.message});}}
  $('add').onclick=()=>add(false);$('insertGate').onclick=()=>add(true);
  $('apply').onclick=()=>{try{const g=JSON.parse($('json').value);if(!Array.isArray(g)||g.some(x=>!x.id||!x.gate_type||!Array.isArray(x.qubit_ids)||x.qubit_ids.some(q=>!/^Q0[0-3][0-9]$/.test(q)||+q.slice(1)>33)))throw Error('每槽需要有效 id、gate_type、qubit_ids（Q000–Q033）');spec.gates=g;selectedGate=null;offset=0;markEdited();}catch(e){fail({message:e.message});}};
  for(const id of ['readoutMode','readoutK','readoutBudget'])$(id).onchange=()=>{spec.readout_policy={mode:$('readoutMode').value,top_k:+$('readoutK').value,candidate_budget:+$('readoutBudget').value};markEdited();};
  $('backend').onchange=()=>{spec.aod_backend=$('backend').value;markEdited();};
  $('router').onchange=()=>{spec.motion_router=$('router').value;markEdited();};
}
