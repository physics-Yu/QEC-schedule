/* Parameter controls for the self-contained Shor sensitivity viewer. */
(function(root) {
  'use strict';
  const D=root.ShorLossTime.DEFAULTS;
  let values={...D}, callback, timer, latest;
  const groups=[
    ['Execution timing',false,[
      ['speed','Mean MOVE speed','µm/µs',.5,2,.05,1,'Reference chat: 0.5–2; MOVE time = actual distance / speed.'],
      ['transfer','Each LOAD / STORE','µs',10,200,1,1,'Reference default 15; range includes saved 10 µs for reproduction.'],
      ['readout','Each readout exposure','µs',10,1000,10,1,'Reference default 100; actual exposures retained; no synthetic 200 µm term.']]],
    ['Loss per event',true,[
      ['loadLoss','SLM → AOD loss','%',0,2,.001,100,'NAL Table II / VI-B: 0.2% per atom per transfer.'],
      ['storeLoss','AOD → SLM loss','%',0,2,.001,100,'NAL VI-B charges the same 0.2% on return to SLM.'],
      ['czLoss','CZ atom loss','%',0,2,.001,100,'NAL Table II: 0.1% per participating atom.'],
      ['cpLoss','CPhase atom loss','%',0,2,.001,100,'Assumption: initialized to CZ rate; arbitrary-angle CP is not calibrated by NAL.'],
      ['imagingLoss','Imaging atom loss','%',0,2,.001,100,'NAL Table II: 0.1% per measured atom.'],
      ['singleLoss','Single-qubit atom loss','%',0,1,.001,100,'NAL baseline: 0%; this slider is an optional deviation.'],
      ['resetLoss','Reset atom loss','%',0,1,.001,100,'NAL baseline: 0%; reset does not reload a physically lost atom.']]],
    ['Transport heating parameters',true,[
      ['mass','Atomic mass','u',80,180,.001,1,'Example: 87Rb. Mass is not fixed numerically in the NAL paper.'],
      ['frequency','Trap frequency f = ω/2π','kHz',10,500,1,1,'Illustrative 90 kHz from Hwang et al.; not a recovered NAL simulation setting.'],
      ['width','Effective trap width a','µm',.3,3,.01,1,'Illustrative 0.73 µm; harmonic-width mapping in U₀ = mω²a²/2.'],
      ['temperature','Atomic temperature T','µK',1,200,1,1,'Illustrative 27 µK transport point from Hwang et al.'],
      ['depthSpread','Depth spread σᵤ/U₀','%',0,50,1,100,'Unspecified by NAL. Default 0 is the homogeneous-trap limit; positive Gaussian is truncated at U > 0.']]],
    ['Other operation durations',true,[
      ['singleTime','Single-qubit gate','µs',0,10,.1,1,'Saved study baseline: 1 µs.'],
      ['czTime','CZ pulse','µs',.01,10,.01,1,'Saved study baseline: 0.5 µs.'],
      ['cpTime','CPhase pulse','µs',.01,10,.01,1,'Saved assumption: 0.5 µs, independent of angle.'],
      ['resetTime','Reset','µs',0,500,1,1,'Saved study baseline: 5 µs.'],
      ['latency','Result / feedback latency','µs',0,5000,10,1,'Added after readout completion; can overlap independent work.']]]
  ];
  const fmt=(x,d=4)=>Number(x).toLocaleString('en-US',{maximumFractionDigits:d});
  function element(tag,cls,text){const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e;}
  function sync() {
    for(const [, ,specs] of groups)for(const [key,,,,,,scale] of specs) {
      document.getElementById('param-'+key).value=values[key]*scale;
      document.getElementById('number-'+key).value=Number((values[key]*scale).toFixed(6));
    }
  }
  function run() {
    clearTimeout(timer);
    try {root.ShorLossTime.validate(values);callback();document.getElementById('parameter-error').textContent='';}
    catch(error){document.getElementById('parameter-error').textContent=error.message;}
  }
  function mount(onChange) {
    callback=onChange;
    const host=document.getElementById('parameter-groups');
    for(const [title,collapsed,specs] of groups) {
      const section=element(collapsed?'details':'section','parameter-group');
      section.append(element(collapsed?'summary':'h3',null,title));
      const grid=element('div','parameter-grid');section.append(grid);host.append(section);
      for(const [key,label,unit,min,max,step,scale,note] of specs) {
        const field=element('div','parameter-field'),head=element('div','parameter-field-head');
        const caption=element('label',null,label);caption.htmlFor='param-'+key;
        const number=element('input','parameter-number');number.type='number';number.id='number-'+key;
        number.min=min;number.max=max;number.step=step;number.setAttribute('aria-label',label+' numeric');
        head.append(caption,number,element('span','parameter-unit',unit));
        const slider=element('input');slider.type='range';slider.id='param-'+key;
        slider.min=min;slider.max=max;slider.step=step;slider.setAttribute('aria-label',label);
        field.append(head,slider,element('small','parameter-note',note));grid.append(field);
        function change(e) {
          const v=Number(e.target.value);
          if(!Number.isFinite(v)||v<min||v>max){document.getElementById('parameter-error').textContent=label+': expected '+min+'–'+max;return;}
          values[key]=v/scale;sync();clearTimeout(timer);timer=setTimeout(run,90);
        }
        slider.addEventListener('input',change);number.addEventListener('change',change);
      }
    }
    for(const [id,preset] of [
      ['preset-reference',()=>({...D})],
      ['preset-original',()=>({...values,speed:1,transfer:10,readout:10,singleTime:1,czTime:.5,cpTime:.5,resetTime:5,latency:500})],
      ['preset-nal-loss',()=>({...values,loadLoss:.002,storeLoss:.002,czLoss:.001,cpLoss:.001,imagingLoss:.001,singleLoss:0,resetLoss:0})]
    ])document.getElementById(id).addEventListener('click',()=>{values=preset();sync();run();});
    document.getElementById('export-scenario').addEventListener('click',()=>{
      if(!latest)return;
      const report={schema:'nadit.shor-loss-sensitivity/1',case:latest.title,parameters:values,
        duration_us:latest.duration_us,statistics:latest.statistics,
        assumptions:['Fixed ideal-case schedule, independent atom loss; not logical error or circuit fidelity.',
          'CP defaults to CZ loss as an uncalibrated proxy.',
          'Transport trap settings are illustrative; depth distribution is positive-truncated Gaussian.'],
        references:['https://arxiv.org/html/2609.10079v1#S6.SS2','https://arxiv.org/html/2410.22627v1',
          'codex://threads/01a17b96-34c5-72e3-a7c5-708bcc423b29']};
      const url=URL.createObjectURL(new Blob([JSON.stringify(report,null,2)],{type:'application/json'}));
      const a=element('a');a.href=url;a.download=latest.title+'-loss-scenario.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    });
    sync();
  }
  function report(trace,analysis) {
    const r=trace.loss_time_result,final=analysis.finalRisk;
    latest={title:trace.title,duration_us:trace.duration_us,statistics:{
      expected_lost_atoms:final.expected,mean_atom_loss:final.average,
      max_atom_loss:final.maximum.probability,all_atoms_survive:final.allSurvive,
      contributions:final.contributions,per_atom:[...final.atoms].map(([atom,loss])=>({atom,loss})),
      feedback_wait_us:r.feedback_wait_us,pending_result_tail_us:r.pending_result_tail_us,
      saturated_move_events:r.heating_saturated,maximum_delta_n:r.maximum_delta_n}};
    document.getElementById('scenario-duration').textContent=fmt(trace.duration_us/1000,3)+' ms';
    document.getElementById('scenario-loss').textContent=fmt(final.average*100,4)+'%';
    document.getElementById('scenario-expected').textContent=fmt(final.expected,4)+' / '+trace.initial.atoms.length;
    document.getElementById('scenario-survival').textContent=fmt(final.allSurvive*100,6)+'%';
    document.getElementById('transport-detail').textContent='Derived mean depth U₀/kB: '+fmt(r.depth_microkelvin,2)+' µK · max Δn: '+fmt(r.maximum_delta_n,2)+
      ' · inserted feedback wait: '+fmt(r.feedback_wait_us,2)+' µs · final result tail: '+fmt(r.pending_result_tail_us,2)+' µs';
    document.getElementById('heating-warning').textContent=r.heating_saturated?
      r.heating_saturated+' atom-MOVE events saturate the heating model near 100% loss. Inspect short, fast moves and trap assumptions; these values are not clipped to look favorable.':
      'No MOVE event saturates the heating model at the current parameters.';
    const tbody=document.getElementById('atom-loss-rows');tbody.replaceChildren();
    for(const [id,loss] of final.atoms) {
      const row=element('tr');row.append(element('th',null,'Atom '+id),element('td',null,fmt(loss*100,6)+'%'));
      const sources=final.atomContributions.get(id)||{};
      for(const key of root.ShorLossTime.SOURCES)row.append(element('td',null,fmt((sources[key]||0)*100,5)+'%'));
      tbody.append(row);
    }
  }
  root.ShorControls={mount,values:()=>({...values}),report};
})(globalThis);
