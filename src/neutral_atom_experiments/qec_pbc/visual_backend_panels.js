/* Canonical backend experiments. All acceptance values come from supplied data. */
(() => {
  const H = () => window.QECViz.helpers;
  const palette = {ink:'#25364b', blue:'#2563eb', red:'#dc2626', green:'#15803d', idle:'#e2e8f0'};
  function picker(label, items, change) {
    const {el} = H();
    const input = el('select', {});
    items.forEach((item,i) => input.append(el('option', {value:String(i)}, item)));
    input.addEventListener('change', () => change(Number(input.value)));
    return el('label', {class:'control'}, label, input);
  }
  function text(canvas,x,y,label,color=palette.ink,size=12) {
    canvas.append(H().svg('text', {x,y,fill:color,'font-size':size,'text-anchor':'middle'}, label));
  }
  function line(canvas,a,b,color,width=2,dash=null) {
    const attrs={x1:a[0],y1:a[1],x2:b[0],y2:b[1],stroke:color,'stroke-width':width};
    if(dash) attrs['stroke-dasharray']=dash;
    canvas.append(H().svg('line',attrs));
  }
  function arrow(canvas,a,b,color) {
    line(canvas,a,b,color,2);
    const dx=b[0]-a[0],dy=b[1]-a[1],len=Math.hypot(dx,dy)||1;
    const ux=dx/len,uy=dy/len,x=b[0]-ux*17,y=b[1]-uy*17;
    canvas.append(H().svg('polygon',{points:`${x},${y} ${x-ux*9+uy*4},${y-uy*9-ux*4} ${x-ux*9-uy*4},${y-uy*9+ux*4}`,fill:color}));
  }
  function node(canvas,pos,label,color=palette.idle) {
    canvas.append(H().svg('circle',{cx:pos[0],cy:pos[1],r:16,fill:color,stroke:palette.ink,'stroke-width':1}));
    text(canvas,pos[0],pos[1]+4,label,palette.ink,10);
  }
  function canvas(width,height) {
    return H().svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'img',style:'width:100%;height:auto;max-height:440px;'});
  }
  function scope(message) {return H().el('p',{class:'scope'},message);}
  function renderE2(container,data) {
    const {el,box,table,fmt} = H();
    const layerArea=el('div',{class:'stack'}), snapshotArea=el('div',{class:'stack'});
    function drawLayer(index) {
      const layer=data.layers[index], drawing=canvas(470,340);
      drawing.setAttribute('aria-label',`耦合层 ${layer.layer_id}，有向 CNOT 与目标 H`);
      const coords=data.role_coordinates;
      const xs=Object.values(coords).map(p=>p[0]),ys=Object.values(coords).map(p=>p[1]);
      const minX=Math.min(...xs),maxX=Math.max(...xs),minY=Math.min(...ys),maxY=Math.max(...ys);
      const scale=Math.min(340/Math.max(1,maxX-minX),230/Math.max(1,maxY-minY));
      const point=q=>[65+(coords[q][0]-minX)*scale,45+(coords[q][1]-minY)*scale];
      layer.directed_pairs.forEach(([a,b])=>arrow(drawing,point(a),point(b),palette.blue));
      const targets=new Set(layer.hadamard_targets);
      Object.keys(coords).forEach(q=>node(drawing,point(q),q,targets.has(q)?'#fde68a':palette.idle));
      text(drawing,235,315,'蓝箭头：CNOT control → target；黄色：H(target)');
      layerArea.replaceChildren(drawing,el('p',{class:'muted'},`逻辑整数格坐标，无微米单位。前驱层：${layer.predecessor_layer ?? '无'}。`),
        table(['Control','Target','分解'],layer.directed_pairs.map(([a,b])=>[a,b,`H(${b}) → CZ → H(${b})`])),
        scope(layer.claim));
    }
    function drawSnapshot(index) {
      const sample=data.pulse_cases[index], drawing=canvas(480,350);
      drawing.setAttribute('aria-label',`静态 CZ 配对快照 ${sample.name}`);
      const entries=Object.entries(sample.positions),r=sample.radius_um;
      const xs=entries.map(([,p])=>p[0]),ys=entries.map(([,p])=>p[1]);
      const xmin=Math.min(...xs)-r,xmax=Math.max(...xs)+r,ymin=Math.min(...ys)-r,ymax=Math.max(...ys)+r;
      const scale=Math.min(390/(xmax-xmin),240/(ymax-ymin));
      const point=q=>[40+(sample.positions[q][0]-xmin)*scale,30+(sample.positions[q][1]-ymin)*scale];
      entries.forEach(([q])=>drawing.append(H().svg('circle',{cx:point(q)[0],cy:point(q)[1],r:r*scale,fill:'none',stroke:'#cbd5e1','stroke-dasharray':'4 4'})));
      const intended=new Set(sample.intended_pairs.map(p=>[...p].sort().join('|')));
      sample.intended_pairs.forEach(([a,b])=>line(drawing,point(a),point(b),palette.blue,6,'5 3'));
      sample.actual_pairs.forEach(([a,b])=>line(drawing,point(a),point(b),intended.has([a,b].sort().join('|'))?palette.green:palette.red,3));
      entries.forEach(([q])=>node(drawing,point(q),q,q==='S'?'#fed7aa':palette.idle));
      text(drawing,240,315,`等比例微米坐标；距离阈值 ${fmt(r)} μm`);
      snapshotArea.replaceChildren(drawing,el('p',{class:'verify'},sample.accepted?'静态配对审查通过':'静态配对审查拒绝'),
        el('p',{class:'muted'},'蓝色虚线：请求；绿色：吻合的实际作用对；红色：额外作用对。'),
        table(['原子','x / μm','y / μm'],entries.map(([q,p])=>[q,fmt(p[0]),fmt(p[1])])),
        el('p',{},sample.rejection ?? '实际作用集合与请求集合一致。'),scope(sample.claim));
    }
    const life=data.lifecycle,rect=data.rectangle_case;
    container.replaceChildren(
      box('Canonical 耦合层',picker('选择层',data.layers.map(l=>l.layer_id),drawLayer),layerArea,
          scope(data.claim)),
      box('Ancilla 生命周期',el('p',{},`容量 ${life.capacity}；对照 ${life.comparison_rounds} 轮（独立于当前层选择）。`),
          table(['模式','最低原子数','能力审查','原因'],['reuse','fresh'].map(mode=>[mode,life[mode].minimum_atoms,life[mode].compatible?'通过':'拒绝',life[mode].issues.join(', ')||'必要能力满足'])),
          scope(life.reuse.claim)),
      box('全局 CZ 静态快照',picker('选择快照',data.pulse_cases.map(c=>c.name),drawSnapshot),snapshotArea),
      box('AOD 行 × 列捕获审查',el('p',{},`活动行 ${rect.active_rows.join(', ')}；活动列 ${rect.active_columns.join(', ')}；请求 ${rect.requested_atoms.join(', ')}`),
          table(['行','列','实际捕获'],rect.captures.map(c=>[c.row,c.column,c.atom])),
          el('p',{class:'verify'},rect.accepted?'捕获集合审查通过':`捕获集合审查拒绝：${rect.rejection}`),
          scope('示意为静态捕获集合；没有绘制或执行运输轨迹。')));
    if(data.layers.length) drawLayer(0);
    if(data.pulse_cases.length) drawSnapshot(0);
  }
  function renderE3(container,data) {
    const {el,box,table,pauli}=H();
    const images=Object.entries(data.logical_images), area=el('div',{class:'stack'});
    function draw(index) {
      const [name,image]=images[index],drawing=canvas(660,370);
      drawing.setAttribute('aria-label',`双 patch transversal CNOT 与 ${name} 的像`);
      const support=new Map(image.factors),coords={};
      [data.control,data.target].forEach((patch,k)=>{
        text(drawing,k?490:160,25,`${patch.id}：${patch.orientation}`);
        Object.entries(patch.coordinates).forEach(([q,p])=>coords[q]=[80+k*330+p[0]*75,85+p[1]*95]);
      });
      data.directed_pairs.forEach(([a,b])=>arrow(drawing,coords[a],coords[b],'#cbd5e1'));
      Object.entries(coords).forEach(([q,p])=>{
        node(drawing,p,q,support.has(q)?'#bfdbfe':palette.idle);
        if(support.has(q)) text(drawing,p[0],p[1]+32,support.get(q),palette.blue,13);
      });
      const input={X_control:data.control.logical_x,Z_control:data.control.logical_z,
        X_target:data.target.logical_x,Z_target:data.target.logical_z}[name];
      area.replaceChildren(drawing,el('p',{class:'formula'},`${name}: ${pauli(input)} → ${pauli(image)}`),
        el('p',{class:'muted'},'高亮为输出 Pauli support。位置是逻辑格编号，不是微米布局；连线表示协议配对。'));
    }
    const h=data.hadamard,hdrawing=canvas(660,350);
    hdrawing.setAttribute('aria-label','逻辑 H 前后朝向与 checks 更新；坐标保持');
    [h.input_patch,h.output_patch].forEach((patch,k)=>{
      text(hdrawing,k?490:160,25,`${k?'输出':'输入'}：${patch.orientation}`);
      Object.entries(patch.coordinates).forEach(([q,p])=>node(hdrawing,[80+k*330+p[0]*75,80+p[1]*90],q));
    });
    text(hdrawing,330,165,'9 × H');
    text(hdrawing,330,320,'坐标保持；X/Z checks 与边界类型交换');
    const checks=(patch)=>[...patch.x_checks.map((p,i)=>[`X${i}`,pauli(p)]),...patch.z_checks.map((p,i)=>[`Z${i}`,pauli(p)])];
    container.replaceChildren(
      box('双块 Transversal CNOT',picker('选择逻辑算符',images.map(([name])=>name),draw),area,scope(data.claim)),
      box('稳定子保持验证',el('p',{class:'verify'},data.all_stabilizers_preserved?'全部稳定子像保持在原 group 中':'稳定子验证出现失败'),
          table(['生成元','输入','共轭像','验证'],data.stabilizer_checks.map(row=>[row.id,pauli(row.input),pauli(row.image),row.passed?'通过':'失败']))),
      box('逻辑 H：显式朝向更新',hdrawing,el('p',{},h.boundary_update),
          el('div',{class:'grid2'},box('输入 checks',table(['类型','Pauli'],checks(h.input_patch))),box('输出 checks',table(['类型','Pauli'],checks(h.output_patch)))),
          table(['算符','输入','输出共轭像'],Object.entries(h.logical_images).map(([name,p])=>[name,pauli(name==='X'?h.input_patch.logical_x:h.input_patch.logical_z),pauli(p)])),
          scope(h.claim)));
    if(images.length) draw(0);
  }
  window.QECBackendPanels={renderE2,renderE3};
})();
