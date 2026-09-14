"""Inspect the formal offline baseline; no compilation and no data mutation."""
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


output=Path('artifacts/surface-2d/patch_symmetric').resolve()
recording=json.loads((output/'recording.json').read_text(encoding='utf-8'))
errors=[];checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1700,'height':1250})
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto((output/'index.html').as_uri())
    page.wait_for_function("typeof viewer!=='undefined'&&viewer.getStatus().time_us===0")
    initial=page.evaluate('viewer.debug.current.atoms')
    assert len(initial)==36
    for atom in initial:
        q=int(atom['id'][1:]);block,local=divmod(q,9)
        assert atom['position']=={'x_um':40*(block%2)+10*(local%3),
                                 'y_um':40*(block//2)+10*(local//3)}
    page.locator('#atom-viewer').screenshot(path=str(output/'baseline-initial-four-patches.png'))
    page.locator('#mode').select_option('physical')
    for count in (9,18):
        op=next(o for o in recording['operations'] if len(o.get('gate_ids',[]))==count)
        mid=(op['start']+op['end'])/2
        page.locator('#slider').evaluate("(el,time)=>{el.value=time;el.dispatchEvent(new Event('input',{bubbles:true}))}",mid)
        # Instrument one actual draw without replacing its data or geometry.
        observed=page.locator('#canvas').evaluate("""canvas=>{
            const ctx=canvas.getContext('2d'),active=viewer.debug.data.theme.active_color;
            const savedFill=ctx.fill,savedStroke=ctx.stroke;
            let redAtomMarkers=0,pairLines=0;
            ctx.fill=function(...args){if(this.fillStyle===active&&this.globalAlpha===1)redAtomMarkers++;return savedFill.apply(this,args)};
            ctx.stroke=function(...args){if(this.strokeStyle===active&&this.lineWidth===2&&this.globalAlpha===1)pairLines++;return savedStroke.apply(this,args)};
            try{viewer.debug.draw()}finally{ctx.fill=savedFill;ctx.stroke=savedStroke}
            const {X,Y}=viewer.debug.projection();
            return {redAtomMarkers,pairLines,x10Pixels:Math.abs(X(10)-X(0)),y10Pixels:Math.abs(Y(10)-Y(0)),
              gatingAtoms:viewer.debug.current.atoms.filter(a=>a.activity==='gating').map(a=>a.id),
              effects:viewer.debug.operationsAt(viewer.getStatus().time_us).filter(o=>o.kind==='entangling_pulse')};
        }""")
        assert observed['redAtomMarkers']==2*count,observed
        assert observed['pairLines']==count,observed
        assert len(observed['gatingAtoms'])==2*count
        assert abs(observed['x10Pixels']-observed['y10Pixels'])<1e-8
        assert sum(len(o['intended_pairs']) for o in observed['effects'])==count
        assert f'{count} 门' in page.locator('#status').inner_text()
        page.locator('#atom-viewer').screenshot(path=str(output/f'baseline-batch-{count}.png'))
        if count==18:
            page.locator('summary').filter(has_text='画布显示').click()
            for name in ('slm','aod','planned-path'):page.locator('#'+name).uncheck()
            center=page.locator('#canvas').evaluate("""canvas=>{
                const atoms=viewer.debug.current.atoms.filter(a=>a.activity==='gating');
                const x=atoms.reduce((s,a)=>s+a.position.x_um,0)/atoms.length;
                const y=atoms.reduce((s,a)=>s+a.position.y_um,0)/atoms.length;
                const {X,Y}=viewer.debug.projection(),r=canvas.getBoundingClientRect();
                return {x:r.left+X(x),y:r.top+Y(y)};
            }""")
            page.mouse.move(center['x'],center['y']);page.mouse.wheel(0,-420)
            page.wait_for_timeout(150)
            page.locator('#atom-viewer').screenshot(path=str(output/'baseline-batch-18-detail.png'))
            page.locator('#fit').click()
            for name in ('slm','aod','planned-path'):page.locator('#'+name).check()
            page.locator('summary').filter(has_text='画布显示').click()
        checks.append({'count':count,'time_us':mid,'red_atom_markers':observed['redAtomMarkers'],
            'actual_red_pair_lines':observed['pairLines'],'gating_atom_ids':observed['gatingAtoms'],
            'equal_axis_scale_pixels_per_10um':observed['x10Pixels'],'intended_pairs':op['intended_pairs']})
    page.locator('#slider').evaluate("(el,time)=>{el.value=time;el.dispatchEvent(new Event('input',{bubbles:true}))}",recording['duration'])
    terminal=page.evaluate('viewer.debug.current.atoms')
    assert {a['id']:a['position'] for a in terminal}=={a['id']:a['position'] for a in initial}
    assert all(a['holder']['holder_type']=='static' for a in terminal)
    page.locator('#atom-viewer').screenshot(path=str(output/'baseline-terminal.png'))
    assert not errors,errors
    browser.close()
report={'browser':'real headless Microsoft Edge via Playwright','source':'formal offline patch_symmetric',
        'source_html':str(output/'index.html'),'compiler':'patch_symmetric','recompiled':False,
        'initial_four_2d_patches_verified':True,'batch_views':checks,'terminal_restored':True,
        'simulation_duration_us':recording['duration'],'page_errors':errors,'status':'passed'}
(output/'baseline-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False),flush=True)
