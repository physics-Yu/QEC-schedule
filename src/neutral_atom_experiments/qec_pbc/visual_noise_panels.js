/* Read-only presentation of seeded Stim / MWPM experiment evidence. */
window.QECNoisePanels = {
  renderE5(container, data) {
    const {el, svg, box, table, fmt} = window.QECViz.helpers;
    container.replaceChildren();
    const names = {gate_only: '门噪声 gate-only', readout_only: '读出噪声 readout-only', both: '门＋读出 both'};
    const colors = {gate_only: 'var(--series1)', readout_only: 'var(--series2)', both: 'var(--series3)'};
    const num = (x, digits=3) => Number(x).toFixed(digits);
    const allPoints = data.curves.flatMap(c => c.points);
    const maxP = Math.max(...allPoints.map(p => p.event_probability));
    const maxY = Math.max(0.01, ...allPoints.map(p => p.wilson_95[1])) * 1.12;

    function memoryChart(basis) {
      const W=560, H=350, left=66, right=24, top=22, bottom=63;
      const x=p=>left+p/maxP*(W-left-right);
      const y=p=>H-bottom-p/maxY*(H-top-bottom);
      const chart=svg('svg', {viewBox:`0 0 ${W} ${H}`, width:'100%', role:'img',
        'aria-label':`${basis} memory：人工 Pauli 事件概率与逻辑失败率，含 95% 置信区间`});
      chart.append(svg('rect',{x:0,y:0,width:W,height:H,fill:'var(--surface)'}));
      for(let i=0;i<=4;i++) {
        const py=maxY*i/4;
        chart.append(svg('line',{x1:left,x2:W-right,y1:y(py),y2:y(py),stroke:'var(--border)'}),
          svg('text',{x:left-9,y:y(py)+4,'text-anchor':'end',fill:'var(--muted)','font-size':12},`${num(py*100,1)}%`));
      }
      const xs=[...new Set(allPoints.map(p=>p.event_probability))].sort((a,b)=>a-b);
      for(const p of xs) chart.append(svg('text',{x:x(p),y:H-bottom+23,'text-anchor':'middle',fill:'var(--muted)','font-size':12},`${num(p*100,1)}%`));
      chart.append(svg('line',{x1:left,x2:W-right,y1:H-bottom,y2:H-bottom,stroke:'var(--foreground)'}),
        svg('line',{x1:left,x2:left,y1:top,y2:H-bottom,stroke:'var(--foreground)'}),
        svg('text',{x:(left+W-right)/2,y:H-12,'text-anchor':'middle',fill:'var(--foreground)','font-size':13},'人工单事件错误概率 p (%)'),
        svg('text',{x:16,y:(top+H-bottom)/2,transform:`rotate(-90 16 ${(top+H-bottom)/2})`,'text-anchor':'middle',fill:'var(--foreground)','font-size':13},'逻辑 observable 失败率 (%)'));
      for(const curve of data.curves.filter(c=>c.basis===basis)) {
        const color=colors[curve.scenario];
        chart.append(svg('polyline',{points:curve.points.map(p=>`${x(p.event_probability)},${y(p.logical_failure_probability)}`).join(' '),
          fill:'none',stroke:color,'stroke-width':2}));
        for(const p of curve.points) {
          const cx=x(p.event_probability), lo=y(p.wilson_95[0]), hi=y(p.wilson_95[1]);
          chart.append(svg('line',{x1:cx,x2:cx,y1:lo,y2:hi,stroke:color,'stroke-width':1.5}),
            svg('line',{x1:cx-4,x2:cx+4,y1:lo,y2:lo,stroke:color}),
            svg('line',{x1:cx-4,x2:cx+4,y1:hi,y2:hi,stroke:color}));
          const dot=svg('circle',{cx,cy:y(p.logical_failure_probability),r:3.5,fill:color});
          dot.append(svg('title',{},`${basis} ${names[curve.scenario]} p=${p.event_probability}; ${p.failures}/${p.shots}; Wilson 95% ${p.wilson_95.join('–')}; seed ${p.seed}`));
          chart.append(dot);
        }
      }
      return box(`${basis} memory · d=${data.distance}, ${data.rounds} rounds`,chart,
        el('p',{class:'muted'},'点为实际采样估计，竖线为 Wilson 95% 区间；两图使用相同坐标尺度。'));
    }

    container.append(box('E5 · 带噪 memory 与解码实验',
      el('p',{class:'scope'},'真实 Stim 采样与 PyMatching 解码；输入参数为人工设定。结果是逻辑 observable 失败率，不是完整量子态 fidelity 或中性原子实测性能。'),
      el('div',{class:'metrics'},
        el('div',{class:'metric'},`${data.shots_per_point.toLocaleString()} shots / 点`),
        el('div',{class:'metric'},`${allPoints.length} 个实际采样点`),
        el('div',{class:'metric'},`seed ${data.seed}`),
        el('div',{class:'metric'},`Stim ${data.versions.stim} · PyMatching ${data.versions.pymatching}`)),
      el('div',{class:'chips'},...Object.keys(names).map(key=>el('span',{style:`color:${colors[key]}`},`● ${names[key]}`)))));
    container.append(el('div',{class:'grid2'},memoryChart('X'),memoryChart('Z')));
    container.append(box('全部采样证据 · 30 点',table(
      ['Basis','噪声类别','事件 p','失败 / shots','逻辑失败率','Wilson 95%','seed'],
      data.curves.flatMap(c=>c.points.map(p=>[c.basis,names[c.scenario],`${num(p.event_probability*100,2)}%`,
        `${p.failures} / ${p.shots}`,`${num(p.logical_failure_probability*100,3)}%`,
        `${num(p.wilson_95[0]*100,3)}–${num(p.wilson_95[1]*100,3)}%`,String(p.seed)])))));

    const decay=data.dephasing, dp=decay.points;
    const dw=560,dh=265,dl=66,dr=22,dt=20,db=48;
    const timeMax=Math.max(...dp.map(p=>p.duration_us));
    const dx=t=>dl+t/timeMax*(dw-dl-dr),dy=v=>dh-db-v*(dh-dt-db);
    const ds=svg('svg',{viewBox:`0 0 ${dw} ${dh}`,width:'100%',role:'img','aria-label':'裸单比特纯退相干示意；时间微秒，contrast 和 pZ'});
    for(let i=0;i<=4;i++) ds.append(svg('line',{x1:dl,x2:dw-dr,y1:dy(i/4),y2:dy(i/4),stroke:'var(--border)'}),
      svg('text',{x:dl-8,y:dy(i/4)+4,'text-anchor':'end',fill:'var(--muted)','font-size':12},num(i/4,2)));
    for(const [key,label,color] of [['ramsey_contrast','相干对比度 contrast','var(--series1)'],['p_z','Z 错误概率 pZ','var(--series2)']]) {
      ds.append(svg('polyline',{points:dp.map(p=>`${dx(p.duration_us)},${dy(p[key])}`).join(' '),stroke:color,fill:'none','stroke-width':2}));
      for(const p of dp) {
        const dot=svg('circle',{cx:dx(p.duration_us),cy:dy(p[key]),r:3,fill:color});
        dot.append(svg('title',{},`${label}: ${p[key]}, t=${p.duration_us} μs`)); ds.append(dot);
      }
    }
    for(const t of [0,timeMax/2,timeMax]) ds.append(svg('text',{x:dx(t),y:dh-db+20,'text-anchor':'middle',fill:'var(--muted)','font-size':12},String(t/1000)));
    ds.append(svg('text',{x:dw/2,y:dh-6,'text-anchor':'middle',fill:'var(--foreground)','font-size':13},'等待时间 t (ms)'));
    container.append(box('裸单比特纯退相干示意 · 不是 logical lifetime',
      el('p',{class:'scope'},`人工 Tφ=${decay.parameters.tphi_us.toLocaleString()} μs；运输 depolarizing rate=${decay.parameters.move_depolarizing_rate_per_us}/μs 是独立示意参数，未构成完整 T1/T2 模型。`),
      el('div',{class:'chips'},el('span',{style:'color:var(--series1)'},'● contrast'),el('span',{style:'color:var(--series2)'},'● pZ')),
      ds,el('p',{class:'formula'},'contrast = exp(−t/Tφ)；pZ = (1−contrast)/2'),
      table(['t (μs)','contrast','pZ','独立运输 depolarization'],dp.map(p=>[String(p.duration_us),num(p.ramsey_contrast,6),num(p.p_z,6),num(p.move_depolarizing_probability,6)]))));

    const detail=el('div',{class:'stack'});
    let basis='X',kind='detected_and_decoded';
    function bits(title, entries) {
      return box(title,el('div',{class:'chips'},...entries.map(([key,bit])=>el('span',{
        title:`${key} = ${bit}`,style:`border:1px solid var(--border);padding:5px 7px;border-radius:5px;${bit ? 'background:var(--series3);color:var(--bg)' : 'background:var(--surface);color:var(--muted)'}`},`${key}: ${bit}`))));
    }
    function redraw() {
      detail.replaceChildren();
      const summary=data.shot_examples[basis],shot=summary.examples[kind];
      if(!shot.found) { detail.append(el('p',{class:'scope'},`${summary.searched_shots} shots 中未找到该类案例。`)); return; }
      detail.append(el('p',{class:'scope'},`同一 raw shot → m2d converter → MWPM；basis ${basis}，seed ${shot.sample_seed}，shot ${shot.shot_index}。未混用独立采样。`),
        table(['实际 observable flips','预测 observable flips','逻辑结果'],[[shot.actual_observable_flips.join(', '),shot.predicted_observable_flips.join(', '),shot.logical_failure?'逻辑失败':'解码结果匹配']]),
        el('p',{class:'muted'},'Detector 是相对无噪声参考的变化；出现 detector 不等于逻辑失败。亮格表示 bit 1。'),
        bits('Detector flips · 完整编号',Object.entries(shot.detector_flips)),
        bits('原始物理测量 reported bits',Object.entries(shot.raw_measurements)),
        bits('Semantic measurement bits',Object.entries(shot.semantic_measurements)),
        table(['语义输出类别','ID','绝对 XOR 值'],Object.entries(shot.semantic_outputs).flatMap(([group, values])=>Object.entries(values).map(([key,value])=>[group,key,String(value)]))));
    }
    function picker(label, choices, callback) {
      const input=el('select',{'aria-label':label},...choices.map(([value,text])=>el('option',{value},text)));
      input.addEventListener('change',()=>{callback(input.value);redraw();});
      return el('label',{class:'control'},label,input);
    }
    container.append(box('同一 shot 的解码证据',
      el('div',{class:'controls'},picker('Basis ',[['X','X memory'],['Z','Z memory']],value=>basis=value),
        picker('案例 ',[['detected_and_decoded','检测到异常，解码匹配'],['logical_failure','逻辑失败']],value=>kind=value)),detail));
    redraw();
    container.append(box('适用范围',el('ul',{},...data.limits.map(t=>el('li',{},t))),
      el('p',{class:'muted'},'没有生成硬件时间线；这些曲线不代表 loss-aware、非 Pauli 或 magic-state 工厂实验。')));
  }
};
