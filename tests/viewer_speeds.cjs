// Control-level timing checks on actual recordings, not browser FPS.
const fs=require('node:fs'),assert=require('node:assert/strict');
const html=fs.readFileSync(process.argv[2]||'artifacts/circuit-workbench-demo/index.html','utf8');
const {get,el}=require('./viewer_harness.cjs')(html);
const original=get('JSON.stringify(data)');
for(const speed of [.25,1,2,4,8,16,32]){
 for(const mode of ['physical','keyframe']){
  el('mode').value=mode;el('mode').onchange();el('speed').value=String(speed);
  get('seek(0); ui.playing=true; tick(1000); tick(1100)');
  // Real-time mode advances 25 us/s at 1x; keyframe advances display milliseconds.
  const actual=mode==='physical'?get('ui.time'):get('displayAt(ui.time)');
  const expected=100*speed*(mode==='physical'?.025:1);
  assert(Math.abs(actual-expected)<1e-7,`${mode} ${speed}x: ${actual} != ${expected}`);
 }
}
el('mode').value='physical';el('mode').onchange();el('speed').value='32';
get('seek(data.duration-1); ui.playing=true; tick(2000); tick(2100)');
assert.equal(get('ui.time'),get('data.duration'));assert.equal(get('ui.playing'),false);
assert.equal(get('JSON.stringify(data)'),original);
console.log('PASS playback .25x–32x: both time mappings, exact progress, endpoint stop, unchanged physical data');
