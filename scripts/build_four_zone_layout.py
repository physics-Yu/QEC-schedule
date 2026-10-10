"""Build the requested static four-zone layout without invoking a compiler."""
from pathlib import Path
import hashlib,json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src')]
from na_pipeline.runtime.four_zone_layout import build_four_zone_layout,validate_layout,audit_obsolete_resources
from na_pipeline.runtime.compilation_guard import CompilationGuard

OUT=ROOT/'artifacts/deliveries/four-zone-layout-20261009'

HTML=r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>四区原子平台 · 布局验收</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f5f7f8;color:#344c58;font:14px/1.6 system-ui,"Microsoft Yahei",sans-serif}header{padding:18px 26px;background:#fff;border-bottom:1px solid #e1e7eb;display:flex;align-items:center;justify-content:space-between}h1{margin:0;font-size:22px;letter-spacing:.3px}.eyebrow{font-size:10px;letter-spacing:2px;color:#7e939a}.count{font-variant-numeric:tabular-nums;color:#607781}main{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:14px;padding:16px}.canvas,.panel{background:white;border:1px solid #e0e7eb;border-radius:12px;overflow:hidden}.tools{padding:10px 14px;display:flex;gap:14px;align-items:center;flex-wrap:wrap;border-bottom:1px solid #edf1f3}button,select{font:inherit;color:inherit;background:white;border:1px solid #d7e0e5;border-radius:6px;padding:5px 9px;cursor:pointer}input{accent-color:#618677}svg{display:block;width:100%;height:auto;min-height:510px;touch-action:none}.legend{border-top:1px solid #edf1f3;padding:10px 14px;font-size:12px;color:#6f858c}.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin:0 4px 0 12px}.panel{padding:16px;margin-bottom:12px}h2{font-size:15px;margin:0 0 10px}p{margin:7px 0}.muted{color:#819299;font-size:12px}.stats{display:grid;grid-template-columns:1fr 1fr;gap:8px}.stat{padding:10px;background:#f6f8f9;border-radius:7px}.stat b{display:block;font-size:22px;font-weight:550}.line{padding:7px 0;border-bottom:1px solid #edf1f3}.line:last-child{border:0}.badge{font-size:11px;padding:2px 6px;background:#eaf1ed;border-radius:4px;color:#507763}a{color:#56776d}#info{min-height:100px;white-space:pre-line}.warning{padding:10px 16px;background:#fafbf8;border-top:1px solid #e6ebe5;font-size:12px;color:#7d8877}details{margin-top:10px}summary{cursor:pointer;color:#73878e}.footer{padding:0 24px 18px;color:#85949b;font-size:12px}@media(max-width:950px){main{grid-template-columns:1fr}aside{display:grid;grid-template-columns:1fr 1fr;gap:12px}.panel{margin:0}header{gap:16px}.count{font-size:11px}svg{min-height:400px}}@media(max-width:550px){aside{grid-template-columns:1fr}h1{font-size:18px}.tools{gap:8px}svg{min-height:320px}}
</style></head><body><header><div><div class="eyebrow">NEUTRAL ATOM PLATFORM / LAYOUT</div><h1>两行四区 · 原子平台布局</h1></div><div class="count">17 data patches · 4 factories · <b>697 atoms</b><br><span class="badge">布局预览 · 用户视觉待验</span></div></header>
<main><section class="canvas"><div class="tools"><button id="fit">全景</button><button id="data-view">Compute 区</button><button id="factory-view">四座工厂</button><label><input id="labels" type="checkbox" checked>Patch 标签</label><label><input id="traps" type="checkbox">Trap</label><label><input id="beams" type="checkbox">2Q 光覆盖区</label><label><input id="measure-zone" type="checkbox">测量预留区</label></div>
<svg id="scene" viewBox="0 0 1560 1200" role="img" aria-label="上排compute与processor，下排reloading与magic factory，697个原子"></svg><div class="legend"><span class="dot" style="background:#42675b"></span>数据原子 <span class="dot" style="background:#76a8a0"></span>X 辅助 <span class="dot" style="background:#8d9eb6"></span>Z 辅助　·　patch 透明底　·　点击 patch 查看角色</div><div class="warning">当前页面验收布局与资源划分；未播放生产动作，不代表四厂并行时间表已验收。</div></section>
<aside><section class="panel"><h2>原子与码块</h2><div class="stats"><div class="stat"><b>289</b>Compute · 17 patch</div><div class="stat"><b>408</b>Magic · 4 × 6 patch</div><div class="stat"><b>0</b>Y patch / probe</div><div class="stat"><b>0</b>预置成品魔态</div></div><p class="muted">每 patch 17 原子。Processor 无常驻 patch；Reloading 为空预留区。</p></section>
<section class="panel"><h2>区域与设备</h2><div class="line"><b>AOD data</b><br>Compute 内常规逻辑门，按需进入 Processor</div><div class="line"><b>AOD magic</b><br>右下四厂共同生产，输出送往 Processor</div><div class="line"><b>独立 Rydberg 通道</b><br>data：Compute / Processor<br>magic：Magic factory</div><p class="muted">区域独立打光按用户配置建模。共享同一 AOD 的动作仍需行列波形兼容。</p></section>
<section class="panel"><h2>四厂供给关系</h2><div class="line">F0 / F1 / F2 / F3 · 共同启动</div><div class="line">W0–W3 · 蒸馏工作块<br>W4 · 工作块与成品输出<br>M · 原始魔态输入</div><p>生产不等待 data 门完成；库存满时等待消费。T 交接在 Processor 汇合。</p><p class="muted">200 ms 仅为此前容量估算，不按定时器生成魔态。</p></section>
<section class="panel"><h2>Patch 信息</h2><div id="info">点击任一 patch，查看身份、用途和坐标。</div><details><summary>布局数据与检查</summary><p><a href="layout.json">Layout JSON</a> · <a href="resource-contract.json">设备接口</a> · <a href="checks.json">检查报告</a></p></details></section></aside></main><div class="footer">Processor 仅用于 T 注入交接。已有电路与历史动画保留；此布局采用 6-patch 工厂资源配置，不继承旧布局的路径资格。</div>
<script src="layout.js"></script><script>
const d=window.FOUR_ZONE_LAYOUT,svg=document.getElementById('scene'),NS='http://www.w3.org/2000/svg';let selected=null;
const colors={data:'#42675b',xanc:'#76a8a0',zanc:'#8d9eb6'};
function el(tag,attrs={},text){const n=document.createElementNS(NS,tag);for(const[k,v]of Object.entries(attrs))n.setAttribute(k,v);if(text!==undefined)n.textContent=text;svg.appendChild(n);return n;}
function text(x,y,str,size=14,color='#5e7580'){return el('text',{x,y,'font-size':size,fill:color,'font-family':'system-ui, sans-serif'},str)}
function render(){svg.replaceChildren();const my=y=>1040-y;
 const zoneInfo={compute:['Compute zone','17 data patches · 常规逻辑门','#eaf0f4'],processor:['Processor zone','仅用于 T 注入交接','#eef2f4'],reloading:['Reloading zone','原子补充预留 · 当前为空','#f2f3ef'],magic:['Magic factory zone','4 factories · 6 patches / factory','#edf2eb']};
 for(const[id,[title,sub,c]]of Object.entries(zoneInfo)){const z=d.regions[id];el('rect',{x:z[0],y:my(z[3]),width:z[2]-z[0],height:z[3]-z[1],rx:7,fill:c,stroke:'#ccd8df','stroke-width':1});text(z[0]+18,my(z[3])+30,title,23);text(z[0]+18,my(z[3])+53,sub,13);}
 if(document.getElementById('beams').checked){for(const name of ['compute','processor','magic']){const z=d.regions[name];el('rect',{x:z[0]+4,y:my(z[3])+4,width:z[2]-z[0]-8,height:z[3]-z[1]-8,rx:6,fill:'none',stroke:name==='magic'?'#7d9d7e':'#7f96ad','stroke-width':3,'stroke-dasharray':'10 7','data-beam':name});}}
 if(document.getElementById('measure-zone').checked){const z=d.regions.measurement.preview_bounds_um;el('rect',{x:z[0],y:my(z[3]),width:z[2]-z[0],height:z[3]-z[1],fill:'#eef3e9',stroke:'#cbd5c5'});text(z[0]+18,my(z[3])+30,'Measurement · x 方向开放，连接路径尚未绑定',18);}
 for(const p of d.patches){const[x,y]=p.anchor_um;const box=el('rect',{x:x-3,y:my(y+80),width:86,height:80,fill:'transparent',stroke:selected===p.id?'#446b5d':'#c0cfca','stroke-width':selected===p.id?2:0.6,'data-patch':p.id,role:'button','aria-label':p.id+' '+p.role,tabindex:0});box.style.cursor='pointer';box.onclick=()=>select(p.id);box.onkeydown=e=>{if(e.key==='Enter')select(p.id)};
 if(document.getElementById('labels').checked)text(x+2,my(y)+17,p.id,p.zone==='magic'?12:14,p.output_carrier?'#436b55':'#506a73');}
 for(const a of d.atoms){const[x,y]=a.xy_um;const c=a.local_id.startsWith('x')?colors.xanc:a.local_id.startsWith('z')?colors.zanc:colors.data;
 if(document.getElementById('traps').checked)el('circle',{cx:x,cy:my(y),r:6.1,fill:'none',stroke:'#9dadb2','stroke-width':.6});
 const circle=el('circle',{cx:x,cy:my(y),r:3.4,fill:c,'data-atom':a.id});circle.style.pointerEvents='none';}
 for(const f of d.factories)text(753,my(f.origin_um[1]+42),f.id,15);
 for(const[x,label]of [[950,'data 交接端口'],[1240,'W4 交接端口']]){el('rect',{x:x-43,y:my(748),width:86,height:86,rx:6,fill:'none',stroke:'#aebdc6','stroke-width':1.5,'stroke-dasharray':'7 6'});text(x-52,my(650),label,15);}
 text(947,my(570),'按请求接入 data 与同载体魔态',16);
 text(245,my(190),'空闲预留区',20,'#8b9796');text(202,my(155),'不计入当前 697 个原子',14,'#8b9796');
}
function select(id){selected=id;const p=d.patches.find(p=>p.id===id);const roles={algorithm_data:'算法逻辑比特 · 常规门在 Compute 区执行',distillation_work:'蒸馏工作块 · 最后进行逻辑 X 检查',distilled_output_and_work:'蒸馏工作块 · 通过检查后输出留在同一 W4 载体',raw_magic_input:'原始魔态输入 · 反复制备、注入、读出与复位'};document.getElementById('info').textContent=id+'\n'+roles[p.role]+'\n17 原子 · '+p.aod_group+' AOD\n锚点 ('+p.anchor_um.join(', ')+') μm';render();}
document.getElementById('fit').onclick=()=>svg.setAttribute('viewBox',document.getElementById('measure-zone').checked?'0 -480 1560 1600':'0 0 1560 1200');
document.getElementById('factory-view').onclick=()=>svg.setAttribute('viewBox','740 565 750 635');
document.getElementById('data-view').onclick=()=>svg.setAttribute('viewBox','60 40 620 610');
for(const id of ['labels','traps','beams','measure-zone'])document.getElementById(id).onchange=()=>{render();if(id==='measure-zone')document.getElementById('fit').click()};render();
</script></body></html>'''

def build():
    OUT.mkdir(parents=True,exist_ok=True)
    source=ROOT/'artifacts/qualification/cnot-t-bottom-20261009/run-v1/layout.json'
    original=json.loads(source.read_bytes());layout=build_four_zone_layout(original)
    checks=validate_layout(layout)
    paths=sorted((ROOT/'artifacts/demos/joint-factory-repaired-20261008').glob('factory.*/physical-dag.json'))
    audit=audit_obsolete_resources([(p.parent.name,json.loads(p.read_bytes())) for p in paths])
    layout['source_layout_sha256']=hashlib.sha256(source.read_bytes()).hexdigest()
    checks['source_cleanup_audit_passed']=audit['passed']
    checks['frozen_inputs_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [source,*paths]}
    for name,value in [('layout.json',layout),('checks.json',checks),('obsolete-resource-audit.json',audit),
        ('resource-contract.json',dict(schema_version='FourZoneResources/1',profile=layout['resource_profile'],
          counts=layout['counts'],resources=layout['device_resources'],production=layout['production_policy'],
          processor=layout['processor_interface'],reloading=layout['reloading_interface'],
          source=layout['hardware_assumptions']))]:
        (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUT/'layout.js').write_text('window.FOUR_ZONE_LAYOUT='+json.dumps(layout,ensure_ascii=False,separators=(',',':'))+';',encoding='utf-8')
    (OUT/'index.html').write_text(HTML,encoding='utf-8')
    print(json.dumps(checks,ensure_ascii=False)[:400])


if __name__=='__main__':
    with CompilationGuard() as guard:
        build();(OUT/'compilation-guard.json').write_text(json.dumps(guard.receipt(),indent=2),encoding='utf-8')
