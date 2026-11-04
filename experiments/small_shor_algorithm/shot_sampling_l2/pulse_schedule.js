/* Draw the engine's pulse schedule without deriving another timing model. */
(function (root) {
  'use strict';
  const COLORS = {X:'#087e82',Y:'#ce6e27',gate:'#5e7eb2',cz:'#7957a6',measure:'#4b8b62',reset:'#7f9d6c',context:'#c6d0d5',idle:'#edf0f2'};
  const CONTEXT = new Set(['Move','Load','Store','Wait']);
  const LABELS = {Move:'搬运',Load:'装载 LOAD',Store:'卸载 STORE',Wait:'等待',LocalU:'单比特门',CZPulse:'CZ',Measure:'测量',Reset:'初始化'};
  const $ = id => document.getElementById(id);
  const fmt = value => Number(value).toLocaleString('zh-CN',{maximumFractionDigits:3});
  let current = null, zoom = 0, start = 0, bound = false, hits = [], plot = null;

  function condition(action) {
    if (!action.guard) return 'unconditional';
    if (current.selected_bitstring === null || current.selected_bitstring === undefined) return 'pending';
    const bit = current.selected_bitstring[current.selected_bitstring.length - 1 - action.guard.bit];
    return Number(bit) === action.guard.value ? 'active' : 'skipped';
  }
  function span() {
    return current ? Math.max(current.duration_us,1e-9) / (2 ** zoom) : 1;
  }
  function fitStart() {
    start = Math.max(0,Math.min(start,Math.max(0,current.duration_us-span())));
  }
  function syncControls() {
    const available = Math.max(0,current.duration_us-span());
    $('pulse-zoom').value = String(zoom);
    $('pulse-zoom-label').textContent = fmt(2 ** zoom)+'×';
    $('pulse-position').value = String(available ? Math.round(start/available*1000) : 0);
    $('pulse-position').disabled = available === 0;
    $('pulse-window').textContent = '当前范围：'+fmt(start)+'–'+fmt(Math.min(current.duration_us,start+span()))+' μs';
  }
  function canvasContext(canvas,height,minWidth) {
    const width = Math.max(minWidth || 0,canvas.parentElement.clientWidth || 680);
    const dpr = root.devicePixelRatio || 1;
    canvas.style.height = height+'px';
    canvas.width = Math.round(width*dpr);canvas.height = Math.round(height*dpr);
    const ctx = canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,width,height);
    return {ctx,width,height};
  }
  function describe(item) {
    if (item.type === 'pulse') {
      const p = item.data;
      return 'DD '+p.axis+' 脉冲；'+(p.scope_label||(p.scope==='storage_during_readout'?'读出期间的存储区保护':'空闲期间的全局保护'))+'；瞬时旋转时刻 '+fmt(p.time_us)+' μs；预留时间 '+fmt(p.start_us)+'–'+fmt(p.end_us)+' μs（宽 '+fmt(p.end_us-p.start_us)+' μs）；作用于 '+p.qubits.map(q=>'q'+q).join('、')+'。槽宽不表示有限脉宽动力学。';
    }
    const a = item.data, state = condition(a);
    let text = (a.label || LABELS[a.kind] || a.kind)+'；'+a.qubits.map(q=>'q'+q).join('、')+'；时间槽 '+fmt(a.start_us)+'–'+fmt(a.end_us)+' μs（'+fmt(a.end_us-a.start_us)+' μs）';
    if (a.guard) {
      text += '；条件 b['+a.guard.bit+'] = '+a.guard.value;
      text += state === 'pending' ? '，尚未选定测量分支' : state === 'skipped' ? '，本分支不作用门，保留空闲时间槽' : '，本分支执行';
    }
    if (Number.isFinite(a.quantum_time_us) && state !== 'skipped') text += '；量子操作时刻 '+fmt(a.quantum_time_us)+' μs';
    return text+'。';
  }
  function addHit(type,data,x,y,width,height) {
    hits.push({type,data,x,y,width,height});
  }
  function drawOverview() {
    const {ctx,width,height} = canvasContext($('pulse-overview'),52,0);
    const left = 10, right = width-10, total = Math.max(current.duration_us,1e-9), x=t=>left+t/total*(right-left);
    ctx.fillStyle='#edf3f5';ctx.fillRect(left,13,right-left,22);
    for (const a of current.actions) {
      if (CONTEXT.has(a.kind)) continue;
      ctx.fillStyle=a.kind==='CZPulse'?COLORS.cz:COLORS.gate;
      ctx.globalAlpha=.35;ctx.fillRect(x(a.start_us),13,Math.max(.6,x(a.end_us)-x(a.start_us)),22);
    }
    ctx.globalAlpha=.65;
    for (const p of current.pulses) {ctx.fillStyle=COLORS[p.axis]||COLORS.X;ctx.fillRect(x(p.time_us),9,1,30);}
    ctx.globalAlpha=1;
    const a=x(start), b=x(Math.min(current.duration_us,start+span()));
    ctx.fillStyle='rgba(8,126,130,.10)';ctx.fillRect(a,5,Math.max(2,b-a),38);
    ctx.strokeStyle='#087e82';ctx.lineWidth=1.5;ctx.strokeRect(a,5,Math.max(2,b-a),38);
    ctx.fillStyle='#617883';ctx.font='10px "Microsoft YaHei",sans-serif';ctx.textAlign='left';ctx.fillText('0',left,height-2);ctx.textAlign='right';ctx.fillText(fmt(total/1000)+' ms',right,height-2);
  }
  function draw() {
    if (!current) return;
    fitStart();syncControls();hits=[];
    const row=29, top=39, bottom=34, rows=current.qubits.length+1;
    const {ctx,width,height} = canvasContext($('pulse-canvas'),top+rows*row+bottom,520);
    const left=104, right=width-16, view=span(), x=t=>left+(t-start)/view*(right-left);
    const yIndex=new Map(current.qubits.map((q,i)=>[q.qubit,i+1]));
    const y=q=>top+(yIndex.get(q)+.5)*row;
    plot={left,right,top,row,width,height,start,end:start+view};
    ctx.font='11px "Microsoft YaHei",sans-serif';ctx.textBaseline='middle';
    for (let i=0;i<rows;i++) {
      ctx.fillStyle=i%2?'#fff':'#f5f8f9';ctx.fillRect(0,top+i*row,width,row);
      ctx.fillStyle='#526c79';ctx.textAlign='right';
      const q=current.qubits[i-1];ctx.fillText(i===0?'DD 脉冲':'q'+q.qubit+' · 原子 '+q.atom,left-10,top+(i+.5)*row);
    }
    const unit = current.duration_us>=1000 ? 1000 : 1;
    ctx.fillStyle='#617883';ctx.textAlign='left';ctx.fillText('物理时间（'+(unit===1000?'ms':'μs')+'）',left,14);
    const tickCount=Math.max(3,Math.min(8,Math.floor((right-left)/90)));
    for(let i=0;i<=tickCount;i++) {
      const t=start+view*i/tickCount,px=x(t);
      ctx.strokeStyle='#dfe8ec';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(px,top);ctx.lineTo(px,height-bottom);ctx.stroke();
      ctx.fillStyle='#617883';ctx.textAlign=i===0?'left':i===tickCount?'right':'center';ctx.fillText(fmt(t/unit),px,height-15);
    }
    ctx.save();ctx.beginPath();ctx.rect(left,top,right-left,height-top-bottom);ctx.clip();
    for(const b of current.blocks) {
      if(b.end_us<start||b.start_us>start+view) continue;
      ctx.fillStyle='rgba(8,126,130,.08)';ctx.fillRect(x(b.start_us),top+3,Math.max(1,x(b.end_us)-x(b.start_us)),row-6);
    }
    const showContext=$('pulse-context').checked;
    // A separate pass keeps transport backgrounds below gate and pulse marks.
    for(const context of [true,false]) for(const a of current.actions) {
      if(CONTEXT.has(a.kind)!==context||(context&&!showContext)||a.end_us<start||a.start_us>start+view) continue;
      const status=condition(a),color=context?COLORS.context:a.kind==='CZPulse'?COLORS.cz:a.kind==='Measure'?COLORS.measure:a.kind==='Reset'?COLORS.reset:COLORS.gate;
      const xs=x(a.start_us),xe=x(a.end_us),barWidth=Math.max(1,xe-xs),barHeight=context?8:18;
      if(a.kind==='CZPulse'&&a.qubits.length>1) {
        for(const pair of a.pairs || [a.qubits]) {
          const positions=pair.filter(q=>yIndex.has(q)).map(y);
          if(positions.length>1){ctx.strokeStyle=color;ctx.lineWidth=1.2;ctx.beginPath();ctx.moveTo(xs,Math.min(...positions));ctx.lineTo(xs,Math.max(...positions));ctx.stroke();}
        }
      }
      for(const q of a.qubits) {
        if(!yIndex.has(q)) continue;
        const cy=y(q),ys=cy-barHeight/2;
        ctx.fillStyle=status==='skipped'?COLORS.idle:color;ctx.globalAlpha=status==='pending'?.45:context?.7:1;
        ctx.fillRect(xs,ys,barWidth,barHeight);ctx.globalAlpha=1;
        if(status==='pending'||status==='skipped'){ctx.strokeStyle=status==='skipped'?'#9ba8ae':color;ctx.setLineDash([3,2]);ctx.strokeRect(xs,ys,barWidth,barHeight);ctx.setLineDash([]);}
        const label=status==='skipped'?'空闲':(a.label||LABELS[a.kind]||a.kind)+(status==='pending'?' ?':'');
        if(!context&&barWidth>ctx.measureText(label).width+7){ctx.fillStyle=status==='skipped'?'#617883':'#fff';ctx.textAlign='center';ctx.fillText(label,xs+barWidth/2,cy);}
        addHit('action',a,xs,ys,Math.max(4,barWidth),barHeight);
      }
    }
    for(const p of current.pulses) {
      if(p.end_us<start||p.start_us>start+view) continue;
      const cx=x(p.time_us),xs=x(p.start_us),pw=Math.max(1,x(p.end_us)-xs),color=COLORS[p.axis]||COLORS.X;
      const allY=[top+row/2,...p.qubits.filter(q=>yIndex.has(q)).map(y)];
      for(const cy of allY){ctx.fillStyle=color;ctx.globalAlpha=.18;ctx.fillRect(xs,cy-10,pw,20);ctx.globalAlpha=1;ctx.fillRect(cx-.6,cy-10,1.2,20);addHit('pulse',p,cx-3,cy-11,6,22);}
      if(pw>=10){ctx.fillStyle=color;ctx.textAlign='center';ctx.fillText(p.axis,cx,top+row/2);}
    }
    ctx.restore();drawOverview();
  }
  function inspect(event) {
    if (!current||!plot) return;
    const box=$('pulse-canvas').getBoundingClientRect(),px=(event.clientX-box.left)*plot.width/box.width,py=(event.clientY-box.top)*plot.height/box.height;
    if(px<plot.left||px>plot.right||py<plot.top)return;
    const candidates=hits.filter(h=>px>=h.x-2&&px<=h.x+h.width+2&&py>=h.y&&py<=h.y+h.height);
    candidates.sort((a,b)=>(a.type==='pulse'?0:1)-(b.type==='pulse'?0:1)||Math.abs(px-a.x-a.width/2)-Math.abs(px-b.x-b.width/2));
    if(candidates.length)$('pulse-detail').textContent=describe(candidates[0]);
  }
  function bind() {
    if (bound) return;
    for(const id of ['pulse-panel','pulse-canvas','pulse-overview','pulse-zoom','pulse-position']) if(!$(id)) throw Error('缺少脉冲调度图元素：'+id);
    bound=true;
    $('pulse-full').addEventListener('click',()=>{zoom=0;start=0;draw();});
    $('pulse-readout').addEventListener('click',()=>{
      if(!current)return;const block=current.blocks.find(b=>b.scope==='storage_during_readout');if(!block)return;
      const width=Math.max(block.end_us-block.start_us,1)*1.5;
      zoom=Math.min(10,Math.max(0,Math.floor(Math.log2(Math.max(current.duration_us,1)/width)*4)/4));
      start=(block.start_us+block.end_us)/2-span()/2;draw();
      $('pulse-detail').textContent='读出期间，X/Y 作用于存储区原子 '+block.qubits.map(q=>'q'+q).join('、')+'；测量原子不参与这一组脉冲。';
    });
    $('pulse-zoom').addEventListener('input',event=>{if(!current)return;const center=start+span()/2;zoom=Number(event.target.value);start=center-span()/2;draw();});
    $('pulse-position').addEventListener('input',event=>{if(!current)return;start=Number(event.target.value)/1000*Math.max(0,current.duration_us-span());draw();});
    $('pulse-context').addEventListener('change',draw);
    $('pulse-canvas').addEventListener('mousemove',inspect);$('pulse-canvas').addEventListener('click',inspect);
    $('pulse-overview').addEventListener('click',event=>{if(!current)return;const box=event.currentTarget.getBoundingClientRect();const ratio=Math.max(0,Math.min(1,(event.clientX-box.left-10)/(box.width-20)));start=ratio*current.duration_us-span()/2;draw();});
    if(typeof ResizeObserver!=='undefined')new ResizeObserver(()=>draw()).observe($('pulse-panel'));
    else root.addEventListener('resize',draw);
  }
  function render(schedule) {
    bind();
    if(!schedule||!Number.isFinite(schedule.duration_us)||schedule.duration_us<0||!Array.isArray(schedule.qubits)||!Array.isArray(schedule.actions)||!Array.isArray(schedule.pulses)||!Array.isArray(schedule.blocks)) throw Error('脉冲调度数据格式无效。');
    current=schedule;zoom=0;start=0;
    $('pulse-readout').disabled=!schedule.blocks.some(b=>b.scope==='storage_during_readout');
    $('pulse-summary').textContent=fmt(schedule.duration_us/1000)+' ms · '+schedule.pulses.length+' 个 DD 脉冲';
    $('pulse-branch').textContent=schedule.selected_bitstring===null||schedule.selected_bitstring===undefined?'尚未采样，条件门显示为待定。':(schedule.selection_label||'本次采样选定的读数分支')+'：'+schedule.selected_bitstring+'。';
    $('pulse-detail').textContent='将鼠标移到脉冲或门上，可查看时间、作用比特和条件。';
    draw();
  }
  root.ShorPulseSchedule={render};
})(typeof window!=='undefined'?window:globalThis);
