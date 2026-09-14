"""Package a completed, replay-verified execution with the current shared viewer."""
import hashlib
import json
from pathlib import Path

from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization.viewer import javascript

SOURCE=Path('artifacts/qec-roadmap/step4C-resumed-attempt3')
OUTPUT=Path('artifacts/deliveries/ghz4-animation');OUTPUT.mkdir(parents=True,exist_ok=True)
read=lambda name:json.loads((SOURCE/name).read_text(encoding='utf-8'))
recording=read('recording.json');result=read('result.json');verification=read('verification.json');circuit=read('input.json')
assert verification['compiler_free_replay']=='PASS'
assert result['metrics']['completed_gate_count']==len(circuit['gates'])==1868
assert recording['duration']==result['metrics']['simulation_time_us']
assert abs(recording['duration']-105285.6)<1e-7
assert circuit['atom_count']==68
payload=canonical_json(recording).replace('<',r'\u003c')
bundle=javascript().replace('</script',r'<\/script')
html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,"><title>四逻辑 GHZ · 已编译原子执行动画</title>
<style>body{margin:0;background:#f4f6fa;color:#25334b;font:14px/1.6 system-ui}main{max-width:1440px;margin:auto;padding:18px}h1{font-size:23px;margin:0}header{padding:0 12px 12px}p{margin:5px 0;color:#65738a}a{color:#18785e}.facts{font-size:13px}#animation{background:white;border-radius:14px}</style>
<main><header><h1>四逻辑 GHZ · 原子执行动画</h1><p class="facts">68 原子 · 1868 / 1868 门与控制槽完成 · 105285.6 μs · 独立物理重放验证通过</p>
<p>已载入完整执行，点击「播放」开始；默认 32×，全程约 2 分 4 秒。拖动时间轴或输入 μs 可定位。
<a href="circuit.json" download>下载线路输入</a> · <a href="http://127.0.0.1:8788/?job=87eef4dc58e467e0e6b423bfda158c43">打开可编辑工作台</a></p></header>
<div id="animation"></div></main><script>'''+bundle+'''
window.deliveryViewer=NeutralAtomViewer.mount(document.getElementById('animation'),'''+payload+''',{compact:true});
document.getElementById('animation').shadowRoot.getElementById('speed').value='32';
</script></html>'''
(OUTPUT/'animation.html').write_text(html,encoding='utf-8')
(OUTPUT/'circuit.json').write_text(canonical_json(circuit),encoding='utf-8')
manifest={'status':'packaged_pending_playback_check','source':str(SOURCE),'reused_verified_compilation':True,
          'fresh_physical_compile':False,'atom_count':68,'completed_slots':1868,'duration_us':recording['duration'],
          'compiler_free_replay':verification['compiler_free_replay'],'recording_sha256':hashlib.sha256((SOURCE/'recording.json').read_bytes()).hexdigest(),
          'animation_sha256':hashlib.sha256((OUTPUT/'animation.html').read_bytes()).hexdigest(),'default_speed':32}
(OUTPUT/'delivery.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
print(str((OUTPUT/'animation.html').resolve()),flush=True)
