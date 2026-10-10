// Exhaust the display-only movement adapter over the frozen embedded datasets.
const fs=require('node:fs'),path=require('node:path'),zlib=require('node:zlib'),assert=require('node:assert/strict');
const M=require('../viewer/motion-preview.js');
const out=path.resolve(process.argv[2]),html=fs.readFileSync(path.join(out,'full-viewer.html'),'utf8'),rows=[];
const started=Date.now();
for(const match of html.matchAll(/id="packed-([^"]+)">([^<]+)<\/script>/g)){
 const d=JSON.parse(zlib.gunzipSync(Buffer.from(match[2],'base64'))),engine=M.create(d),types={},fallbacks=[];let paths=0,minGap=Infinity;
 for(const a of engine.moves){const r=engine.routeFor(a);types[r.type]=(types[r.type]||0)+1;if(r.fallback)fallbacks.push({start_us:a[0],end_us:a[1],original_min_gap:r.minGap});else{assert(r.passed);minGap=Math.min(minGap,r.minGap);}
  for(const tr of a[4]){const ps=r.paths.get(tr[0]);assert.deepEqual(ps[0],[a[0],tr[1],tr[2]]);assert.deepEqual(ps.at(-1),[a[1],tr[3],tr[4]]);if(!r.fallback)for(let k=1;k<ps.length;k++){assert(ps[k][0]>ps[k-1][0]);assert(Math.abs(ps[k][1]-ps[k-1][1])<1e-8||Math.abs(ps[k][2]-ps[k-1][2])<1e-8);}paths++;}
 }
 rows.push({id:d.id,moves:engine.moves.length,atom_paths:paths,types,min_gap_um:Number.isFinite(minGap)?minGap:null,original_fallbacks:fallbacks});
 if(rows.length%10===0)console.log(JSON.stringify({checked_components:rows.length,elapsed_seconds:(Date.now()-started)/1000}));
}
const result={schema_version:'ViewerPathAudit/0.1',passed:true,clearance_um:1,components:rows.length,moves:rows.reduce((s,r)=>s+r.moves,0),atom_paths:rows.reduce((s,r)=>s+r.atom_paths,0),original_fallback_count:rows.reduce((s,r)=>s+r.original_fallbacks.length,0),elapsed_seconds:(Date.now()-started)/1000,rows,compiler_invoked:false,scope:'exhaustive display endpoint/time/axis and continuous atom-center distance checks; no device or AOD capture qualification'};
fs.writeFileSync(path.join(out,'viewer-path-audit.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,rows:undefined}));
