/* Adapt one guarded plan and one reported bit string to the standard viewer.
 * Geometry, timing, and loss probabilities use the same prepare() as sampling.
 * The risk curve is a full-plan conditional physical-loss estimate, not a
 * reconstruction of loss-aborted quantum trajectories or a T2-error statistic.
 */
(function(root) {
  'use strict';
  const clone = x => JSON.parse(JSON.stringify(x));
  const names = {Load:'装载到 AOD', Store:'卸载到 SLM', Move:'移动原子',
    Measure:'测量', Reset:'初始化', Wait:'等待', CZPulse:'CZ 门'};

  function referenceBits(base, plan) {
    const values = new Map(base.measurements.map(x => [x.measurement_id, x.value]));
    const bits = Array(plan.num_bits).fill(0);
    for (const measurement of plan.measurements) {
      if (!values.has(measurement.measurement_id) || ![0,1].includes(values.get(measurement.measurement_id))) {
        throw Error('参考分支缺少有效的测量结果。');
      }
      bits[measurement.bit] = values.get(measurement.measurement_id);
    }
    return bits.reverse().join('');
  }

  function riskCurve(prepared, bitstring) {
    const classical = [...bitstring].reverse().map(Number);
    const ids = prepared.plan.initial.atoms.map(a => a.id);
    const survival = new Map(ids.map(id => [id, 1]));
    const events = prepared.losses.filter(e => !e.guard || classical[e.guard.bit] === e.guard.value);
    const curve = [{time_us:0, mean_loss:0}];
    let mean = 0, index = 0;
    while (index < events.length) {
      const time = events[index].time_us;
      curve.push({time_us:time, mean_loss:mean});
      do {
        const event = events[index++];
        survival.set(event.atom, survival.get(event.atom) * (1-event.probability));
      } while (index < events.length && events[index].time_us === time);
      mean = ids.reduce((total, id) => total + 1-survival.get(id), 0) / ids.length;
      curve.push({time_us:time, mean_loss:mean});
    }
    curve.push({time_us:prepared.plan.duration_us, mean_loss:mean});
    return {curve, final_mean_loss:mean};
  }

  function buildTrace(base, guarded, parameters, suppliedBits, selectionLabel) {
    const prepared = root.ShorBrowserEngine.prepare(guarded, parameters);
    const plan = prepared.plan;
    const fallback = suppliedBits === null || suppliedBits === undefined;
    const bitstring = fallback ? referenceBits(base, plan) : suppliedBits;
    if (typeof bitstring !== 'string' || !(new RegExp('^[01]{'+plan.num_bits+'}$')).test(bitstring)) {
      throw Error('动画分支的测量位串长度或内容无效。');
    }
    const bits = [...bitstring].reverse().map(Number);
    const bitByMeasurement = new Map(plan.measurements.map(m => [m.measurement_id, m.bit]));
    const trace = clone(base);
    trace.initial = clone(plan.initial);
    trace.steps = clone(plan.steps);
    trace.duration_us = plan.duration_us;
    trace.program_duration_us = plan.program_duration_us;
    trace.issues = [];
    trace.operations = [];
    trace.shor_n = plan.n;
    trace.shor_bitstring = bitstring;
    const reference = '理想采样参考分支'+(base.ideal_reference_seed === undefined ? '' : '，种子 '+base.ideal_reference_seed);
    const label = fallback ? (selectionLabel ? selectionLabel+'（采用'+reference+'）' : '未获得本次无丢失读数，采用'+reference) :
      (selectionLabel || '本次采样选定的无丢失读数分支');
    trace.title = 'N = '+plan.n+' · 当前参数下的物理执行动画';
    trace.description = label+'；读数 '+bitstring+'。条件为假时保留空闲时间槽。动画不显示随机 Pauli 错误或原子掉落。';
    for (const key of ['noise_report','compilation','loss_time','loss_time_result']) delete trace[key];
    for (const step of trace.steps) {
      step.actions = step.actions.map(action => {
        if (action.guard && bits[bitByMeasurement.get(action.guard.measurement_id)] !== action.guard.value) {
          return {index:action.index, kind:'Wait', duration_us:action.duration_us,
            source_ids:action.source_ids, atoms:[], parameters:{}, pairs:[], coverage:null,
            patch:{atoms:[],grids:[]}, text:'条件不满足：不发门脉冲，保留时间槽', gate_label:'条件不满足：空闲'};
        }
        if (names[action.kind]) action.gate_label = names[action.kind];
        return action;
      });
    }
    trace.measurements = plan.measurement_times.map(m => ({
      measurement_id:m.measurement_id, value:bits[m.bit], available_at_us:m.available_at_us,
      atom_id:plan.initial.atoms.find(a => a.qubit === m.qubit).id,
    }));
    trace.atom_ir = trace.steps.map(s => s.actions.map(a => a.text).join('\n')+
      '\nTICK(duration_us='+s.duration_us+')').join('\n');
    const risk = riskCurve(prepared, bitstring);
    return {trace, risk:{type:'shor-replay-risk', n:plan.n, bitstring,
      selection_label:label, parameters:prepared.parameters, duration_us:plan.duration_us,
      ...risk, scope:'完整固定计划、给定读数分支的物理原子平均丢失估计；不含 T2，不是丢失后继续执行模拟。'}};
  }

  const api = {buildTrace, referenceBits, riskCurve};
  root.ShorReplayBridge = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window !== 'undefined' ? window : globalThis);
