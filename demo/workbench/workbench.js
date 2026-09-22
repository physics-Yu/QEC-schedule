if(location.protocol!=='file:'){
/* The draft is input only. All motion is supplied by the Python physical pipeline. */
(()=>{'use strict';
const $=id=>document.getElementById(id), clone=v=>JSON.parse(JSON.stringify(v));
const types=['H','X','Y','Z','T','CZ'];
const isFourPatch=()=>draft.layout==='surface_qec_ghz4';
const qecDataCount=()=>isFourPatch()?36:18;
const defaultOrigins=()=>isFourPatch()?[[0,0],[40,0],[0,40],[40,40]]:[[0,0],[40,0]];
const isTemporal=()=>['qec_temporal','qec_temporal_four'].includes(draft.compiler)||Array.isArray(draft.qec_protocol?.noisy_rounds);
const availableTypes=()=>draft.qec_enabled?['H','X','Y','Z','CZ','MEASURE','RESET']:types;
const roleOf=q=>draft.qec_enabled?(Number(q.slice(1))<qecDataCount()?'data':'ancilla'):'';
const MAX_ATOMS=128,MAX_GATES=4096,MAX_COLUMNS=4096,PAGE_SIZE=64;
const ordered=()=>['ordered_greedy','smt_ordered','zoned_ids'].includes(draft.compiler);
const nativeQmap=()=>draft.compiler==='qmap_native';
function useNativePlatform(implementation){
 if(implementation==='qmap_native'){
  draft.layout='qmap_paired';draft.aod_backend='row_column_orthogonal';draft.ez_neighbor_guard_enabled=false;
  draft.placement_search={...draft.placement_search,enabled:false};
  draft.aod_row_offsets_um=Array.from({length:draft.aod_rows},(_,i)=>i*2);
  draft.aod_column_offsets_um=Array.from({length:draft.aod_columns},(_,i)=>i*2);
 }else if(draft.layout==='qmap_paired'){draft.layout='grid';}
}
const policyNames={zoned_ids:'分层驻留 · IDS',ordered_greedy:'有序轴贪心 · 当前版',smt_ordered:'SMT 有序轴批次 · 当前版',basic:'逐门归还基线',greedy:'贪心',critical_path:'关键路径',lookahead:'有限前瞻',row_symmetric:'对称逐门基线',row_greedy:'行预置 · 下界剪枝贪心',patch_symmetric:'二维 patch · 对称基线',patch_greedy:'二维 patch · 并行贪心'};
policyNames.qec_ghz2='QEC · 测量与条件纠错';
policyNames.qec_temporal_four='QEC · 四逻辑比特多轮 GHZ';
policyNames.qec_temporal='QEC · 多轮 syndrome 与报告位噪声';
policyNames.qec_joint='QEC · 批光与读出联合优化';
policyNames.qec_persistent='QEC · 保留 AOD 状态与复用';
const policyNotes={zoned_ids:'门依赖 → 驻留复用 → 有限 IDS 落点 → 兼容分组 → 正交物理动作；保留完整物理校验。',ordered_greedy:'独立于电路的有序行列合批，2.5 μm 占据格筛选和 axis-hold 路线；按容量分批运输，保留全部物理校验。',smt_ordered:'独立 SMT 约束选择当前 READY CZ 批次，复用有序路线与实际物理执行；不保证全电路最优。',basic:'每门后归还；与其他 M4 策略共用动作空间，方便同条件对比。',greedy:'优先比较当前合法服务的实际成本，保留可复用位置。',critical_path:'先处理后继依赖较长的门，再比较物理成本。',lookahead:'有限推演后续门，比较驻留、归还和终态成本；更多搜索可能增加编译时间。',row_symmetric:'整行预置 EZ，按固定方向逐门服务后恢复行布局，最后统一归还。要求 row 初态与覆盖整行的 AOD。',row_greedy:'与对称基线共用整行平台和终态，按下界筛选后验证服务候选；只在声明的行服务动作族内比较。'};
policyNotes.patch_symmetric='二维 patch 保持真实坐标，使用对称服务与完整归还；并行效果由实际物理执行记录展示。';
policyNotes.patch_greedy='在二维布局中搜索可并行门与运输，显式检查实际作用对；可切换四邻格停驻保护，其他安全校验保持。';
policyNotes.qec_ghz2='实际编辑线路经物理执行、辅助原子测量和条件 X/Z 纠错；最终逻辑校验来自量子状态，不保证任意改写仍得到 GHZ。';
policyNotes.qec_temporal_four='四个二维 patch、36 data＋32 ancilla；三噪声轮＋完美闭合轮。沿用真实分组运输与全部校验，编辑不保证仍属于受支持单事件历史。';
policyNotes.qec_temporal='三轮受限单事件噪声抽取＋真实完美闭合轮；译码仅读报告位，未知历史明确报告。可编辑 Clifford 线路与测量报告翻转，不保证任意改写仍可纠正。';
policyNotes.qec_joint='同类单比特门按真实条件批量执行；读出比较 SLM 落地与静止 AOD 服务的完整合法成本，保留全部校验与原测量次序。';
policyNotes.qec_persistent='保留已捕获原子，在满足真实间距和支撑约束时执行单比特门及复用同组运输；不保证编译墙钟更快，最终完整归还。';
const qid=i=>'Q'+String(i).padStart(3,'0');
const escape=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const studioModel=window.AtomStudioModel;
const studioCatalog=window.AtomStudioCatalog;
$('preset').innerHTML='<option value="">选择门线路…</option>'+studioCatalog.circuit_presets.map(p=>'<option value="'+escape(p.id)+'">'+escape(p.label)+'</option>').join('');
let draft=studioModel.newCustom(studioCatalog),revision=0,columns=8,page=0,tool='H',selected=null,pending=null,history=[],future=[];
let customDraft=null,inputValid=false;
const workspaceMode=()=>draft.studio?.mode||'history';
const locked=()=>workspaceMode()!=='custom';
let previewController=null,job=null,viewer=null,result=null,resultRevision=-1,startQueue=Promise.resolve();
let failureBundle=null,replayFocused=false;
let placementJob=null,placementReport=null,placementRevision=-1;
const budgetKeys=['max_decisions','ready_limit','site_limit','lookahead_depth','beam_width','rollout_budget','compile_timeout_s','row_candidate_budget','route_expansions','plan_budget','route_budget','solver_timeout_ms','model_budget','readout_candidate_budget','readout_top_k','motion_router','readout_mode','qmap_routing'];
const platformKeys=['aod_backend','aod_rows','aod_columns','aod_row_offsets_um','aod_column_offsets_um','ez_neighbor_guard_enabled','ez_policy'];
function normalizeConfiguration(value){
 value.circuit_profile??=value.compiler==='qec_temporal_four'?'qec_temporal_four':value.compiler==='qec_temporal'?'qec_temporal':value.qec_enabled?'qec_ghz2':'physical';
 if(!value.compilation){
  const p=value.circuit_profile,surface=value.layout==='surface_patches';
  const recommended=p==='physical'?(surface?'patch_greedy':'greedy'):p==='qec_ghz2'?'qec_joint':p;
  const baseline=p==='physical'?(surface?'patch_symmetric':'basic'):p==='qec_ghz2'?'qec_ghz2':null;
  value.compilation={strategy:value.compiler===recommended?'recommended':baseline&&value.compiler===baseline?'baseline':'legacy'};
  if(value.compilation.strategy==='legacy')value.compilation.implementation=value.compiler||'legacy';
  for(const key of budgetKeys)if(value[key]!==undefined)value.compilation[key]=value[key];
 }
 const legacyQec=value.qec_enabled&&(!value.aod_traps||value.aod_traps===98);
 const rows=value.aod_rows??(legacyQec?7:value.layout==='surface_patches'&&!value.aod_traps?6:1);
 const cols=value.aod_columns??(legacyQec?14:value.aod_traps??(value.layout==='surface_patches'?6:1));
 value.aod_rows=rows;value.aod_columns=cols;delete value.aod_traps;
 return value;
}
// Flat mirrors keep older local services and exported recordings readable.
// The Python resolver validates capabilities and is authoritative for execution.
function syncCompilation(value){
 normalizeConfiguration(value);
 const c=value.compilation,p=value.circuit_profile;
 if(c.strategy==='legacy')value.compiler=c.implementation;
 else if(p==='physical')value.compiler=value.layout==='surface_patches'?(c.strategy==='baseline'?'patch_symmetric':'patch_greedy'):(c.strategy==='baseline'?'basic':'greedy');
 else if(p==='qec_ghz2')value.compiler=c.strategy==='baseline'?'qec_ghz2':'qec_joint';
 else value.compiler=p;
 for(const key of budgetKeys){delete value[key];if(c[key]!==undefined)value[key]=c[key];}
 return value;
}
normalizeConfiguration(draft);
function showWorkspace(config=false){
 $('placement-panel').hidden=config||replayFocused||!(placementReport||placementJob);
 $('configuration-workspace').hidden=!config;$('circuit-workspace').hidden=config||replayFocused;
 $('execution-workspace').hidden=config;
 $('tab-circuit').setAttribute('aria-pressed',String(!config));$('tab-config').setAttribute('aria-pressed',String(config));
}
$('tab-circuit').onclick=$('return-circuit').onclick=()=>showWorkspace(false);
$('tab-config').onclick=$('open-platform').onclick=$('open-compilation').onclick=()=>showWorkspace(true);
$('focus-replay').onclick=()=>{replayFocused=!replayFocused;$('focus-replay').textContent=replayFocused?'返回线路与回放':'专注回放';showWorkspace(false);$('execution-workspace').scrollIntoView({behavior:'smooth',block:'start'});};
$('edit-initial').onclick=()=>{$('initial-body').hidden=!$('initial-body').hidden;$('edit-initial').textContent=$('initial-body').hidden?'调整初态':'收起初态';};
const profileNames={physical:'普通物理线路',qec_ghz2:'两逻辑比特 · 单轮 QEC',qec_temporal:'两逻辑比特 · 多轮 QEC',qec_temporal_four:'四逻辑比特 · 多轮 QEC'};
const strategyNames={recommended:'推荐调度',baseline:'基线对照',legacy:'历史配置'};
const compilationPresets=studioCatalog.algorithms;
for(const p of compilationPresets)policyNames[p.id]=p.label;
const needsUpgrade=()=>!locked()&&(!compilationPresets.some(p=>p.id===draft.compiler)||(draft.aod_backend||'rigid')!=='row_column_orthogonal'||(draft.compilation.motion_router||'axis_hold')!=='axis_hold');
function presetUnavailable(p){return p.single_trap&&draft.aod_rows*draft.aod_columns!==1?'需要 1 × 1 AOD':'';}
function renderConfiguration(){
 const c=draft.compilation;
 const implementation=c.strategy==='legacy'?c.implementation:c.strategy==='baseline'?'basic':'greedy';
 const currentPreset=compilationPresets.find(p=>p.id===implementation);
 $('compiler').innerHTML=locked()?'<option value="locked">'+escape(policyNames[draft.compiler]||draft.compiler)+' · 配套锁定</option>':compilationPresets.map(p=>{const reason=presetUnavailable(p);return '<option value="preset:'+p.id+'" '+(reason?'disabled':'')+'>'+p.label+(reason?'（'+reason+'）':'')+'</option>';}).join('')+(!currentPreset?'<option disabled value="preset:'+escape(implementation)+'">历史配置：'+escape(policyNames[implementation]||implementation)+'</option>':'');
 $('compiler').value=locked()?'locked':'preset:'+implementation;
 $('compiler').disabled=locked();
 $('strategy-preset-note').textContent=locked()?'此实验使用已验证的配套配置，不自动替换其协议或算法。':needsUpgrade()?'此草稿含旧算法、后端或路线。点击下方更新按钮会显式换成当前默认流程，保留原子数、布局、初始偏移和门列表；之后需重新编译。':'算法独立于电路示例；这里只列出已接入完整工作台流程的版本。旧单原子、刚性阵列和实验对照实现不再混入常用菜单。';
 $('upgrade-current').hidden=!needsUpgrade();
 $('compiler-guide').innerHTML=currentPreset?'<h3>'+escape(currentPreset.version)+'</h3>'+[['如何作决定',currentPreset.decision],['取舍与限制',currentPreset.tradeoff],['验证范围',currentPreset.validation]].map(([k,v])=>'<p><strong>'+k+'：</strong>'+escape(v)+'</p>').join(''):'<p>历史或专用实现：保留原设置与执行语义，不能把旧回放视为当前版本重新编译的结果。</p>';
 $('greedy-budget-fields').hidden=!['ordered_greedy','zoned_ids'].includes(draft.compiler);
 $('zoned-budget-fields').hidden=draft.compiler!=='zoned_ids';
 $('ordered-beam-label').textContent=draft.compiler==='zoned_ids'?'IDS 备选队列容量':'每层保留的候选组合数';
 $('plan-budget-label').textContent=draft.compiler==='zoned_ids'?'IDS 完成候选数':'实际评估的完整计划数';
 $('smt-budget-fields').hidden=draft.compiler!=='smt_ordered';
 $('readout-budget-fields').hidden=!draft.gates.some(g=>['MEASURE','RESET'].includes(g.gate_type));
 $('aod-backend').innerHTML='<option value="row_column_orthogonal">有序行列 · 横平竖直分段移动</option>'+((draft.aod_backend||'rigid')!=='row_column_orthogonal'?'<option disabled value="'+escape(draft.aod_backend||'rigid')+'">历史后端：'+escape(draft.aod_backend||'rigid')+'</option>':'');
 $('platform-title').textContent=(draft.aod_backend||'rigid')==='rigid'?'平台 · 历史固定间距 AOD':'平台 · 可变行列 AOD';
 $('aod-coordinate-note').innerHTML=(draft.aod_backend||'rigid')==='rigid'?'<strong>此记录使用历史固定间距后端</strong><p>初始偏移在运行中保持不变，直接决定可抓取的几何形状。更新到当前版本后才能自动重构行列。</p>':'<strong>通常只需要设置行数和列数</strong><p>编译器按每批原子的实际位置选择抓取轴、作用轴和运输偏移，不要求预先填好所有抓取点。</p><p>初始偏移定义起始和最终归还构型，会影响空载定位、归还耗时及世界边界；通常可保留 10 μm 等间距。</p>';
 $('aod-backend-label').textContent=(draft.aod_backend||'rigid')==='row_column_orthogonal'?'有序行列 · 横平竖直分段移动':'历史后端：'+(draft.aod_backend||'rigid');
 $('motion-router-label').textContent=(c.motion_router||'axis_hold')==='axis_hold'?'自动直接到位 / 分轴保持':'历史通道路线';
 $('aod-backend').value=draft.aod_backend||'rigid';$('aod-backend').disabled=locked();
 $('ordered-controls').hidden=!ordered();
 $('current-compiler-flow').hidden=!ordered();
 $('motion-router').innerHTML='<option value="axis_hold">自动直接到位 / 分轴保持</option>'+((c.motion_router||'axis_hold')!=='axis_hold'?'<option disabled value="legacy_corridor">历史通道路线</option>':'');
 for(const [id,key,fallback]of [['zoned-site-limit','site_limit',8],['ordered-beam','beam_width',64],['plan-budget','plan_budget',4],['route-budget','route_budget',128],['solver-timeout','solver_timeout_ms',5000],['model-budget','model_budget',24],['readout-budget','readout_candidate_budget',16],['readout-top-k','readout_top_k',3],['motion-router','motion_router','axis_hold'],['readout-mode','readout_mode','adaptive']]){$(id).value=c[key]??fallback;$(id).disabled=locked();}
 $('policy-note').textContent=locked()?(studioCatalog.demos.find(d=>d.id===draft.studio?.demo_id)?.note||'保持历史输入的实际实现与参数。'):(currentPreset?.purpose||policyNotes[draft.compiler]||'保留历史实现。');
 $('initial-summary').textContent=draft.atom_count+' 个原子 · '+({row:'单行',grid:'网格',shuffled:'随机映射',surface_patches:'四个 surface patch',surface_qec_ghz2:'两块 data + ancilla',surface_qec_ghz4:'四块 data + ancilla'}[draft.layout]||draft.layout);
 $('circuit-profile-summary').textContent=profileNames[draft.circuit_profile]||draft.circuit_profile;
 $('open-platform').textContent='平台 · AOD '+draft.aod_rows+' × '+draft.aod_columns;
 $('open-compilation').textContent='算法 · '+(locked()?'实验配套':currentPreset?.label||'请选择');
 $('legacy-controls').hidden=true;
 $('compilation-compatibility').textContent=locked()?'初态、平台、线路和编译配置已锁定。返回顶部选择自定义工作区可恢复自己的草稿。':'通用指不依赖某份 demo 的门编号或协议阶段；有限搜索仍可能失败，并不保证任意布局可行或最优。';
 if(!$('qmap-routing')){
  const label=document.createElement('label');label.id='qmap-routing-field';label.textContent='作者运输分组';
  const select=document.createElement('select');select.id='qmap-routing';select.innerHTML='<option value="strict">Strict · 同批保持序关系</option><option value="relaxed">Relaxed · 分次装载 / 分列卸载</option>';
  select.onchange=()=>{if(!locked())change(()=>{draft.compilation.qmap_routing=select.value;});};label.appendChild(select);$('compiler').parentElement.after(label);
 }
 $('qmap-routing-field').hidden=!nativeQmap();$('qmap-routing').value=c.qmap_routing||'strict';$('qmap-routing').disabled=locked();
 if(nativeQmap()){
  $('initial-summary').textContent=draft.atom_count+' 个原子 · QMAP 成对 SLM 平台';
  $('aod-coordinate-note').innerHTML='<strong>作者选初态、落点和运输分组；这里配置 AOD 容量</strong><p>SZ 间距 10 μm；EZ 的 SLM 成对间距 2 μm。方格四邻停驻规则关闭；碰撞、完整活动交点、支撑和 5 μm 单比特光间距仍检查。</p><p>初始空 AOD 坐标由兼容层生成，不作为搜索参数。作者分组超过行列容量时明确报错。</p>';
  $('compilation-compatibility').textContent='原生 C++ 编译与本地物理执行分别计时。此平台不冒充旧 row/grid 布局；H/X/Y/Z/T/CZ 仍可编辑。测量与反馈保留原 QEC 入口。';
 }
 renderMode();
}
function renderMode(){
 const mode=workspaceMode(),isLocked=locked(),demo=studioCatalog.demos.find(d=>d.id===draft.studio?.demo_id);
 document.body.dataset.workspaceMode=mode;
 $('experiment-demo').innerHTML='<option value="custom">自定义工作区</option>'+studioCatalog.demos.map(d=>'<option value="'+d.id+'">Demo · '+d.label+'</option>').join('')+(mode==='history'?'<option value="history">历史输入 / 回放 · 只读</option>':'');
 $('experiment-demo').value=mode==='demo'?demo?.id:mode;
 $('mode-badge').textContent=isLocked?'配套配置已锁定':'自由编辑';
 $('mode-description').textContent=demo?demo.note+' 平台、初态、线路与算法成套锁定；只在点击编译后运行。':mode==='history'?'按原记录展示历史设置与执行。专用实现不会自动变成通用算法；选择自定义可恢复自己的草稿。':'自行设置初态和平台；电路示例只填充门列表，算法由你独立选择。';
 document.querySelector('.session-card').dataset.locked=String(isLocked);
 for(const root of ['platform-config','compilation-config','initial-fields'])for(const el of $(root).querySelectorAll('input,select,button')){
  if(isLocked){if(el.dataset.beforeLock===undefined)el.dataset.beforeLock=String(el.disabled);el.disabled=true;}
  else if(el.dataset.beforeLock!==undefined){el.disabled=el.dataset.beforeLock==='true';delete el.dataset.beforeLock;}
 }
 $('compiler').disabled=isLocked;
 for(const id of ['random-circuit','preset','clear','import-input','apply-gate','delete-gate'])$(id).disabled=isLocked;
 for(const el of document.querySelectorAll('#palette button,.cell.empty'))el.disabled=isLocked;
 if(isLocked)$('hint').textContent='锁定实验线路 · 可查看门详情和定位执行；编辑请切回自定义工作区。';
 $('seed').disabled=isLocked||draft.layout!=='shuffled';
 $('seed').parentElement.hidden=draft.layout!=='shuffled';
 for(const id of ['layout','aod-row-offsets','aod-column-offsets','ez-neighbor-guard','reset-aod-offsets'])if($(id))$(id).disabled=isLocked||nativeQmap();
 $('undo').disabled=isLocked||!history.length;$('redo').disabled=isLocked||!future.length;
 $('compile').disabled=!inputValid||Boolean(job)||Boolean(placementJob)||mode==='history'||needsUpgrade()||Boolean(draft.compilation_backend?.configuration_error);
 renderPlacementControls();
 if(draft.compilation_backend?.configuration_error)$('compilation-compatibility').textContent=draft.compilation_backend.configuration_error;
 $('compilation-compatibility').classList.toggle('configuration-error',Boolean(draft.compilation_backend?.configuration_error));
 const x=$('aod-column-offsets').value.split(',').map(Number),y=$('aod-row-offsets').value.split(',').map(Number);
 $('aod-coordinate-example').textContent='例：整体位置 (20, −30)，交点 ('+(y.length-1)+','+(x.length-1)+') = ('+(20+x.at(-1))+', '+(-30+y.at(-1))+') μm';
}
function replaceWorkspace(value){
 draft=normalizeConfiguration(value);history=[];future=[];selected=null;pending=null;columns=8;page=0;edited();
}
$('reset-aod-offsets').onclick=()=>{if(locked())return;change(()=>{draft.aod_column_offsets_um=Array.from({length:draft.aod_columns},(_,i)=>i*10);draft.aod_row_offsets_um=Array.from({length:draft.aod_rows},(_,i)=>i*10);});};
$('upgrade-current').onclick=()=>{if(locked())return;change(()=>{const p=compilationPresets.find(p=>p.id===studioCatalog.default_algorithm);for(const key of budgetKeys)delete draft[key];draft.compilation={strategy:'legacy',implementation:p.id,...studioCatalog.compilation_defaults,...p.defaults,motion_router:'axis_hold',readout_mode:'adaptive'};draft.compiler=p.id;draft.aod_backend='row_column_orthogonal';useNativePlatform(p.id);delete draft.compilation_backend;});};
$('experiment-demo').onchange=async()=>{
 const id=$('experiment-demo').value,rev=revision;
 if(!locked())customDraft=clone(draft);
 if(id==='custom'){replaceWorkspace(customDraft?clone(customDraft):studioModel.newCustom(studioCatalog));return;}
 try{const value=await api('/api/studio/demos/'+id);if(rev!==revision)throw Error('载入期间草稿已变化，请重新选择。');replaceWorkspace(value);}
 catch(e){render();toast('Demo 载入失败：'+e.message);}
};
$('aod-backend').onchange=()=>{if(!locked())change(()=>{draft.aod_backend=$('aod-backend').value;});};
for(const [id,key,text]of [['zoned-site-limit','site_limit'],['ordered-beam','beam_width'],['plan-budget','plan_budget'],['route-budget','route_budget'],['solver-timeout','solver_timeout_ms'],['model-budget','model_budget'],['readout-budget','readout_candidate_budget'],['readout-top-k','readout_top_k'],['motion-router','motion_router',true],['readout-mode','readout_mode',true]]){
 $(id).onchange=()=>{if(!locked())change(()=>{draft.compilation[key]=text?$(id).value:Number($(id).value);});};
}
$('compiler').onchange=()=>{
 const preset=compilationPresets.find(p=>'preset:'+p.id===$('compiler').value);
 if(locked()||!preset||presetUnavailable(preset)){render();return;}
 change(()=>{const timeout=draft.compilation.compile_timeout_s;draft.compilation={strategy:'legacy',implementation:preset.id,...studioCatalog.compilation_defaults,...preset.defaults};if(timeout!==undefined)draft.compilation.compile_timeout_s=timeout;useNativePlatform(preset.id);});
};
function savedConfigurations(kind){try{return JSON.parse(window.localStorage?.getItem('atom-studio.configurations.'+kind)||'{}');}catch{return {};}}
function renderSavedConfigurations(kind){const saved=savedConfigurations(kind);$(''+kind+'-saved').innerHTML='<option value="">选择配置…</option>'+Object.keys(saved).map(name=>'<option value="'+escape(name)+'">'+escape(name)+'</option>').join('');}
function configurationPayload(kind){
 if(kind==='compilation')return clone(draft.compilation);
 const value=clone(draft);
 value.aod_row_offsets_um=$('aod-row-offsets').value.split(',').map(Number);
 value.aod_column_offsets_um=$('aod-column-offsets').value.split(',').map(Number);
 value.ez_neighbor_guard_enabled??=true;value.ez_policy??='adaptive';
 return Object.fromEntries(platformKeys.filter(key=>value[key]!==undefined).map(key=>[key,value[key]]));
}
async function applyConfiguration(kind,config){
 if(locked())throw Error('当前实验配置已锁定。');
 if(!config||typeof config!=='object'||Array.isArray(config))throw Error('配置须为 JSON 对象');
 const allowed=kind==='platform'?platformKeys:['strategy','implementation',...budgetKeys];
 if(Object.keys(config).some(key=>!allowed.includes(key)))throw Error('配置包含不属于此配置层的字段');
 const candidate=clone(draft),rev=revision;
 if(kind==='compilation')candidate.compilation=clone(config);
 else{for(const key of platformKeys)delete candidate[key];Object.assign(candidate,clone(config));}
 syncCompilation(candidate);
 const valid=await api('/api/preview',candidate);
 if(rev!==revision)throw Error('载入期间草稿已变化，请重试');
 change(()=>{draft=candidate;draft.compilation=clone(valid.input.compilation||candidate.compilation);draft.compilation_backend=valid.input.compilation_backend;});
 toast('已应用'+(kind==='platform'?'平台':'编译')+'配置；点击线路区的编译按钮后运行。');
}
for(const kind of ['platform','compilation']){
 renderSavedConfigurations(kind);
 $(kind+'-save').onclick=()=>{
  const name=$(kind+'-name').value.trim();if(!name){toast('请先填写配置名称。');return;}
  try{if(!window.localStorage)throw Error('浏览器不支持本地保存，请导出 JSON');const saved=savedConfigurations(kind);if(Object.hasOwn(saved,name))throw Error('名称已存在，请使用新名称保存副本');saved[name]=configurationPayload(kind);window.localStorage.setItem('atom-studio.configurations.'+kind,JSON.stringify(saved));renderSavedConfigurations(kind);$(kind+'-saved').value=name;toast('配置已保存：'+name);}catch(e){toast(e.message);}
 };
 $(kind+'-load').onclick=async()=>{try{const config=savedConfigurations(kind)[$(kind+'-saved').value];if(!config)throw Error('请先选择配置');await applyConfiguration(kind,config);}catch(e){toast('配置载入失败：'+e.message);}};
 $(kind+'-export').onclick=()=>download('atom-'+kind+'-configuration.json',JSON.stringify({schema:'atom-studio-configuration/v1',kind,name:$(kind+'-name').value.trim(),config:configurationPayload(kind)},null,2),'application/json');
 $(kind+'-import').onclick=()=>$(kind+'-file').click();
 $(kind+'-file').onchange=async()=>{const file=$(kind+'-file').files[0];if(!file)return;try{if(file.size>1024*1024)throw Error('配置文件过大');const value=JSON.parse(await file.text());if(value.schema!=='atom-studio-configuration/v1'||value.kind!==kind)throw Error('请选择匹配类型的配置文件');await applyConfiguration(kind,value.config);$(kind+'-name').value=value.name||'';}catch(e){toast('配置导入失败：'+e.message);}finally{$(kind+'-file').value='';}};
}
function showFailure(report,value,extra={}){
 const code=report.code||report.error?.code||'COMPILE_FAILED';
 const messages={DECISION_BUDGET_EXHAUSTED:'决策预算耗尽：门执行与最终归还尚未同时完成。',CANDIDATES_EXHAUSTED:'当前有限搜索未找到合法的 READY 门执行方案。',COMPILE_TIMEOUT:'编译超过时间上限，工作进程已停止。',INPUT_ERROR:'输入校验失败，请检查门参数和操作数。'};
 failureBundle={input:clone(value),report,...extra};
 $('failure-summary').textContent=`${messages[code]||report.message||report.error?.message||'编译未完成'} 阶段：${report.phase||'request'}；已完成 ${report.completed_gates??report.progress?.completed_gates??'未知'} / ${value.gates.length} 门。`;
 $('failure-causes').textContent=[code,...(report.causes||[]).map(c=>`${c.code} × ${c.count}：${c.example?.violation?.message||''}`)].join('\n');
 $('failure-note').textContent=report.note||'输入已保留。可修改后重新编译；进程中断不保证有最终执行快照。';
 $('failure-raw').textContent=JSON.stringify(report,null,2);
 $('failure-dialog').hidden=false;$('failure-close').focus?.();
}
$('failure-close').onclick=()=>{$('failure-dialog').hidden=true;$('compile').focus?.();};
$('failure-dialog').onkeydown=e=>{
 if(e.key==='Escape'){$('failure-close').onclick();e.stopPropagation();}
 if(e.key==='Tab'){
  const controls=[$('failure-close'),$('failure-download')];
  if(e.target===controls[e.shiftKey?0:1]){e.preventDefault();controls[e.shiftKey?1:0].focus();}
 }
};
$('failure-download').onclick=()=>download('atom-compile-failure.json',JSON.stringify(failureBundle,null,2),'application/json');
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function toast(message=''){$('toast').textContent=message}
async function api(path,value,signal){const r=await fetch(path,value===undefined?{signal}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value),signal});const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data}
function status(state,title,detail='',fraction=0){$('compile-state').dataset.state=state;$('compile-message').textContent=title;$('compile-detail').textContent=detail;$('progress-fill').style.width=Math.max(0,Math.min(100,fraction*100))+'%'}
function markStale(){$('qec-result').hidden=true;$('saved-provenance').hidden=true;if(result){$('viewer').classList.add('stale');$('playback-revision').textContent=`旧版本 ${resultRevision}`;$('playback-note').textContent='线路已修改；下方保留上次运行结果，等待当前版本编译完成。'}$('greedy-decisions').hidden=true;$('export-replay').disabled=!result}
function decisionReason(d){
 const strategy=d.strategy||result?.input?.compiler;
 if(d.selected==='explicit-terminal')return '满足完整终态';
 if(strategy==='qec_joint'&&d.readout_search){const r=d.readout_search;return '选用 '+(r.selected_family==='loaded_return'?'静止 AOD 读出':'SLM 落地读出')+' · '+r.selected_duration_us.toFixed(2)+' μs · 较落地服务节省 '+r.saved_us.toFixed(2)+' μs · '+r.candidates.map(c=>c.family+': '+(c.status==='valid'?c.duration_us.toFixed(2)+' μs':c.violation?.code||'拒绝')).join(' / ');}
 if(['qec_persistent','qec_joint','qec_temporal','qec_temporal_four'].includes(strategy))return d.kind==='cohort_release'?'释放保留原子：'+d.reason:d.cohort_reused?'复用保留 AOD 原子：'+(d.retained_atoms||[]).join(', '):(d.retained_atoms?.length?'保留 AOD：'+d.retained_atoms.join(', '):d.kind||'实际服务');
 if(strategy==='zoned_ids'&&d.placement_search)return 'IDS 展开 '+d.placement_search.expanded+' 个节点；'+(d.cz_batches||[]).map(b=>b.length+' 对 CZ').join(' / ')+'；先落点分组，后物理路径；规划 '+d.planning_seconds.toFixed(3)+' s';
 if(strategy==='qmap_native')return '作者 NAViz 第 '+d.line+' 行 · '+(d.kind==='CZ'?'保持原生 CZ 分层':d.reason||'本地物理兼容');
 if(strategy==='basic')return '逐门归还';
 if(strategy==='row_symmetric')return '固定对称行服务';
 if(strategy==='row_greedy')return `构造 ${d.constructed||0} · 下界剪枝 ${d.bound_pruned||0}${d.local_optimum_certified?' · 本步候选族已覆盖':''}`;
 if(strategy==='patch_symmetric'||strategy==='patch_greedy')return `二维服务 · 构造 ${d.constructed||0}${d.bound_pruned?' · 下界剪枝 '+d.bound_pruned:''}`;
 if(strategy==='critical_path')return '关键路径 '+(d.selected_features?.critical_path_us??0).toFixed(2)+' μs · 复用 '+(d.selected_features?.reuse_count??0)+' 原子';
 if(strategy==='lookahead'){const p=d.policy_search||{},e=(p.evaluations||[]).find(e=>e.candidate===d.selected);return `${p.nodes_used||0}/${p.node_budget||0} 推演节点${p.budget_exhausted?' · 已截断':''}${e?' · 视野评分 '+e.projected_total_us.toFixed(2)+' μs':''} · ${d.selected_features?.disposition==='return'?'归还':'驻留'}`;}
 return '当前实际服务成本';
}
function resumedExecutionText(next){
 if(next.compile_timing_scope!=='suffix_only')return '';
 const p=next.provenance?.resume||{},show=v=>v===null||v===undefined?'未记录':String(v);
 const elapsed=typeof p.parent_observed_elapsed_seconds==='number'?p.parent_observed_elapsed_seconds.toFixed(2)+' s':'未记录';
 return `前缀 ${show(p.prefix_completed_gates)} 个门/控制槽、${show(p.prefix_plans)} 个计划，来源 ${p.parent_output||'未记录'}；前缀检查点观察耗时 ${elapsed}（不代表完整成功编译耗时），前次尝试分类 ${p.classification||'未记录'}。完整动画含前缀与后缀；候选与服务日志仅含后缀。`;
}
function resumedCompileSummary(next,serviceCount){
 if(next.compile_timing_scope!=='suffix_only')return '';
 const seconds=typeof next.compile_seconds==='number'?next.compile_seconds.toFixed(2)+' s':'未记录';
 return `后缀续编译 ${seconds} · 后缀 ${serviceCount} 个服务段 · `+resumedExecutionText(next);
}
function axisDecision(d){
 if(d.strategy==='zoned_ids'&&d.placements)return d.placements.map(p=>escape(p.gate_id)+': '+escape(p.anchor)+' 驻留 '+escape(p.site)+'；抓取 '+escape(p.mobile)+' → ('+p.x+', '+p.y+') μm').join('<br>');
 if(!d.pickup||!d.target)return '见回放实际行列坐标';
 const axis=c=>'x ['+c.x_um.join(', ')+']; y ['+c.y_um.join(', ')+']';
 return escape('抓取 '+axis(d.pickup))+'<br>'+escape('作用 '+axis(d.target))+'<br><button data-axis-time="'+d.start_us+'">查看本批过程</button>';
}
$('greedy-rows').onclick=e=>{const button=e.target.closest('[data-axis-time]');if(button&&viewer){viewer.setTime(Number(button.dataset.axisTime));$('viewer').scrollIntoView({behavior:'smooth',block:'start'});}};
function renderDecisions(next){const allEntries=next.decision_log||[],reuse=allEntries.find(d=>d.kind==='reuse_summary'),entries=allEntries.filter(d=>d.kind!=='reuse_summary');$('greedy-decisions').hidden=!entries.length&&next.input?.compiler!=='qmap_native';if(!entries.length&&next.input?.compiler!=='qmap_native')return;
 const slots=entries.reduce((n,d)=>n+(d.raman_slots?.length??d.raman_count??0),0),count=entries.reduce((n,d)=>n+(d.candidates?.length??d.readout_search?.candidates?.length??d.candidate_count??0),0);
 $('greedy-summary').textContent=`${policyNames[next.input?.compiler]||'调度'} · ${next.input?.aod_backend||'rigid'} · 编译 ${(next.compile_seconds||0).toFixed(2)} s · ${entries.length} 个服务段 · ${count} 个候选 · 补充 ${slots} 个 Raman 时隙`;
 if(next.input?.compiler==='qmap_native'){const t=next.diagnostics?.find(x=>x.strategy==='qmap_native');if(t)$('greedy-summary').textContent='作者 C++ 内核 '+t.native_compile_seconds.toFixed(4)+' s · 前端进程（含导入） '+t.frontend_process_seconds.toFixed(2)+' s · 本地物理适配/执行/记录 '+t.physical_adapter_execute_record_seconds.toFixed(2)+' s · CZ '+t.author_metrics.cz_layers+' 层 / 最多 '+t.author_metrics.max_parallel_cz+' 门并行';}
 if(reuse)$('greedy-summary').textContent=`${policyNames[next.input?.compiler]} · 历史编译 ${(next.compile_seconds||0).toFixed(2)} s · ${entries.length} 个服务段 · 实际复用 ${reuse.reuse_count} 次 · 释放 ${reuse.flush_count} 次`;
 if(next.compile_timing_scope==='suffix_only')$('greedy-summary').textContent=(policyNames[next.input?.compiler]||'调度')+' · '+resumedCompileSummary(next,entries.length);
 if(next.input?.compiler==='qec_joint'&&reuse)$('greedy-summary').textContent+=' · AOD 读出 '+reuse.loaded_readout_visits+' 次 · 读出服务节省 '+reuse.readout_saved_us.toFixed(2)+' μs';
 $('decision-raw').textContent=JSON.stringify(allEntries,null,2);
 $('greedy-rows').innerHTML=entries.map(d=>`<tr><td>${d.decision+1}</td><td>${d.start_us.toFixed(2)} μs</td><td>${escape(d.selected==='explicit-terminal'?'统一终态归还':d.selected||d.kind||'实际服务')}</td><td>${d.duration_us.toFixed(2)} μs</td><td>${escape(decisionReason(d))}</td><td>${d.candidates?.length??d.readout_search?.candidates?.length??d.candidate_count??0}${d.truncated?'（截断 '+d.truncated+'）':''}</td><td>${axisDecision(d)}</td><td>${(d.ez_changes||[]).map(c=>escape(c.site)+' '+(c.enabled?'开启':'关闭')).join('<br>')||'见实际操作'}</td><td>${(d.raman_slots||[]).map(s=>escape(s.gate_id)+' @ '+s.start_us.toFixed(2)+'–'+s.end_us.toFixed(2)).join('<br>')||(d.kind==='raman'&&next.input?.compiler==='qec_joint'?d.batch_size+' 门 / 1 个原生批次':d.raman_count?d.raman_count+' 个时隙':'—')}</td></tr>`).join('');}
function change(mutator){if(locked()){toast('当前实验已锁定，请切回自定义工作区。');return;}history.push(clone(draft));if(history.length>60)history.shift();future=[];mutator();selected=null;pending=null;edited()}
function edited(){revision++;inputValid=false;$('compile').disabled=true;syncCompilation(draft);toast();$('diagnostics').hidden=true;$('revision').textContent='DRAFT '+revision;render();markStale();
 if(placementJob)api('/api/placement/'+placementJob+'/cancel',{}).catch(()=>{});
 if(placementReport)$('placement-result-label').textContent='草稿已修改：下方是旧版本对照，请重新优化。';
 if(job){const old=job;job=null;api('/api/jobs/'+old+'/cancel',{}).catch(()=>{});}$('cancel').disabled=true;
 status('idle','草稿已更新',`版本 ${revision} · 点击线路区的编译按钮生成动画`);
 updatePreview(revision);
}
function mount(recording){if(viewer)viewer.destroy();viewer=window.NeutralAtomViewer.mount($('viewer'),recording,{compact:true,...(nativeQmap()?{gridStepUm:10,showCandidateSites:false}:{})})}
async function updatePreview(rev){if(previewController)previewController.abort();previewController=new AbortController();try{
 const p=await api('/api/preview',clone(draft),previewController.signal);if(rev!==revision)return;
 inputValid=true;
 if(p.input?.compilation_backend){draft.compilation_backend=p.input.compilation_backend;draft.compiler=p.input.compiler;renderConfiguration();}
 const scene=p.recording.scene,b=scene.bounds,w=b.upper.x_um-b.lower.x_um,h=b.upper.y_um-b.lower.y_um;
 const scale=Math.min(230/w,155/h),X=x=>20+(x-b.lower.x_um)*scale,Y=y=>14+(b.upper.y_um-y)*scale;
 const svg=$('layout-preview');svg.setAttribute('viewBox','0 0 275 185');
 svg.innerHTML=scene.zones.map((z,i)=>`<rect x="${X(z.bounds.lower.x_um)}" y="${Y(z.bounds.upper.y_um)}" width="${(z.bounds.upper.x_um-z.bounds.lower.x_um)*scale}" height="${(z.bounds.upper.y_um-z.bounds.lower.y_um)*scale}" fill="${['#e4efe6','#eee7de','#e7eaf2'][i]}"/><text x="${X(z.bounds.upper.x_um)-2}" y="${Y(z.bounds.lower.y_um)-2}" text-anchor="end" font-size="8" fill="#6c8075">${['SZ','EZ','MZ'][i]}</text>`).join('')+
 scene.traps.filter(t=>t.enabled!==false).map(t=>`<circle cx="${X(t.position.x_um)}" cy="${Y(t.position.y_um)}" r="${t.enabled===false?2:3.8}" fill="none" stroke="${t.enabled===false?'#c6cfc9':'#93a3b0'}"><title>${t.id} ${t.enabled===false?'关闭的候选位置':'初始开启'}</title></circle>`).join('')+
 p.recording.frames[0].atom_updates.map(a=>`<circle cx="${X(a.position.x_um)}" cy="${Y(a.position.y_um)}" r="2.5" fill="#5364bc"><title>${a.id}: ${a.position.x_um}, ${a.position.y_um} μm</title></circle>`).join('');
 $('layout-caption').textContent=`${draft.atom_count} 原子 · ${draft.layout} · seed ${draft.seed} · 单位 μm`;
 if(!result){mount(p.recording);$('playback-revision').textContent='初始预览 · '+rev;}
 }catch(e){if(e.name!=='AbortError'&&rev===revision){inputValid=false;$('compile').disabled=true;toast(e.message);$('layout-caption').textContent='当前输入无有效预览';}}
}
function render(){
 if(!availableTypes().includes(tool))tool='H';
 const shape=draft.aod_rows?[draft.aod_rows,draft.aod_columns]:draft.qec_enabled?[7,14]:draft.aod_traps?[1,draft.aod_traps]:draft.layout==='surface_patches'?[6,6]:[1,1];
 $('aod-capacity').textContent=shape[0]+' × '+shape[1]+' = '+(shape[0]*shape[1])+' 个交点';$('aod-rows').value=shape[0];$('aod-columns').value=shape[1];
 for(const [id,key,count] of [['aod-row-offsets','aod_row_offsets_um',shape[0]],['aod-column-offsets','aod_column_offsets_um',shape[1]]]){
  const offsets=draft[key]||(draft.qec_enabled?(key==='aod_row_offsets_um'?Array.from({length:count},(_,i)=>i*5):Array.from({length:count},(_,i)=>i*5+(i>=7?5:0))):null)||(draft.layout==='surface_patches'&&count===6?[0,10,20,40,50,60]:Array.from({length:count},(_,i)=>i*(shape[0]*shape[1]===1?5:10)));
  $(id).value=offsets.join(', ');
 }
 $('ez-neighbor-guard').checked=draft.ez_neighbor_guard_enabled??true;
 $('atom-count').value=draft.atom_count;$('layout').innerHTML=nativeQmap()?'<option value="qmap_paired">QMAP 成对 SLM · 作者初态</option>':locked()?'<option value="'+escape(draft.layout)+'">'+escape(draft.layout)+' · 配套布局</option>':'<option value="row">单行排列</option><option value="grid">紧凑网格</option><option value="shuffled">网格 + 随机映射</option>';$('layout').value=draft.layout;$('seed').value=draft.seed;$('anchor-order').value=draft.anchor_order;renderConfiguration();
 $('ez-policy').value=draft.ez_policy||'pair';$('max-decisions').value=draft.max_decisions||10000;
 $('compile-timeout').value=draft.compile_timeout_s??'';

 const rowMode=['row_symmetric','row_greedy','patch_symmetric','patch_greedy','qec_ghz2','qec_persistent','qec_joint','qec_temporal','qec_temporal_four'].includes(draft.compiler);
 for(const [id,key,fallback] of [['ready-limit','ready_limit',16],['site-limit','site_limit',4],['lookahead-depth','lookahead_depth',2],['beam-width','beam_width',3],['rollout-budget','rollout_budget',12]]){$(id).value=draft[key]||fallback;$(id).disabled=!policyNames[draft.compiler]||rowMode;}
 $('row-controls').hidden=!rowMode;$('row-candidate-budget').value=draft.row_candidate_budget||4096;$('route-expansions').value=draft.route_expansions||100000;
 $('geometry-note').textContent=draft.qec_enabled?'按实际 AOD 几何构造分组运输；只使用当前协议支持的调度实现。':draft.compiler?.startsWith('patch_')?'二维实验需 AOD 行列覆盖所选原子组；具体捕获和并行门均由物理后端检查。':ordered()?'有序轴：按实际布局与 AOD 容量拆分捕获；行列可非均匀，活动交点均校验。':'旧通用策略受其原有平台能力限制。';
 $('lookahead-controls').hidden=draft.compiler!=='lookahead';
 for(const id of ['ready-limit','site-limit'])$(id).parentElement.hidden=['returning','resident'].includes(draft.compiler)||ordered();
 $('max-decisions').disabled=locked()||!draft.compiler||draft.compiler==='legacy';
 $('anchor-order').disabled=Boolean(draft.compiler&&draft.compiler!=='legacy');
 $('palette').innerHTML=availableTypes().map(t=>`<button type="button" draggable="true" data-tool="${t}" aria-pressed="${tool===t}" title="放置 ${t}">${t}</button>`).join('');
 columns=Math.min(MAX_COLUMNS,Math.max(columns,...draft.gates.map(g=>g.column+2),8));
 page=Math.max(0,Math.min(page,Math.floor((columns-1)/PAGE_SIZE)));
 const first=page*PAGE_SIZE,last=Math.min(columns,first+PAGE_SIZE),visible=last-first;
 const occupied=new Map();for(const g of draft.gates)for(const q of g.qubit_ids)occupied.set(q+':'+g.column,g);
 const circuit=$('circuit');circuit.style.width=(70+58*visible)+'px';
 let html='<div class="columns">'+Array.from({length:visible},(_,c)=>`<span>${String(first+c+1).padStart(2,'0')}</span>`).join('')+'</div>';
 for(let q=0;q<draft.atom_count;q++){
  html+=`<div class="wire"><span class="wire-label">${qid(q)}${roleOf(qid(q))?'<small style="display:block;font-size:9px">'+roleOf(qid(q))+'</small>':''}</span>`;
  for(let c=first;c<last;c++){const g=occupied.get(qid(q)+':'+c),active=pending?.q===q&&pending?.column===c;
   html+=`<button class="cell ${g?'gate '+(g.gate_type==='CZ'?'':'single'):'empty'} ${g?.id===selected?'selected':''} ${active?'pending':''}" data-q="${q}" data-column="${c}" ${g?`data-gate="${g.id}"`:''} aria-label="${qid(q)} 第 ${c+1} 列${g?' '+escape(g.id+' '+g.gate_type):' 空位'}" title="${g?escape(g.id+' '+g.gate_type+' '+g.parameters.join(', ')+(g.readout_flip?' · 报告位翻转':'')):'点击放置 '+tool}">${g?escape(g.gate_type)+(g.readout_flip?' ↯':''):''}</button>`;
  }html+='</div>';
 }
 for(const g of draft.gates.filter(g=>g.gate_type==='CZ'&&g.column>=first&&g.column<last)){const qs=g.qubit_ids.map(q=>Number(q.slice(1)));html+=`<div class="connector" style="left:${70+(g.column-first)*58+28}px;top:${28+Math.min(...qs)*48+24}px;height:${Math.abs(qs[1]-qs[0])*48}px"></div>`;}
 circuit.innerHTML=html;$('circuit-count').textContent=`${draft.atom_count} 条线路 · ${draft.gates.length} / ${MAX_GATES} 门 · ${columns} 列`;
 $('page-info').textContent=`显示 ${first+1}–${last} 列`;$('column-jump').value=first+1;
 $('previous-page').disabled=page===0;$('next-page').disabled=last>=columns;
 $('undo').disabled=!history.length;$('redo').disabled=!future.length;$('add-column').disabled=columns>=MAX_COLUMNS;
 $('hint').textContent=pending?`CZ：已选 ${qid(pending.q)}，请点击第 ${pending.column+1} 列的另一条线路。Esc 取消。`:`当前工具 ${tool} · 点击空位放置，点击已有门编辑。CZ 在同一列选两个原子；列不代表物理并行。`;
 renderDetails();renderMode();
}
function gateExecution(id){return result?.recording.operations.find(o=>(o.gate_id===id||o.gate_ids?.includes(id))&&['entangling_pulse','raman_rotation','measurement','reset'].includes(o.kind));}
function renderDetails(){const g=draft.gates.find(g=>g.id===selected);$('gate-details').hidden=!g;if(!g)return;
 $('readout-flip-control').hidden=g.gate_type!=='MEASURE';$('edit-readout-flip').checked=g.readout_flip===true;
 const readoutMeta=draft.qec_protocol?.readouts?.find(r=>r.gate_id===g.id);
 $('readout-flip-note').textContent='仅翻转报告位，真实量子投影不变；点击应用修改后生效。'+(readoutMeta?' 当前轮：'+readoutMeta.round+'。':'')+(isTemporal()?' 三个噪声轮仅支持声明的单事件；闭合轮须完美，改写后可能超出纠错范围。':'');
 $('selected-title').textContent=`${g.id} / ${g.gate_type}`;
 $('gate-condition').textContent=(g.condition?.length?'条件：'+g.condition.map(([id,bit])=>id+' = '+bit).join(' AND ')+'；不满足时只消耗控制时隙。 ':'')+(g.depends_on?.length?'显式依赖：'+g.depends_on.join(', ')+'。':'')+' 条件和依赖可通过线路 JSON 编辑。';
 const wireOptions=q=>Array.from({length:draft.atom_count},(_,i)=>`<option ${q===qid(i)?'selected':''}>${qid(i)}</option>`).join('');
 $('gate-fields').innerHTML=`<label>列（1–${MAX_COLUMNS}）<input id="edit-column" type="number" min="1" max="${MAX_COLUMNS}" value="${g.column+1}"></label>`+g.qubit_ids.map((q,i)=>`<label>操作数 ${i+1}<select id="edit-q${i}">${wireOptions(q)}</select></label>`).join('')+g.parameters.map((p,i)=>`<label class="wide">${g.parameters.length===3?['θ / rad','φ / rad','λ / rad'][i]:'角度 / rad'}<input type="number" step="any" id="edit-p${i}" value="${p}"></label>`).join('');
 $('seek-gate').disabled=resultRevision!==revision||!gateExecution(g.id);
 for(const el of $('gate-fields').querySelectorAll('input,select'))el.disabled=locked();
 $('apply-gate').disabled=$('delete-gate').disabled=$('edit-readout-flip').disabled=locked();
}
function newId(){let i=0;while(draft.gates.some(g=>g.id==='G'+String(i).padStart(3,'0')))i++;return 'G'+String(i).padStart(3,'0')}
function place(q,column){const existing=draft.gates.find(g=>g.column===column&&g.qubit_ids.includes(qid(q)));if(existing){selected=existing.id;pending=null;render();return;}
 if(locked())return;
 if(draft.gates.length>=MAX_GATES){toast(`最多 ${MAX_GATES} 门，请先删除部分门。`);return;}
 if(tool==='CZ'&&!pending){pending={q,column};render();return;}
 if(tool==='CZ'&&(pending.column!==column||pending.q===q)){toast('CZ 需要同一列的两个不同原子。');return;}
 const qubits=tool==='CZ'?[qid(pending.q),qid(q)]:[qid(q)];
 const parameters=[];
 const g={id:newId(),gate_type:tool,qubit_ids:qubits,parameters,column};change(()=>draft.gates.push(g));selected=g.id;renderDetails();
}
$('palette').onclick=e=>{const b=e.target.closest('[data-tool]');if(b){tool=b.dataset.tool;pending=null;render();}};
$('palette').ondragstart=e=>{const b=e.target.closest('[data-tool]');if(b)e.dataTransfer.setData('text/plain',b.dataset.tool);};
$('circuit').onclick=e=>{const b=e.target.closest('[data-q]');if(b)place(Number(b.dataset.q),Number(b.dataset.column));};
$('circuit').ondragover=e=>{if(e.target.closest('[data-q]'))e.preventDefault();};
$('circuit').ondrop=e=>{e.preventDefault();const t=e.dataTransfer.getData('text/plain'),b=e.target.closest('[data-q]');if(b&&availableTypes().includes(t)){tool=t;pending=null;place(Number(b.dataset.q),Number(b.dataset.column));}};
document.addEventListener('keydown',e=>{if(e.key==='Escape'){pending=null;selected=null;render();}});
$('deselect').onclick=()=>{selected=null;renderDetails();};
$('delete-gate').onclick=()=>change(()=>{draft.gates=draft.gates.filter(g=>g.id!==selected);});
$('apply-gate').onclick=()=>{const old=draft.gates.find(g=>g.id===selected),g=clone(old);g.column=Number($('edit-column').value)-1;g.qubit_ids=g.qubit_ids.map((_,i)=>$('edit-q'+i).value);g.parameters=g.parameters.map((_,i)=>$('edit-p'+i).value.trim()===''?NaN:Number($('edit-p'+i).value));
 if(g.gate_type==='MEASURE'&&($('edit-readout-flip').checked||Object.hasOwn(g,'readout_flip')))g.readout_flip=$('edit-readout-flip').checked;
 if(!Number.isInteger(g.column)||g.column<0||g.column>=MAX_COLUMNS||new Set(g.qubit_ids).size!==g.qubit_ids.length||g.parameters.some(p=>!Number.isFinite(p))){toast('请填写有效列、不同操作数和有限角度。');return;}
 if(draft.gates.some(x=>x.id!==g.id&&x.column===g.column&&x.qubit_ids.some(q=>g.qubit_ids.includes(q)))){toast('目标位置已有门，请换列或原子。');return;}
 change(()=>{draft.gates=draft.gates.map(x=>x.id===g.id?g:x);page=Math.floor(g.column/PAGE_SIZE);});selected=g.id;renderDetails();};
$('seek-gate').onclick=()=>{if(resultRevision!==revision)return;const op=gateExecution(selected);if(op){viewer.setTime((op.start+op.end)/2);viewer.selectAtom(draft.gates.find(g=>g.id===selected).qubit_ids[0]);$('viewer').scrollIntoView({behavior:'smooth',block:'start'});}};
$('undo').onclick=()=>{if(history.length){future.push(clone(draft));draft=history.pop();selected=null;pending=null;edited();}};
$('redo').onclick=()=>{if(future.length){history.push(clone(draft));draft=future.pop();selected=null;pending=null;edited();}};
$('clear').onclick=()=>change(()=>{draft.gates=[];});
$('add-column').onclick=()=>{columns=Math.min(MAX_COLUMNS,columns+4);page=Math.floor((columns-1)/PAGE_SIZE);pending=null;render();};
$('previous-page').onclick=()=>{page--;pending=null;render();};
$('next-page').onclick=()=>{page++;pending=null;render();};
$('column-jump').onchange=()=>{const c=Number($('column-jump').value);if(!Number.isInteger(c)||c<1||c>MAX_COLUMNS){render();toast(`列须为 1–${MAX_COLUMNS} 整数。`);return;}columns=Math.max(columns,c);page=Math.floor((c-1)/PAGE_SIZE);pending=null;render();};
function randomGates(atomCount){
 const count=Math.min(12,Math.max(4,atomCount*2)),pick=n=>Math.floor(Math.random()*n);
 const singles=draft.qec_enabled?['H','X','Y','Z']:['H','X','Y','Z','T'];
 return Array.from({length:count},(_,column)=>{
  // Include an allowed 1Q and, with >=2 atoms, at least one real CZ candidate.
  const kind=column===0?'H':atomCount>1&&(column===1||Math.random()<.3)?'CZ':singles[pick(singles.length)];
  const first=pick(atomCount),qubits=[qid(first)];
  if(kind==='CZ'){const other=pick(atomCount-1);qubits.push(qid(other>=first?other+1:other));}
  return {id:'G'+String(column).padStart(3,'0'),gate_type:kind,qubit_ids:qubits,
          parameters:[],column};
 });
}
$('random-circuit').onclick=()=>{
 const gates=randomGates(draft.atom_count);
 change(()=>{draft.gates=gates;if(draft.qec_enabled)draft.qec_fault=null;});
 $('preset').value='';
 $('hint').textContent=`已随机载入 ${gates.length} 门 · 可继续编辑，或撤销恢复上一条线路。`;
};
for(const [id,key] of [['atom-count','atom_count'],['seed','seed'],['layout','layout'],['anchor-order','anchor_order'],['ez-policy','ez_policy'],['max-decisions','max_decisions'],['ready-limit','ready_limit'],['site-limit','site_limit'],['lookahead-depth','lookahead_depth'],['beam-width','beam_width'],['rollout-budget','rollout_budget'],['compile-timeout','compile_timeout_s'],['row-candidate-budget','row_candidate_budget'],['route-expansions','route_expansions']])$(id).onchange=()=>{
 if(key==='layout'&&$('layout').value.startsWith('surface_qec_')&&$('layout').value!==draft.layout){render();toast('QEC patch 数与协议相关，请从线路模板载入对应初态。');return;}
 if(key==='compile_timeout_s'&&$(id).value.trim()===''){change(()=>{delete draft.compilation[key];delete draft[key];});return;}
 const value=['layout','anchor_order','compiler','ez_policy'].includes(key)?$(id).value:Number($(id).value);
 const limits={ready_limit:128,site_limit:128,lookahead_depth:8,beam_width:32,rollout_budget:4096,aod_traps:128,compile_timeout_s:86400,row_candidate_budget:65536,route_expansions:1000000};
 if(limits[key]&&(!Number.isInteger(value)||value<1||value>limits[key])){render();toast('搜索参数超出允许范围。');return;}
 if(key==='max_decisions'&&(!Number.isInteger(value)||value<1||value>10000)){render();toast('决策预算须为 1–10000 整数。');return;}
 if((key==='atom_count'&&(!Number.isInteger(value)||value<1||value>MAX_ATOMS))||(key==='seed'&&(!Number.isInteger(value)||value<0||value>2147483647))){render();toast('输入超出允许范围。');return;}
 if(key==='atom_count'&&draft.gates.some(g=>g.qubit_ids.some(q=>Number(q.slice(1))>=value))){render();toast('减少原子前，请删除或重定向引用这些原子的门。');return;}
 if(key==='atom_count'&&draft.layout==='surface_patches'&&value!==36){render();toast('四个 3×3 patch 需要 36 原子；其他数量请切换布局。');return;}
 if(key==='layout'&&value==='surface_patches'&&draft.gates.some(g=>g.qubit_ids.some(q=>Number(q.slice(1))>=36))){render();toast('切换到 36 原子 patch 前，请删除或重定向超出 Q035 的门。');return;}
 change(()=>{draft[key]=value;if(budgetKeys.includes(key))draft.compilation[key]=value;if(key==='aod_traps'){delete draft.aod_rows;delete draft.aod_columns;delete draft.aod_row_offsets_um;delete draft.aod_column_offsets_um;}
  if(key==='layout'&&value==='surface_patches'){draft.atom_count=36;draft.aod_rows=6;draft.aod_columns=6;draft.aod_row_offsets_um=[0,10,20,40,50,60];draft.aod_column_offsets_um=[0,10,20,40,50,60];delete draft.aod_traps;}
 });};
for(const [id,key] of [['aod-rows','aod_rows'],['aod-columns','aod_columns']])$(id).onchange=()=>{
 const rows=Number($('aod-rows').value),cols=Number($('aod-columns').value);
 if(!Number.isInteger(rows)||!Number.isInteger(cols)||rows<1||cols<1||rows*cols>128){render();toast('AOD 行列须为正整数，总容量不超过 128。');return;}
 change(()=>{draft.aod_rows=rows;draft.aod_columns=cols;delete draft.aod_traps;
  if(draft.aod_row_offsets_um?.length!==rows)delete draft.aod_row_offsets_um;
  if(draft.aod_column_offsets_um?.length!==cols)delete draft.aod_column_offsets_um;
 });
};
for(const [id,key,countId] of [['aod-row-offsets','aod_row_offsets_um','aod-rows'],['aod-column-offsets','aod_column_offsets_um','aod-columns']])$(id).onchange=()=>{
 const raw=$(id).value.trim(),values=raw?raw.split(/[,，\s]+/).map(Number):[];
 if(values.length!==Number($(countId).value)||values[0]!==0||values.some((x,i)=>!Number.isFinite(x)||(i>0&&x<=values[i-1]))){render();toast('行列偏移需从 0 开始严格递增，数量与行列数一致。');return;}
 change(()=>{draft[key]=values;});
};
$('ez-neighbor-guard').onchange=()=>{const enabled=$('ez-neighbor-guard').checked;change(()=>{draft.ez_neighbor_guard_enabled=enabled;});};
$('preset').onchange=()=>{const kind=$('preset').value;if(!kind||locked())return;try{const gates=studioModel.circuitPreset(kind,draft.atom_count);change(()=>{draft.gates=gates;columns=8;page=0;});$('preset').value='';}catch(e){toast(e.message);}};
function renderQecResult(report){
 $('qec-result').hidden=!report;if(!report)return;
 const temporal=Object.hasOwn(report,'history_supported')||Object.hasOwn(report,'reported_measurement_results');
 const four=Object.hasOwn(report,'verified_logical_ghz4'),verified=four?report.verified_logical_ghz4:report.verified_logical_ghz2,logicalName=four?'GHZ₄':'GHZ₂';
 $('qec-result-status').textContent=verified===true?'PASS · 实际终态满足逻辑 '+logicalName+' 与码稳定子':verified===false?'FAIL · 当前编辑线路的实际终态未通过逻辑 '+logicalName+' 校验':'执行未完成 · 尚无最终逻辑判定';
 $('qec-result-status').textContent+='；测量协议 '+(report.measurement_protocol_complete===true?'完整':report.measurement_protocol_complete===false?'不完整':'未核验');
 if(temporal)$('qec-result-status').textContent+='；'+(four?'128':'64')+' 位报告历史 '+(report.history_complete===true?'齐全':'未齐全')+' / '+(report.history_supported===true?'译码支持':report.history_supported===false?'不受支持':'未判定');
 $('qec-result-raw').textContent=JSON.stringify(report,null,2);
 const observables=four?'逻辑 XXXX = '+(report.logical_xxxx??'未知')+'；逻辑 ZZ '+['AB','BC','CD'].map(pair=>pair+' = '+(report.logical_zz_pairs?.[pair]??'未知')).join('；'):'逻辑 XX = '+(report.logical_xx??'未知')+'；逻辑 ZZ = '+(report.logical_zz??'未知');
 $('qec-logical').textContent=observables+'。'+(temporal?'三噪声轮＋完美闭合轮，仅支持声明的单数据或单报告位事件；真实投影和报告位分开记录，译码仅使用报告历史。不是任意多故障或门内噪声容错。':'理想投影测量、完美读出模型；不代表通用电路噪声下容错。');
 if(temporal){
  const reported=report.reported_measurement_results||{},truth=report.true_measurement_results||{};
  $('qec-syndromes').innerHTML='<h3>实际提交的测量：'+Object.keys(reported).length+' 位报告 / 协议预期 '+(four?160:80)+' 位</h3><p>下表是已执行结果汇总；动画侧栏按回放时间逐步显示读出。</p><div style="max-height:300px;overflow:auto"><table><thead><tr><th>测量门</th><th>真实投影位</th><th>报告位</th><th>差异</th></tr></thead><tbody>'+Object.entries(reported).map(([id,bit])=>'<tr><td>'+escape(id)+'</td><td>'+escape(truth[id]??'未记录')+'</td><td>'+escape(bit)+'</td><td>'+(truth[id]===undefined?'未知':truth[id]===bit?'一致':'报告翻转')+'</td></tr>').join('')+'</tbody></table></div>';
 }else $('qec-syndromes').innerHTML='<h3>已提交的 syndrome 读出</h3><div style="display:flex;gap:8px;flex-wrap:wrap">'+Object.entries(report.syndrome_bits||{}).map(([id,bit])=>'<span class="tag">'+escape(id)+' = '+escape(bit)+'</span>').join('')+'</div>';
 const corrections=report.corrections;
 $('qec-corrections').textContent=(Array.isArray(corrections)?'实际触发的条件纠错 '+corrections.length+' 项：'+corrections.map(c=>c.gate_type+'('+c.qubit_ids.join(', ')+')').join('、'):'未提供实际条件纠错执行摘要')+(temporal?'；历史译码建议见完整记录，不将建议视为实际执行。':'');
}
function acceptResult(next,rev,value,id){
 $('saved-provenance').hidden=!next.provenance;
 if(next.provenance)$('saved-provenance').textContent='保存的真实执行结果 · 未发起新编译。实际策略 '+next.provenance.actual_strategy+'；原参考输入标记 '+next.provenance.source_input_compiler+'。保存时验收状态：'+next.provenance.acceptance_status+'；已保存的独立物理重放：'+next.provenance.compiler_free_replay+'。修改后点击编译会执行当前草稿。';
 if(next.provenance&&next.compile_timing_scope==='suffix_only')$('saved-provenance').textContent+=' '+resumedExecutionText(next);
 result=next;resultRevision=rev;mount(next.recording);renderDecisions(next);renderQecResult(next.qec_result);$('viewer').classList.remove('stale');$('playback-revision').textContent='版本 '+rev+ (next.status==='completed'?' · 已完成':' · 部分执行');$('playback-note').textContent=(next.recording.summary.overlapping?'实际并行执行 · 同类型门并行与运输共享时间轴':'物理执行')+' · 动画、门参数与时序统计来自同一份已提交事件';$('export-replay').disabled=false;
 const m=next.recording.summary.metrics;status(next.status==='completed'?'completed':'failed',next.status==='completed'?'编译完成 · 动画已更新':'编译停滞 · 已保留实际执行片段',`${m.completed_gate_count} / ${value.gates.length} 门 · 总耗时 ${next.recording.duration.toFixed(3)} μs · ${next.recording.operations.length} 个物理操作`,1);
 if(next.status==='stalled'){$('diagnostics').hidden=false;$('diagnostics').textContent=JSON.stringify(next.diagnostics,null,2);showFailure(next.failure_report||{...next.diagnostics[0],phase:'candidate_search'},value,{job_id:id,diagnostics:next.diagnostics,candidate_rejections:next.candidate_rejections,decision_log:next.decision_log,recording:next.recording});}renderDetails();
}
async function compile(){if(job||placementJob||$('compile').disabled||workspaceMode()==='history')return;if(placementEnabled())return compilePlacement();$('placement-comparison').hidden=true;placementReport=null;$('placement-panel').hidden=true;$('compile').disabled=true;const rev=revision,value=clone(syncCompilation(draft));$('diagnostics').hidden=true;toast();status('compiling','正在编译当前线路',`版本 ${rev} · 准备物理输入…`);$('cancel').disabled=false;
 // Serialize starts so a late response cannot replace a newer job on the local server.
 const start=startQueue.then(async()=>{if(rev!==revision)return null;const started=await api('/api/compile',value);if(rev!==revision){await api('/api/jobs/'+started.id+'/cancel',{});return null;}return started.id;});startQueue=start.catch(()=>{});
 try{const id=await start;if(!id)return;job=id;while(rev===revision&&job===id){const state=await api('/api/jobs/'+id);if(rev!==revision||job!==id)return;
  if(state.status==='compiling'){const p=state.progress;status('compiling',`正在编译 · ${p.completed_gates} / ${p.total_gates} 门完成`,`版本 ${rev} · 已用 ${state.elapsed_seconds.toFixed(1)} / ${state.timeout_seconds??90} 秒 · 仿真 ${(p.simulation_time_us||0).toFixed(2)} μs`,p.completed_gates/(p.total_gates||1));await sleep(350);continue;}
  if(state.status==='completed'||state.status==='stalled'){const next=await api('/api/jobs/'+id+'/result');if(rev!==revision||job!==id)return;acceptResult(next,rev,value,id);
  }else if(state.status==='cancelled'){status('idle','本次编译已取消','保留当前草稿，可重新编译。');}
  else{status('failed','编译失败',state.error?.message||'未知错误');$('diagnostics').hidden=false;$('diagnostics').textContent=JSON.stringify(state.error,null,2);showFailure({...state,phase:'worker'},value,{job_id:id});}
  job=null;$('cancel').disabled=true;return;
 }}catch(e){if(rev===revision){status('failed','编译请求失败',e.message);$('cancel').disabled=true;job=null;showFailure({phase:'request',message:e.message},value);}}finally{if(rev===revision){$('compile').disabled=false;renderPlacementControls();}}
}
$('compile').onclick=compile;
$('cancel').onclick=()=>{if(placementJob){if(placementJob!=='starting')api('/api/placement/'+placementJob+'/cancel',{}).catch(e=>toast(e.message));$('placement-status').textContent='正在停止：等待当前批次退出，不再开始后续候选。';return;}$('compile').disabled=false;revision++;$('revision').textContent='DRAFT '+revision;markStale();const old=job;job=null;if(old)api('/api/jobs/'+old+'/cancel',{}).catch(e=>toast(e.message));$('cancel').disabled=true;status('idle','编译已取消','草稿已保留，点击编译可再次运行。');};
function download(name,body,type){const url=URL.createObjectURL(new Blob([body],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}
$('export-input').onclick=()=>download('atom-circuit.json',JSON.stringify(draft,null,2),'application/json');
$('import-input').onclick=()=>$('import-file').click();
$('import-file').onchange=async()=>{const file=$('import-file').files[0];if(!file)return;const rev=revision;try{if(file.size>2*1024*1024)throw Error('线路文件不能超过 2 MiB');const parsed=JSON.parse(await file.text()),valid=await api('/api/preview',parsed);if(rev!==revision)throw Error('导入期间草稿已变化，请再次导入。');replaceWorkspace(valid.input);}catch(e){toast('导入失败：'+e.message);}finally{$('import-file').value='';}};
$('export-replay').onclick=async()=>{const saved=result,rev=resultRevision;if(!saved)return;try{const response=await fetch('/atom-viewer.js');if(!response.ok)throw Error('读取回放组件失败');const bundle=await response.text(),payload=JSON.stringify(saved.input?.compiler==='qmap_native'?{...saved.recording,scene:{...saved.recording.scene,display_grid_step_um:10,show_candidate_sites:false}}:saved.recording).replace(/</g,'\\u003c');
 const html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Atom Studio replay</title><body style="margin:20px;background:#f3f6f3"><p>版本 '+rev+' · '+escape(saved.status)+' · 只读编译回放</p><div id="viewer"></div><script>'+bundle.replace(/<\/script/gi,'<\\/script')+'</'+'script><script>NeutralAtomViewer.mount(document.getElementById("viewer"),'+payload+');</'+'script></body></html>';
 download('atom-replay-v'+rev+'.html',html,'text/html');}catch(e){toast(e.message);}};
window.addEventListener('beforeunload',()=>{if(placementJob&&placementJob!=='starting')fetch('/api/placement/'+placementJob+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});if(job)fetch('/api/jobs/'+job+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});});
async function openInitialLink(){
 const search=window.location?.search||'';
 if(!search){edited();return;}
 const params=new URLSearchParams(search),id=params.get('job'),example=params.get('example');
 if(!id&&!example){edited();return;}
 // Reading a saved result or a large example must never start a new compile.
 edited();const rev=revision;$('compile').disabled=true;
 status('idle','正在载入链接','当前草稿保留；链接载入后可编辑并手动编译。');
 try{
  let next,value;
  if(id){
   if(!/^[a-f0-9]{32}$/.test(id))throw Error('无效的编译任务标识。');
   const saved=await api('/api/jobs/'+id);
   if(!['completed','stalled'].includes(saved.status))throw Error('该任务尚无可用回放：'+saved.status);
   next=await api('/api/jobs/'+id+'/result');
   if(!['completed','stalled'].includes(next.status))throw Error('该任务没有完成的执行记录。');
   const valid=await api('/api/preview',next.input);value=valid.input;
  }else{
   if(!studioCatalog.demos.some(d=>d.id===example))throw Error('未知示例。');
   value=await api('/api/studio/demos/'+example);
  }
  if(rev!==revision)return;
  replaceWorkspace(value);
  if(next)acceptResult(next,revision,value,id);
  else status('idle','锁定 demo 已载入',value.atom_count+' 原子；配套配置固定，点击编译开始真实物理执行。');
 }catch(e){if(rev===revision){toast('链接载入失败：'+e.message);status('failed','链接载入失败',e.message+' 当前草稿已保留。');}}
 finally{$('compile').disabled=!inputValid||workspaceMode()==='history'||Boolean(draft.compilation_backend?.configuration_error);}
}

function placementSettings(){return {enabled:Boolean(draft.placement_search),proposal_pool:256,evaluations:16,workers:4,terminal_mode:'stable',expand_storage:true,...draft.placement_search};}
function placementEnabled(){return !locked()&&ordered()&&!draft.qec_enabled&&placementSettings().enabled;}
$('compile-mode').onchange=()=>{const enabled=$('compile-mode').value==='optimize';change(()=>{draft.placement_search={...placementSettings(),enabled};});};
function renderPlacementControls(){
 const o=placementSettings(),eligible=!locked()&&ordered()&&!draft.qec_enabled;
 $('compile-mode').value=placementEnabled()?'optimize':'fixed';$('compile-mode').disabled=!eligible||Boolean(job)||Boolean(placementJob);
 $('compile-mode').options[0].textContent=nativeQmap()?'作者初态与动态落点':'固定初态';
 $('compile').textContent=placementEnabled()?'编译：优化初态并生成动画 ↗':'编译并生成动画 ↗';
 $('placement-panel').hidden=!$('configuration-workspace').hidden||replayFocused||!(placementReport||placementJob);
 $('placement-search-options').hidden=!eligible;
 $('placement-eligibility').textContent=eligible?'当前 '+(policyNames[draft.compiler]||draft.compiler)+' · 基线使用你选定的初态；优化只更改原子的初始站点。':'仅适用于自定义物理线路 + 当前有序轴贪心 / SMT；专用协议保持原配置。';
 for(const [id,key] of [['placement-pool','proposal_pool'],['placement-evaluations','evaluations'],['placement-workers','workers'],['placement-terminal','terminal_mode']]){$(id).value=o[key];$(id).disabled=!eligible;}
 $('placement-expand').checked=o.expand_storage;$('placement-expand').disabled=!eligible;
 $('placement-search-summary').textContent=`搜索配置 · 候选池 ${o.proposal_pool} / 评估 ${o.evaluations} / ${o.workers} 进程`;
 for(const name of ['baseline','optimized'])$('placement-'+name).disabled=placementRevision!==revision;
}
for(const [id,key] of [['placement-pool','proposal_pool'],['placement-evaluations','evaluations'],['placement-workers','workers'],['placement-terminal','terminal_mode'],['placement-expand','expand_storage']])$(id).onchange=()=>{
 const value=key==='terminal_mode'?$(id).value:key==='expand_storage'?$(id).checked:Number($(id).value);
 change(()=>{draft.placement_search={...placementSettings(),[key]:value};});
};
function placementMap(target,mapping){
 const sites=placementReport.candidate_sites,bySite=new Map(mapping.map(([q,s])=>[s,q]));
 const xs=sites.map(s=>s.x_um),ys=sites.map(s=>s.y_um),minX=Math.min(...xs),minY=Math.min(...ys),dx=Math.max(...xs)-minX,dy=Math.max(...ys)-minY;
 const scale=Math.min(400/Math.max(dx,10),210/Math.max(dy,10)),w=70+dx*scale,h=65+dy*scale;
 $(target).innerHTML=`<svg viewBox="0 0 ${w} ${h}" style="width:100%;height:260px" role="img" aria-label="原子初态格点布局">`+sites.map(s=>{const q=bySite.get(s.id),x=35+(s.x_um-minX)*scale,y=25+(s.y_um-minY)*scale;return `<g><title>${escape(s.id)} (${s.x_um}, ${s.y_um}) μm ${q||'空位'}</title><circle cx="${x}" cy="${y}" r="${q?5:2}" fill="${q?'#5364bc':'none'}" stroke="${q?'#5364bc':'#c4cfca'}" ${q?'':'stroke-dasharray="2 2"'}/>${q?`<text x="${x}" y="${y+15}" text-anchor="middle" font-size="9">${escape(q)}</text>`:''}</g>`;}).join('')+'</svg>';
}
function showPlacementReplay(which){
 if(!placementReport||placementRevision!==revision)return;
 const r=placementReport,recording=r.recordings[which];
 acceptResult({status:'completed',input:r.input,recording,diagnostics:[],decision_log:[],compile_seconds:r.wall_seconds},revision,r.input,'placement');
 $('playback-revision').textContent=(which==='baseline'?'当前布局基线':'优化布局')+' · 版本 '+revision;
 $('playback-note').textContent=(r.options.terminal_mode==='stable'?'不追加原 layout 归还；保留每批 CZ 收尾。':'恢复共同终态。')+' 初态为已准备状态，未计装配时间。';
 for(const name of ['baseline','optimized'])$('placement-'+name).setAttribute('aria-pressed',String(name===which));
}
function acceptPlacement(r,id){
 placementReport=r;placementRevision=revision;$('placement-comparison').hidden=false;
 $('placement-result-label').textContent=`${r.input.atom_count} 原子 · ${r.input.gates.length} 门 · ${r.trials.length} 次评估（${r.trials.filter(t=>t.valid).length} 个有效） · ${r.options.workers} 编译进程 · ${r.improvement_percent>0?'物理完成时间下降 '+r.improvement_percent.toFixed(2)+'%':'预算内无更快候选，保留基线'}`;
 placementMap('placement-baseline-map',r.baseline.mapping);placementMap('placement-optimized-map',r.selected.mapping);
 const a=r.recordings.baseline,b=r.recordings.optimized,ma=a.summary.metrics,mb=b.summary.metrics;
 $('placement-metrics').textContent=`物理完成时间 ${a.duration.toFixed(3)} → ${b.duration.toFixed(3)} μs；装载 ${ma.aod_load_count} → ${mb.aod_load_count} 批；原子总路程 ${ma.total_atom_distance_um.toFixed(1)} → ${mb.total_atom_distance_um.toFixed(1)} μm。`;
 $('placement-trials').textContent=r.trials.map(t=>`${t.index===0?'基线':t.index} · ${t.origin} · ${t.valid?t.time_us.toFixed(3)+' μs':t.failure}`).join('\n');
 $('placement-status').textContent=`完成 · 基线与选中结果的物理校验、独立重放通过 · 搜索及录制 ${r.wall_seconds.toFixed(1)} 秒`;
 historyReplacePlacement(id);renderPlacementControls();showPlacementReplay('optimized');
}
function historyReplacePlacement(id){window.history.replaceState(null,'','/?placement='+encodeURIComponent(id));}
$('placement-baseline').onclick=()=>showPlacementReplay('baseline');$('placement-optimized').onclick=()=>showPlacementReplay('optimized');
$('placement-initial').onclick=()=>viewer?.setTime(0);$('placement-end').onclick=()=>viewer?.setTime(result?.recording.duration||0);
$('placement-report').onclick=()=>{if(placementReport)download('placement-comparison.json',JSON.stringify(placementReport,null,2),'application/json');};
async function compilePlacement(){
 if(!inputValid||!placementEnabled()||placementJob||job)return;
 const rev=revision,value=clone(syncCompilation(draft));value.placement_search=placementSettings();placementJob='starting';renderPlacementControls();$('compile').disabled=true;$('cancel').disabled=true;
 $('placement-status').textContent='正在准备当前线路与布局基线…';status('compiling','正在优化当前线路初态','各候选独立编译；进度见下方初态优化区。');
 try{
  const started=await api('/api/placement',value),{id}=started;placementJob=id;$('cancel').disabled=false;
  if(rev!==revision)await api('/api/placement/'+id+'/cancel',{});
  while(true){const state=await api('/api/placement/'+id),p=state.progress||{};
   $('placement-status').textContent=state.status==='cancelling'?'正在停止，等待当前批次退出…':p.trial!==undefined?`已评估 ${p.trial}/${p.budget} · ${p.valid?p.time_us.toFixed(3)+' μs':'候选失败，原因已记录'}`:p.message||state.status;
   if(['running','cancelling'].includes(state.status)){status('compiling',state.status==='cancelling'?'正在停止初态搜索':p.phase==='recording'?'生成已验证计划的回放':p.trial?'并行评估候选布局':'编译当前布局基线',$('placement-status').textContent,p.trial?(p.trial/p.budget):0);await sleep(600);continue;}
   if(state.status==='completed'&&rev===revision){const r=await api('/api/placement/'+id+'/result');if(rev===revision){acceptPlacement(r,id);if(started.reused){$('placement-status').textContent='复用同输入、同配置的已验证结果；本次没有重新编译。';status('completed','已复用编译结果','输入和配置未变化，直接载入两份已验证动画。',1);}}}
   else if(state.status==='failed'){
    const r=await api('/api/placement/'+id+'/result').catch(()=>null),message=state.error||r?.trials?.filter(t=>!t.valid).map(t=>t.failure).join('\n')||'没有完整有效的基线与优化结果';
    $('placement-status').textContent='优化失败：'+message;status('failed','初态搜索失败',message);showFailure({phase:'initial_placement',message},value,{job_id:id,comparison:r});
   }else {$('placement-status').textContent='已停止；保留当前草稿。';status('idle','初态搜索已停止','保留当前草稿与旧回放。');}
   break;
  }
 }catch(e){$('placement-status').textContent='优化失败：'+e.message;status('failed','初态搜索失败',e.message);showFailure({phase:'initial_placement',message:e.message},value);}
 finally{placementJob=null;$('cancel').disabled=true;renderConfiguration();}
};
async function openPlacementLink(){
 const id=new URLSearchParams(window.location.search).get('placement');
 if(!id){openInitialLink();return;}
 edited();const rev=revision;
 try{if(!/^[a-f0-9]{32}$/.test(id))throw Error('无效的初态搜索任务编号');const r=await api('/api/placement/'+id+'/result');if(rev!==revision)return;if(r.status!=='completed')throw Error('该搜索未完成');replaceWorkspace(r.input);acceptPlacement(r,id);}
 catch(e){toast(e.message);}
}
openPlacementLink();

})();

}