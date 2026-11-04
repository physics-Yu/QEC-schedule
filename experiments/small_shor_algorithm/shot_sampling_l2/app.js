
'use strict';
const $=id=>document.getElementById(id);
const groups=[
 ['时间与相干',true,[
  ['speed','移动平均速度','μm/μs',2,.01,'耗时由距离除以速度得到；最小值 0.01 μm/μs。'],
  ['transfer','每次 LOAD／STORE','μs',1000,1,'每次并行转移的时间，可调范围 0–1000 μs。'],
  ['readout','每次读出曝光','μs',1000,10,'曝光结束时进行 Z 测量并返回比特，可立即判断条件门；没有额外返回延迟。']]],
 ['退相位与 DD（层级 2）',true,[
  ['t2Star','单格点 T₂*','ms',20,.1,'单格点 Ramsey 的 1/e 时间（已含快涨落的贡献）；0 表示不含静态部分。'],
  ['t2Echo','T₂^echo','ms',2000,1,'Hahn echo（中间只打一个 π 脉冲）的 1/e 时间，用来确定涨落强度。'],
  ['tauC','涨落关联时间 τ_c','ms',100,.01,'失谐涨落保持相关的时间；由实验噪声谱标定。必须大于 0。'],
  ['dd','XY4 动态解耦','',1,1,'开启时插入 X–Y–X–Y 脉冲块；测量区读出期间，存储区空闲原子继续接受保护。'],
  ['tPi','π 脉冲时长 t_π','μs',50,.1,'微波约 20 μs，Raman 约 1 μs；最小间隔 τ_min = 5·t_π，区间短于 4·τ_min 时不放块。'],
  ['tauMax','DD 最大间隔 τ_max','μs',2000,1,'每段空闲放 n = ⌈L / (4·τ_max)⌉ 个块；不得小于 5·t_π。'],
  ['pulseError','脉冲转角误差','比例',.1,.001,'每个 π 脉冲实际转 π·(1 + 误差)，所有原子相同；0 为理想脉冲。'],
  ['pulseDuringTransfer','转移期间可打脉冲','',1,1,'关闭时，LOAD／STORE 期间不打脉冲，空闲区间在转移处切开。']]],
 ['每次操作的原子丢失概率',false,[
  ['loadLoss','LOAD 丢失概率','概率',.05,.0001,'每颗原子、每次装载；NAL 默认 0.002。'],
  ['storeLoss','STORE 丢失概率','概率',.05,.0001,'每颗原子、每次卸载；NAL 默认 0.002。'],
  ['czLoss','CZ 丢失概率','概率',.05,.0001,'每颗参与原子、每次 CZ 的丢失概率。'],
  ['imagingLoss','成像丢失概率','概率',.05,.0001,'每颗被测原子的成像丢失概率。'],
  ['singleLoss','单比特门丢失概率','概率',.05,.0001,'仅实际执行的单比特门计入。'],
  ['resetLoss','初始化丢失概率','概率',.05,.0001,'每颗原子、每次初始化。']]],
 ['门时间与量子错误',false,[
  ['singleTime','单比特门时间','μs',10,.1,'条件为假时也保留同样长的空闲时间槽。'],
  ['czTime','CZ 门时间','μs',10,.01,'一个并行 CZ 脉冲的时间。'],
  ['resetTime','初始化时间','μs',500,1,'每次初始化的时间。'],
  ['singlePauli','单比特 Pauli 错误','概率',.1,.0001,'总错误概率；非零时 X、Y、Z 等概率，属于噪声假设。'],
  ['czPauli','CZ Pauli 错误','概率',.1,.0001,'每对原子的总错误概率；15 个非平凡双比特 Pauli 等概率。'],
  ['readoutError','读出误判概率','概率',.1,.0001,'测量坍缩后，翻转报告比特的概率；与成像丢失分开。'],
  ['resetError','初始化错误概率','概率',.1,.0001,'初始化后处于错误计算基态的概率。']]],
 ['搬运模型参数（论文假设）',false,[
  ['mass','原子质量','u',180,.001,'87Rb 示例；0 时物理模型无定义。'],
  ['frequency','陷阱频率 f','kHz',500,1,'角频率 ω=2πf；0 时模型无定义。'],
  ['width','有效阱宽 a','μm',3,.01,'用于计算平均阱深；0 时模型无定义。'],
  ['temperature','原子温度 T','μK',200,1,'每次搬运独立使用这一温度；0 为零温极限。'],
  ['depthSpread','阱深相对标准差','比例',.5,.01,'标准差除以平均阱深；0 为均匀阱深。']]]
];
const switchKeys=new Set(['dd','pulseDuringTransfer']);
let defaults={},parameters={},lastResult=null,lastRequest=null,controller=null,requestVersion=0,chartBins=[];
const number=x=>Number(x).toLocaleString('zh-CN',{maximumFractionDigits:4});
const percent=x=>number(100*x)+'%';
function element(tag,text){const el=document.createElement(tag);if(text!==undefined)el.textContent=text;return el;}
function status(text,error=false){$('status').textContent=text;$('status').className=error?'error':'';}
function errorText(text){const labels=Object.fromEntries(groups.flatMap(group=>group[2].map(spec=>[spec[0],spec[1]])));const zero=text.match(/^(\w+)=0: no finite physical simulation is defined\.$/);if(zero)return (labels[zero[1]]||zero[1])+'为 0，当前物理模型无法完成有限时间的计算，请输入正值。';const probability=text.match(/^(\w+) must be between 0 and 1\.$/);if(probability)return (labels[probability[1]]||probability[1])+'必须在 0 到 1 之间。';return text;}
function stale(){if(lastResult)status('参数已修改。图中仍为上次采样结果；点击“开始采样”更新。');}
function syncSwitch(key){const button=$('switch-'+key);if(button){button.setAttribute('aria-checked',String(parameters[key]===1));$('switch-state-'+key).textContent=parameters[key]===1?'开启':'关闭';}}
function sync(){for(const [,,specs] of groups)for(const [key] of specs){if(switchKeys.has(key)){syncSwitch(key);continue;}const range=$('range-'+key),input=$('number-'+key);if(range){range.value=parameters[key];input.value=parameters[key];}}}
function readInputs(){
 const values={...parameters};
 for(const [,,specs] of groups)for(const [key,label] of specs){if(switchKeys.has(key)){values[key]=$('switch-'+key).getAttribute('aria-checked')==='true'?1:0;continue;}const input=$('number-'+key);if(!input)continue;const value=Number(input.value);
  if(input.value===''||!Number.isFinite(value)||value<0)throw Error(label+'请输入非负有限数。');values[key]=value;
 }return values;
}
function buildParameters(){
 for(const [title,open,specs] of groups){const section=element('details');section.open=open;section.append(element('summary',title));
  for(const [key,label,unit,max,step,note] of specs){if(!(key in defaults))continue;const field=element('div');field.className='field';
   if(switchKeys.has(key)){
    const top=element('div');top.className='switch-field-top';const button=element('button');button.type='button';button.id='switch-'+key;button.className='parameter-switch';button.setAttribute('role','switch');button.setAttribute('aria-label',label);button.setAttribute('aria-checked','false');
    const state=element('span');state.id='switch-state-'+key;state.className='switch-state';state.setAttribute('aria-hidden','true');const control=element('div');control.className='switch-control';control.append(button,state);top.append(element('span',label),control);field.append(top,element('small',note));section.append(field);
    button.addEventListener('click',()=>{parameters[key]=button.getAttribute('aria-checked')==='true'?0:1;syncSwitch(key);stale();});continue;
   }
   const top=element('div');top.className='field-top';const caption=element('label',label);caption.htmlFor='range-'+key;const input=element('input');input.type='number';input.id='number-'+key;input.min=key==='speed'?0.01:0;if(key==='transfer')input.max=1000;input.step=step;input.setAttribute('aria-label',label+'数值');const range=element('input');range.type='range';range.id='range-'+key;range.min=key==='speed'?0.01:0;range.max=max;range.step=step;range.setAttribute('aria-label',label);top.append(caption,input,element('small',unit));field.append(top,range,element('small',note));section.append(field);
   function update(event){const value=Number(event.target.value);if(event.target.value===''||!Number.isFinite(value)||value<(key==='speed'?0.01:0)||(key==='transfer'&&value>1000)){event.target.value=parameters[key];status(key==='speed'?'移动速度不能小于 0.01 μm/μs。':key==='transfer'?'LOAD／STORE 时间必须在 0–1000 μs。':'请输入非负有限数。',true);return;}parameters[key]=value;sync();stale();}input.addEventListener('change',update);range.addEventListener('input',update);
  }$('parameter-groups').append(section);
 }sync();
}
function wilson(k,n){const z=1.95996398454,p=k/n,d=1+z*z/n,c=(p+z*z/(2*n))/d,h=z*Math.sqrt(p*(1-p)/n+z*z/(4*n*n))/d;return [Math.max(0,c-h),Math.min(1,c+h)];}
function rows(id,records){const root=$(id);root.replaceChildren();for(const cells of records){const tr=element('tr');for(const cell of cells)tr.append(element('td',String(cell)));root.append(tr);}}
function draw(){
 if(!lastResult)return;const canvas=$('histogram'),rect=canvas.getBoundingClientRect();if(rect.width<=0||rect.height<=0)return;const dpr=window.devicePixelRatio||1;canvas.width=Math.round(rect.width*dpr);canvas.height=Math.round(rect.height*dpr);const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);const w=rect.width,h=rect.height,pad={left:49,right:14,top:20,bottom:34};const bins=2**(lastRequest.n===15?8:9);chartBins=Array(bins).fill(0);for(const [key,value] of Object.entries(lastResult.histogram))chartBins[parseInt(key,2)]=value/lastResult.shots;const ceiling=Math.max(.01,...chartBins)*1.08;const plotW=w-pad.left-pad.right,plotH=h-pad.top-pad.bottom;
 ctx.font='11px "Microsoft YaHei",sans-serif';ctx.textAlign='right';for(let i=0;i<=4;i++){const y=pad.top+plotH*(1-i/4);ctx.strokeStyle='#e0e8eb';ctx.beginPath();ctx.moveTo(pad.left,y);ctx.lineTo(w-pad.right,y);ctx.stroke();ctx.fillStyle='#617883';ctx.fillText(percent(ceiling*i/4),pad.left-7,y+4);}
 ctx.fillStyle='#087e82';for(let i=0;i<bins;i++){const barH=chartBins[i]/ceiling*plotH;ctx.fillRect(pad.left+i*plotW/bins,pad.top+plotH-barH,Math.max(.8,plotW/bins),barH);}ctx.textAlign='center';ctx.fillStyle='#617883';for(let i=0;i<=4;i++){const value=Math.round(i*(bins-1)/4);ctx.fillText(String(value),pad.left+(value+.5)*plotW/bins,h-10);}
}
function render(result,request){
 lastResult=result;lastRequest=request;$('results').hidden=false;$('empty').hidden=true;$('download').disabled=false;
 $('total-shots').textContent=number(result.shots);$('valid-shots').textContent=number(result.valid_shots);$('loss-rate').textContent=percent(result.lost_shots/result.shots);$('duration').textContent=number(result.plan_duration_us/1000)+' ms';$('loss-bar').style.width=100*result.lost_shots/result.shots+'%';$('loss-count').textContent=result.lost_shots+' / '+result.shots;
 const ci=wilson(result.lost_shots,result.shots);$('uncertainty').textContent='丢失运行比例的 95% Wilson 区间：'+percent(ci[0])+'–'+percent(ci[1])+'。采样误差不包含物理模型和标定误差。';$('run-description').textContent='本次结果：N='+request.n+'，种子 '+result.seed+'，采样用时 '+number(result.elapsed_seconds)+' s。完整参数可导出。';
 {const l2=result.level2,fmt=x=>number(Number(x.toPrecision(3)));let text='';
  if(l2){text='本次 L2 模拟：σ_s/(2π) = '+fmt(l2.sigma_s_hz)+' Hz，σ_f/(2π) = '+fmt(l2.sigma_f_hz)+' Hz，τ_c = '+fmt(l2.tau_c_ms)+' ms。';
   const d=l2.dd;text+=d.enabled?' XY4：'+d.blocks+' 个块、'+d.pulses+' 个脉冲；其中 '+(d.storage_readout_pulses||0)+' 个在测量期间作用于存储区。':' 未插入 DD。';}
  $('noise-description').textContent=text;}
 rows('histogram-rows',Object.entries(result.histogram).sort((a,b)=>parseInt(a[0],2)-parseInt(b[0],2)).map(([bits,count])=>[bits,parseInt(bits,2),count,percent(count/result.shots),result.valid_shots?percent(count/result.valid_shots):'—']));
 const names={load:'装载 LOAD',store:'卸载 STORE',move:'搬运',cz:'CZ 门',imaging:'成像',single:'单比特门',reset:'初始化'};
 rows('loss-causes',Object.entries(result.first_loss_by_cause||{}).map(([key,count])=>[names[key]||key,count]));rows('loss-atoms',Object.entries(result.first_loss_by_atom||{}).map(([key,count])=>['原子 '+key,count]));draw();syncReplay(request,result);if(result.pulse_schedule)ShorPulseSchedule.render(result.pulse_schedule);
}

