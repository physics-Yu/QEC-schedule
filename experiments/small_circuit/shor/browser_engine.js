/* L2 instantaneous-pulse statevector trajectories for a fixed physical plan.
 * Static Gaussian detuning plus exact event-to-event OU integrals; all pulse
 * rotations enter the quantum state. Pulse width reserves schedule space only:
 * finite-width drive Hamiltonians, leakage and correlated atom noise are absent.
 */
(function (root) {
  'use strict';
  const DEFAULTS = Object.freeze({speed:1,transfer:15,readout:100,singleTime:1,
    czTime:.5,resetTime:5,latency:0,loadLoss:.002,storeLoss:.002,czLoss:.001,
    imagingLoss:.001,singleLoss:0,resetLoss:0,mass:86.909180531,frequency:90,
    width:.73,temperature:27,depthSpread:0,
    singlePauli:0,czPauli:.0005,readoutError:.001,resetError:.001,
    t2Star:3,t2Echo:300,tauC:1,
    dd:1,tPi:1,tauMax:250,pulseError:0,pulseDuringTransfer:1});
  const PROBABILITIES = new Set(['loadLoss','storeLoss','czLoss','imagingLoss',
    'singleLoss','resetLoss','singlePauli','czPauli','readoutError','resetError']);
  const SWITCHES = new Set(['dd','pulseDuringTransfer']);
  const TIMING = ['speed','transfer','readout','singleTime','czTime','resetTime','latency'];
  const clone = x => JSON.parse(JSON.stringify(x));
  const now = () => typeof performance !== 'undefined' ? performance.now() : Date.now();
  function parameters(values) {
    const p={...DEFAULTS,...(values||{})};
    for (const [key,value] of Object.entries(p)) {
      if (!(key in DEFAULTS)) throw Error('Unknown parameter: '+key);
      if (typeof value!=='number'||!Number.isFinite(value)||value<0) throw Error(key+' must be finite and nonnegative.');
      if (PROBABILITIES.has(key)&&value>1) throw Error(key+' must be between 0 and 1.');
      if (SWITCHES.has(key)&&value!==0&&value!==1) throw Error(key+' 只能取 0（关）或 1（开）。');
    }
    if (p.speed<.01) throw Error('移动平均速度不得低于 0.01 μm/μs。');
    if (p.transfer>1000) throw Error('LOAD／STORE 时间不得超过 1000 μs。');
    if (p.latency!==0) throw Error('读出曝光结束后结果立即可用；额外延迟固定为 0。');
    for (const key of ['mass','frequency','width']) if (!p[key]) throw Error(key+' must be positive.');
    {
      if (!(p.t2Echo>0)) throw Error('T₂^echo 必须为正。');
      if (!(p.tauC>0)) throw Error('关联时间 τ_c 必须为正。');
      if (p.dd===1) {
        if (!(p.tPi>0)) throw Error('π 脉冲时长必须为正。');
        if (p.tauMax<5*p.tPi) throw Error('DD 最大间隔 τ_max 不得小于 5·t_π（当前 5·t_π = '+5*p.tPi+' μs）。');
      }
      noiseRates(p); // throws if T2* and T2echo are inconsistent
    }
    return p;
  }

  // ---- Level-2 noise: rates and exact OU sampling (all times in microseconds) ----
  // g(x) = x - 3 + 4e^{-x/2} - e^{-x}  (Hahn echo of OU noise, x = t/tau_c)
  // h(x) = x - 1 + e^{-x}              (Ramsey of OU noise)
  function smallSeries(x,start,coefficient){
    let sum=0,power=1,factorial=1;
    for(let k=1;k<=16;k++){power*=x;factorial*=k;if(k>=start)sum+=coefficient(k)*power/factorial;}
    return sum;
  }
  const echoG = x => x<.01 ? smallSeries(x,3,k=>(k%2?-1:1)*(4/2**k-1)) : x+4*Math.expm1(-x/2)-Math.expm1(-x);
  const ramseyH = x => x<.01 ? smallSeries(x,2,k=>k%2?-1:1) : x+Math.expm1(-x);
  const ouIntegralVariance = y => y<.01 ? smallSeries(y,3,k=>(k%2?-1:1)*(4-2**k)) : 2*y+4*Math.expm1(-y)-Math.expm1(-2*y);
  function noiseRates(p) {
    const tc=p.tauC*1000, te=p.t2Echo*1000;
    const varF=1/(tc*tc*echoG(te/tc));            // sigma_f^2 [rad^2/us^2]: echo Var(T2echo) = 2
    if(!Number.isFinite(tc)||!Number.isFinite(te)||!Number.isFinite(varF)||varF<0)
      throw Error('相干时间参数超出可稳定计算的数值范围。');
    let varS=0;
    if (p.t2Star>0) {
      const ts=p.t2Star*1000, fastRamsey=2*varF*tc*tc*ramseyH(ts/tc);
      if (!Number.isFinite(ts)||!Number.isFinite(fastRamsey)||fastRamsey>2+1e-12) throw Error('T₂* 与 T₂^echo、τ_c 不相容：仅快涨落就会让 Ramsey 在 T₂* 之前衰减到 1/e。请减小 T₂*，或增大 T₂^echo。');
      varS=Math.max(0,2-fastRamsey)/(ts*ts);         // total Ramsey Var(T2*) = 2
      if(!Number.isFinite(varS))throw Error('T₂* 超出可稳定计算的数值范围。');
    }
    return {sigmaS:Math.sqrt(varS),sigmaF:Math.sqrt(varF),tauC:tc};
  }
  // Exact joint step of an OU process x and its integral over dt.
  function ouStep(x,dt,sigma,tc,gauss){
    if(!(dt>0)||sigma===0)return [x,0];
    const y=dt/tc,e1=Math.expm1(-y),a=1+e1;
    const v1=sigma*sigma*(-Math.expm1(-2*y));
    const v2=sigma*sigma*tc*tc*ouIntegralVariance(y);
    const c12=sigma*sigma*tc*e1*e1;
    const l11=Math.sqrt(Math.max(v1,0)),l21=l11>0?c12/l11:0,l22=Math.sqrt(Math.max(v2-l21*l21,0));
    const z1=gauss(),z2=gauss();
    return [a*x+l11*z1, -tc*e1*x+l21*z1+l22*z2];
  }

  function retime(input, values) {
    const p=parameters(values),plan=clone(input),nodes=new Map(plan.dag.nodes.map(x=>[x.id,x]));
    const predecessors=new Map(plan.dag.nodes.map(x=>[x.id,[]]));
    for (const [a,b] of plan.dag.edges) predecessors.get(b).push(a);
    const ends=new Map(),available=new Map(),metadata=new Map(plan.measurements.map(x=>[x.measurement_id,x]));
    const positions=new Map(plan.initial.atoms.map(x=>[x.id,[x.x,x.y]]));
    const original=plan.steps,steps=[],measured=[];let clock=0,index=0;
    function conditionTime(node) {
      if (!node.condition) return 0;
      const id=node.condition.result.measurement_id;
      if (!available.has(id)) throw Error('Feedback references unscheduled measurement '+id);
      return available.get(id);
    }
    function nodeEnd(id) {
      if (!ends.has(id)) {
        const node=nodes.get(id);
        if (!['barrier','global_phase'].includes(node.name)) throw Error('Unscheduled native dependency '+id);
        ends.set(id,Math.max(0,conditionTime(node),...predecessors.get(id).map(nodeEnd)));
      }
      return ends.get(id);
    }
    let upcoming=[];const requirements=Array(original.length);
    for (let i=original.length-1;i>=0;i--) {
      const ids=original[i].actions.flatMap(a=>a.source_ids);
      if (ids.length) upcoming=ids;
      requirements[i]=upcoming;
    }
    function wait(duration,oi,reason) {
      steps.push({index:steps.length,original_index:oi,start_us:clock,duration_us:duration,
        actions:[{index:index++,kind:'Wait',duration_us:duration,source_ids:[],atoms:[],parameters:{},pairs:[],coverage:null,patch:{atoms:[],grids:[]},text:reason}]});
      clock+=duration;
    }
    const keys={Load:'transfer',Store:'transfer',Measure:'readout',LocalU:'singleTime',
      Rotation:'singleTime',GlobalRY:'singleTime',CZPulse:'czTime',Reset:'resetTime'};
    for (let i=0;i<original.length;i++) {
      const old=original[i];if(old.actions.every(a=>a.kind==='Wait'))continue;
      let earliest=clock;
      for(const id of requirements[i]) earliest=Math.max(earliest,conditionTime(nodes.get(id)),...predecessors.get(id).map(nodeEnd));
      if(earliest>clock)wait(earliest-clock,i,'WAIT: classical result availability');
      const actions=old.actions;
      for(const a of actions){
        let duration;
        if(a.kind==='Move'){
          const targets=new Map(a.patch.atoms.map(x=>[x.id,[x.x,x.y]]));
          a.movement=a.atoms.map(atom=>{const first=positions.get(atom),last=targets.get(atom)||first;
            return {atom,distance_um:Math.hypot(last[0]-first[0],last[1]-first[1])};});
          duration=Math.max(0,...a.movement.map(x=>x.distance_um))/p.speed;
        }else if(a.kind in keys)duration=p[keys[a.kind]];
        else throw Error('Unsupported guarded-plan action: '+a.kind);
        a.duration_us=duration;a.index=index++;a.text=a.kind+': '+duration+' us';
        for(const id of a.source_ids)ends.set(id,Math.max(ends.get(id)||0,clock+duration));
        if(a.kind==='Measure')for(const x of a.parameters.results){
          available.set(x.measurement_id,clock+duration);
          measured.push({...metadata.get(x.measurement_id),start_us:clock,end_us:clock+duration,available_at_us:clock+duration});
        }
      }
      const duration=Math.max(...actions.map(a=>a.duration_us));
      steps.push({index:steps.length,original_index:old.original_index??i,start_us:clock,duration_us:duration,actions});clock+=duration;
      for(const a of actions)for(const atom of a.patch.atoms)positions.set(atom.id,[atom.x,atom.y]);
    }
    const programDuration=clock,last=Math.max(clock,...available.values());
    if(last>clock)wait(last-clock,original.length,'WAIT: final classical results');
    return {...plan,steps,duration_us:clock,program_duration_us:programDuration,
      measurement_times:measured,timing:Object.fromEntries(TIMING.map(k=>[k,p[k]]))};
  }

  function legendre(n){
    const result=[];
    for(let i=1;i<=n;i++){
      let x=Math.cos(Math.PI*(i-.25)/(n+.5)),derivative=0;
      for(let iteration=0;iteration<40;iteration++){
        let a=1,b=x;
        for(let j=2;j<=n;j++){const c=((2*j-1)*x*b-(j-1)*a)/j;a=b;b=c;}
        derivative=n*(x*b-a)/(x*x-1);
        const next=x-b/derivative;if(Math.abs(next-x)<1e-15){x=next;break;}x=next;
      }
      result.push([x,2/((1-x*x)*derivative*derivative)]);
    }
    return result;
  }
  const GAUSS=legendre(64),KB=1.380649e-23,AMU=1.66053906660e-27;
  function moveLoss(distance,duration,p){
    if(distance===0)return 0;
    if(!(duration>0))throw Error('A nonzero Move needs positive duration.');
    const omega=2*Math.PI*p.frequency*1000,m=p.mass*AMU;
    const depth=m*omega**2*(p.width*1e-6)**2/2;
    const energy=(50/3)*m*(distance*1e-6)**2/(omega**2*(duration*1e-6)**4),thermal=KB*p.temperature*1e-6;
    function at(z){const remaining=depth*(1+p.depthSpread*z)-energy;
      if(!thermal)return remaining<=0?1:0;
      const eta=Math.max(0,Math.min(745,remaining/thermal));return (1+eta+eta*eta/2)*Math.exp(-eta);}
    if(!p.depthSpread)return at(0);
    const low=Math.max(-8,-1/p.depthSpread),threshold=(energy/depth-1)/p.depthSpread;
    const cuts=[low,...(threshold>low&&threshold<8?[threshold]:[]),8];let total=0,weight=0;
    for(let i=1;i<cuts.length;i++)for(const [x,w] of GAUSS){
      const scale=(cuts[i]-cuts[i-1])/2,z=(cuts[i]+cuts[i-1])/2+scale*x,q=scale*w*Math.exp(-z*z/2);
      total+=q*at(z);weight+=q;
    }
    return Math.max(0,Math.min(1,total/weight));
  }
  function mergeIntervals(list){
    const sorted=list.filter(x=>x[1]>x[0]).sort((a,b)=>a[0]-b[0]),out=[];
    for(const [s,e] of sorted){if(out.length&&s<=out[out.length-1][1])out[out.length-1][1]=Math.max(out[out.length-1][1],e);else out.push([s,e]);}
    return out;
  }
  function complement(merged,end){
    const out=[];let t=0;for(const [s,e] of merged){if(s>t)out.push([t,s]);t=Math.max(t,e);}if(end>t)out.push([t,end]);return out;
  }
  function luMatrix(theta,phi,lam){const c=Math.cos(theta/2),s=Math.sin(theta/2);
    return [c,0,-s*Math.cos(lam),-s*Math.sin(lam),s*Math.cos(phi),s*Math.sin(phi),c*Math.cos(phi+lam),c*Math.sin(phi+lam)];}
  function storageReadoutWindows(plan,retirement,p={pulseDuringTransfer:0}){
    const zones=(plan.dd_zones||[]).filter(z=>z.role==='storage').map(z=>z.bounds);
    if(!zones.length)return [];
    for(const b of zones)if(!b||!['x_min','y_min','x_max','y_max'].every(k=>Number.isFinite(b[k]))||b.x_max<b.x_min||b.y_max<b.y_min)
      throw Error('Storage DD requires valid compiler-supplied zone bounds.');
    const contains=(p,b)=>p.x>=b.x_min&&p.x<=b.x_max&&p.y>=b.y_min&&p.y<=b.y_max;
    const inStorage=p=>zones.some(b=>contains(p,b));
    const crossesStorage=(a,b)=>zones.some(z=>Math.max(a.x,b.x)>=z.x_min&&Math.min(a.x,b.x)<=z.x_max&&Math.max(a.y,b.y)>=z.y_min&&Math.min(a.y,b.y)<=z.y_max);
    const entry=new Map(plan.initial.atoms.map(a=>[a.id,{x:a.x,y:a.y}]));
    const qubit=new Map(plan.initial.atoms.map(a=>[a.id,a.qubit])),records=[],patches=[],cuts=new Set([0,plan.duration_us]);
    for(const step of plan.steps){
      for(const action of step.actions){
        const start=step.start_us,end=start+action.duration_us;
        const atoms=action.kind==='CZPulse'?[...new Set(action.pairs.flat())]:action.atoms;
        const destination=new Map(action.patch.atoms.map(a=>[a.id,{x:a.x,y:a.y}]));
        records.push({kind:action.kind,start,end,atoms,
          routes:atoms.map(atom=>({atom,from:entry.get(atom),to:destination.get(atom)||entry.get(atom)}))});
        cuts.add(start);cuts.add(end);
        for(const atom of action.patch.atoms)patches.push({t:end,atom:atom.id,position:{x:atom.x,y:atom.y},index:action.index??0});
      }
      for(const action of step.actions)for(const atom of action.patch.atoms)entry.set(atom.id,{x:atom.x,y:atom.y});
    }
    const boundaries=[...cuts].sort((a,b)=>a-b),positions=new Map(plan.initial.atoms.map(a=>[a.id,{x:a.x,y:a.y}]));
    patches.sort((a,b)=>a.t-b.t||a.index-b.index);
    const result=[];let patchIndex=0;
    for(let i=1;i<boundaries.length;i++){
      const start=boundaries[i-1],end=boundaries[i];
      while(patchIndex<patches.length&&patches[patchIndex].t<=start){const change=patches[patchIndex++];positions.set(change.atom,change.position);}
      if(!(end>start))continue;
      const active=records.filter(a=>a.start<end&&a.end>start);
      if(!active.some(a=>a.kind==='Measure'))continue;
      // Zone-wide illumination is assumed. If any atom in the storage region
      // is addressed or may move through it, the entire region's DD is paused.
      const blocked=active.some(a=>{
        if(a.kind==='Move')return a.routes.some(r=>crossesStorage(r.from,r.to));
        if(a.kind==='Load'||a.kind==='Store')return a.routes.some(r=>crossesStorage(r.from,r.to)&&
          (p.pulseDuringTransfer!==1||r.from.x!==r.to.x||r.from.y!==r.to.y));
        return ['LocalU','CZPulse','Reset','Measure'].includes(a.kind)&&
          a.atoms.some(atom=>inStorage(positions.get(atom)));
      });
      if(blocked)continue;
      const targets=plan.initial.atoms.filter(a=>inStorage(positions.get(a.id))&&
        (!retirement.has(a.qubit)||retirement.get(a.qubit)>start)).map(a=>a.qubit);
      if(targets.length)result.push({start_us:start,end_us:end,qubits:targets,scope:'storage_during_readout',scope_label:'读出期间存储区 XY4'});
    }
    return result;
  }
  function buildLevel2(plan,p,wires,bits){
    const end=plan.duration_us,atomIds=plan.initial.atoms.map(a=>a.id);
    const busy=new Map(atomIds.map(a=>[a,[]])),instantBoundaries=new Set(),events=[],actions=[];let seq=0;
    const sourceNodes=new Map(plan.dag.nodes.map(n=>[n.id,n]));
    for(const step of plan.steps){
      const t0=step.start_us;
      for(const a of step.actions){
        const t1=t0+a.duration_us,guard=a.guard?{bit:bits.get(a.guard.measurement_id),value:a.guard.value}:null;
        const mark=atoms=>{
          for(const atom of atoms)busy.get(atom).push([t0,t1]);
          if(atoms.length&&t1===t0)instantBoundaries.add(t0);
        };
        const meta={action_index:a.index,source_ids:a.source_ids||[],start_us:t0,end_us:t1};
        const names=(a.source_ids||[]).map(id=>sourceNodes.get(id)?.name).filter(Boolean);
        const label=names.length?[...new Set(names)].join('/'):{Load:'LOAD',Store:'STORE',Move:'MOVE',Wait:'WAIT'}[a.kind]||a.kind;
        const qubits=(a.kind==='CZPulse'?[...new Set(a.pairs.flat())]:a.atoms).map(atom=>wires.get(atom));
        const pairs=a.kind==='CZPulse'?a.pairs.map(pair=>pair.map(atom=>wires.get(atom))):[];
        actions.push({...meta,kind:a.kind,qubits,pairs,guard,label,quantum_time_us:a.kind==='Measure'?t1:
          ['LocalU','CZPulse','Reset'].includes(a.kind)?t0:null});
        if(a.kind==='LocalU'){
          const {theta,phi,lam}=a.parameters;
          mark(a.atoms); // All gates reserve their slots, including false conditional Phase.
          for(const atom of a.atoms)events.push({...meta,t:t0,cls:1,seq:seq++,type:'gate',q:wires.get(atom),
            matrix:luMatrix(theta,phi,lam),guard,error:p.singlePauli,label});
        }else if(a.kind==='CZPulse'){
          mark(a.pairs.flat());
          for(const pair of a.pairs)events.push({...meta,t:t0,cls:1,seq:seq++,type:'cz',q:wires.get(pair[0]),q2:wires.get(pair[1]),error:p.czPauli,label:'CZ'});
        }else if(a.kind==='Measure'){
          mark(a.parameters.results.map(r=>r.atom_id));
          for(const r of a.parameters.results)events.push({...meta,t:t1,cls:0,seq:seq++,type:'measure',q:wires.get(r.atom_id),
            bit:bits.get(r.measurement_id),measurement_id:r.measurement_id,error:p.readoutError,release:false});
        }else if(a.kind==='Reset'){
          mark(a.atoms);
          for(const atom of a.atoms)events.push({...meta,t:t0,cls:1,seq:seq++,type:'reset',q:wires.get(atom),error:p.resetError});
        }else if(a.kind==='Load'||a.kind==='Store'){
          if(p.pulseDuringTransfer!==1)mark(a.atoms);
        }
      }
    }
    const busyMerged=new Map(atomIds.map(a=>[a,mergeIntervals(busy.get(a))]));
    // A zero-width algorithm operation is still an ordering boundary: a whole
    // XY4 block cannot straddle it even though it removes no idle duration.
    const boundaries=[...instantBoundaries].sort((a,b)=>a-b);
    const globalIdle=complement(mergeIntervals([...busy.values()].flat()),end).flatMap(([s,e])=>{
      const cuts=[s,...boundaries.filter(t=>t>s&&t<e),e];
      return cuts.slice(1).map((t,i)=>[cuts[i],t]);
    });
    const eventOrder=(a,b)=>a.t-b.t||((a.action_index??Infinity)-(b.action_index??Infinity))||a.cls-b.cls||a.seq-b.seq;
    events.sort(eventOrder);
    const later=new Set();
    for(let i=events.length-1;i>=0;i--){const ev=events[i];
      if(ev.type==='measure'&&!later.has(ev.q))ev.release=true;
      later.add(ev.q);if(ev.q2!==undefined)later.add(ev.q2);}
    const retirement=new Map(events.filter(ev=>ev.type==='measure'&&ev.release).map(ev=>[ev.q,ev.t]));
    const storageIdle=storageReadoutWindows(plan,retirement,p);
    const windows=[...globalIdle.map(([start_us,end_us])=>({start_us,end_us,scope:'global',scope_label:'全局空闲 XY4',
      qubits:plan.initial.atoms.map(a=>a.qubit).filter(q=>!retirement.has(q)||retirement.get(q)>start_us)})),...storageIdle].sort((a,b)=>a.start_us-b.start_us);
    const blocks=[],pulses=[];
    if(p.dd===1){
      for(const window of windows){
        const s=window.start_us,e=window.end_us;if(!window.qubits.length)continue;
        const L=e-s;if(L<20*p.tPi)continue;
        const n=Math.ceil(L/(4*p.tauMax)),tau=L/(4*n);if(tau<5*p.tPi)continue;
        if(pulses.length+4*n>100000)throw Error('本计划超过 100000 个 DD 脉冲；请增大 DD 间隔或提高移动速度。');
        const block_index=blocks.length;
        blocks.push({...window,n,tau_us:tau});
        for(let k=0;k<4*n;k++){
          const t=s+tau/2+k*tau,axis=k%2;
          const pulse={time_us:t,start_us:t-p.tPi/2,end_us:t+p.tPi/2,axis:axis?'Y':'X',angle_rad:Math.PI*(1+p.pulseError),
            block_index,scope:window.scope,scope_label:window.scope_label,qubits:[...window.qubits]};
          if(pulse.start_us<s-1e-9||pulse.end_us>e+1e-9)throw Error('DD pulse reservation exceeds idle interval.');
          pulses.push(pulse);events.push({t,cls:2,seq:seq++,type:'pulse',axis,pulse_index:pulses.length-1,targets:[...window.qubits]});
        }
      }
    }
    // Source action ordering resolves ties when duration-zero actions share time;
    // a completed measurement must precede any feedback depending on it.
    events.sort(eventOrder);
    const n=plan.num_qubits,neighbors=Array.from({length:n},()=>[]),active=new Set();
    for(const ev of events){if(ev.type==='measure')active.add(ev.q);if(ev.type==='cz'){neighbors[ev.q].push(ev.q2);neighbors[ev.q2].push(ev.q);}}
    const queue=[...active];for(let i=0;i<queue.length;i++)for(const q of neighbors[queue[i]])if(!active.has(q)){active.add(q);queue.push(q);}
    const kept=[...active].sort((a,b)=>a-b),index=new Map(kept.map((q,i)=>[q,i]));
    const compact=events.filter(ev=>ev.type==='pulse'||index.has(ev.q)).map(ev=>{
      if(ev.type==='pulse')return {...ev,targets:ev.targets.filter(q=>index.has(q)).map(q=>index.get(q))};
      const r={...ev,original_q:ev.q,q:index.get(ev.q)};
      if(ev.q2!==undefined){r.original_q2=ev.q2;r.q2=index.get(ev.q2);}return r;});
    let idleTotal=0,scheduledTotal=0,longest=0;
    for(const atom of plan.initial.atoms){
      const terminal=retirement.get(atom.qubit)??end;
      const idle=complement(busyMerged.get(atom.id),end).map(([a,b])=>[a,Math.min(b,terminal)]).filter(([a,b])=>b>a);
      for(const [a,b] of idle){
        idleTotal+=b-a;let cursor=a;
        for(const block of blocks){if(!block.qubits.includes(atom.qubit))continue;
          const left=Math.max(a,block.start_us),right=Math.min(b,block.end_us);
          if(right<=left)continue;longest=Math.max(longest,left-cursor);scheduledTotal+=right-left;cursor=right;}
        longest=Math.max(longest,b-cursor);
      }
    }
    const schedule={duration_us:end,qubits:plan.initial.atoms.map(a=>({qubit:a.qubit,atom:a.id,retired_at_us:retirement.get(a.qubit)??null})),
      actions,pulses,blocks,global_idle:globalIdle.map(([start_us,end_us])=>({start_us,end_us})),storage_readout_idle:storageIdle,
      selected_bitstring:null,selection_label:'尚未采样；条件门显示保留的时间槽',
      pulse_model:'instantaneous unitary at center; displayed width is reserved time, not finite-width drive evolution',
      storage_readout_assumption:'Storage-region addressing can operate while the separate readout region is illuminated; zone-wide pulses pause for storage-region gates or intersecting movement. Stationary LOAD/STORE permits pulses only when pulseDuringTransfer=1; not a hardware validation.'};
    return {events:compact,num_qubits:kept.length,kept_qubits:kept,rates:noiseRates(p),schedule,
      busy:[...busyMerged].map(([atom,intervals])=>({atom,intervals})),globalIdle,storageIdle,blocks,pulses,
      dd:{enabled:p.dd===1,blocks:blocks.reduce((sum,b)=>sum+b.n,0),windows:blocks.length,pulses:pulses.length,
        global_pulses:pulses.filter(p=>p.scope==='global').length,
        storage_readout_windows:blocks.filter(b=>b.scope==='storage_during_readout').length,
        storage_readout_pulses:pulses.filter(p=>p.scope==='storage_during_readout').length,
        global_idle_us:globalIdle.reduce((s,[a,b])=>s+b-a,0),scheduled_fraction:idleTotal?scheduledTotal/idleTotal:0,
        longest_unscheduled_idle_us:longest,mean_unscheduled_idle_us:atomIds.length?(idleTotal-scheduledTotal)/atomIds.length:0,
        coverage_scope:'fraction of pre-readout idle atom-time inside scheduled XY4 blocks; not a fidelity guarantee',deferred_diagonal_gates:0}};
  }
  const caches=new WeakMap();
  function prepare(input,values){
    const p=parameters(values),key=JSON.stringify(Object.keys(p).sort().map(k=>[k,p[k]]));
    let cache=caches.get(input);if(!cache){cache=new Map();caches.set(input,cache);}
    if(cache.has(key))return cache.get(key);
    const plan=retime(input,p),wires=new Map(plan.initial.atoms.map(a=>[a.id,a.qubit]));
    const bits=new Map(plan.measurements.map(m=>[m.measurement_id,m.bit])),losses=[];
    for(const step of plan.steps)for(const a of step.actions){
      if(!['LocalU','CZPulse','Reset','Measure','Load','Store','Move','Wait'].includes(a.kind))throw Error('Unsupported physical action '+a.kind);
      const guard=a.guard?{bit:bits.get(a.guard.measurement_id),value:a.guard.value}:null;
      const source={Load:'load',Store:'store',Move:'move',CZPulse:'cz',Measure:'imaging',LocalU:'single',Reset:'reset'}[a.kind];
      if(!source)continue;
      const participants=a.kind==='CZPulse'?[...new Set(a.pairs.flat())].sort((a,b)=>a-b):a.atoms;
      const distances=new Map((a.movement||[]).map(x=>[x.atom,x.distance_um]));
      for(const atom of participants){const probability=a.kind==='Move'?moveLoss(distances.get(atom),a.duration_us,p):p[source+'Loss'];
        if(probability)losses.push({time_us:step.start_us+a.duration_us,atom,cause:source,probability,guard});}
    }
    losses.sort((a,b)=>a.time_us-b.time_us);
    const result={parameters:p,plan,losses,level2:buildLevel2(plan,p,wires,bits)};
    if(cache.size>=8)cache.delete(cache.keys().next().value);cache.set(key,result);return result;
  }

  function random(seed){let state=seed>>>0;return function(){
    state=(state+0x6D2B79F5)>>>0;let t=state;t=Math.imul(t^(t>>>15),t|1);
    t^=t+Math.imul(t^(t>>>7),t|61);return ((t^(t>>>14))>>>0)/4294967296;
  };}
  class State {
    constructor(n){this.n=n;this.r=new Float64Array(2**n);this.i=new Float64Array(2**n);this.map=new Int16Array(n);this.reset();}
    reset(){this.size=2**this.n;this.r.fill(0);this.i.fill(0);this.r[0]=1;for(let q=0;q<this.n;q++)this.map[q]=q;}
    z(q){const bit=1<<this.map[q],block=bit*2,r=this.r,im=this.i;
      for(let start=0;start<this.size;start+=block)for(let j=start+bit;j<start+block;j++){r[j]=-r[j];im[j]=-im[j];}}
    x(q){const bit=1<<this.map[q],block=bit*2,r=this.r,im=this.i;
      for(let start=0;start<this.size;start+=block)for(let j=start;j<start+bit;j++){const k=j+bit,t=r[j],u=im[j];r[j]=r[k];im[j]=im[k];r[k]=t;im[k]=u;}}
    pauli(q,type){if(type===1)this.x(q);else if(type===2){this.x(q);this.z(q);}else if(type===3)this.z(q);}
    h(q){const bit=1<<this.map[q],block=bit*2,r=this.r,im=this.i,k=Math.SQRT1_2;
      for(let start=0;start<this.size;start+=block)for(let j=start;j<start+bit;j++){const l=j+bit,a=r[j],b=im[j],c=r[l],d=im[l];r[j]=(a+c)*k;im[j]=(b+d)*k;r[l]=(a-c)*k;im[l]=(b-d)*k;}}
    phase(q,m){const bit=1<<this.map[q],block=bit*2,r=this.r,im=this.i,pr=m[6],pi=m[7],zero=m[0];
      for(let start=0;start<this.size;start+=block){
        if(zero!==1)for(let j=start;j<start+bit;j++){r[j]*=zero;im[j]*=zero;}
        for(let j=start+bit;j<start+block;j++){const a=r[j],b=im[j];r[j]=pr*a-pi*b;im[j]=pr*b+pi*a;}
      }}
    u(q,m){const bit=1<<this.map[q],block=bit*2,r=this.r,im=this.i;
      for(let start=0;start<this.size;start+=block)for(let j=start;j<start+bit;j++){const k=j+bit,a=r[j],b=im[j],c=r[k],d=im[k];
        r[j]=m[0]*a-m[1]*b+m[2]*c-m[3]*d;im[j]=m[0]*b+m[1]*a+m[2]*d+m[3]*c;
        r[k]=m[4]*a-m[5]*b+m[6]*c-m[7]*d;im[k]=m[4]*b+m[5]*a+m[6]*d+m[7]*c;}}
    cz(q,q2){const mask=(1<<this.map[q])|(1<<this.map[q2]),r=this.r,im=this.i;
      for(let j=0;j<this.size;j++)if((j&mask)===mask){r[j]=-r[j];im[j]=-im[j];}}
    measure(q,rng,release){const at=this.map[q],bit=1<<at,block=bit*2,r=this.r,im=this.i;let p1=0,total=0;
      for(let start=0;start<this.size;start+=block){for(let j=start;j<start+bit;j++)total+=r[j]*r[j]+im[j]*im[j];
        for(let j=start+bit;j<start+block;j++){const p=r[j]*r[j]+im[j]*im[j];p1+=p;total+=p;}}
      if(!(total>0)||!Number.isFinite(total))throw Error('Invalid state norm.');
      const value=rng()<Math.max(0,Math.min(1,p1/total))?1:0,probability=value?p1:total-p1;
      if(!(probability>0))throw Error('Sampled a zero-probability measurement.');
      const norm=1/Math.sqrt(probability);
      if(release){const size=this.size/2,low=bit-1;
        for(let j=0;j<size;j++){const k=(j&low)|((j>>>at)<<(at+1))|(value<<at);r[j]=r[k]*norm;im[j]=im[k]*norm;}
        this.size=size;this.map[q]=-1;for(let k=0;k<this.map.length;k++)if(this.map[k]>at)this.map[k]--;
      }else for(let j=0;j<this.size;j++){if(((j&bit)!==0)===Boolean(value)){r[j]*=norm;im[j]*=norm;}else{r[j]=0;im[j]=0;}}
      return value;
    }
  }
  function sample(plan,values,shots,seed){
    if(!Number.isInteger(shots)||shots<1||shots>10000)throw Error('shots must be an integer from 1 to 10000.');
    if(!Number.isInteger(seed)||seed<0||seed>=2**32)throw Error('seed must be an unsigned 32-bit integer.');
    const start=now(),prepared=prepare(plan,values),preparation=(now()-start)/1000;
    const {losses,parameters:p}=prepared,rng=random(seed),lossRng=random((seed^0x4C4F5353)>>>0);
    const counts=runLevel2(prepared.level2,p,plan.num_bits,shots,rng);
    return finish(plan,prepared,counts,losses,lossRng,shots,seed,start,preparation,prepared.level2.num_qubits);
  }

  // ---- Level-2 trajectories ----
  const PAULI_M=[null,[0,0,1,0,1,0,0,0],[0,0,1,0,-1,0,0,0],[1,0,0,0,0,0,-1,0]]; // X, Z·X (legacy "Y"), Z
  function mul2(A,B,out){ // out = A·B, 2x2 complex, layout [00re,00im,01re,01im,10re,10im,11re,11im]
    const r00=A[0]*B[0]-A[1]*B[1]+A[2]*B[4]-A[3]*B[5],i00=A[0]*B[1]+A[1]*B[0]+A[2]*B[5]+A[3]*B[4];
    const r01=A[0]*B[2]-A[1]*B[3]+A[2]*B[6]-A[3]*B[7],i01=A[0]*B[3]+A[1]*B[2]+A[2]*B[7]+A[3]*B[6];
    const r10=A[4]*B[0]-A[5]*B[1]+A[6]*B[4]-A[7]*B[5],i10=A[4]*B[1]+A[5]*B[0]+A[6]*B[5]+A[7]*B[4];
    const r11=A[4]*B[2]-A[5]*B[3]+A[6]*B[6]-A[7]*B[7],i11=A[4]*B[3]+A[5]*B[2]+A[6]*B[7]+A[7]*B[6];
    out[0]=r00;out[1]=i00;out[2]=r01;out[3]=i01;out[4]=r10;out[5]=i10;out[6]=r11;out[7]=i11;return out;
  }
  function pulseMatrix(axis,error){ // R(pi(1+error), phi), phi = 0 (X) or pi/2 (Y)
    const th=Math.PI*(1+error),c=Math.cos(th/2),s=Math.sin(th/2),ph=axis?Math.PI/2:0;
    // [[c, -i e^{-i ph} s], [-i e^{i ph} s, c]]
    return [c,0,-s*Math.sin(ph),-s*Math.cos(ph),s*Math.sin(ph),-s*Math.cos(ph),c,0];
  }
  function gaussian(rng){let spare=null;return function(){
    if(spare!==null){const v=spare;spare=null;return v;}
    let u=0;while(u===0)u=rng();const v=rng(),r=Math.sqrt(-2*Math.log(u));spare=r*Math.sin(2*Math.PI*v);return r*Math.cos(2*Math.PI*v);};}
  function runLevel2(model,p,numBits,shots,rng){
    const {events,num_qubits:n,rates}=model,{sigmaS,sigmaF,tauC}=rates,gauss=gaussian(rng);
    const state=new State(n),classical=new Uint8Array(numBits),counts=new Map();
    const M=Array.from({length:n},()=>new Float64Array(8)),tmp=new Float64Array(8),D=new Float64Array(8);
    const eps=new Float64Array(n),xi=new Float64Array(n),tLast=new Float64Array(n),live=new Uint8Array(n),dirty=new Uint8Array(n);
    const allTargets=Array.from({length:n},(_,q)=>q);
    const P=[pulseMatrix(0,p.pulseError),pulseMatrix(1,p.pulseError)];
    const identity=m=>{m.fill(0);m[0]=1;m[6]=1;};
    function leftMul(q,G){mul2(G,M[q],tmp);M[q].set(tmp);dirty[q]=1;}
    function advance(q,t){
      const dt=t-tLast[q];if(!(dt>0))return;tLast[q]=t;
      const [x,integral]=ouStep(xi[q],dt,sigmaF,tauC,gauss);xi[q]=x;
      const phi=eps[q]*dt+integral;if(phi===0)return;
      const c=Math.cos(phi/2),s=Math.sin(phi/2);            // Rz(phi) = diag(e^{-i phi/2}, e^{i phi/2})
      D[0]=c;D[1]=-s;D[2]=0;D[3]=0;D[4]=0;D[5]=0;D[6]=c;D[7]=s;leftMul(q,D);
    }
    function flush(q){if(dirty[q]){state.u(q,M[q]);identity(M[q]);dirty[q]=0;}}
    for(let shot=0;shot<shots;shot++){
      state.reset();classical.fill(0);
      for(let q=0;q<n;q++){identity(M[q]);dirty[q]=0;live[q]=1;tLast[q]=0;eps[q]=sigmaS*gauss();xi[q]=sigmaF*gauss();}
      for(const ev of events){
        switch(ev.type){
          case 'pulse':
            for(const q of ev.targets??allTargets)if(live[q]){advance(q,ev.t);leftMul(q,P[ev.axis]);}
            break;
          case 'gate':
            if(ev.guard&&classical[ev.guard.bit]!==ev.guard.value)break;
            advance(ev.q,ev.t);leftMul(ev.q,ev.matrix);
            if(ev.error&&rng()<ev.error)leftMul(ev.q,PAULI_M[1+Math.floor(rng()*3)]);
            break;
          case 'cz':
            advance(ev.q,ev.t);advance(ev.q2,ev.t);flush(ev.q);flush(ev.q2);state.cz(ev.q,ev.q2);
            if(ev.error&&rng()<ev.error){const code=1+Math.floor(rng()*15);
              if(code&3)leftMul(ev.q,PAULI_M[code&3]);if(code>>>2)leftMul(ev.q2,PAULI_M[code>>>2]);}
            break;
          case 'measure':{
            advance(ev.q,ev.t);flush(ev.q);let b=state.measure(ev.q,rng,ev.release);
            if(ev.error&&rng()<ev.error)b^=1;classical[ev.bit]=b;if(ev.release)live[ev.q]=0;break;}
          case 'reset':
            advance(ev.q,ev.t);flush(ev.q);if(state.measure(ev.q,rng,false))state.x(ev.q);
            if(ev.error&&rng()<ev.error)state.x(ev.q);break;
          default:throw Error('Unsupported level-2 event.');
        }
      }
      let value=0;for(let b=0;b<classical.length;b++)value|=classical[b]<<b;
      counts.set(value,(counts.get(value)||0)+1);
    }
    return counts;
  }

  function finish(plan,prepared,counts,losses,lossRng,shots,seed,start,preparation,statevectorQubits){
    const p=prepared.parameters;
    const histogram={},causes={},atoms={};let lost=0;
    for(const [value,count] of [...counts].sort((a,b)=>a[0]-b[0])){
      const cdf=new Float64Array(losses.length);let survival=1;
      for(let i=0;i<losses.length;i++){const event=losses[i],active=!event.guard||((value>>>event.guard.bit)&1)===event.guard.value;
        if(active)survival*=1-event.probability;cdf[i]=1-survival;}
      let valid=0;
      for(let j=0;j<count;j++){const u=lossRng();let lo=0,hi=cdf.length;
        while(lo<hi){const mid=(lo+hi)>>>1;if(cdf[mid]>u)hi=mid;else lo=mid+1;}
        if(lo===losses.length)valid++;else{const event=losses[lo];lost++;causes[event.cause]=(causes[event.cause]||0)+1;atoms[event.atom]=(atoms[event.atom]||0)+1;}}
      if(valid)histogram[value.toString(2).padStart(plan.num_bits,'0')]=valid;
    }
    return {schema:'nadit.shor-shots/1',n:plan.n,shots,seed,parameters:p,histogram,
      valid_shots:shots-lost,lost_shots:lost,first_loss_by_cause:causes,first_loss_by_atom:atoms,
      elapsed_seconds:(now()-start)/1000,preparation_seconds:preparation,
      plan_duration_us:prepared.plan.duration_us,compiled_programs:1,
      statevector_qubits:statevectorQubits,
      circuit_provenance:plan.provenance||{},
      bit_order:'highest classical bit on the left; integer=int(bitstring,2)',
      policy:'fixed slots; false guard is idle; state-independent first-loss abort',
      noise_model:'level2: static eps + OU xi'+(p.dd===1?' + explicitly targeted global-idle/storage-readout XY4':''),
      level2:{
        sigma_s_hz:prepared.level2.rates.sigmaS*1e6/(2*Math.PI),
        sigma_f_hz:prepared.level2.rates.sigmaF*1e6/(2*Math.PI),
        tau_c_ms:prepared.level2.rates.tauC/1000,dd:prepared.level2.dd},
      pulse_schedule:{...prepared.level2.schedule,selected_bitstring:Object.entries(histogram).sort((a,b)=>b[1]-a[1])[0]?.[0]??null,
        selection_label:Object.keys(histogram).length?'本次无丢失样本中出现次数最多的测量分支':'本次没有无丢失完整读数；条件门仅显示保留槽'},
      backend:'browser-statevector-l2/1'};
  }
  const api={DEFAULTS,parameters,retime,moveLoss,prepare,sample,
    _internal:{noiseRates,ouStep,echoG,ramseyH,mul2,pulseMatrix,gaussian,random,buildLevel2,runLevel2,luMatrix,State,ouIntegralVariance}};
  root.ShorBrowserEngine=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
