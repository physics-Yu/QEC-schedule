/* Fixed-geometry retiming and NAL physical-loss sensitivity; no quantum sampling. */
(function(root) {
  'use strict';
  const KB = 1.380649e-23, HBAR = 1.054571817e-34, AMU = 1.66053906660e-27;
  const DEFAULTS = Object.freeze({speed:1, transfer:15, readout:100, singleTime:1,
    czTime:.5, cpTime:.5, resetTime:5, latency:500,
    loadLoss:.002, storeLoss:.002, czLoss:.001, cpLoss:.001, imagingLoss:.001,
    singleLoss:0, resetLoss:0, mass:86.909180531, frequency:90, width:.73,
    temperature:27, depthSpread:0});
  const SOURCES = ['load','store','move','cz','cp','imaging','single','reset'];
  const clone = x => JSON.parse(JSON.stringify(x));
  function probabilityFromEta(eta) {
    if (eta <= 0) return 1;
    if (eta > 745) return 0;
    return Math.min(1, (1 + eta + eta * eta / 2) * Math.exp(-eta));
  }
  function legendre(n) {
    const rows = [];
    for (let i=1;i<=n;i++) {
      let x=Math.cos(Math.PI*(i-.25)/(n+.5)), derivative=0;
      for (let k=0;k<30;k++) {
        let a=1,b=x;
        for(let j=2;j<=n;j++) {const c=((2*j-1)*x*b-(j-1)*a)/j;a=b;b=c;}
        derivative=n*(x*b-a)/(x*x-1);
        const next=x-b/derivative;
        if(Math.abs(next-x)<1e-15){x=next;break;}
        x=next;
      }
      rows.push([x,2/((1-x*x)*derivative*derivative)]);
    }
    return rows;
  }
  const QUADRATURE=legendre(64);
  function transportLoss(distanceUm, durationUs, p) {
    if(distanceUm===0)return {probability:0, deltaN:0, eta:Infinity};
    if(!(durationUs>0))throw Error('Moving atoms require positive duration.');
    const m=p.mass*AMU, omega=2*Math.PI*p.frequency*1e3;
    const distance=distanceUm*1e-6, duration=durationUs*1e-6;
    const deltaN=(50/3)*m*distance**2/(HBAR*omega**3*duration**4);
    const energy=deltaN*HBAR*omega, depth=.5*m*omega**2*(p.width*1e-6)**2;
    const thermal=KB*p.temperature*1e-6;
    const lossAtDepth=u=>thermal===0?(u<=energy?1:0):probabilityFromEta((u-energy)/thermal);
    const eta=thermal===0?(depth<=energy?-Infinity:Infinity):(depth-energy)/thermal;
    if(!p.depthSpread)return {probability:lossAtDepth(depth),deltaN,eta};
    // Positive-truncated Gaussian, integrated over at most eight standard deviations.
    const low=Math.max(-8,-1/p.depthSpread), high=8;
    let total=0, weight=0;
    const threshold=(energy/depth-1)/p.depthSpread;
    const bounds=[low,...(threshold>low&&threshold<high?[threshold]:[]),high];
    for(let i=1;i<bounds.length;i++)for(const [x,w] of QUADRATURE) {
      const left=bounds[i-1],right=bounds[i],scale=(right-left)/2;
      const z=(right+left)/2+scale*x, q=scale*w*Math.exp(-z*z/2);
      total+=q*lossAtDepth(depth*(1+p.depthSpread*z));weight+=q;
    }
    return {probability:Math.max(0,Math.min(1,total/weight)),deltaN,eta};
  }
  function validate(p) {
    for(const key of Object.keys(DEFAULTS))if(!Number.isFinite(p[key]))throw Error('Invalid parameter: '+key);
    for(const key of ['speed','mass','frequency','width'])if(p[key]<=0)throw Error(key+' must be positive.');
    if(p.temperature<0)throw Error('temperature cannot be negative.');
    for(const key of ['transfer','readout','singleTime','czTime','cpTime','resetTime','latency','depthSpread'])if(p[key]<0)throw Error(key+' cannot be negative.');
    for(const key of ['loadLoss','storeLoss','czLoss','cpLoss','imagingLoss','singleLoss','resetLoss'])if(p[key]<0||p[key]>1)throw Error(key+' must be in [0, 1].');
  }
  function retime(base, params) {
    const p={...DEFAULTS,...params};validate(p);
    const trace=clone(base), meta=trace.loss_time, nodes=meta.nodes;
    const predecessors=nodes.map(()=>[]);
    for(const [a,b] of meta.edges)predecessors[b].push(a);
    const status=new Map(base.operations.map(o=>[o.operation_id,o.status]));
    const ends=new Map(), available=new Map(), starts=new Map();
    const newSteps=[], losses=[], diagnostics=[], positions=new Map(base.initial.atoms.map(a=>[a.id,{x:a.x,y:a.y}]));
    const budget=Object.fromEntries([...SOURCES,'feedback_wait'].map(k=>[k,0]));
    const durations={}, counts={};let clock=0, actionIndex=0;
    const sourceCache=new Map();
    function conditionTime(node) {
      if(!node.condition)return 0;
      const id=node.condition.result.measurement_id;
      if(!available.has(id))throw Error('Feedback referenced before measurement '+id);
      return available.get(id);
    }
    function nodeEnd(id) {
      if(ends.has(id))return ends.get(id);
      if(status.get(id)==='emitted')throw Error('Unscheduled native predecessor '+id);
      const node=nodes[id], end=Math.max(0,conditionTime(node),...predecessors[id].map(nodeEnd));
      ends.set(id,end);starts.set(id,end);return end;
    }
    const requirements=ids=>Math.max(0,...ids.map(id=>Math.max(conditionTime(nodes[id]),...predecessors[id].map(nodeEnd))));
    let upcoming=[];
    const guards=base.steps.map(()=>[]);
    for(let i=base.steps.length-1;i>=0;i--) {
      const ids=base.steps[i].actions.flatMap(a=>a.source_ids);
      if(ids.length)upcoming=ids;
      guards[i]=upcoming;
    }
    function addLoss(atom,probability,cause,start,duration,stepIndex) {
      if(probability<=0)return;
      losses.push({atom,kind:cause,cause,start_us:start,duration_us:duration,
        survival_probability:1-probability,step_index:stepIndex});
      budget[cause]=(budget[cause]||0)+probability;
    }
    for(let originalIndex=0;originalIndex<base.steps.length;originalIndex++) {
      const original=base.steps[originalIndex];
      if(original.actions.every(a=>a.kind==='Wait'))continue;
      const earliest=requirements(guards[originalIndex]);
      if(earliest>clock+1e-9) {
        const delay=earliest-clock;
        newSteps.push({index:newSteps.length,original_index:originalIndex,start_us:clock,duration_us:delay,
          actions:[{index:actionIndex++,kind:'Wait',duration_us:delay,source_ids:[],atoms:[],
            parameters:{},pairs:[],coverage:null,patch:{atoms:[],grids:[]},text:'WAIT: feedback result availability'}]});
        budget.feedback_wait+=delay;clock=earliest;
      }
      const actions=clone(original.actions), index=newSteps.length;
      for(const action of actions) {
        action.index=actionIndex++;
        let dt=action.duration_us;
        if(action.kind==='Move') {
          const target=new Map(action.patch.atoms.map(a=>[a.id,a]));
          action.movement=action.atoms.map(id=>{
            const before=positions.get(id),after=target.get(id)||before;
            return {atom:id,distance_um:Math.hypot(after.x-before.x,after.y-before.y)};
          });
          dt=Math.max(0,...action.movement.map(m=>m.distance_um))/p.speed;
        } else if(['Load','Store'].includes(action.kind))dt=p.transfer;
        else if(action.kind==='Measure')dt=p.readout;
        else if(['LocalU','Rotation','GlobalRY'].includes(action.kind))dt=p.singleTime;
        else if(action.kind==='CZPulse')dt=p.czTime;
        else if(action.kind==='CPhasePulse')dt=p.cpTime;
        else if(action.kind==='Reset')dt=p.resetTime;
        action.duration_us=dt;
        action.text=action.text.replace(/duration_us=[^,)]+/,'duration_us='+dt);
        for(const id of action.source_ids){starts.set(id,clock);ends.set(id,clock+dt);}
        if(action.kind==='Measure')for(const pair of action.parameters.results)available.set(pair.measurement_id,clock+dt+p.latency);
        if(action.kind==='Move') {
          for(const move of action.movement) {
            const key=move.distance_um+':'+dt;
            if(!sourceCache.has(key))sourceCache.set(key,transportLoss(move.distance_um,dt,p));
            const value=sourceCache.get(key);
            addLoss(move.atom,value.probability,'move',clock,dt,index);
            diagnostics.push({atom:move.atom,step_index:index,distance_um:move.distance_um,duration_us:dt,...value});
          }
        } else {
          const record={Load:['load',p.loadLoss],Store:['store',p.storeLoss],CZPulse:['cz',p.czLoss],
            CPhasePulse:['cp',p.cpLoss],Measure:['imaging',p.imagingLoss],LocalU:['single',p.singleLoss],
            Rotation:['single',p.singleLoss],GlobalRY:['single',p.singleLoss],Reset:['reset',p.resetLoss]}[action.kind];
          const atoms=['CZPulse','CPhasePulse'].includes(action.kind)?[...new Set(action.pairs.flat())]:action.atoms;
          if(record)for(const id of atoms)addLoss(id,record[1],record[0],clock,dt,index);
        }
        counts[action.kind]=(counts[action.kind]||0)+1;
        durations[action.kind]=(durations[action.kind]||0)+dt;
      }
      const duration=Math.max(0,...actions.map(a=>a.duration_us));
      newSteps.push({index,original_index:originalIndex,start_us:clock,duration_us:duration,actions});
      for(const action of actions)for(const atom of action.patch.atoms)positions.set(atom.id,{x:atom.x,y:atom.y});
      clock+=duration;
    }
    trace.steps=newSteps;trace.program_duration_us=clock;
    trace.measurements=base.measurements.map(m=>({...m,available_at_us:available.get(m.measurement_id)}));
    trace.duration_us=Math.max(clock,...available.values());
    trace.operations=base.operations.map(o=>{const end=nodeEnd(o.operation_id);return {...o,start_us:starts.get(o.operation_id)??end,end_us:end};});
    trace.issues=base.issues.map(issue=>{
      const step=newSteps.find(s=>s.original_index===issue.step_index&&s.actions[0]?.kind!=='Wait');
      return {...issue,step_index:step?.index??-1,time_us:step?step.start_us+step.duration_us:0};
    });
    trace.atom_ir=newSteps.map(step=>step.actions.map(a=>a.text).join('\n')+'\nTICK(duration_us='+step.duration_us+')').join('\n');
    trace.noise_report={model:'NAL physical loss sensitivity',version:'1',params:p,metrics:{fidelity:0},
      noise:{loss:{events:losses},channels:[],gate_diagnostics:[],upstream_records:{}}};
    trace.loss_time_result={durations,counts,raw_event_probability_sum:budget,diagnostics,
      heating_saturated:diagnostics.filter(d=>d.probability>=1-1e-12).length,
      maximum_delta_n:Math.max(0,...diagnostics.map(d=>d.deltaN)),feedback_wait_us:budget.feedback_wait,
      pending_result_tail_us:trace.duration_us-clock,
      depth_microkelvin:.5*p.mass*AMU*(2*Math.PI*p.frequency*1e3)**2*(p.width*1e-6)**2/KB*1e6};
    // The original validation applies to the saved schedule, not these new timestamps.
    trace.compilation={metrics:{duration_us:trace.duration_us},sensitivity:'Fixed geometry and action order; times recomputed in browser.'};
    return trace;
  }
  const api={DEFAULTS,SOURCES,transportLoss,probabilityFromEta,retime,validate};
  root.ShorLossTime=api;
  if(typeof module!=='undefined')module.exports=api;
})(globalThis);