// The standard compiler viewer owns animation; this page only shares parameters.
// Mechanical replay shares L2 timing/loss preparation; DD has its own 2D view.
let replayRequest=null,replayRisk=null,replayTime=0;
function sendReplay(){const frame=$('compile-animation');if(frame&&replayRequest)frame.contentWindow.postMessage(replayRequest,'*');}
function syncReplay(request,result){
 const rows=Object.entries(result?.histogram||{}).sort((a,b)=>b[1]-a[1]);
 replayRequest={type:'shor-replay-parameters',n:request.n,parameters:{...request.parameters},bitstring:rows[0]?.[0]||null,
  selection_label:rows.length?'本次无丢失样本中出现次数最多的测量分支':result?'未取得无丢失的完整读数，使用固定参考分支':'尚未采样，使用固定参考分支'};
 replayTime=0;sendReplay();
}
function drawRisk(){
 const canvas=$('atom-risk-curve');if(!canvas||!replayRisk)return;
 const points=replayRisk.curve,box=canvas.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
 canvas.width=Math.round(box.width*dpr);canvas.height=Math.round(box.height*dpr);
 const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);const w=box.width,h=box.height,left=64,right=18,top=18,bottom=38;
 const end=Math.max(replayRisk.duration_us,1),peak=Math.min(1,Math.max(.001,...points.map(p=>p.mean_loss))*1.12);
 const x=t=>left+(w-left-right)*t/end,y=p=>h-bottom-(h-top-bottom)*p/peak;
 ctx.font='11px "Microsoft YaHei",sans-serif';ctx.lineWidth=1;
 for(let i=0;i<=4;i++){const v=peak*i/4;ctx.strokeStyle='#e4ecef';ctx.beginPath();ctx.moveTo(left,y(v));ctx.lineTo(w-right,y(v));ctx.stroke();ctx.fillStyle='#617883';ctx.textAlign='right';ctx.fillText(percent(v),left-8,y(v)+4);ctx.textAlign='center';ctx.fillText(number(end*i/4000),x(end*i/4),h-bottom+18);}
 ctx.fillText('时间（ms）',w/2,h-3);ctx.strokeStyle='#087e82';ctx.lineWidth=2;ctx.beginPath();let last=0;
 for(const p of points){ctx.lineTo(x(p.time_us),y(last));ctx.lineTo(x(p.time_us),y(p.mean_loss));last=p.mean_loss;}ctx.lineTo(x(end),y(last));ctx.stroke();
 let current=0;for(const p of points){if(p.time_us>replayTime)break;current=p.mean_loss;}
 const marker=Math.max(0,Math.min(replayTime,end));ctx.strokeStyle='#bd6351';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(x(marker),top);ctx.lineTo(x(marker),h-bottom);ctx.stroke();
 $('risk-at-time').textContent='动画时刻 '+number(marker/1000)+' ms：平均原子丢失概率 '+percent(current)+'；计划结束时 '+percent(replayRisk.final_mean_loss)+'。';
}
window.addEventListener('message',event=>{
 const frame=$('compile-animation');if(!frame||event.source!==frame.contentWindow)return;
 const data=event.data||{};
 if(data.type==='shor-replay-ready')sendReplay();
 else if(data.type==='shor-replay-risk'){
  replayRisk=data;replayTime=0;
  $('replay-description').textContent='N='+data.n+'；'+data.selection_label+'：'+data.bitstring+'。时间和曲线使用本次提交的参数；动画显示计划，不回放随机 Pauli 错误，也不随机移除原子。';drawRisk();
 }else if(data.type==='shor-replay-error'){$('replay-description').textContent='动画更新失败：'+data.message;}else if(data.type==='shor-replay-clock'&&Number.isFinite(data.time_us)){replayTime=data.time_us;drawRisk();}
});
if($('compile-animation')){$('compile-animation').addEventListener('load',sendReplay);new ResizeObserver(drawRisk).observe($('atom-risk-curve'));}

