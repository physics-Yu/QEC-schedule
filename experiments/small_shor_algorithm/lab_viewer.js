/* Minimal Chinese experiment-facing controls, playback, schedule and loss tables. */
(function(){
  'use strict';
  const data=JSON.parse(document.getElementById('lab-data').textContent),M=ShorLabModel,$=id=>document.getElementById(id);
  const groups=[
    ['时间与 T₂',true,[
      ['speed','平均移动速度','μm/μs',2,.01,1,'每个 MOVE 耗时 = 最远原子的位移 / 速度；0 表示无法完成移动。'],
      ['transfer','每次 LOAD / STORE','μs',200,1,1,'SLM↔AOD 转移时间；一次并行转移计一次耗时，loss 按原子计。'],
      ['readout','每次测量曝光','μs',1000,10,1,'每个真实测量动作的耗时；测量结束后还需等待反馈延迟。'],
      ['t2Slm','SLM 中的 T₂','ms',3000,10,1,'越大越能保持相干；1000 ms 是示例值。0 表示有暴露即完全退相干。'],
      ['t2Aod','AOD 中的 T₂','ms',3000,10,1,'控制 AOD 中空闲与搬运的相干衰减；示例值 1000 ms，需实测替换。']]],
    ['每次操作的原子 loss',false,[
      ['loadLoss','SLM → AOD 丢失','%',2,.001,100,'每次装载、每颗原子的条件丢失概率；论文默认 0.2%。'],
      ['storeLoss','AOD → SLM 丢失','%',2,.001,100,'每次卸载、每颗原子的条件丢失概率；论文默认 0.2%。'],
      ['czLoss','CZ 门原子丢失','%',2,.001,100,'每颗参与 CZ 的原子，每次门的丢失概率；默认 0.1%。'],
      ['imagingLoss','测量成像丢失','%',2,.001,100,'每颗被测原子，每次成像的丢失概率；默认 0.1%。'],
      ['singleLoss','单比特门丢失','%',1,.001,100,'H / T / T† / Phase 每次作用的物理丢失；论文默认 0，不含 T₂。'],
      ['resetLoss','初始化丢失','%',1,.001,100,'每次 reset 的物理丢失；论文默认 0。reset 不会补回已丢失原子。']]],
    ['门时间与反馈延迟',false,[
      ['singleTime','单比特门时间','μs',10,.1,1,'一个原生单比特门的时间；与其他原子的门并行时取最长值。'],
      ['czTime','CZ 脉冲时间','μs',10,.01,1,'一次 CZ 脉冲的时间；一个脉冲可以服务多个独立原子对。'],
      ['resetTime','初始化时间','μs',500,1,1,'reset 的执行时间；门前等待会改变后续时间轴。'],
      ['latency','测量结果返回延迟','μs',5000,10,1,'从测量曝光结束到经典结果可用；可与无依赖的工作重叠。']]],
    ['搬运加热模型参数',false,[
      ['mass','原子质量','u',180,.001,1,'示例 87Rb：86.909 u。进入加热量和阱深公式；0 时模型无定义。'],
      ['frequency','陷阱频率 f','kHz',500,1,1,'ω = 2πf；同时影响加热量和阱深。示例 90 kHz；0 时无法计算。'],
      ['width','有效阱宽 a','μm',3,.01,1,'以 U₀ = mω²a²/2 推出平均阱深；示例 0.73 μm，0 时无束缚。'],
      ['temperature','原子温度 T','μK',200,1,1,'决定能量分布；示例 27 μK。0 采用零温极限，不进行除零。'],
      ['depthSpread','阱深标准差 / U₀','%',50,1,100,'各陷阱深度的相对波动；0 为均匀陷阱，非零时做高斯平均。']]]
  ];
  let params={...M.DEFAULTS},selected=0,model,finalRisk,replay,cursor={step:0,fraction:0},frame,time=0;
  let playing=false,raf=null,previousTimestamp=null,timer=null,chosenAtom=null,currentRow=-1,schedule=[],canvasPositions=[];
  const f=(x,d=3)=>Number.isFinite(x)?Number(x).toLocaleString('zh-CN',{maximumFractionDigits:d}):x===Infinity?'∞':'—';
  const percent=x=>x===0?'0%':x*100<.0001?(x*100).toExponential(2)+'%':f(x*100,4)+'%';
  const duration=x=>x===Infinity?'∞':x===null?'—':x>=1000?f(x/1000,3)+' ms':f(x,3)+' μs';
  const e=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  function angle(x){const r=x/Math.PI;for(const d of [1,2,4,8,16,32,64,128,256])if(Math.abs(r*d-Math.round(r*d))<1e-10){const n=Math.round(r*d);return (n===-1?'−':n===1?'':String(n))+'π'+(d===1?'':'/'+d);}return f(x,4);}
  function atomLabel(id){const atom=data.traces[selected].initial.atoms.find(a=>a.id===id);return 'q'+(atom?.qubit??id);}
  function actionLabel(a){
    const names={Load:'装载到 AOD',Store:'卸载到 SLM',Move:'移动原子',Measure:'测量',Reset:'初始化',Wait:'等待经典结果',CZPulse:'CZ 门'};
    if(names[a.kind])return names[a.kind];
    const node=model?.trace?.loss_time.nodes[a.source_ids[0]];
    return {h:'H 门',t:'T 门',tdg:'T† 门',p:'相位门 P('+angle(node?.params[0]||0)+')'}[node?.name]||'单比特门';
  }
  function conditions(a){return [...new Set(a.source_ids.map(id=>model.trace.loss_time.nodes[id].condition).filter(Boolean).map(c=>{
    const bit=data.traces[selected].lab.measurements.find(m=>m.measurement_id===c.result.measurement_id)?.bit;
    return 'b'+bit+'='+c.value;
  }))].join('、');}
  function formula(a){
    if(a.kind==='Move')return f(Math.max(...a.movement.map(m=>m.distance_um)),3)+' μm ÷ '+f(params.speed)+' μm/μs';
    const keys={Load:'transfer',Store:'transfer',Measure:'readout',Reset:'resetTime',CZPulse:'czTime',LocalU:'singleTime',Rotation:'singleTime'};
    return a.kind==='Wait'?'补足结果返回前的等待':f(params[keys[a.kind]]??a.duration_us)+' μs／次';
  }
  function syncInputs(){for(const [,,specs] of groups)for(const [key,,,,,scale] of specs){$('slider-'+key).value=params[key]*scale;$('value-'+key).value=Number((params[key]*scale).toFixed(6));}$('t2-enabled').checked=params.t2Enabled;}
  function setupParameters(){
    for(const [title,open,specs] of groups){
      const section=e('details','parameter-group');section.open=open;section.append(e('summary',null,title));$('parameters').append(section);
      for(const [key,label,unit,max,step,scale,note] of specs){
        const field=e('div','field'),head=e('div','field-head'),caption=e('label',null,label);caption.htmlFor='slider-'+key;
        const number=e('input');number.type='number';number.id='value-'+key;number.min=0;number.max=max;number.step=step;number.setAttribute('aria-label',label+'数值');
        const slider=e('input');slider.type='range';slider.id='slider-'+key;slider.min=0;slider.max=max;slider.step=step;slider.setAttribute('aria-label',label);
        head.append(caption,number,e('span',null,unit));field.append(head,slider,e('p',null,note));section.append(field);
        function update(event){
          const value=Number(event.target.value);if(!Number.isFinite(value)||value<0||value>max){event.target.value=params[key]*scale;return;}
          params[key]=value/scale;syncInputs();clearTimeout(timer);stop();timer=setTimeout(rebuild,80);
        }
        slider.addEventListener('input',update);number.addEventListener('change',update);
      }
    }
    syncInputs();
  }
  function stop(){playing=false;previousTimestamp=null;if(raf!==null)cancelAnimationFrame(raf);raf=null;$('play').textContent='播放';}
  function rebuild(){
    stop();const ratio=model?.status==='ok'&&model.duration>0?time/model.duration:0;
    try{model=M.build(data.traces[selected],params);}catch(error){model={status:'invalid',trace:null,duration:null,message:'无法计算：'+error.message};}
    const base=data.traces[selected],bits=base.lab.measurements.map(m=>m.value).join('');
    $('title').textContent='N = '+base.lab.n+' · 半经典测量反馈';
    $('branch').textContent='本次模拟测量结果（从 b₀ 开始）：'+bits+'。后续相位门根据已返回的测量结果决定是否执行。';
    $('status').hidden=model.status==='ok';$('status').textContent=model.message||'';
    for(const id of ['play','previous','next','progress','schedule-filter'])$(id).disabled=model.status!=='ok';
    if(model.status!=='ok'){
      finalRisk=null;replay=null;frame={atoms:new Map(base.initial.atoms.map(a=>[a.id,a])),actions:[],entry:{atoms:new Map(base.initial.atoms.map(a=>[a.id,a]))}};time=0;
      $('total-time').textContent=duration(model.duration);for(const id of ['physical-final','coherence-final','combined-final'])$(id).textContent='—';
      $('operation').textContent='参数边界：暂停计算';$('operation-detail').textContent='请调整上方提示的参数';$('clock').textContent='—';
      for(const id of ['loss-rows','schedule-rows','atom-rows','calculations','readouts'])$(id).replaceChildren();$('loss-summary').textContent='当前没有有效的整条电路统计。';$('loss-time').textContent='未计算';$('progress').value=0;draw();return;
    }
    finalRisk=M.at(model,model.duration);replay=new AtomReplayModel.Replay(model.trace,{motion:'direct'});
    time=ratio*model.duration;cursor=replay.cursorAtTime(time);
    $('total-time').textContent=duration(model.duration);$('physical-final').textContent=percent(finalRisk.meanLoss);$('coherence-final').textContent=percent(finalRisk.meanCoherenceLoss);$('combined-final').textContent=percent(finalRisk.meanComposite);
    schedule=model.trace.steps.map((s,i)=>({index:i,step:s,kind:s.actions[0]?.kind||'Wait'}));
    if(model.duration>model.trace.program_duration_us)schedule.push({index:model.trace.steps.length,step:{start_us:model.trace.program_duration_us,duration_us:model.duration-model.trace.program_duration_us,actions:[]},kind:'Wait'});
    buildSchedule();buildCalculations();render();
  }
  function buildSchedule(){
    const tbody=$('schedule-rows');tbody.replaceChildren();currentRow=-1;
    if(model.status!=='ok')return;
    const filter=$('schedule-filter').value;
    for(const row of schedule){
      const category=['Load','Move','Store'].includes(row.kind)?'transport':['Measure','Wait'].includes(row.kind)?'readout':'gate';if(filter!=='all'&&filter!==category)continue;
      const s=row.step,atoms=[...new Set(s.actions.flatMap(a=>a.atoms))];
      const labels=[...new Set(s.actions.map(actionLabel))],guard=[...new Set(s.actions.map(conditions).filter(Boolean))].join('；');
      const label=(labels.join('、')||'等待最终读数')+(guard?'（'+guard+'）':'')+(atoms.length?' · '+atoms.slice(0,4).map(atomLabel).join('/')+(atoms.length>4?'…':''):'');
      const tr=e('tr');tr.dataset.step=row.index;tr.title=guard?'经典条件：'+guard:atoms.map(atomLabel).join('、');
      for(const text of [row.index+1,label,f(s.start_us,2),f(s.duration_us,2),f(s.start_us+s.duration_us,2),s.actions.length?[...new Set(s.actions.map(formula))].join('；'):'最后的结果返回时刻 − 已执行时间'])tr.append(e('td',null,String(text)));
      tr.addEventListener('click',()=>{stop();cursor={step:row.index,fraction:s.duration_us===0?1:0};render();});tbody.append(tr);
    }
  }
  function buildCalculations(){
    const host=$('calculations');host.replaceChildren();if(model.status!=='ok')return;
    const trace=model.trace,r=trace.loss_time_result,n=trace.initial.atoms.length;
    const slm=finalRisk.atoms.reduce((s,a)=>s+a.exposureUs.slm,0)/n,aod=finalRisk.atoms.reduce((s,a)=>s+a.exposureUs.aod,0)/n;
    const blocks=[
      ['时间怎么算','每步耗时 = max(该步各动作耗时)；总时长 = max(全部动作完成，全部结果返回)。',
       '本例：动作 '+f(trace.program_duration_us,3)+' μs；末尾结果等待 '+f(r.pending_result_tail_us,3)+' μs；合计 '+f(trace.duration_us,3)+' μs。反馈不足时另补 '+f(r.feedback_wait_us,3)+' μs（已在动作内计入）。'],
      ['搬运 loss 怎么算','Δn = (50/3)mℓ²/(ℏω³t⁴)；U₀ = mω²a²/2；p(η) = (1+η+η²/2)e⁻η。',
       '当前 U₀/kB = '+f(r.depth_microkelvin,3)+' μK；最大 Δn = '+f(r.maximum_delta_n,3)+'。'+(r.heating_saturated?r.heating_saturated+' 个原子移动事件达到近 100% loss。':'没有移动事件达到近 100% loss。')],
      ['物理原子丢失怎么算','Sᵢ = ∏事件(1−pᵢ,事件)；p丢失,ᵢ = 1−Sᵢ；均值 = Σp丢失,ᵢ/N。',
       '本例：结束时预计丢失 '+f(finalRisk.expectedLost,5)+' / '+n+' 颗；平均丢失 '+percent(finalRisk.meanLoss)+'。各来源按首次丢失归因，避免重复计数。'],
      ['T₂ 与模拟平均 loss 粗估怎么算','Cᵢ = exp[−tSLM,ᵢ/T₂,SLM − tAOD,ᵢ/T₂,AOD]；相干衰减 = 1−Cᵢ；Qᵢ = 1−SᵢCᵢ。',
       '平均有效暴露：SLM '+f(slm/1000,4)+' ms、AOD '+f(aod/1000,4)+' ms。逐原子先计算再平均：相干衰减 '+percent(finalRisk.meanCoherenceLoss)+'，模拟平均 loss 粗估 '+percent(finalRisk.meanComposite)+'。'+(!params.t2Enabled?'当前已关闭 T₂。':'')]
    ];
    for(const [title,math,substitution] of blocks){const b=e('div','formula');b.append(e('h3',null,title),e('p',null,substitution));host.append(b);}
  }
  function renderLoss(risk){
    const tbody=$('loss-rows');tbody.replaceChildren();const n=risk.atoms.length;
    const names={load:'装载 LOAD',store:'卸载 STORE',move:'搬运加热',cz:'CZ 门',imaging:'测量成像',single:'单比特门',reset:'初始化'};
    const keys={load:'loadLoss',store:'storeLoss',cz:'czLoss',imaging:'imagingLoss',single:'singleLoss',reset:'resetLoss'};
    function row(items,cls){const tr=e('tr',cls);for(const item of items)tr.append(e('td',null,item));tbody.append(tr);}
    row(['物理原子丢失（各项可相加）','','','',''],'group');
    for(const key of Object.keys(names))row([names[key],risk.counts[key]+' / '+finalRisk.counts[key]+' 原子次',key==='move'?'距离 + 时间 + 阱参数':percent(params[keys[key]]),percent(risk.physical[key]/n),percent(finalRisk.physical[key]/n)]);
    row(['物理丢失合计','','',percent(risk.meanLoss),percent(finalRisk.meanLoss)],'total');
    row(['T₂ 相干衰减（不会丢原子）','','','',''],'group');
    for(const holder of ['slm','aod']){
      const now=risk.atoms.reduce((s,a)=>s+a.exposureUs[holder],0)/n/1000,end=finalRisk.atoms.reduce((s,a)=>s+a.exposureUs[holder],0)/n/1000;
      row([holder.toUpperCase()+' 中退相干',f(now,3)+' / '+f(end,3)+' ms',params.t2Enabled?'T₂ = '+f(holder==='slm'?params.t2Slm:params.t2Aod)+' ms':'已关闭',percent(risk.decoherence[holder]/n),percent(finalRisk.decoherence[holder]/n)]);
    }
    row(['相干衰减合计','','',percent(risk.meanCoherenceLoss),percent(finalRisk.meanCoherenceLoss)],'total');
    $('loss-summary').textContent='当前预计丢失 '+f(risk.expectedLost,4)+' 颗；当前模拟平均 loss 粗估 '+percent(risk.meanComposite)+'（不能与两组贡献直接相加）。';
    $('loss-time').textContent='当前时刻 '+duration(time);
    const atoms=$('atom-rows');atoms.replaceChildren();for(const a of risk.atoms){const tr=e('tr');for(const x of [atomLabel(a.id),f(a.exposureUs.slm/1000,5),f(a.exposureUs.aod/1000,5),percent(a.loss),percent(a.coherenceLoss),percent(a.composite)])tr.append(e('td',null,x));atoms.append(tr);}
    const a=risk.atoms.find(a=>a.id===chosenAtom);$('atom-detail').textContent=a?atomLabel(a.id)+'：物理丢失 '+percent(a.loss)+'；T₂ 相干衰减 '+percent(a.coherenceLoss)+'；单原子综合估计 '+percent(a.composite):'点击原子查看损失与相干暴露。图中不随机移除原子。';
  }
  function render(){
    if(model.status!=='ok')return;
    frame=replay.frame(cursor.step,cursor.fraction);time=frame.time_us;
    const labels=[...new Set(frame.actions.map(actionLabel))];$('operation').textContent=labels.join('、')||(time<model.duration?'等待最终测量结果':'电路执行完成');
    $('clock').textContent=duration(time)+' / '+duration(model.duration);
    $('operation-detail').textContent=frame.actions.length?formula(frame.actions[0])+([ ...new Set(frame.actions.map(conditions).filter(Boolean))].length?'；反馈条件：'+[...new Set(frame.actions.map(conditions).filter(Boolean))].join('、'):''):time<model.duration?'动作已完成，等待经典读数返回':'';
    $('progress').value=model.duration?Math.round(time/model.duration*10000):10000;
    $('readouts').replaceChildren();const ready=new Map(frame.measurements.map(m=>[m.measurement_id,m.value]));
    for(const m of data.traces[selected].lab.measurements)$('readouts').append(e('span',ready.has(m.measurement_id)?'ready':'','b'+m.bit+' = '+(ready.has(m.measurement_id)?m.value:'等待')));
    if(currentRow!==cursor.step){const old=$('schedule-rows').querySelector('.current');if(old)old.classList.remove('current');const next=$('schedule-rows').querySelector('[data-step="'+cursor.step+'"]');if(next)next.classList.add('current');currentRow=cursor.step;}
    renderLoss(M.at(model,time));draw();
  }
  function draw(){
    const canvas=$('stage'),box=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
    if(canvas.width!==Math.round(box.width*dpr)||canvas.height!==Math.round(box.height*dpr)){canvas.width=Math.round(box.width*dpr);canvas.height=Math.round(box.height*dpr);}
    const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,box.width,box.height);
    const base=data.traces[selected],zones=base.device.zones;
    const bounds=[Math.min(...zones.map(z=>z.bounds[0]))-14,Math.min(...zones.map(z=>z.bounds[1]))-22,Math.max(...zones.map(z=>z.bounds[2]))+14,Math.max(...zones.map(z=>z.bounds[3]))+24];
    const scale=Math.min((box.width-40)/(bounds[3]-bounds[1]),(box.height-40)/(bounds[2]-bounds[0]));
    const x0=(box.width-(bounds[3]-bounds[1])*scale)/2,y0=(box.height-(bounds[2]-bounds[0])*scale)/2;
    const xy=(x,y)=>[x0+(y-bounds[1])*scale,box.height-y0-(x-bounds[0])*scale];
    ctx.font='11px "Microsoft YaHei",sans-serif';ctx.textAlign='left';
    for(const zone of zones){const [x,y]=xy(zone.bounds[2],zone.bounds[1]),w=Math.max(8,(zone.bounds[3]-zone.bounds[1])*scale),h=(zone.bounds[2]-zone.bounds[0])*scale;ctx.fillStyle='#edf3f5';ctx.fillRect(x,y,w,h);ctx.strokeStyle='#cad8de';ctx.setLineDash([4,4]);ctx.strokeRect(x,y,w,h);ctx.setLineDash([]);ctx.fillStyle='#6c818c';ctx.fillText({storage:'存储区',entanglement:'纠缠区',measurement:'测量区'}[zone.id]||zone.id,x,y-6);}
    ctx.fillStyle='#cfdce3';for(const site of base.device.slm_sites){const [x,y]=xy(site.x,site.y);ctx.beginPath();ctx.arc(x,y,1.2,0,2*Math.PI);ctx.fill();}
    const state=frame?.atoms||new Map(base.initial.atoms.map(a=>[a.id,a])),active=new Set((frame?.actions||[]).flatMap(a=>a.atoms));
    for(const action of frame?.actions||[]){
      if(action.kind==='Move')for(const atom of action.patch.atoms){const start=frame.entry.atoms.get(atom.id);if(!start)continue;const [x,y]=xy(start.x,start.y),[tx,ty]=xy(atom.x,atom.y);ctx.strokeStyle='#5ea5a1';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(tx,ty);ctx.stroke();ctx.setLineDash([]);}
      if(action.kind==='CZPulse')for(const [a,b] of action.pairs){const first=state.get(a),last=state.get(b);const [x,y]=xy(first.x,first.y),[tx,ty]=xy(last.x,last.y);ctx.strokeStyle='#9a5ca7';ctx.lineWidth=3;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(tx,ty);ctx.stroke();ctx.lineWidth=1;}
    }
    canvasPositions=[];for(const atom of state.values()){
      const [x,y]=xy(atom.x,atom.y),hot=active.has(atom.id);canvasPositions.push({id:atom.id,x,y});
      if(hot){ctx.fillStyle='#dab9e455';ctx.beginPath();ctx.arc(x,y,7,0,2*Math.PI);ctx.fill();}
      ctx.fillStyle=hot?'#9455a3':atom.holder.kind==='aod'?'#158b7d':'#477bb1';ctx.beginPath();ctx.arc(x,y,3,0,2*Math.PI);ctx.fill();
      ctx.font='10px "Segoe UI",sans-serif';ctx.fillStyle='#365365';ctx.textAlign='center';ctx.fillText(String(atom.id),x+(atom.id%2?11:-11),y+3);
      if(atom.id===chosenAtom){ctx.strokeStyle='#203b49';ctx.beginPath();ctx.arc(x,y,6,0,2*Math.PI);ctx.stroke();}
    }
    ctx.textAlign='left';ctx.fillStyle='#7f929a';ctx.fillText('布局旋转显示，距离不变；数字为原子编号',12,box.height-10);
  }
  function animate(timestamp){
    if(!playing)return;const dt=previousTimestamp===null?0:Math.min(timestamp-previousTimestamp,100);previousTimestamp=timestamp;
    time=Math.min(model.duration,time+dt*model.duration/30000);cursor=replay.cursorAtTime(time);render();if(time>=model.duration)stop();else raf=requestAnimationFrame(animate);
  }
  $('play').addEventListener('click',()=>{if(model.status!=='ok')return;if(playing){stop();return;}if(time>=model.duration){time=0;cursor=replay.cursorAtTime(0);}playing=true;previousTimestamp=null;$('play').textContent='暂停';raf=requestAnimationFrame(animate);});
  $('previous').addEventListener('click',()=>{stop();cursor={step:Math.max(0,cursor.step-1),fraction:0};render();});
  $('next').addEventListener('click',()=>{stop();cursor={step:Math.min(model.trace.steps.length,cursor.step+1),fraction:0};if(cursor.step===model.trace.steps.length)cursor.fraction=1;render();});
  $('progress').addEventListener('input',event=>{stop();time=Number(event.target.value)/10000*model.duration;cursor=replay.cursorAtTime(time);render();});
  $('case').addEventListener('change',event=>{selected=Number(event.target.value);time=0;chosenAtom=null;rebuild();});
  $('reset').addEventListener('click',()=>{params={...M.DEFAULTS};syncInputs();rebuild();});
  $('t2-enabled').addEventListener('change',event=>{params.t2Enabled=event.target.checked;rebuild();});
  $('schedule-filter').addEventListener('change',buildSchedule);
  $('stage').addEventListener('click',event=>{const box=$('stage').getBoundingClientRect(),x=event.clientX-box.left,y=event.clientY-box.top;const candidates=canvasPositions.filter(a=>Math.hypot(a.x-x,a.y-y)<12).sort((a,b)=>Math.hypot(a.x-x,a.y-y)-Math.hypot(b.x-x,b.y-y));chosenAtom=candidates[0]?.id??null;if(model.status==='ok')render();else draw();});
  $('export').addEventListener('click',()=>{
    const report={schema:'nadit.shor-lab-cn/1',circuit:data.traces[selected].lab,parameters:Object.fromEntries(groups.flatMap(g=>g[2].map(s=>[s[0],params[s[0]]]))),t2Enabled:params.t2Enabled,status:model.status,duration_us:Number.isFinite(model.duration)?model.duration:null,duration_infinite:model.duration===Infinity,current:model.status==='ok'?M.at(model,time):null,final:finalRisk,scope:'物理原子丢失与T2衰减预算；模拟平均 loss 是粗估，不是电路失败率。'};
    const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'})),link=e('a');link.href=url;link.download='N'+data.traces[selected].lab.n+'-实验参数与统计.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  new ResizeObserver(draw).observe($('stage'));setupParameters();rebuild();
})();
