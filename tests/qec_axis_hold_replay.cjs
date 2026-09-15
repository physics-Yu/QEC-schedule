// Executes the actual exported viewer with DOM/Canvas doubles, not a browser.
const fs=require('node:fs'),assert=require('node:assert/strict');
const root=process.argv[2]||'artifacts/qec-axis-hold/attempt1/qec_ghz2';
for(const strategy of ['ordered_greedy','smt_ordered']){
  const h=require('./viewer_harness.cjs')(fs.readFileSync(`${root}/${strategy}/animation.html`,'utf8'));
  assert.equal(h.get('data.backend'),'row_column_orthogonal');
  assert(h.get('frames.filter(f=>f.movement).every(f=>f.movement.profile==="cubic")'));
  const error=h.get(`(()=>{let error=0;for(const f of frames.filter(f=>f.movement)){
    const m=f.movement,s=sample(m.start+.25*m.duration);
    for(const [actual,source,target]of [[s.columns,f.axes.x_um,m.target_axes.x_um],[s.rows,f.axes.y_um,m.target_axes.y_um]])
      for(let i=0;i<source.length;i++)error=Math.max(error,Math.abs(actual[i]-(source[i]+.15625*(target[i]-source[i]))));
  }return error})()`);
  assert(error<1e-8,'cubic interpolation and held coordinates');
  for(const mode of ['physical','keyframe']){
    h.nodes.get('mode').value=mode;h.nodes.get('mode').onchange();
    h.nodes.get('speed').value='32';h.get('seek(0)');h.nodes.get('play').onclick();
    h.get('tick(0);for(let now=250;ui.playing&&now<300000;now+=250)tick(now)');
    assert.equal(h.get('ui.time'),h.get('data.duration'));
    assert.equal(h.get('ui.playing'),false);
    assert.equal(h.get('current.atoms.filter(a=>a.holder.holder_type==="mobile").length'),0);
  }
  console.log(`PASS offline ${strategy}: every cubic segment, held axes, full 32x physical/keyframe playback, SLM terminal`);
}
