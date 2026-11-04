/* Standalone noisy statevector trajectories for fixed-slot guarded Atom IR.
 * No network, packages, or Python runtime. Same noise conventions as engine.py.
 * Loss is state independent: candidate quantum histories are sampled first,
 * then first-loss abort is sampled; post-loss results are discarded.
 */
(function (root) {
  'use strict';
  const DEFAULTS = Object.freeze({speed:1,transfer:15,readout:100,singleTime:1,
    czTime:.5,resetTime:5,latency:0,loadLoss:.002,storeLoss:.002,czLoss:.001,
    imagingLoss:.001,singleLoss:0,resetLoss:0,mass:86.909180531,frequency:90,
    width:.73,temperature:27,depthSpread:0,t2Slm:1000,t2Aod:1000,t2Transfer:1000,
    singlePauli:0,czPauli:.0005,readoutError:.001,resetError:.001});
  const PROBABILITIES = new Set(['loadLoss','storeLoss','czLoss','imagingLoss',
    'singleLoss','resetLoss','singlePauli','czPauli','readoutError','resetError']);
  const TIMING = ['speed','transfer','readout','singleTime','czTime','resetTime','latency'];
  const clone = x => JSON.parse(JSON.stringify(x));
  const now = () => typeof performance !== 'undefined' ? performance.now() : Date.now();
  function parameters(values) {
    const p={...DEFAULTS,...(values||{})};
    for (const [key,value] of Object.entries(p)) {
      if (!(key in DEFAULTS)) throw Error('Unknown parameter: '+key);
      if (typeof value!=='number'||!Number.isFinite(value)||value<0) throw Error(key+' must be finite and nonnegative.');
      if (PROBABILITIES.has(key)&&value>1) throw Error(key+' must be between 0 and 1.');
    }
    if (p.speed<.01) throw Error('移动平均速度不得低于 0.01 μm/μs。');
    if (p.transfer>1000) throw Error('LOAD／STORE 时间不得超过 1000 μs。');
    if (p.latency!==0) throw Error('读出曝光结束后结果立即可用；额外延迟固定为 0。');
    for (const key of ['mass','frequency','width']) if (!p[key]) throw Error(key+' must be positive.');
    return p;
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
  const gamma=(duration,t2)=>duration===0?0:t2===0?Infinity:duration/(1000*t2);
  const caches=new WeakMap();
  function prepare(input,values){
    const p=parameters(values),key=JSON.stringify(Object.keys(p).sort().map(k=>[k,p[k]]));
    let cache=caches.get(input);if(!cache){cache=new Map();caches.set(input,cache);}
    if(cache.has(key))return cache.get(key);
    const plan=retime(input,p),wires=new Map(plan.initial.atoms.map(a=>[a.id,a.qubit]));
    const holders=new Map(plan.initial.atoms.map(a=>[a.id,a.holder.kind]));
    const bits=new Map(plan.measurements.map(m=>[m.measurement_id,m.bit]));
    const pending=new Float64Array(plan.num_qubits),instructions=[],losses=[];
    function flush(q){const probability=-Math.expm1(-pending[q])/2;
      if(probability)instructions.push({type:'znoise',q,probability});pending[q]=0;}
    for(const step of plan.steps){
      const transfers=new Map();
      for(const a of step.actions){
        const guard=a.guard?{bit:bits.get(a.guard.measurement_id),value:a.guard.value}:null;
        if(a.kind==='LocalU'){
          const {theta,phi,lam}=a.parameters,c=Math.cos(theta/2),s=Math.sin(theta/2);
          const matrix=[c,0,-s*Math.cos(lam),-s*Math.sin(lam),s*Math.cos(phi),s*Math.sin(phi),c*Math.cos(phi+lam),c*Math.sin(phi+lam)];
          let type=Math.abs(s)<1e-14?'phase':'u';
          if(Math.abs(theta-Math.PI/2)<1e-12&&Math.abs(phi)<1e-12&&Math.abs(lam-Math.PI)<1e-12)type='h';
          for(const atom of a.atoms){const q=wires.get(atom);if(Math.abs(s)>1e-14)flush(q);
            instructions.push({type,q,matrix,guard,error:p.singlePauli});}
        }else if(a.kind==='CZPulse'){
          for(const pair of a.pairs)instructions.push({type:'cz',q:wires.get(pair[0]),q2:wires.get(pair[1]),error:p.czPauli});
        }else if(a.kind==='Reset'){
          for(const atom of a.atoms){const q=wires.get(atom);pending[q]=0;instructions.push({type:'reset',q,error:p.resetError});}
        }else if(a.kind==='Measure'){
          for(const result of a.parameters.results){const q=wires.get(result.atom_id);pending[q]=0;
            instructions.push({type:'measure',q,bit:bits.get(result.measurement_id),error:p.readoutError,release:false});}
        }else if(!['Load','Store','Move','Wait'].includes(a.kind))throw Error('Unsupported physical action '+a.kind);
        if(a.kind==='Load'||a.kind==='Store')for(const atom of a.atoms)transfers.set(atom,a.duration_us);
        const source={Load:'load',Store:'store',Move:'move',CZPulse:'cz',Measure:'imaging',LocalU:'single',Reset:'reset'}[a.kind];
        if(source){
          const participants=a.kind==='CZPulse'?[...new Set(a.pairs.flat())].sort((a,b)=>a-b):a.atoms;
          const distances=new Map((a.movement||[]).map(x=>[x.atom,x.distance_um]));
          for(const atom of participants){const probability=a.kind==='Move'?moveLoss(distances.get(atom),a.duration_us,p):p[source+'Loss'];
            if(probability)losses.push({time_us:step.start_us+a.duration_us,atom,cause:source,probability,guard});}
        }
      }
      for(const [atom,kind] of holders){const transfer=transfers.get(atom)||0;
        pending[wires.get(atom)]+=gamma(transfer,p.t2Transfer)+gamma(step.duration_us-transfer,kind==='aod'?p.t2Aod:p.t2Slm);}
      for(const a of step.actions)for(const atom of a.patch.atoms)holders.set(atom.id,atom.holder.kind);
    }
    // A measured factor may be removed only if no later quantum instruction
    // addresses it. Classical guards continue to refer to the stored readout.
    const later=new Set();
    for(let i=instructions.length-1;i>=0;i--){const op=instructions[i];
      if(op.type==='measure'&&!later.has(op.q))op.release=true;
      later.add(op.q);if(op.q2!==undefined)later.add(op.q2);
    }
    losses.sort((a,b)=>a.time_us-b.time_us);
    const result={parameters:p,plan,instructions,losses};
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
  function measuredComponents(instructions,numQubits){
    // Entire unmeasured components factor out of the measured marginal under
    // the current local-noise model. Keep physical timing and losses untouched.
    const neighbors=Array.from({length:numQubits},()=>[]),active=new Set();
    for(const op of instructions){
      if(op.type==='measure')active.add(op.q);
      if(op.q2!==undefined){neighbors[op.q].push(op.q2);neighbors[op.q2].push(op.q);}
    }
    const queue=[...active];
    for(let i=0;i<queue.length;i++)for(const q of neighbors[queue[i]]){
      if(!active.has(q)){active.add(q);queue.push(q);}
    }
    const qubits=[...active].sort((a,b)=>a-b),mapping=new Map(qubits.map((q,i)=>[q,i]));
    return {num_qubits:qubits.length,instructions:instructions.map(op=>{
      if(!active.has(op.q))return {...op,spectator:true};
      const result={...op,q:mapping.get(op.q)};
      if(op.q2!==undefined)result.q2=mapping.get(op.q2);
      return result;
    })};
  }
  function consumeSpectatorRandomness(op,rng){
    // Preserve draws from the original full-state algorithm, including gates
    // conditioned on measured bits. These draws never affect a kept component.
    if(op.type==='znoise'){rng();return;}
    if(op.type==='reset'){rng();if(op.error)rng();return;}
    if(['h','phase','u','cz'].includes(op.type)){
      if(op.error&&rng()<op.error)rng();return;
    }
    throw Error('Unsupported spectator instruction.');
  }
  function sample(plan,values,shots,seed){
    if(!Number.isInteger(shots)||shots<1||shots>10000)throw Error('shots must be an integer from 1 to 10000.');
    if(!Number.isInteger(seed)||seed<0||seed>=2**32)throw Error('seed must be an unsigned 32-bit integer.');
    const start=now(),prepared=prepare(plan,values);
    const quantum=measuredComponents(prepared.instructions,plan.num_qubits),preparation=(now()-start)/1000;
    const {losses,parameters:p}=prepared,{instructions}=quantum,rng=random(seed),lossRng=random((seed^0x4C4F5353)>>>0);
    const state=new State(quantum.num_qubits),classical=new Uint8Array(plan.num_bits),counts=new Map();
    for(let shot=0;shot<shots;shot++){
      state.reset();classical.fill(0);
      for(const op of instructions){
        if(op.guard&&classical[op.guard.bit]!==op.guard.value)continue;
        if(op.spectator){consumeSpectatorRandomness(op,rng);continue;}
        switch(op.type){
          case 'znoise':if(rng()<op.probability)state.z(op.q);break;
          case 'reset':if(state.measure(op.q,rng,false))state.x(op.q);if(op.error&&rng()<op.error)state.x(op.q);break;
          case 'measure':{let b=state.measure(op.q,rng,op.release);if(op.error&&rng()<op.error)b^=1;classical[op.bit]=b;break;}
          case 'cz':state.cz(op.q,op.q2);if(op.error&&rng()<op.error){const code=1+Math.floor(rng()*15);state.pauli(op.q,code&3);state.pauli(op.q2,code>>>2);}break;
          case 'h':state.h(op.q);if(op.error&&rng()<op.error)state.pauli(op.q,1+Math.floor(rng()*3));break;
          case 'phase':state.phase(op.q,op.matrix);if(op.error&&rng()<op.error)state.pauli(op.q,1+Math.floor(rng()*3));break;
          case 'u':state.u(op.q,op.matrix);if(op.error&&rng()<op.error)state.pauli(op.q,1+Math.floor(rng()*3));break;
          default:throw Error('Unsupported prepared instruction.');
        }
      }
      let value=0;for(let b=0;b<classical.length;b++)value|=classical[b]<<b;
      counts.set(value,(counts.get(value)||0)+1);
    }
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
      statevector_qubits:quantum.num_qubits,
      circuit_provenance:plan.provenance||{},
      bit_order:'highest classical bit on the left; integer=int(bitstring,2)',
      policy:'fixed slots; false guard is idle; state-independent first-loss abort',
      backend:'browser-statevector/1'};
  }
  const api={DEFAULTS,parameters,retime,moveLoss,prepare,sample};
  root.ShorBrowserEngine=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
