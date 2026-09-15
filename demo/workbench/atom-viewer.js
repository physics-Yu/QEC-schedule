// Dependency-free, container-scoped atom motion viewer. Source generated with a shared shell.
(function(scope){
'use strict';
const SHELL="<style>\n:host{color-scheme:light;--ink:#25334b;--muted:#78869c;--line:#e6eaf1;--orange:#e89438;--blue:#5364bc;--red:#d95360}\n*{box-sizing:border-box}:host{margin:0;background:#f4f6fa;color:var(--ink);font:14px/1.5 system-ui,-apple-system,\"Segoe UI\",sans-serif}\nbutton,select,input{font:inherit}button,select{border:1px solid var(--line);background:white;color:var(--ink);border-radius:9px;padding:8px 12px;cursor:pointer}button:hover,select:hover{border-color:#a9b4cc}button:focus-visible,select:focus-visible,input:focus-visible{outline:2px solid var(--blue);outline-offset:3px}button:disabled{opacity:.4;cursor:default}\n.shell{max-width:1600px;margin:auto;padding:26px 32px}.eyebrow{color:var(--blue);font-size:10px;font-weight:750;letter-spacing:2px}header{display:flex;align-items:center;justify-content:space-between;gap:20px;margin-bottom:22px}h1{font-size:25px;letter-spacing:-.7px;margin:4px 0}p{margin:8px 0}.muted{color:var(--muted);font-size:12px}.badge{font-size:11px;border:1px solid var(--line);padding:6px 10px;border-radius:20px;background:white}.workspace{display:grid;grid-template-columns:minmax(0,1fr) 310px;gap:18px}.panel{background:white;border:1px solid var(--line);border-radius:17px;overflow:hidden;box-shadow:0 5px 25px #25334b04}.tools{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:12px 18px}.tools label{font-size:12px;display:inline-flex;gap:5px;align-items:center}.tools select{font-size:12px;padding:6px}.tools input{accent-color:var(--blue)}.spacer{flex:1}.canvas-wrap{height:clamp(480px,68vh,850px);position:relative;background:#fafbfd}canvas{display:block;width:100%;height:100%;touch-action:none;cursor:grab}canvas.dragging{cursor:grabbing}.view-tools{position:absolute;right:16px;bottom:16px;display:flex;gap:5px}.view-tools button{box-shadow:0 2px 8px #25334b08}.view-hint{position:absolute;left:18px;bottom:18px;font-size:10px;color:var(--muted);pointer-events:none}.legend{display:flex;flex-wrap:wrap;gap:12px 20px;padding:14px 18px;font-size:11px;border-top:1px solid var(--line);align-items:center}.symbol{display:inline-block;width:8px;height:8px;background:var(--blue);margin-right:7px;vertical-align:middle}.circle{border-radius:50%}.diamond{transform:rotate(45deg);width:7px;height:7px}.ring{border:2px solid var(--orange);border-radius:50%;background:none;width:14px;height:14px}.swatch{width:7px;height:7px;border-radius:50%;display:inline-block;margin-right:5px}.aside{padding:20px}.aside h2{font-size:10px;letter-spacing:1.5px;color:var(--muted);margin:0 0 12px}.time{font-size:31px;font-variant-numeric:tabular-nums;letter-spacing:-1px}.time small{font-size:13px;color:var(--muted);letter-spacing:0}.rule{height:1px;background:var(--line);margin:21px 0}.gate{font-size:15px;font-weight:650}.status{font-size:11px;color:var(--blue);margin-top:6px}.atom-list{max-height:260px;overflow:auto;display:grid;gap:6px;margin-top:14px}.atom-row{display:flex;align-items:center;width:100%;gap:10px;text-align:left;border-color:transparent;background:#f7f9fc;padding:10px}.atom-row[aria-pressed=true]{border-color:#a4b0e3;background:#eef1fb}.atom-row span:last-child{margin-left:auto;color:var(--muted);font-size:10px}.details{background:#f7f9fc;border-radius:11px;padding:13px;margin-top:14px;font-size:12px;min-height:116px}.details dl{display:grid;grid-template-columns:65px 1fr;gap:7px;margin:0}.details dt{color:var(--muted)}.details dd{margin:0;overflow-wrap:anywhere}.transport{margin-top:18px;padding:18px 22px}.controls{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.primary{background:var(--blue);color:white;border-color:var(--blue);min-width:85px}.readout{font-size:12px;color:var(--muted);font-variant-numeric:tabular-nums}.scrub{width:100%;accent-color:var(--blue);margin:20px 0 13px}.stages{display:grid;grid-template-columns:repeat(auto-fit,minmax(125px,1fr));gap:6px}.stage{padding:9px 5px;text-align:left;font-size:10px;background:#f7f9fc;border-color:transparent;border-top:3px solid #b5bfd9}.stage[data-kind=aod_move]{border-top-color:var(--orange)}.stage[data-kind=entangling_pulse]{border-top-color:var(--red)}.stage[aria-current=true]{background:#edf0fb;box-shadow:inset 0 0 0 1px #aab5e4}.stage strong,.stage span{display:block}.stage strong{overflow-wrap:anywhere}.stage span{white-space:nowrap}.stage span{color:var(--muted);font-size:9px;margin-top:5px}.footer{margin-top:13px;font-size:11px;color:var(--muted)}\n.operation-strip{display:flex;gap:16px;align-items:center;padding:14px 18px;border-bottom:1px solid var(--line);background:linear-gradient(110deg,#fff,#f7f9fc)}.operation-copy{flex:1;min-width:0}.operation-title{font-size:15px;font-weight:650}.operation-caption{font-size:11px;color:var(--muted);margin-top:3px;overflow-wrap:anywhere}.operation-meter{width:100px;flex-shrink:0;text-align:right;font-size:11px;color:var(--muted)}.meter-track{height:4px;background:#e6eaf1;border-radius:4px;margin-top:7px;overflow:hidden}.meter-fill{height:100%;width:0;background:var(--orange)}.mode-note{margin:12px 0 0;font-size:11px;color:var(--muted)}.controls label{display:inline-flex;align-items:center;gap:5px}.stage em{display:block;font-size:9px;font-style:normal;color:var(--blue);margin-top:3px}\n@media(max-width:980px){.workspace{grid-template-columns:1fr}.aside{display:grid;grid-template-columns:1fr 1fr;gap:18px}.aside .rule{display:none}.atom-list{margin:0}.details{margin-top:10px}.shell{padding:16px}.stages{grid-template-columns:repeat(3,1fr)}.canvas-wrap{height:600px}}@media(max-width:540px){.aside{display:block}.aside>div{margin-bottom:18px}header .badge{display:none}.canvas-wrap{height:500px}.view-hint{display:none}.tools{gap:8px}.shell{padding:10px}}\n.display-options{width:100%}.display-options>summary{cursor:pointer;font-weight:650;list-style-position:inside;display:flex;align-items:center;gap:12px}.display-options>summary::before{content:'▸';color:var(--muted)}.display-options[open]>summary::before{content:'▾'}.display-options>summary .muted{margin-left:auto;font-weight:400}.display-groups{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:18px}.display-groups fieldset{border:1px solid var(--line);border-radius:10px;padding:12px;min-width:0;display:flex;flex-direction:column;gap:10px}.display-groups legend{font-size:11px;color:var(--muted);padding:0 5px}.display-groups p{font-size:10px;line-height:1.6;margin:0}.display-options>p{font-size:10px;margin:12px 0 0}@media(max-width:650px){.display-groups{grid-template-columns:1fr}.display-options>summary{font-size:12px}}\n\n.transport{position:sticky;top:8px;z-index:20;margin:0 0 16px;padding:12px 18px;box-shadow:0 4px 16px #25334b10}.playback-status{margin:0 0 8px;font-size:12px;font-weight:650;color:var(--blue)}.transport .scrub{margin:12px 0 2px;height:20px;cursor:pointer}.transport .mode-note{margin-top:8px}.operation-details{margin-top:16px;padding:16px}.canvas-wrap{height:clamp(420px,55vh,650px)}canvas:focus-visible{outline:2px solid var(--blue);outline-offset:-2px}.transport .controls{gap:7px}.transport .mode-note{font-size:10px}@media(max-width:980px){.canvas-wrap{height:480px}.transport{top:0}}@media(max-width:540px){.transport{position:static;padding:12px}.canvas-wrap{height:420px}}\n\n.secondary-controls{margin-top:7px}.shell.compact{padding:16px 24px}.shell.compact>header{display:none}.shell.compact .canvas-wrap{height:clamp(320px,44vh,520px)}.shell.compact .transport{margin-bottom:12px}.shell.compact .mode-note{margin-top:5px}.shell.compact .operation-caption{max-height:48px;overflow:auto}.shell.compact .operation-strip{padding:10px 18px}@media(max-width:540px){.shell.compact{padding:10px}.shell.compact .canvas-wrap{height:360px}}\n</style><div class=\"shell\">\n<header><div><div class=\"eyebrow\">NEUTRAL ATOM LAB / MOTION VIEW</div><h1>原子运动可视化</h1><p class=\"muted\" id=\"backend-caption\"></p></div><span class=\"badge\">事件轨迹 / μm · μs</span></header>\n<section class=\"panel transport\" id=\"playback-controls\"><p class=\"playback-status\" id=\"playback-status\" role=\"status\"></p><div class=\"controls\"><button class=\"primary\" id=\"play\">播放</button><label class=\"muted\">模式 <select aria-label=\"回放模式\" id=\"mode\"><option selected=\"\" value=\"keyframe\">关键帧演示</option><option value=\"physical\">真实时间比例</option></select></label><button id=\"previous\">上一事件</button><button id=\"next\">下一事件</button><label class=\"muted\">速度 <select aria-label=\"播放速度\" id=\"speed\"><option value=\"0.25\">0.25×</option><option selected=\"\" value=\"1\">1×</option><option value=\"2\">2×</option><option value=\"4\">4×</option><option value=\"8\">8×</option><option value=\"16\">16×</option><option value=\"32\">32×</option></select></label><span class=\"spacer\"></span><span class=\"readout\" id=\"readout\"></span></div><div class=\"controls secondary-controls\"><button id=\"pulse\">下一门操作</button><button hidden=\"\" id=\"joint\">查看联合运输</button><button id=\"reset\">回到起点</button><button id=\"end\">到终点</button><label class=\"muted\">跳到 <input aria-label=\"跳转到仿真时间\" id=\"seek-time\" min=\"0\" step=\"any\" style=\"width:110px\" type=\"number\"/> μs</label><button id=\"seek-time-button\">跳转</button><span class=\"muted\" id=\"seek-error\" role=\"alert\"></span></div><p class=\"mode-note\" id=\"mode-note\"></p><input aria-label=\"仿真时间\" class=\"scrub\" id=\"slider\" min=\"0\" step=\"0.01\" type=\"range\"/></section><div class=\"workspace\"><section class=\"panel\">\n<div class=\"tools\"><details class=\"display-options\" id=\"display-options\"><summary>画布显示 <span class=\"muted\" id=\"display-summary\"></span></summary><div class=\"display-groups\">\n<fieldset><legend>布局与陷阱</legend><label><input checked=\"\" id=\"zones\" type=\"checkbox\"/>区域底色与名称</label><label><input checked=\"\" id=\"grid\" type=\"checkbox\"/>坐标网格</label><label><input checked=\"\" id=\"slm\" type=\"checkbox\"/>SLM trap 标记</label><label><input checked=\"\" id=\"slm-empty\" type=\"checkbox\"/>显示空 SLM</label><label><input checked=\"\" id=\"slm-off\" type=\"checkbox\"/>显示关闭 SLM（淡点）</label><label><input checked=\"\" id=\"aod\" type=\"checkbox\"/>AOD trap 标记</label></fieldset>\n<fieldset><legend>编号与轨迹</legend><label>原子编号 <select aria-label=\"原子编号显示\" id=\"labels\"><option value=\"focus\">悬停 / 选中</option><option value=\"all\">全部显示</option><option value=\"none\">全部隐藏</option></select></label><label><input checked=\"\" id=\"planned-path\" type=\"checkbox\"/>计划去程与途经点</label><label><input id=\"trails\" type=\"checkbox\"/>选中原子的历史轨迹</label></fieldset>\n<fieldset><legend>动效与安全边界</legend><label><input checked=\"\" id=\"effects\" type=\"checkbox\"/>抓取 / 卸载 / 门动效</label><label><input id=\"clearance\" type=\"checkbox\"/>SLM 中心排斥边界</label><p class=\"muted\">灰蓝实线环是 trap 位置标记；虚线边界按 μm 绘制，与 trap 同心，表示运输时的安全距离，不是另一光斑。</p></fieldset>\n</div><p class=\"muted\" id=\"spacing-readout\"></p><p class=\"muted\">显示开关只改变画布。隐藏 trap 或安全边界不会关闭 backend 的间距检查；SLM 装卸端点的受限对齐例外单独验证。</p><p class=\"muted\" id=\"route-caption\" style=\"margin:10px 18px\"></p></details></div>\n<div class=\"operation-strip\"><div class=\"operation-copy\"><div class=\"operation-title\" id=\"operation-title\"></div><div class=\"operation-caption\" id=\"operation-caption\"></div></div><div class=\"operation-meter\"><span id=\"operation-progress\"></span><div class=\"meter-track\"><div class=\"meter-fill\" id=\"operation-fill\"></div></div></div></div>\n<div class=\"canvas-wrap\" id=\"viewport\"><canvas aria-label=\"处理器布局；拖动平移、Ctrl+滚轮缩放、点击原子；聚焦画布后空格播放或暂停，左右键逐事件\" id=\"canvas\" tabindex=\"0\"></canvas><div class=\"view-hint\">拖动平移 · Ctrl+滚轮缩放 · 点击原子 · 空格播放/暂停</div><div class=\"view-tools\"><button aria-label=\"缩小\" id=\"zoomout\">−</button><button aria-label=\"放大\" id=\"zoomin\">＋</button><button id=\"fit-atoms\">聚焦原子</button><button id=\"fit\">全景</button></div></div>\n<div class=\"legend\"><span><i class=\"symbol ring\" style=\"border-color:#8190a3\"></i>开启 SLM</span><span><i class=\"swatch\" style=\"background:#bac4d1;width:4px;height:4px\"></i>关闭 SLM</span><span><i class=\"symbol ring\"></i>AOD trap</span><span><i class=\"symbol circle\"></i>SLM 原子</span><span><i class=\"symbol diamond\"></i>AOD 原子</span><span><i class=\"swatch\" style=\"background:var(--blue)\"></i>空闲</span><span><i class=\"swatch\" style=\"background:var(--orange)\"></i>移动</span><span><i class=\"swatch\" style=\"background:var(--red)\"></i>门 / 测量</span></div></section>\n<aside class=\"panel aside\"><div><h2>SIMULATION TIME</h2><div class=\"time\"><span id=\"clock\">0.00</span> <small>μs</small></div><p class=\"muted\" id=\"version\"></p><div class=\"rule\"></div><h2>LOGICAL FRONTIER</h2><div class=\"gate\" id=\"gate\"></div><div class=\"status\" id=\"status\"></div><p class=\"muted\" id=\"event\"></p><p class=\"muted\" id=\"frontier\"></p><p class=\"muted\" id=\"gate-states\"></p><p class=\"muted\" hidden=\"\" id=\"measurement-readout\" style=\"max-height:160px;overflow:auto\"></p></div><div><div class=\"rule\"></div><h2>ATOM INSPECTOR</h2><input aria-label=\"搜索原子\" id=\"atom-search\" placeholder=\"搜索 Q 编号\" style=\"width:100%;box-sizing:border-box\"/><div class=\"atom-list\" id=\"atoms\"></div><div class=\"controls\"><button id=\"atoms-prev\">上一页</button><span id=\"atoms-page\"></span><button id=\"atoms-next\">下一页</button></div><div class=\"details\" id=\"details\">点击画布或列表中的原子，查看位置、承载 trap 和当前操作。</div></div></aside></div><details class=\"panel operation-details\"><summary>操作详情（按需查看）</summary><div class=\"controls\"><button id=\"stages-prev\">上一组</button><span id=\"stages-page\"></span><button id=\"stages-next\">下一组</button></div><div class=\"stages\" id=\"stages\"></div></details><details class=\"panel\" style=\"padding:16px;margin-bottom:18px\"><summary>主要指标与时间占用</summary><div id=\"summary\"></div></details>\n<p class=\"footer\">橙色圆环表示离散 AOD trap；灰蓝圆环表示开启 SLM，淡灰小点表示关闭 SLM；空 SLM 和关闭 SLM 可分别隐藏。标记大小仅用于辨识，不代表实际光腰或作用半径。<span id=\"motion-note\"></span>虚线路线为所选原子本周期截至门操作前的运输路径（未选择时显示首个被搬运的门操作数）；实际回程以回放为准。SLM 中心排斥边界是同心的几何约束，不代表实际光场；源 trap 装卸端点有受限豁免。交接形变、收拢弧线和门连线是操作示意，不表示光场、量子态或原子额外位移；承载关系以侧栏已提交状态为准。</p>\n</div>";
const mounted=new WeakMap();
function upperBound(items,value,key){let lo=0,hi=items.length;while(lo<hi){const mid=(lo+hi)>>>1;if(items[mid][key]<=value)lo=mid+1;else hi=mid}return lo}
function decodeFrames(data){
 if(data.format!=='neutral-atom-view/2')throw new Error('Unsupported visualization format');
 const checkpoints=new Map(),cache=new Map(),working=new Map();
 const masks=[];let enabled=null;data.frames.forEach(f=>{if(f.slm_enabled!==null)enabled=f.slm_enabled;if(!enabled)throw new Error("Missing initial SLM mask");masks.push(enabled)});
 data.frames.forEach((frame,i)=>{for(const a of frame.atom_updates)working.set(a.id,a);if(i%64===0)checkpoints.set(i,new Map(working))});
 function sceneAt(i){
   if(cache.has(i))return cache.get(i);
   const start=Math.floor(i/64)*64,atoms=new Map(checkpoints.get(start));
   for(let j=start+1;j<=i;j++)for(const a of data.frames[j].atom_updates)atoms.set(a.id,a);
   const scene={...data.scene,traps:data.scene.traps.map(t=>({...t,enabled:masks[i][t.id]})),atoms:[...atoms.values()]};cache.set(i,scene);if(cache.size>4)cache.delete(cache.keys().next().value);return scene;
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
 const chartBottom=78+summary.categories.length*40,chartHeight=chartBottom+17;
 const ticks=Array.from({length:6},(_,i)=>{const time=start+(end-start)*i/5,x=X(time);return `<line x1="${x}" x2="${x}" y1="72" y2="${chartBottom}" stroke="#e6eaf1"/><text x="${x}" y="63" text-anchor="middle" fill="#78869c">${format(time)}</text>`}).join('');
 const intervals=summary.schedule||operations;
 const bars=intervals.map(interval=>{
   const i=summary.categories.findIndex(r=>r.key===interval.category);if(i<0)return '';
   const r=summary.categories[i],x=X(interval.start),actualWidth=X(interval.end)-x;
   const candidate=operations.find(o=>o.category===interval.category&&o.start<=interval.start&&o.end>=interval.end);
   const op=candidate&&interval.start<candidate.end?candidate:null;
   const label=`${op?.gate_id||''} ${r.label} · ${format(interval.start)}–${format(interval.end)} μs · ${(interval.end-interval.start).toFixed(3)} μs${op?' · '+op.label:''}`;
   return `<g><rect class="schedule-segment" data-start="${interval.start}" data-end="${interval.end}" data-category="${interval.category}" x="${x}" y="${88+i*40}" width="${Math.max(actualWidth,2)}" height="20" fill="${r.color}" stroke="white" stroke-width=".5" role="button" tabindex="0" aria-label="${esc(label)}"><title>${esc(label)}</title></rect>${interval.category==='pulse'&&op?`<text x="${x}" y="${85+i*40}" text-anchor="middle" fill="${r.color}" font-size="10">${esc(op.gate_id)}</text>`:''}</g>`;
 }).join('');
 const resourceRows=[['AOD_0','AOD 运输 / 交接'],['RAMAN_0','Raman（旧记录）'],...Object.keys(summary.resource_busy_us||{}).filter(id=>id.startsWith('RAMAN:')).sort().map(id=>[id,'Raman '+id.slice(6)]),['ENTANGLING_LASER_0','CZ 激光'],...Object.keys(summary.resource_busy_us||{}).filter(id=>!id.startsWith('RAMAN:')&&!['RAMAN_0','AOD_0','ENTANGLING_LASER_0'].includes(id)).sort().map(id=>[id,id.startsWith('MEASUREMENT')?'测量 '+id:id.startsWith('RESET')?'复位 '+id:id.startsWith('CONTROL')?'条件控制 '+id:id])].filter(([id])=>id in (summary.resource_busy_us||{}));
 const resourceMarkup=resourceRows.length?`<div style="overflow-x:auto"><svg id="resource-schedule" viewBox="0 0 1100 ${60+40*resourceRows.length}" style="width:100%;min-width:780px;font:13px system-ui;fill:#25334b" aria-label="实际资源占用区间"><text x="4" y="22" font-weight="600">资源时间 / μs</text>${resourceRows.map(([id,label],i)=>`<text x="4" y="${55+i*40}">${label}</text><text x="1085" y="${55+i*40}" text-anchor="end">${format(summary.resource_busy_us[id])} μs · ${(100*summary.resource_busy_us[id]/span).toFixed(2)}%</text>${operations.filter(o=>o.resources?.includes(id)).map(o=>`<rect class="schedule-segment" data-start="${o.start}" data-end="${o.end}" data-category="${o.category}" x="${X(o.start)}" y="${40+i*40}" width="${Math.max(2,X(o.end)-X(o.start))}" height="20" fill="${id.startsWith('RAMAN')?'#9a65bc':id==='ENTANGLING_LASER_0'?'#d95360':'#5364bc'}" role="button" tabindex="0"><title>${esc(id+' · '+(o.gate_id||o.task_id||'')+' '+o.label)} · ${format(o.start)}–${format(o.end)} μs</title></rect>`).join('')}`).join('')}</svg></div>`:'';
 return `${resourceMarkup}<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:16px;margin:18px 0">${cards}</div><div style="overflow-x:auto"><svg id="schedule" viewBox="0 0 1100 ${chartHeight}" style="display:block;width:100%;min-width:780px;font:13px system-ui;fill:#25334b" role="group" aria-label="操作时序表，横轴为真实仿真时间"><text x="4" y="26" font-weight="600">操作类别</text><text x="150" y="26" font-weight="600">操作时序 / μs →</text><text x="1085" y="26" text-anchor="end" font-weight="600">累计时间 · 占比</text>${rows}${ticks}${bars}<line id="schedule-playhead" x1="150" x2="150" y1="72" y2="${chartBottom}" stroke="#25334b" stroke-width="1.3" stroke-dasharray="4 3" pointer-events="none"/></svg></div><p id="schedule-current" class="muted"></p><p class="muted">横轴始终为真实仿真时间；同类操作按发生时间分段排列。点击色块跳转，悬停查看起止时间；短脉冲最小显示为 2 px 标记，真实时长不变。虚线与运动回放同步，右列保留累计占用。${summary.overlapping?'并行类别可以重叠，占比之和可超过 100%；各资源按区间并集计时。':''}</p>`;
}
function mount(container,recording,options={}){
if(!recording?.frames?.length)throw new Error('Visualization requires at least one recorded frame');
mounted.get(container)?.destroy();

const data=recording, frames=decodeFrames(data), theme=data.theme;
const hasMeasurements=data.frames.some(frame=>frame.quantum_tracking===true);
const root=container.shadowRoot||container.attachShadow({mode:'open'});
root.innerHTML=SHELL;
if(options.compact)root.querySelector('.shell').classList.add('compact');
const $=id=>root.getElementById(id), canvas=$('canvas'), ctx=canvas.getContext('2d');
const TRAP_RADIUS=7;
const view={zoom:1,panX:0,panY:0}, ui={time:data.start_time||0,mode:'keyframe',playing:false,selected:null,hover:null};
let width=0,height=0,last=null,displayTime=null,hits=[],drag=null,current=null,disposed=false,raf=null;
let atomPage=0,stagePage=-1,atomQuery="",visibleAtoms=[],visibleOperations=[];
const ATOM_PAGE=32,STAGE_PAGE=12;
const names={controlling:'条件控制（未打光）',resetting:'复位',idle:'空闲',moving:'移动',gating:'门操作',measuring:'测量',lost:'丢失'};
const statuses={blocked:'依赖未满足',failed:'失败',pending:'等待',ready:'就绪',reserved:'已预约',running:'执行中',completed:'已完成'};
const labels={'Load anchor in SZ':'在 SZ 装载原子 a','Transport anchor to EZ':'将 a 运送至 EZ','Park anchor in EZ SLM':'将 a 卸载到 EZ 的 SLM','Load partner in SZ':'在 SZ 装载原子 b','Transport partner to CZ':'将 b 运到 a 旁边','Return partner to SZ':'将 b 运回 SZ','Offload partner in SZ':'在 SZ 卸载 b','Pick up anchor from EZ':'从 EZ 的 SLM 接回 a','Return anchor to SZ':'将 a 运回 SZ','Offload anchor in SZ':'在 SZ 卸载 a','Empty reposition':'空 AOD 定位','Joint load in SZ':'SZ 联合装载','Joint transport to EZ':'共同运输至 EZ','Park operand in EZ SLM':'目标原子转交 EZ 的 SLM','Local approach to parked operand':'局部靠近静态目标','Restore joint transport configuration':'恢复共同运输构型','Recapture parked operand':'从 SLM 重新接回目标','Joint return to SZ':'共同返回 SZ','Joint offload in SZ':'SZ 联合卸载','Depart source':'脱离源 trap','Approach offload':'接近卸载 trap','Corridor transport':'格间通道运输','Return corridor':'沿通道返回','Idle':'等待 / 空闲','Load':'装载','Escape':'脱离 SLM','Lateral alignment':'横向对齐','Transport to interaction':'前往作用位','CZ pulse':'CZ 作用','Reconfigure axes':'阵列伸缩','Return / approach':'返回 / 接近','Offload':'卸载','Empty reposition to source':'空载前往源原子','Empty return to initial pose':'空载返回起始位'};
const escapeHTML=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
// Presentation time is a monotone mapping of simulation time, never a state edit.
const clamp=(v,lo,hi)=>Math.max(lo,Math.min(hi,v));
const smooth=u=>u*u*(3-2*u);
const US_PER_MS=.025; // Physical proportion: 1x = 25 simulation microseconds / screen second.
// Only presentation boundaries are grouped; recorded physical times stay intact.
const timeTolerance=(a,b)=>16*Number.EPSILON*Math.max(1,Math.abs(a),Math.abs(b));
let presentationEnd=0;
const timelineOperations=[];
let cursor=data.start_time||0;
for(const op of data.operations){if(op.start-cursor>timeTolerance(op.start,cursor))timelineOperations.push({index:-1,kind:'idle',label:'Idle',start:cursor,end:op.start,captured:[]});timelineOperations.push(op);cursor=Math.max(cursor,op.end)}
if(data.duration-cursor>timeTolerance(cursor,data.duration))timelineOperations.push({index:-1,kind:'idle',label:'Idle',start:cursor,end:data.duration,captured:[]});
const segments=timelineOperations.map(op=>{
    const milliseconds=['aod_load','aod_recapture'].includes(op.kind)?1800:['aod_offload','aod_park'].includes(op.kind)?1600:
        ['entangling_pulse','raman_rotation','measurement','reset'].includes(op.kind)?1800:clamp((op.end-op.start)/US_PER_MS,800,2200);
    const segment={...op,displayStart:presentationEnd,displayEnd:presentationEnd+milliseconds};
    presentationEnd=segment.displayEnd;
    return segment;
});
const parallel=Boolean(data.summary?.overlapping);
const timeSlices=[];
if(parallel){
 const rawPoints=[...new Set([data.start_time||0,data.duration,...data.operations.flatMap(o=>[o.start,o.end])])].sort((a,b)=>a-b);
 const points=[];
 for(const point of rawPoints){if(points.length&&point-points.at(-1)<=timeTolerance(point,points.at(-1)))points[points.length-1]=point;else points.push(point)}
 presentationEnd=0;
 for(let i=1;i<points.length;i++){
  const start=points[i-1],end=points[i],active=data.operations.filter(o=>o.start<=start+timeTolerance(o.start,start)&&o.end>=end-timeTolerance(o.end,end));
  const pulse=active.some(o=>['raman_rotation','entangling_pulse','measurement','reset'].includes(o.kind));
  const span=pulse?1800:clamp((end-start)/US_PER_MS,800,2200);
  timeSlices.push({start,end,displayStart:presentationEnd,displayEnd:presentationEnd+span});presentationEnd+=span;
 }
 for(const op of segments){op.displayStart=displayAt(op.start);op.displayEnd=displayAt(op.end)}
}
let activeCacheTime=null,activeCache=[];
function operationsAt(time){if(time!==activeCacheTime){activeCacheTime=time;activeCache=data.operations.filter(o=>o.start<=time&&time<o.end)}return activeCache}
function operationAt(time){if(parallel){const active=segments.filter(o=>o.start<=time&&time<o.end);return active.find(o=>['raman_rotation','entangling_pulse','measurement','reset'].includes(o.kind))||active[0]||null}const i=upperBound(segments,time,'start')-1;const op=segments[i];return op&&time<op.end?op:null}
function displayAt(time){
    const op=parallel?timeSlices.find(s=>s.start<=time&&time<s.end):operationAt(time);
    if(!op){
        if(time>=data.duration)return presentationEnd;
        const mapping=parallel?timeSlices:segments,next=mapping[upperBound(mapping,time,'start')];
        return next&&next.start-time<=timeTolerance(next.start,time)?next.displayStart:0;
    }
    return op.displayStart+(time-op.start)/(op.end-op.start)*(op.displayEnd-op.displayStart);
}
function simulationAt(milliseconds){
    const t=clamp(milliseconds,0,presentationEnd);
    const mapping=parallel?timeSlices:segments;const op=mapping[upperBound(mapping,t,'displayEnd')];
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
function appliedQubits(o){
 if(o.applied===false)return [];
 if(Array.isArray(o.applied_gate_ids)&&o.gate_qubits)return o.applied_gate_ids.flatMap(id=>o.gate_qubits[id]||[]);
 return o.qubit_ids||[];
}
function atomColor(a){if(operationsAt(ui.time).some(o=>o.qubit_ids?.includes(a.id)&&!appliedQubits(o).includes(a.id)))return theme.static_color;return a.activity==='moving'?theme.moving_color:['gating','measuring','resetting'].includes(a.activity)?theme.active_color:theme.static_color}
function ramanCaption(op,effects){
 const illuminated=effects.filter(o=>o.kind==='raman_rotation').flatMap(o=>appliedQubits(o).map(q=>[q,o.target_holders?.[q]]));
 const inactive=effects.filter(o=>o.kind==='raman_rotation').flatMap(o=>(o.qubit_ids||[]).filter(q=>!appliedQubits(o).includes(q)));
 return 'Raman 单比特 · '+illuminated.map(([q,h])=>q+' '+(h?.holder_type==='mobile'?'静止 AOD':'SLM')).join(' / ')+
  (inactive.length?' · 条件为假、不打光：'+inactive.join(', '):'')+' · 邻距 ≥'+(data.scene.raman_minimum_separation_um??5)+' μm · '+(op.end-op.start).toFixed(2)+' μs'+
  (op.gate_ids?.length>1?' · 同型批次 '+appliedQubits(op).length+'/'+op.gate_ids.length+' 实际打光':' · U('+(op.u_parameters_rad||[]).map(v=>Number(v).toFixed(4)).join(', ')+') rad');
}
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
if($('zones').checked)scene.zones.forEach((z,i)=>{const zi={storage:0,entanglement:1,measurement:2}[z.zone_type]??i;ctx.fillStyle=theme.zone_colors[zi%theme.zone_colors.length];ctx.fillRect(X(z.bounds.lower.x_um),Y(z.bounds.upper.y_um),(z.bounds.upper.x_um-z.bounds.lower.x_um)*scale,(z.bounds.upper.y_um-z.bounds.lower.y_um)*scale)});
if($('grid').checked){for(const x of scene.grid_x)line(X(x),Y(b.upper.y_um),X(x),Y(b.lower.y_um),theme.grid_color,.6);for(const y of scene.grid_y)line(X(b.lower.x_um),Y(y),X(b.upper.x_um),Y(y),theme.grid_color,.6);const configuredSlm=new Set(scene.traps.map(t=>t.position.x_um+','+t.position.y_um));for(const p of scene.candidates)if(!configuredSlm.has(p.x_um+','+p.y_um))circle(X(p.x_um),Y(p.y_um),1.4,theme.muted_color);ctx.fillStyle=theme.muted_color;ctx.textAlign='center';let lastX=-Infinity;for(const x of scene.grid_x){if(X(x)-lastX>=32){ctx.fillText(x,X(x),Y(b.lower.y_um)+18);lastX=X(x)}}ctx.textAlign='right';let lastY=Infinity;for(const y of scene.grid_y){if(lastY-Y(y)>=18){ctx.fillText(y,X(b.lower.x_um)-10,Y(y)+3);lastY=Y(y)}}}
ctx.textAlign='left';if($('zones').checked)scene.zones.forEach((z,i)=>{const label={storage:'STORAGE',entanglement:'ENTANGLEMENT',measurement:'MEASUREMENT'}[z.zone_type]||z.id;const text=String(i+1).padStart(2,'0')+'  '+label;const x=X(z.bounds.lower.x_um)+9,y=Y(z.bounds.upper.y_um)+17;ctx.fillStyle='rgba(250,251,253,.92)';ctx.fillRect(x-4,y-11,126,16);ctx.fillStyle=theme.muted_color;ctx.fillText(text,x,y)});
const routePlan=(data.plans||[]).find(p=>p.id===f.plan_id)||(data.plans||[])[0];
const routeAtom=ui.selected||(routePlan?.requested.find(q=>routePlan.paths[q]));
const route=routePlan?.paths[routeAtom]||[];
$('route-caption').textContent=(operationAt(ui.time)?.kind==='raman_rotation'||routePlan?.planner_id==='addressed-raman-u-v1')?`${operationAt(ui.time)?.gate_id||routePlan?.gate_id||''} · Raman 寻址 · 原子保持当前 SLM / AOD 坐标 · 无运输路径`:routePlan?`${routePlan.gate_id||routePlan.task_id||'运输任务'} · planner: ${routePlan.planner_id} · ${routeAtom||'—'} 去程 ${Math.max(0,route.length-1)} 段 · 序号为途经点 · SLM 边界半径 ${scene.slm_clearance_um} μm`:'当前记录无物理运输计划';
if($('clearance').checked){ctx.setLineDash([3,3]);for(const trap of scene.traps){if(trap.enabled)circle(X(trap.position.x_um),Y(trap.position.y_um),(scene.slm_clearance_um||0)*scale,null,'#6d829a99',1)}ctx.setLineDash([])}
if($('planned-path').checked&&route.length){ctx.setLineDash([5,5]);for(let i=1;i<route.length;i++)line(X(route[i-1].x_um),Y(route[i-1].y_um),X(route[i].x_um),Y(route[i].y_um),'#bd7d3599',1.6);ctx.setLineDash([]);for(let i=0;i<route.length;i++){const p=route[i];circle(X(p.x_um),Y(p.y_um),3,'#fafbfd','#bd7d35',1);ctx.fillStyle='#966326';ctx.fillText(String(i),X(p.x_um)+(i%2?-16:10),Y(p.y_um)+(i%2?19:-9))}}
if($('trails').checked&&ui.selected){const a=atoms.find(a=>a.id===ui.selected),end=upperBound(frames,ui.time,'time'),step=Math.max(1,Math.ceil(end/128)),samples=[];for(let i=0;i<end;i+=step){const p=sample(frames[i].time).atoms.find(a=>a.id===ui.selected)?.position;if(p)samples.push(p)}if(a?.position)samples.push(a.position);ctx.setLineDash([3,4]);for(let i=1;i<samples.length;i++)line(X(samples[i-1].x_um),Y(samples[i-1].y_um),X(samples[i].x_um),Y(samples[i].y_um),'#a6b1c5',1);ctx.setLineDash([])}
if($('slm').checked){
 const occupied=new Set(atoms.filter(a=>a.holder.holder_type==='static').map(a=>a.holder.holder_id));
 for(const trap of scene.traps){
  if(!$('slm-empty').checked&&!occupied.has(trap.id))continue;
  const x=X(trap.position.x_um),y=Y(trap.position.y_um);
  if(trap.enabled)circle(x,y,TRAP_RADIUS,null,theme.muted_color,1.2);
  else if($('slm-off').checked)circle(x,y,1.6,'#bac4d1');
 }
}
if($('aod').checked){for(let row=0;row<f.aod.rows;row++)for(let column=0;column<f.aod.columns;column++){if(!f.aod.enabled_rows[row]||!f.aod.enabled_columns[column])continue;const x=X(columns[column]),y=Y(rows[row]);circle(x,y,TRAP_RADIUS,null,theme.moving_color,1.4)}}
const op=operationAt(ui.time),transfer=$('effects').checked?transferAt(ui.time):null;
const effects=operationsAt(ui.time).filter(o=>['raman_rotation','entangling_pulse','measurement','reset'].includes(o.kind));
const effectQubits=o=>o.qubit_ids?.length?o.qubit_ids:f.requested;
const effectLabel=o=>`${o.gate_ids?.length>1?(o.gate_type||o.kind)+' × '+o.gate_ids.length+' ['+o.gate_ids.join(', ')+']':o.gate_id||''} ${o.gate_type||o.kind}(${effectQubits(o).join(', ')})`;
for(const effect of effects){
 if(effect.applied===false)continue;
 const points=(effect.kind==='raman_rotation'?appliedQubits(effect):effectQubits(effect)).map(q=>atoms.find(a=>a.id===q)?.position);
 if(effect.kind==='entangling_pulse'){
  const pairs=effect.intended_pairs?.length?effect.intended_pairs:[effectQubits(effect)];
  for(const pair of pairs){const pairPoints=pair.map(q=>atoms.find(a=>a.id===q)?.position);
   if(pairPoints.length!==2||!pairPoints.every(Boolean))continue;
   if($('effects').checked)gateEffect(pairPoints,effect,X,Y);
   line(X(pairPoints[0].x_um),Y(pairPoints[0].y_um),X(pairPoints[1].x_um),Y(pairPoints[1].y_um),theme.active_color,2);
  }
 }
 if(['raman_rotation','measurement','reset'].includes(effect.kind)&&$('effects').checked){
  for(const p of points.filter(Boolean)){ctx.beginPath();ctx.arc(X(p.x_um),Y(p.y_um),13,-Math.PI/2,-Math.PI/2+2*Math.PI*clamp((ui.time-effect.start)/(effect.end-effect.start),0,1));ctx.strokeStyle=theme.active_color;ctx.lineWidth=2;ctx.stroke();
  }
 }
}
hits=[];for(const a of atoms){if(!a.position)continue;const x=X(a.position.x_um),y=Y(a.position.y_um),mobile=a.holder.holder_type==='mobile',color=atomColor(a);hits.push({id:a.id,x,y});if(ui.selected===a.id)circle(x,y,16,null,'#5364bc80',1.3);else if(ui.hover===a.id)circle(x,y,16,null,'#5364bc40',1);const handingOver=transfer?.ids.includes(a.id);if(handingOver)transferEffect(x,y,transfer);atomMarker(x,y,handingOver?transfer.mobileMix:(mobile?1:0),color);if($('labels').value==='all'||($('labels').value==='focus'&&(ui.selected===a.id||ui.hover===a.id))){ctx.font='600 10px system-ui';const w=ctx.measureText(a.id).width;ctx.fillStyle='#fafbfdf0';ctx.fillRect(x-w/2-3,y+17,w+6,14);ctx.fillStyle=theme.text_color;ctx.textAlign='center';ctx.fillText(a.id,x,y+28);ctx.textAlign='left';ctx.font='10px system-ui'}}
ctx.fillStyle=theme.muted_color;ctx.font='10px system-ui';ctx.textAlign='center';ctx.fillText('x / μm',X((b.lower.x_um+b.upper.x_um)/2),Y(b.lower.y_um)+36);ctx.save();ctx.translate(X(b.lower.x_um)-36,Y((b.lower.y_um+b.upper.y_um)/2));ctx.rotate(-Math.PI/2);ctx.fillText('y / μm',0,0);ctx.restore();ctx.textAlign='left';updatePanel()}
function updatePanel(){const {f,atoms}=current,op=operationAt(ui.time),transfer=transferAt(ui.time);
const effects=operationsAt(ui.time).filter(o=>['raman_rotation','entangling_pulse','measurement','reset'].includes(o.kind));
const effectQubits=o=>o.qubit_ids?.length?o.qubit_ids:f.requested;
const effectLabel=o=>`${o.gate_ids?.length>1?(o.gate_type||o.kind)+' × '+o.gate_ids.length+' ['+o.gate_ids.join(', ')+']':o.gate_id||''} ${o.gate_type||o.kind}(${effectQubits(o).join(', ')})`;
const measurements=f.measurement_results||{};$('measurement-readout').hidden=!hasMeasurements;$('measurement-readout').textContent='已提交测量（随回放时间更新）：'+(Object.entries(measurements).map(([id,bit])=>id+'='+bit).join(' · ')||'尚无读出');
const projectionAudit=data.operations.filter(o=>o.end<=ui.time&&o.measurement_true_results).flatMap(o=>Object.entries(o.measurement_true_results).filter(([id])=>Object.hasOwn(measurements,id)).map(([id,bit])=>id+': 投影 '+bit+' → 报告 '+measurements[id]+(o.readout_flips?.[id]?'（报告翻转）':'')));
if(projectionAudit.length)$('measurement-readout').textContent+='\n仿真审计（不供译码）：'+projectionAudit.join(' · ');
const flags=['zones','grid','slm','aod','planned-path','trails','effects','clearance'];
$('display-summary').textContent=flags.filter(id=>$(id).checked).length+' / '+flags.length+' 图层开启';
$('slm-empty').disabled=!$('slm').checked;$('slm-off').disabled=!$('slm').checked;
const gaps=[...current.columns.slice(1).map((x,i)=>x-current.columns[i]),...current.rows.slice(1).map((y,i)=>y-current.rows[i])];
const minGap=gaps.length?Math.min(...gaps):null,limit=data.scene.aod_minimum_spacing_um??1.01;
$('spacing-readout').textContent='AOD 活动 / 容量：'+(f.aod.enabled_rows.filter(Boolean).length*f.aod.enabled_columns.filter(Boolean).length)+' / '+(f.aod.rows*f.aod.columns)+'；当前最小中心距：'+(minGap==null?'单 trap，无邻居':minGap.toFixed(3)+' μm')+'；硬约束 > '+limit+' μm（包括空 trap）。SLM 中心排斥边界半径：'+data.scene.slm_clearance_um+' μm。';
if(data.summary){const s=data.summary,x=150+700*clamp((ui.time-s.window_start_us)/(s.wall_time_us||1),0,1);$('schedule-playhead').setAttribute('x1',x);$('schedule-playhead').setAttribute('x2',x);$('schedule-current').textContent=`当前 ${ui.time.toFixed(2)} μs`+(op?` · ${op.gate_id||''} ${labels[op.label]||op.label} · ${op.start.toFixed(2)}–${op.end.toFixed(2)} μs`:' · 记录结束')}
$('clock').textContent=ui.time.toFixed(2);$('version').textContent='STATE v'+String(f.version).padStart(2,'0');$('gate').textContent=effects.length?effects.map(effectLabel).join(' · '):f.gate_label;$('status').textContent=effects.length?'执行中 '+effects.reduce((n,o)=>n+(o.gate_ids?.length||1),0)+' 门':statuses[f.gate_status]||f.gate_status;$('frontier').textContent='READY '+f.ready_count+': '+(f.ready_frontier.join(', ')||'—')+(f.ready_count>20?' …':'');$('gate-states').textContent=Object.entries(f.gate_counts).map(([status,count])=>(statuses[status]||status)+' '+count).join(' · ');$('event').textContent=op?(labels[op.label]||op.label):'周期完成';$('readout').textContent=ui.time.toFixed(2)+' / '+data.duration.toFixed(2)+' μs';$('slider').value=ui.mode==='keyframe'?displayAt(ui.time):ui.time;$('play').textContent=ui.playing?'暂停':'播放';$('previous').disabled=ui.time<=(data.start_time||0);$('next').disabled=ui.time>=data.duration;if(op&&op.index>=0&&Math.floor(op.index/STAGE_PAGE)!==stagePage)renderStages(Math.floor(op.index/STAGE_PAGE));for(const o of visibleOperations)$('stage-'+o.index).setAttribute('aria-current',String(operationsAt(ui.time).some(active=>active.index===o.index)));
const progress=op?clamp((ui.time-op.start)/(op.end-op.start),0,1):1;
$('operation-title').textContent=op?(transfer?(['aod_load','aod_recapture'].includes(op.kind)?'SLM → AOD · 原位抓取':'AOD → SLM · 原位释放'):['entangling_pulse','raman_rotation','measurement','reset'].includes(op.kind)?effects.map(effectLabel).join(' · '):(labels[op.label]||op.label)):'记录结束 · 已显示全部已提交状态';
$('operation-caption').textContent=transfer?transfer.ids.join(' / ')+' · 目标支撑已建立 · 交接预览；承载与源支撑在操作结束时提交':op?.applied===false?'条件不满足 · '+(op.end-op.start).toFixed(2)+' μs 控制时隙 · 未施加激光':op?.kind==='measurement'?'MZ 投影测量 · '+(op.end-op.start).toFixed(2)+' μs（本次仿真假设）· 结果在操作结束提交':op?.kind==='reset'?'MZ 原位复位到 |0⟩ · '+(op.end-op.start).toFixed(2)+' μs（本次仿真假设）':op?.kind==='raman_rotation'?ramanCaption(op,effects):op?.kind==='trap_switch'?'光阱开关 · 完成时提交启用状态':op?.kind==='idle'?'无设备操作 · 原子位置保持不变':op?.kind==='entangling_pulse'?'真实脉冲 '+(op.end-op.start).toFixed(2)+' μs · 红色连线表示作用对':op?(atoms.some(a=>a.holder.holder_type==='mobile')?(['row_column','row_column_orthogonal'].includes(data.backend)?'行列联动 · 同步三次轨迹 · 保持行列顺序':'刚性平移 · 所有已捕获原子同步移动'):(f.aod.enabled_rows.some(Boolean)&&f.aod.enabled_columns.some(Boolean)?'开启的空 AOD 移动 · 全轨迹安全已验证':'AOD 关灯定位 · 运动显式计时')):'所有时间与物理指标来自原始事件';
if(op?.transfer_phase)$('operation-caption').textContent+=(op.transfer_phase==='depart'?' · 仅允许离开自身源 trap':' · 仅允许接近自身卸载 trap');
if(parallel&&operationsAt(ui.time).length>1)$('operation-caption').textContent+=' · 同时执行：'+operationsAt(ui.time).filter(o=>o.index!==op?.index).map(o=>o.gate_id?effectLabel(o):(labels[o.label]||o.label)).join('、');
$('operation-progress').textContent=Math.round(progress*100)+'%';
$('operation-fill').style.width=(progress*100)+'%';
$('operation-fill').style.background=['entangling_pulse','raman_rotation','measurement','reset'].includes(op?.kind)?theme.active_color:theme.moving_color;
$('readout').textContent=ui.mode==='keyframe'?'演示 '+(displayAt(ui.time)/1000).toFixed(2)+' / '+(presentationEnd/1000).toFixed(2)+' s · 仿真 '+ui.time.toFixed(2)+' μs':ui.time.toFixed(2)+' / '+data.duration.toFixed(2)+' μs';
$('playback-status').textContent=!data.operations.length?'静态布局 · 当前记录没有可回放操作。编辑线路并编译后可播放。':ui.playing?'正在播放 · 可暂停或拖动时间轴':ui.time>=data.duration?'已到终点 · 点击播放可重播，也可拖动查看任意时刻':'已暂停 · 点击播放，或拖动时间轴查看执行过程';
$('play').disabled=!data.operations.length;$('slider').disabled=!data.operations.length;$('seek-time').disabled=!data.operations.length;$('seek-time-button').disabled=!data.operations.length;$('end').disabled=!data.operations.length||ui.time>=data.duration;
if(root.activeElement!==$('seek-time'))$('seek-time').value=String(Number(ui.time.toFixed(6)));
if(!data.operations.length){$('event').textContent='无执行操作';$('operation-title').textContent='静态布局 · 无运输或门操作';$('operation-caption').textContent='此处显示当前记录的原子与光阱位置。';}
$('mode-note').textContent=ui.mode==='keyframe'?(parallel?'关键帧演示：并行操作共享同一时间映射；短门展示 1.8 s（1×），运输同步推进。':'关键帧演示：装载 1.8 s · 卸载 1.6 s · 短门 1.8 s（1×）；阶段内按原轨迹推进。展示时长不计入物理指标。'):'真实时间比例：1× = 25 μs 仿真 / 1 s 屏幕时间，所有操作统一缩放；0.3 μs 门约显示 12 ms。';
for(const a of atoms.filter(a=>visibleAtoms.includes(a.id))){const row=$('atom-'+a.id);row.setAttribute('aria-pressed',String(ui.selected===a.id));row.querySelector('.symbol').style.background=atomColor(a);row.querySelector('.symbol').className='symbol '+(a.holder.holder_type==='mobile'?'diamond':'circle');row.querySelector('.atom-state').textContent=(a.holder.holder_type==='mobile'?'AOD':'SLM')+' · '+(names[a.activity]||a.activity)}
const a=atoms.find(a=>a.id===ui.selected);if(a){const h=a.holder,holder=h.holder_type==='mobile'?`AOD · row ${h.holder_id.row}, col ${h.holder_id.column}`:`SLM · ${h.holder_id}`;const batchPair=effects.flatMap(o=>o.intended_pairs||[]).find(pair=>pair.includes(a.id));const partner=batchPair?batchPair.filter(id=>id!==a.id).join(', '):f.requested.includes(a.id)?f.requested.filter(id=>id!==a.id).join(', '):'无（附带 / 旁观原子）';const active=transfer?.ids.includes(a.id)?(['aod_load','aod_recapture'].includes(op.kind)?'装载中（目标支撑已建立）':'卸载中（目标支撑已建立）'):a.activity==='gating'||a.activity==='measuring'||a.activity==='resetting'?(effects.filter(o=>effectQubits(o).includes(a.id)).map(effectLabel).join(' · ')||f.gate_label):a.holder.holder_type==='mobile'&&op?(labels[op.label]||op.label):'空闲';$('details').innerHTML='<dl>'+[['原子',a.id],...(data.scene.atom_roles?.[a.id]?[['角色',data.scene.atom_roles[a.id].role+' · patch '+data.scene.atom_roles[a.id].patch]]:[]),['坐标',a.position?`${a.position.x_um.toFixed(2)}, ${a.position.y_um.toFixed(2)} μm`:'—'],['承载',holder],['当前操作',active],['目标伙伴',partner]].map(([k,v])=>`<dt>${escapeHTML(k)}</dt><dd>${escapeHTML(v)}</dd>`).join('')+'</dl>'}else $('details').textContent='点击画布或列表中的原子，查看位置、承载 trap 和当前操作。'}
function seek(time){if(!Number.isFinite(time))throw new Error('Simulation time must be finite');ui.playing=false;last=null;displayTime=null;ui.time=Math.max(data.start_time||0,Math.min(data.duration,time));draw()}
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
$('mode').onchange=()=>{ui.mode=$('mode').value;ui.playing=false;last=null;displayTime=null;configureTimeline();draw()};
$('slider').oninput=()=>{const t=Number($('slider').value);seek(ui.mode==='keyframe'?simulationAt(t):t)};$('play').onclick=()=>{if(ui.time>=data.duration)ui.time=data.start_time||0;ui.playing=!ui.playing;last=null;displayTime=null;draw()};$('reset').onclick=()=>seek(data.start_time||0);$('pulse').disabled=!data.operations.some(o=>['raman_rotation','entangling_pulse','measurement','reset'].includes(o.kind));$('pulse').onclick=()=>{const pulses=data.operations.filter(o=>['raman_rotation','entangling_pulse','measurement','reset'].includes(o.kind)),pulse=pulses.find(o=>o.start>ui.time+1e-8)||pulses[0];if(pulse)seek((pulse.start+pulse.end)/2)};$('previous').onclick=()=>seek([...frames].reverse().find(f=>f.time<ui.time-1e-8)?.time??0);$('next').onclick=()=>seek(frames.find(f=>f.time>ui.time+1e-8)?.time??data.duration);for(const id of ['labels','grid','slm','slm-empty','slm-off','aod','trails','effects','planned-path','clearance','zones'])$(id).onchange=draw;
$('fit').onclick=()=>{Object.assign(view,{zoom:1,panX:0,panY:0});draw()};$('zoomin').onclick=()=>zoom(1.3);$('zoomout').onclick=()=>zoom(1/1.3);
$('end').onclick=()=>seek(data.duration);
$('seek-time').min=String(data.start_time||0);$('seek-time').max=String(data.duration);
$('seek-time-button').onclick=()=>{const raw=$('seek-time').value.trim(),time=Number(raw);if(!raw||!Number.isFinite(time)||time<(data.start_time||0)||time>data.duration){$('seek-error').textContent='请输入 '+(data.start_time||0)+'–'+data.duration+' μs';return;}$('seek-error').textContent='';seek(time);};
$('seek-time').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();$('seek-time-button').onclick();}};
$('fit-atoms').onclick=()=>{
 const atoms=sample(ui.time).atoms;if(!atoms.length)return;
 const xs=atoms.map(a=>a.position.x_um),ys=atoms.map(a=>a.position.y_um),cx=(Math.min(...xs)+Math.max(...xs))/2,cy=(Math.min(...ys)+Math.max(...ys))/2;
 const b=frames[0].scene.bounds,base=Math.min((width-110)/(b.upper.x_um-b.lower.x_um),(height-100)/(b.upper.y_um-b.lower.y_um));
 const scale=Math.min((width-100)/Math.max(20,Math.max(...xs)-Math.min(...xs)+20),(height-100)/Math.max(20,Math.max(...ys)-Math.min(...ys)+20));
 view.zoom=clamp(scale/base,.65,8);view.panX=-(cx-(b.lower.x_um+b.upper.x_um)/2)*base*view.zoom;view.panY=(cy-(b.lower.y_um+b.upper.y_um)/2)*base*view.zoom;draw();
};
canvas.addEventListener('keydown',e=>{if(e.key===' '){e.preventDefault();if(!$('play').disabled)$('play').onclick();}else if(e.key==='ArrowLeft'){e.preventDefault();$('previous').onclick();}else if(e.key==='ArrowRight'){e.preventDefault();$('next').onclick();}});
canvas.addEventListener('wheel',e=>{if(!e.ctrlKey&&!e.metaKey)return;e.preventDefault();const p=point(e);zoom(Math.exp(-e.deltaY*.001),p.x,p.y)},{passive:false});
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
 $('stages').innerHTML=visibleOperations.map(o=>`<button id="stage-${o.index}" class="stage" data-kind="${o.kind}" aria-current="false"><strong>${o.index+1} · ${escapeHTML(o.gate_id||o.task_id||'运输任务')} · ${escapeHTML(labels[o.label]||o.label)}</strong><span>${o.start.toFixed(1)}–${o.end.toFixed(1)} μs</span><em></em></button>`).join('');
 for(const op of visibleOperations)$('stage-'+op.index).onclick=()=>seek(op.start);
 $('stages-page').textContent=`${data.operations.length} 操作 · ${stagePage+1}/${Math.max(1,Math.ceil(data.operations.length/STAGE_PAGE))}`;
 $('stages-prev').disabled=stagePage===0;$('stages-next').disabled=(stagePage+1)*STAGE_PAGE>=data.operations.length;
 configureTimeline();
}
$('atom-search').oninput=()=>{atomQuery=$('atom-search').value.trim().toLowerCase();atomPage=0;renderAtoms();draw()};
$('atoms-prev').onclick=()=>{atomPage--;renderAtoms();draw()};$('atoms-next').onclick=()=>{atomPage++;renderAtoms();draw()};
$('stages-prev').onclick=()=>renderStages(stagePage-1);$('stages-next').onclick=()=>renderStages(stagePage+1);
renderAtoms();renderStages(0);
const jointMove=data.operations.find(o=>o.kind==='aod_move'&&o.moving_count>1);
$('joint').hidden=!jointMove;$('joint').onclick=()=>{if(jointMove)seek((jointMove.start+jointMove.end)/2)};
$('summary').innerHTML=summaryMarkup(data.summary,data.operations);
if(data.summary){
 const activate=e=>{const value=e.target.getAttribute?.('data-start');if(value!=null){seek(Number(value));return true}return false};
 $('schedule').onclick=activate;
 if(Object.keys(data.summary.resource_busy_us||{}).some(id=>id==='AOD_0'||id==='ENTANGLING_LASER_0'||id.startsWith('RAMAN'))){$('resource-schedule').onclick=activate;$('resource-schedule').onkeydown=e=>{if((e.key==='Enter'||e.key===' ')&&activate(e))e.preventDefault()};}
 $('schedule').onkeydown=e=>{if((e.key==='Enter'||e.key===' ')&&activate(e))e.preventDefault()};
}
// Hidden tabs pause; a resumed tab must not jump over the short gate.
const visibility=()=>{if(document.hidden){ui.playing=false;last=null;draw()}};document.addEventListener('visibilitychange',visibility);
function tick(now){
    if(disposed)return;
    if(ui.playing&&last!==null){
        const elapsed=Math.max(0,now-last)*Number($('speed').value);
        if(ui.mode==='keyframe'){
            if(displayTime===null)displayTime=displayAt(ui.time);
            displayTime=Math.min(presentationEnd,displayTime+elapsed);
            ui.time=simulationAt(displayTime);
        }else ui.time=Math.min(data.duration,ui.time+elapsed*US_PER_MS);
        if(ui.time>=data.duration)ui.playing=false;
        draw();
    }
    last=now;raf=requestAnimationFrame(tick);
}
$('backend-caption').textContent=hasMeasurements?'QEC · 物理运输 / MZ 测量复位 / 测量条件控制 · 同一物理时钟':parallel?'门操作 / AOD 重叠 · 同一物理时钟':data.operations.some(op=>op.task_id)?'独立任务 · 准备 / 门效果 / 清理 · 当前串行执行':data.operations.some(op=>op.kind==='raman_rotation')?'CZ / RAMAN · 单 trap 串行调度 · 1Q 静止 SLM / AOD 原位执行':data.operations.length===0?'初始布局 / 无物理操作 · trap 与 holder 来自输入':['row_column','row_column_orthogonal'].includes(data.backend)?'ROW / COLUMN AOD · 行列伸缩与平移 · 返回并卸载':data.operations.some(op=>op.planner_id?.startsWith('single-trap-return'))?'SINGLE TRAP · a → EZ SLM · b → CZ · b / a 依次返回 SZ':data.operations.some(op=>op.kind==='aod_park')?'RIGID AOD · SZ 同运 → EZ 局部交接 → CZ → 恢复构型并同返':'RIGID AOD · 刚性平移 · 静态伙伴配对 · 返回并卸载';
$('motion-note').textContent=['row_column','row_column_orthogonal'].includes(data.backend)?'按行列坐标与三次轨迹采样；采用配置的峰值速度/加速度/段内 jerk 限制，未模拟光场、加热与损失。':'轨迹按移动事件线性插值，未模拟加速度与加热。';
const observer=new ResizeObserver(resize);observer.observe($('viewport'));resize();raf=requestAnimationFrame(tick);

const api={setTime:seek,selectAtom(id){ui.selected=id;draw()},
 play(){ui.playing=true;last=null;displayTime=null},pause(){ui.playing=false;last=null;draw()},
 getStatus(){return {time_us:ui.time,selected_atom:ui.selected,playing:ui.playing,visible_atom_rows:visibleAtoms.length,visible_operation_rows:visibleOperations.length}},
 destroy(){disposed=true;cancelAnimationFrame(raf);observer.disconnect();document.removeEventListener('visibilitychange',visibility);root.innerHTML='';mounted.delete(container)},
 debug:{data,frames,ui,view,seek,sample,displayAt,simulationAt,operationAt,operationsAt,transferAt,tick,renderStages,draw,projection,
        get presentationEnd(){return presentationEnd},get current(){return current},get hits(){return hits}}};
mounted.set(container,api);return api;

}
scope.NeutralAtomViewer={mount};
})(typeof window!=="undefined"?window:globalThis);
