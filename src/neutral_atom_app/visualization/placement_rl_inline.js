/* Read-only inspection of saved discrete compiler witnesses, not physical replay. */
(function () {
  'use strict';
  function replayState(c, replay, time) {
    const positions = replay.mapping.map(i => c.hardware.storage[i].slice());
    const holders = positions.map(() => 'SLM'), done = [];
    let eventIndex = 0, active = null;
    for (const e of replay.events) {
      if (e.t + e.d > time) { if (e.t <= time) active = e; break; }
      if (e.k === 'move') e.q.forEach((q, i) => { positions[q] = e.p[i].slice(); });
      if (e.k === 'load' || e.k === 'unload') e.q.forEach(q => { holders[q] = e.k === 'load' ? 'AOD' : 'SLM'; });
      if (e.k === 'pulse') e.gi.forEach(g => done.push(`${e.l}:${g}`));
      eventIndex++;
    }
    return { positions, holders, done, active, eventIndex, completedGates: done.length };
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = { replayState }; return; }
  const root = document.getElementById('rl-placement-explorer');
  const data = JSON.parse(document.getElementById('rl-placement-data').textContent);
  for (const replay of Object.values(data.replays)) {
    replay.events = replay.events.map(([t, d, index]) => ({ ...data.event_pool[index], t, d }));
  }
  delete data.event_pool;
  const el = name => root.querySelector(`[data-role="${name}"]`);
  const svgNS = 'http://www.w3.org/2000/svg';
  const modeNames = { adversarial: '共同学习', uniform: '均匀场景消融' };
  const scenarioNames = ['标称', '搬运偏重 · 正序', '装卸偏重 · 正序', '搬运偏重 · 逆序', '装卸偏重 · 逆序'];
  const kinds = { load: '抓取', move: '搬运', unload: '卸载', pulse: 'CZ 脉冲' };
  const phases = { parking: '移出纠缠区', inbound: '进入纠缠区', terminal: '终态归还' };
  const qid = q => `Q${String(q).padStart(3, '0')}`;
  const fmt = n => n.toFixed(2), pct = n => `${n > 0 ? '+' : ''}${(n * 100).toFixed(2)}%`;
  let time = 0, playing = false, lastFrame = null, variant, c, baseline, policy, maximum = 1, boundaries = [];
  let visibleSeries = [true, true], selectedGate = null;
  function node(tag, attrs, text) {
    const n = document.createElementNS(svgNS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => n.setAttribute(k, v));
    if (text !== undefined) n.textContent = text;
    return n;
  }
  function add(parent, tag, attrs, text) { const n = node(tag, attrs, text); parent.appendChild(n); return n; }
  function option(select, value, label) { const o = document.createElement('option'); o.value = value; o.textContent = label; select.appendChild(o); }
  data.variants.forEach(v => option(el('variant'), v.id, `${modeNames[v.mode]} / seed ${v.seed}`));
  data.cases.forEach(c => option(el('case'), c.id, `${c.id} · ${c.circuit.n_qubits} 比特 · ${c.family}`));
  data.scenarios.forEach((s, i) => option(el('scenario'), i, scenarioNames[i]));
  function save() {
    if (!window.openai?.setWidgetState) return;
    window.openai.setWidgetState({ modelContent: { variant: variant.id, circuit: c.id, scenario: data.scenarios[+el('scenario').value].name, model_time_us: time }, privateContent: { variant: variant.id, case: c.id, scenario: el('scenario').value, time, selectedGate } }).catch(() => {});
  }
  function pause() { playing = false; lastFrame = null; el('play').textContent = '播放'; }
  function select(reset = true) {
    pause(); selectedGate = null;
    variant = data.variants.find(v => v.id === el('variant').value);
    c = data.cases.find(x => x.id === el('case').value);
    const s = +el('scenario').value;
    baseline = data.replays[c.baseline[s]]; policy = data.replays[variant.cases[c.id].replays[s]];
    maximum = Math.max(baseline.duration_us, policy.duration_us);
    boundaries = [...new Set([0, ...baseline.events.map(e => e.t + e.d), ...policy.events.map(e => e.t + e.d)])].sort((a, b) => a - b);
    time = reset ? 0 : Math.min(time, maximum); el('time').max = maximum;
    const sc = data.scenarios[s];
    el('scope').textContent = `离散模型 · ${c.circuit.n_qubits} 原子 · AOD ${c.hardware.aod_rows}×${c.hardware.aod_cols} · 搬运 ×${sc.move_scale} / 装卸 ×${sc.transfer_scale} · 时间含归还 · 未做连续物理校验`;
    el('baseline-total').textContent = `${fmt(baseline.duration_us)} μs · ${baseline.metrics.transport_groups} 组搬运`;
    el('policy-total').textContent = `${fmt(policy.duration_us)} μs · ${policy.metrics.transport_groups} 组搬运 · ${pct(policy.duration_us / baseline.duration_us - 1)}`;
    el('selection-status').textContent = `${c.id} · 使用验证集选定的第 ${variant.training.selected_step} 次更新 · 全部场景离散审计通过`;
    buildCircuit(); drawLearning(); render();
  }
  function drawMap(svg, state, replay) {
    const width = svg.getBoundingClientRect().width || 280, height = 345;
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('height', height); svg.replaceChildren();
    add(svg, 'title', {}, `模型时间 ${fmt(time)} 微秒；已完成 ${state.completedGates} 个 CZ`);
    const sites = [...c.hardware.storage, ...c.hardware.entangling.flat()];
    const xs = sites.map(p => p[0]), ys = sites.map(p => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const scale = Math.min((width - 112) / Math.max(1, maxX - minX), (height - 98) / Math.max(1, maxY - minY));
    const ox = (width - (maxX - minX) * scale) / 2;
    const x = v => ox + (v - minX) * scale, y = v => height - 57 - (v - minY) * scale;
    add(svg, 'text', { x: 5, y: 18, class: 'text-small' }, 'y (μm)');
    add(svg, 'text', { x: width - 4, y: height - 10, 'text-anchor': 'end', class: 'text-small' }, 'x (μm)');
    [minY, maxY].forEach(v => add(svg, 'text', { x: 6, y: y(v) + 4, class: 'text-small' }, String(v)));
    [...new Set([minX, maxX])].forEach(v => add(svg, 'text', { x: x(v), y: height - 30, 'text-anchor': 'middle', class: 'text-small' }, String(v)));
    add(svg, 'line', { x1: 38, x2: 38, y1: 28, y2: height - 42, stroke: 'var(--border)' });
    add(svg, 'line', { x1: 38, x2: width - 22, y1: height - 42, y2: height - 42, stroke: 'var(--border)' });
    sites.forEach(p => add(svg, 'rect', { x: x(p[0]) - 3, y: y(p[1]) - 3, width: 6, height: 6, fill: 'none', stroke: 'var(--muted-foreground)', opacity: .5 }));
    add(svg, 'text', { x: width - 4, y: y(maxY) - 16, 'text-anchor': 'end', class: 'text-small' }, '纠缠区');
    add(svg, 'text', { x: width - 4, y: y(Math.max(...c.hardware.storage.map(p => p[1]))) - 18, 'text-anchor': 'end', class: 'text-small' }, '存储区');
    const held = state.positions.filter((_, q) => state.holders[q] === 'AOD');
    if (held.length) {
      const ax = [...new Set(held.map(p => p[0]))], ay = [...new Set(held.map(p => p[1]))];
      ax.forEach(vx => ay.forEach(vy => {
        add(svg, 'path', { d: `M${x(vx)-3},${y(vy)}h6 M${x(vx)},${y(vy)-3}v6`, stroke: 'var(--viz-series-2)', fill: 'none' });
      }));
    }
    const active = state.active;
    if (active?.k === 'move') active.q.forEach((q, i) => {
      const p = state.positions[q], target = active.p[i];
      add(svg, 'line', { x1: x(p[0]), y1: y(p[1]), x2: x(target[0]), y2: y(target[1]), stroke: 'var(--viz-series-1)', 'stroke-dasharray': '3 4', opacity: .6 });
      add(svg, 'circle', { cx: x(target[0]), cy: y(target[1]), r: 5, fill: 'none', stroke: 'var(--viz-series-1)', 'stroke-dasharray': '2 2' });
    });
    if (active?.k === 'pulse') active.pairs.forEach(([a, b]) => add(svg, 'line', { x1: x(state.positions[a][0]), y1: y(state.positions[a][1]), x2: x(state.positions[b][0]), y2: y(state.positions[b][1]), stroke: 'var(--viz-series-3)', 'stroke-width': 5 }));
    state.positions.forEach((p, q) => {
      const px = x(p[0]), py = y(p[1]), on = active && (active.q || active.pairs?.flat() || []).includes(q);
      const color = on ? 'var(--viz-series-1)' : 'var(--foreground)';
      const mark = state.holders[q] === 'AOD' ? add(svg, 'path', { d: `M${px},${py-4}l4,4 -4,4 -4,-4Z`, fill: color }) : add(svg, 'circle', { cx: px, cy: py, r: 3, fill: color });
      mark.setAttribute('data-tooltip', `${qid(q)} · ${state.holders[q]} · (${p.join(', ')}) μm`);
      const neighbor = state.positions.findIndex((p2, q2) => q !== q2 && p2[1] === p[1] && Math.abs(p2[0] - p[0]) < 4);
      const close = neighbor >= 0, left = close && state.positions[neighbor][0] > p[0];
      const dx = close ? (left ? -8 : 8) : 0;
      const dy = close ? -9 : (Math.round(p[0] / 10) % 2 ? -23 : -9);
      add(svg, 'text', { x: px + dx, y: py + dy, 'text-anchor': close ? (left ? 'end' : 'start') : 'middle', class: 'text-small' }, qid(q));
    });
  }
  function describe(state, replay) {
    if (!state.active) return `完成 ${state.completedGates} CZ · 全部原子已归还存储区 · AOD 空载`;
    const e = state.active, ids = e.q || e.pairs.flat();
    const terminal = state.completedGates === c.circuit.layers.flat().length;
    return `${kinds[e.k]} ${e.k === 'pulse' ? `· 第 ${e.l + 1} 层` : `· ${terminal ? '终态归还' : (phases[e.ph] || e.ph)} · 组 ${e.g}`} [${fmt(e.t)}, ${fmt(e.t + e.d)}] μs；${ids.map(qid).join(' / ')}；已完成 ${state.completedGates} CZ`;
  }
  function buildCircuit() {
    const host = el('circuit'); host.replaceChildren(); let gate = 0;
    c.circuit.layers.forEach((pairs, l) => {
      const row = document.createElement('div'); row.className = 'rp-layer';
      const label = document.createElement('span'); label.textContent = `层 ${l + 1}`; row.appendChild(label);
      const gates = document.createElement('div'); gates.className = 'rp-gates'; row.appendChild(gates);
      pairs.forEach(([a, b], g) => {
        const button = document.createElement('button'); button.type = 'button'; button.className = 'btn';
        button.dataset.gate = `${l}:${g}`; button.dataset.label = `G${String(gate++).padStart(2, '0')} ${qid(a)}↔${qid(b)}`;
        button.onclick = () => { pause(); selectedGate = `${l}:${g}`; const pulse = policy.events.find(e => e.k === 'pulse' && e.l === l && e.gi.includes(g)); time = pulse.t + pulse.d / 2; render(); save(); };
        gates.appendChild(button);
      }); host.appendChild(row);
    });
  }
  function gateStatus(state, key) {
    if (state.done.includes(key)) return '✓';
    const [l, g] = key.split(':').map(Number), e = state.active;
    return e?.k === 'pulse' && e.l === l && e.gi.includes(g) ? '作用中' : '待做';
  }
  function render() {
    const a = replayState(c, baseline, time), b = replayState(c, policy, time);
    el('time').value = time; el('time-label').textContent = `${fmt(time)} / ${fmt(maximum)} μs`;
    drawMap(el('baseline-map'), a, baseline); drawMap(el('policy-map'), b, policy);
    el('baseline-detail').textContent = describe(a, baseline); el('policy-detail').textContent = describe(b, policy);
    root.querySelectorAll('[data-gate]').forEach(button => {
      const content = document.createElement('span'), status = document.createElement('span');
      content.append(document.createTextNode(button.dataset.label), document.createElement('br'));
      status.className = 'text-small'; status.textContent = `基 ${gateStatus(a, button.dataset.gate)} / RL ${gateStatus(b, button.dataset.gate)}`;
      content.appendChild(status); button.replaceChildren(content);
      button.setAttribute('aria-pressed', String(button.dataset.gate === selectedGate));
    });
  }
  function drawLearning() {
    const peers = ['adversarial', 'uniform'].map(mode => data.variants.find(v => v.mode === mode && v.seed === variant.seed));
    const controls = el('series-controls'); controls.replaceChildren();
    peers.forEach((v, i) => {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'rp-series-toggle cursor-interaction';
      button.setAttribute('aria-pressed', String(visibleSeries[i]));
      const swatch = document.createElement('span'); swatch.className = `rp-swatch${i ? ' rp-swatch-second' : ''}`; button.appendChild(swatch);
      button.appendChild(document.createTextNode(` ${modeNames[v.mode]}`)); button.onclick = () => { visibleSeries[i] = !visibleSeries[i]; drawLearning(); }; controls.appendChild(button);
    });
    drawCurve(peers);
    el('checkpoint').textContent = `当前选用更新 ${variant.training.selected_step}；验证值 ${variant.training.validation_score.toFixed(5)}。更新 0 为未训练布局。`;
    const row = variant.cases[c.id];
    el('opponent-title').textContent = `当前线路上的对手概率 · 更新 ${variant.final_step}`;
    el('opponent-caption').textContent = `诊断：最终对手评估所选布局；布局权重来自更新 ${variant.training.selected_step}。概率不是最坏场景的证明。`;
    const probabilities = el('probabilities'); probabilities.replaceChildren();
    row.adversary_probabilities.forEach((p, i) => {
      const line = document.createElement('div'); line.className = 'rp-prob-row';
      const label = document.createElement('span'); label.textContent = scenarioNames[i];
      const value = document.createElement('span'); value.className = 'tabular-nums text-end'; value.textContent = `${(p * 100).toFixed(1)}%`;
      const track = document.createElement('div'); track.className = 'rp-prob-track'; const fill = document.createElement('div'); fill.className = 'rp-prob-fill'; fill.style.width = `${p * 100}%`; track.appendChild(fill);
      line.append(label, value, track); probabilities.appendChild(line);
    });
    const labels = { interaction: '交互图启发式', untrained_greedy: '未训练 · 单次', trained_greedy: 'RL · 单次', random: '随机 · 8 个候选', anneal: '退火 · 8 个候选', trained_search: 'RL 搜索 · 8 个候选（含基线回退）' };
    const tbody = el('aggregate'); tbody.replaceChildren();
    Object.entries(labels).forEach(([method, label]) => {
      const tr = document.createElement('tr'), name = document.createElement('td'); name.textContent = label; tr.appendChild(name);
      ['test', 'size_holdout'].forEach(split => { const td = document.createElement('td'); td.className = 'text-end'; td.textContent = pct(variant.aggregate[split][method].nominal_mean_change); tr.appendChild(td); }); tbody.appendChild(tr);
    });
  }
  function drawCurve(peers) {
    const svg = el('curve'), width = svg.getBoundingClientRect().width || 280, height = 265;
    svg.replaceChildren(); svg.setAttribute('height', height); svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    if (!window.d3) { add(svg, 'text', { x: 8, y: 40 }, '曲线组件未加载；选点结果见下方'); return; }
    const d3 = window.d3, rows = peers.flatMap(v => v.training.validations);
    const xd = d3.extent(rows, d => d.step), yd = d3.extent([...rows.map(d => d.score), 0]);
    const pad = Math.max(.001, (yd[1] - yd[0]) * .18), x = d3.scaleLinear().domain(xd).range([72, width - 20]), y = d3.scaleLinear().domain([yd[0] - pad, yd[1] + pad]).range([height - 48, 40]);
    add(svg, 'text', { x: 4, y: 18, class: 'text-small' }, '最坏场景有界遗憾（越低越好）');
    add(svg, 'rect', { x: 64, y: 30, width: width - 76, height: height - 70, fill: 'none', stroke: 'var(--border)', 'data-chart-frame': '' });
    [0, 8, 16].forEach(v => add(svg, 'text', { x: x(v), y: height - 25, 'text-anchor': 'middle', class: 'text-small' }, v));
    y.ticks(3).forEach(v => { add(svg, 'text', { x: 56, y: y(v) + 4, 'text-anchor': 'end', class: 'text-small' }, v.toFixed(3)); add(svg, 'line', { x1: 65, x2: width - 13, y1: y(v), y2: y(v), stroke: 'var(--border)' }); });
    add(svg, 'text', { x: width - 12, y: height - 3, 'text-anchor': 'end', class: 'axis-title text-small', 'data-axis': 'x' }, '更新次数');
    add(svg, 'text', { x: 4, y: 32, class: 'axis-title text-small', 'data-axis': 'y' }, '无量纲');
    peers.forEach((v, i) => {
      if (!visibleSeries[i]) return;
      const color = `var(--viz-series-${i + 1})`;
      add(svg, 'path', { d: d3.line().x(d => x(d.step)).y(d => y(d.score))(v.training.validations), fill: 'none', stroke: color, 'stroke-width': 2, 'stroke-dasharray': i ? '5 3' : '' });
      v.training.validations.forEach(d => add(svg, 'circle', { cx: x(d.step), cy: y(d.score), r: d.step === v.training.selected_step ? 5 : 2.5, fill: color, 'data-tooltip': `${modeNames[v.mode]} · 更新 ${d.step} · ${d.score.toFixed(5)}${d.step === v.training.selected_step ? ' · 已选用' : ''}` }));
    });
    const guide = add(svg, 'line', { y1: 31, y2: height - 41, stroke: 'var(--muted-foreground)', visibility: 'hidden', 'data-chart-hover-guide': '' });
    const marks = peers.map((_, i) => add(svg, 'circle', { r: 4, fill: `var(--viz-series-${i + 1})`, visibility: 'hidden', 'data-chart-hover-marker': '' }));
    const overlay = add(svg, 'rect', { x: 64, y: 30, width: width - 76, height: height - 70, fill: 'transparent', 'data-chart-hit': '', 'data-chart-hover-overlay': 'cross-series' });
    const tooltip = el('curve-tooltip');
    function hover(event) {
      const px = Math.max(x(xd[0]), Math.min(x(xd[1]), event.clientX - svg.getBoundingClientRect().left)), step = x.invert(px);
      guide.setAttribute('x1', px); guide.setAttribute('x2', px); guide.setAttribute('visibility', 'visible');
      const lines = [`更新 ${step.toFixed(1)}（线段插值）`];
      peers.forEach((v, i) => {
        if (!visibleSeries[i]) { marks[i].setAttribute('visibility', 'hidden'); return; }
        const values = v.training.validations, near = d3.bisector(d => d.step).center(values, step);
        let lo = near; if (values[lo].step > step) lo--; lo = Math.max(0, Math.min(values.length - 2, lo));
        const a = values[lo], b = values[lo + 1], val = a.score + (b.score - a.score) * (step - a.step) / (b.step - a.step);
        marks[i].setAttribute('cx', px); marks[i].setAttribute('cy', y(val)); marks[i].setAttribute('visibility', 'visible'); lines.push(`${modeNames[v.mode]} ${val.toFixed(5)}`);
      });
      tooltip.textContent = lines.join(' · '); tooltip.hidden = false; tooltip.style.position = 'absolute'; tooltip.style.pointerEvents = 'none'; tooltip.style.left = '4px'; tooltip.style.top = '34px'; tooltip.style.maxWidth = `${width - 8}px`;
    }
    overlay.onpointermove = hover; overlay.onclick = hover; overlay.onpointerleave = () => { tooltip.hidden = true; guide.setAttribute('visibility', 'hidden'); marks.forEach(m => m.setAttribute('visibility', 'hidden')); };
  }
  el('variant').onchange = el('case').onchange = el('scenario').onchange = () => { select(); save(); };
  el('time').oninput = () => { pause(); time = +el('time').value; render(); }; el('time').onchange = save;
  el('start').onclick = () => { pause(); time = 0; selectedGate = null; render(); save(); };
  el('end').onclick = () => { pause(); time = maximum; render(); save(); };
  el('next').onclick = () => { pause(); time = boundaries.find(t => t > time + 1e-9) ?? maximum; render(); save(); };
  el('prev').onclick = () => { pause(); time = boundaries.filter(t => t < time - 1e-9).at(-1) ?? 0; render(); save(); };
  function tick(now) {
    if (!playing) return;
    if (lastFrame !== null) time = Math.min(maximum, time + Math.min(now - lastFrame, 100) * .04);
    lastFrame = now; render();
    if (time >= maximum) { pause(); save(); } else requestAnimationFrame(tick);
  }
  el('play').onclick = () => { if (playing) { pause(); save(); return; } if (time >= maximum) time = 0; playing = true; lastFrame = null; el('play').textContent = '暂停'; requestAnimationFrame(tick); };
  function restore(state) {
    const saved = state?.privateContent;
    if (saved && data.variants.some(v => v.id === saved.variant) && data.cases.some(v => v.id === saved.case)) {
      el('variant').value = saved.variant; el('case').value = saved.case;
      el('scenario').value = ['0', '1', '2', '3', '4'].includes(String(saved.scenario)) ? String(saved.scenario) : '0';
      time = Number.isFinite(saved.time) ? Math.max(0, saved.time) : 0; select(false);
      selectedGate = typeof saved.selectedGate === 'string' ? saved.selectedGate : null; render();
    } else select();
  }
  restore(window.openai?.widgetState);
  window.addEventListener('openai:set_globals', e => { if (e.detail?.globals?.widgetState) restore(e.detail.globals.widgetState); });
  new ResizeObserver(() => { render(); drawCurve(['adversarial', 'uniform'].map(mode => data.variants.find(v => v.mode === mode && v.seed === variant.seed))); }).observe(root);
})();