$('fixed-seed').addEventListener('change',()=>{$('seed').disabled=!$('fixed-seed').checked;});
$('defaults').addEventListener('click',()=>{parameters={...defaults};sync();stale();});$('circuit').addEventListener('change',()=>{stale();if(!lastResult)ShorPulseSchedule.render(ShorOffline.schedules[$('circuit').value]);});
$('run').addEventListener('click',async()=>{
 try{parameters=readInputs();sync();}catch(error){status(error.message,true);return;}
 const shots=Number($('shots').value);if(!Number.isInteger(shots)||shots<1||shots>10000){status('采样次数必须是 1–10000 的整数。',true);return;}
 const seed=$('fixed-seed').checked?Number($('seed').value):crypto.getRandomValues(new Uint32Array(1))[0];if(!Number.isInteger(seed)||seed<0||seed>4294967295){status('随机种子必须是 0–4294967295 的整数。',true);return;}
 const request={n:Number($('circuit').value),parameters:{...parameters},shots,seed},version=++requestVersion;controller=new AbortController();$('run').disabled=true;$('stop').disabled=false;$('results').hidden=true;$('download').disabled=true;$('empty').hidden=false;$('empty').textContent='正在计算本次参数…';status('正在独立采样 '+shots+' 次…');
 try{const result=await window.ShorOffline.run(request,controller.signal);if(version!==requestVersion)return;render(result,request);const changed=JSON.stringify(parameters)!==JSON.stringify(request.parameters)||Number($('circuit').value)!==request.n;status(changed?'采样完成；参数已在计算期间修改，当前图仍对应所提交的参数。':'采样完成。');}
 catch(error){if(version===requestVersion){$('empty').textContent='本次参数尚未生成结果。';status(error.name==='AbortError'?'已停止本次采样。':errorText(error.message),error.name!=='AbortError');}}
 finally{if(version===requestVersion){controller=null;$('run').disabled=false;$('stop').disabled=true;}}
});
$('stop').addEventListener('click',()=>{if(controller)controller.abort();});
$('download').addEventListener('click',()=>{if(!lastResult)return;const url=URL.createObjectURL(new Blob([JSON.stringify({request:lastRequest,result:lastResult},null,2)],{type:'application/json'}));const a=element('a');a.href=url;a.download='shor-'+lastRequest.n+'-shots-'+lastResult.seed+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$('histogram').addEventListener('mousemove',event=>{if(!lastResult)return;const rect=event.currentTarget.getBoundingClientRect(),x=event.clientX-rect.left;const index=Math.floor((x-49)/(rect.width-63)*chartBins.length);if(index<0||index>=chartBins.length)return;const bits=index.toString(2).padStart(lastRequest.n===15?8:9,'0'),count=lastResult.histogram[bits]||0;$('chart-hover').textContent='读数 '+index+'（'+bits+'）：'+count+' 次，占全部运行 '+percent(count/lastResult.shots)+'。';});
new ResizeObserver(draw).observe($('histogram'));
(async()=>{try{defaults=window.ShorOffline.defaults;$('stop').textContent='停止采样';parameters={...defaults};buildParameters();$('run').disabled=false;status('参数已载入，尚未采样。');syncReplay({n:Number($('circuit').value),parameters},null);ShorPulseSchedule.render(ShorOffline.schedules[$('circuit').value]);}catch(error){status(error.message+'。请使用支持 Web Worker 的现代浏览器打开此 HTML。',true);}})();
