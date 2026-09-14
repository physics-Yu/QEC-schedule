// Full playback of actual saved cases, including adjacent events a few ULP apart.
const fs=require('node:fs'),assert=require('node:assert/strict'),harness=require('./viewer_harness.cjs');
const paths=process.argv.slice(2);
assert(paths.length,'Pass regenerated replay HTML files');
for(const path of paths){
 const {get,el}=harness(fs.readFileSync(path,'utf8')),original=get('JSON.stringify(data)');
 for(const speed of [1,32]){
  el('speed').value=String(speed);get('seek(0);ui.playing=true;tick(0)');
  const end=get('displayAt(data.duration)'),step=1000/60,budget=Math.ceil(end/(step*speed))+3;
  let previous=-1,stuck=0;
  for(let i=1;i<=budget&&get('ui.playing');i++){
   get(`tick(${step*i})`);const time=get('ui.time');assert(time>=previous);
   stuck=time===previous?stuck+1:0;assert(stuck<4,`${path}: stuck at ${time}`);previous=time;
  }
  assert.equal(get('ui.time'),get('data.duration'));assert.equal(get('ui.playing'),false);
  // Seeking to the failing boundary, pause/resume, and changing modes remain safe.
  get('seek(Math.min(1059.3106781186546,data.duration/2))');
  el('play').onclick();get('tick(500000);tick(500017)');const first=get('ui.time');
  el('play').onclick();get('tick(500034)');assert.equal(get('ui.time'),first);
  el('play').onclick();get('tick(500051);tick(500068)');assert(get('ui.time')>first);
 }
 assert.equal(get('JSON.stringify(data)'),original);
 console.log('PASS complete keyframe playback, 1x/32x and resume:',path);
}
