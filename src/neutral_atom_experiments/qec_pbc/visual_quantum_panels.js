(function () {
  'use strict';
  const H = () => window.QECViz.helpers;
  function metric(label, value) {
    const { el } = H();
    return el('div', { class: 'metric' }, el('span', {}, label), el('strong', {}, String(value)));
  }
  function stateTable(labels, states) {
    const { table, fmt } = H();
    const headers = ['基态'];
    for (const s of states) headers.push(s.name + ' 概率', s.name + ' 复振幅', s.name + ' 相位 / rad');
    return table(headers, labels.map((label, i) => {
      const row = ['|' + label + '⟩'];
      for (const s of states) row.push(fmt(s.state.probabilities[i]),
        fmt(s.state.amplitudes.real[i]) + ' + (' + fmt(s.state.amplitudes.imag[i]) + ')i',
        s.state.probabilities[i] < 1e-14 ? '振幅为零：相位无定义' : fmt(s.state.phases_rad[i]));
      return row;
    }));
  }
  function renderE1(container, data) {
    const { el, box, table, circuit, pauliCircuit, bars, pauli, fmt, select } = H();
    container.replaceChildren();
    let selected = 0;
    const panel = el('div', { class: 'stack' });
    const program = data.compiled_program;
    container.append(el('p', { class: 'scope' }, '已实现：exact PPR 酉表示。未实现：自适应 PBC 测量线路、资源态注入展开及 surface-code physical lowering。'),
      el('div', { class: 'metrics' }, metric('独立完整酉矩阵最大误差', fmt(data.unitary_max_abs_error)),
        metric('逻辑 wires', data.wire_order.length), metric('Pauli rotations', program.rotations.length)),
      box('原始 Clifford+T 电路', circuit(data.input_gates, data.wire_order)),
      box('编译后：依次执行 Pauli rotations，再执行 residual Clifford',
        el('p', { class: 'formula' }, 'U = exp(iπφ/8) C Rlast … Rfirst；R(P,k)=exp(−iπkP/8)；φ=' + program.global_phase_eighth_turns),
        pauliCircuit(program.rotations, data.wire_order),
        el('p', { class: 'muted' }, '图中每列是一个多比特 Pauli rotation，连接处的 X/Y/Z 是算符因子；它们不是各自独立的单比特门，也不是已实现的 Pauli 测量。'),
        table(['顺序', '原始门索引', 'signed Pauli', 'k：角度 kπ/4'],
          program.rotations.map((r, i) => [i, r.source_index, pauli(r.observable), r.quarter_turns])),
        circuit(program.residual_clifford, data.wire_order)),
      select('选择输入态', data.probes.map((p, i) => ({ value: String(i), label: p.name })), value => {
        selected = Number(value); update();
      }), panel);
    function update() {
      const probe = data.probes[selected];
      panel.replaceChildren(el('div', { class: 'metrics' }, metric('原电路与编译后输出 fidelity', fmt(probe.fidelity))),
        box('输入态', bars(data.basis_labels, [{ name: '输入概率', values: probe.input.probabilities }]),
          stateTable(data.basis_labels, [{ name: '输入', state: probe.input }])),
        box('输出概率对照', bars(data.basis_labels, [
          { name: '原电路', values: probe.original_output.probabilities },
          { name: '编译后', values: probe.compiled_output.probabilities }])),
        box('输出复振幅与相位', stateTable(data.basis_labels, [
          { name: '原电路', state: probe.original_output }, { name: '编译后', state: probe.compiled_output }])),
        el('p', { class: 'muted' }, '完整矩阵比较包含全局相位；概率相同本身不足以证明量子通道等价。这里展示理想逻辑编译，不包含中性原子运输或 QEC 噪声。'));
    }
    update();
  }
  function renderE4(container, data) {
    const { el, box, injectionCircuit, bars, fmt, select } = H();
    container.replaceChildren();
    let caseIndex = 0, branchIndex = 0;
    const panel = el('div', { class: 'stack' });
    container.append(el('p', { class: 'scope' }, '仅实现理想逻辑 T/Tdg 注入合同与分支态验证。magic-state 编码制备、surface-code 协议、physical circuit 和 Executor 执行均未实现。'),
      el('div', { class: 'grid2' },
        select('选择 injection 与输入态', data.cases.map((c, i) => ({ value: String(i), label: c.gate + ' · ' + c.input_name })), value => {
          caseIndex = Number(value); update();
        }),
        select('选择测量分支', [{ value: '0', label: '资源 Z 读出 0' }, { value: '1', label: '资源 Z 读出 1' }], value => {
          branchIndex = Number(value); update();
        })), panel);
    function update() {
      const c = data.cases[caseIndex], branch = c.branches[branchIndex], contract = c.contract;
      const resource = contract.resource, measurement = contract.measurement;
      panel.replaceChildren(el('div', { class: 'metrics' },
        metric('该分支概率', fmt(branch.probability)), metric('校正前 fidelity', fmt(branch.before_correction_fidelity)),
        metric('校正后 fidelity', fmt(branch.after_correction_fidelity)), metric('Kraus 完整性误差', fmt(c.kraus_completeness_error))),
        box('T 门的逻辑替代协议：magic-state 输入 → CX → MZ → 条件 S/Sdg', injectionCircuit(contract, branch.outcome, c.reference_entangled),
          el('p', {}, '目标 '+ c.gate +' 门的非 Clifford 资源在输入 |'+resource.state+'⟩ 中。这里没有可执行的物理 '+c.gate+' 门；资源态被测量并消耗。'),
          el('p', { class: 'formula' }, branch.correction ?
            measurement.id + '=1 → data 上执行 ' + branch.correction + '；校正依赖资源测量结果。' :
            measurement.id + '=0 → 无需额外校正。'),
          el('p', {}, '资源 |' + resource.state + '⟩：quality=' + resource.quality +
            '；consumed=' + String(resource.consumed) + '；来源：' + resource.provenance),
          el('p', { class: 'muted' }, '此图中的 CX、测量及 S/Sdg 是逻辑操作。尚未展开为 surface-code 物理协议、decoder 或中性原子运动。')),
        box('数据输入态', bars(c.basis_labels, [{ name: '输入', values: c.input.probabilities }]),
          stateTable(c.basis_labels, [{ name: '输入', state: c.input }])),
        box('magic-state 资源输入（理想外部输入，未实现制备）',
          el('p', {class:'formula'}, '|'+resource.state+'⟩ = (|0⟩ + exp('+ (c.gate==='T'?'i':'−i') +'π/4)|1⟩)/√2'),
          stateTable(['0','1'], [{name:'资源',state:c.resource}])),
        box('选定分支：校正前、校正后与目标概率', bars(c.basis_labels, [
          { name: '校正前', values: branch.before_correction.probabilities },
          { name: '校正后', values: branch.after_correction.probabilities },
          { name: '目标', values: c.expected_output.probabilities }])),
        box('分支复振幅与相位', stateTable(c.basis_labels, [
          { name: '校正前', state: branch.before_correction }, { name: '校正后', state: branch.after_correction },
          { name: '目标', state: c.expected_output }])),
        el('p', { class: 'muted' }, '分支态已按该分支概率归一化。fidelity 忽略无可观测的分支全局相位；相位表保留原始复振幅。纠缠案例的参考寄存器不参与 injection。'));
    }
    update();
  }
  window.QECQuantumPanels = { renderE1, renderE4 };
})();
