"""A report around the common committed-state spatial viewer."""
from __future__ import annotations

from collections import Counter
import hashlib
import html
import json
from pathlib import Path


def render_report(directory):
    from neutral_atom_env.visualization.viewer import write_bundle

    directory = Path(directory)
    recording_bytes = (directory/'recording.json').read_bytes()
    recording = json.loads(recording_bytes)
    summary = json.loads((directory/'summary.json').read_text(encoding='utf-8'))
    audit = json.loads((directory/'independent-audit.json').read_text(encoding='utf-8'))
    if summary['status'] != 'completed' or audit.get('passed') is not True:
        raise ValueError('The physical report requires completed execution and independent acceptance')
    if (not summary.get('audit') or
            any(value is not True for value in summary['audit'].values())):
        raise ValueError('The physical report requires all producer checks, including original-state replay')
    if (hashlib.sha256(recording_bytes).hexdigest() !=
            audit.get('artifact_sha256', {}).get('recording.json')):
        raise ValueError('The recording differs from the independently audited artifact')
    operations = recording['operations']
    effects = [o for o in operations if o.get('gate_ids') or o.get('gate_id')]
    counts = Counter()
    pulse_counts = Counter()
    for op in effects:
        counts[op['gate_type']] += len(op.get('gate_ids') or [op['gate_id']])
        pulse_counts[op['gate_type']] += 1
    bookmarks = [{'label': '初始码块放置', 'time': recording['start_time']}]
    for kind, label in [('reset', 'MZ 批量复位'), ('raman_rotation', '码块共同 H'),
                        ('entangling_pulse', '并行 CZ 配对'), ('measurement', 'MZ 综合征读出')]:
        candidates = [o for o in effects if o['kind'] == kind]
        if candidates:
            op = max(candidates, key=lambda o: len(o.get('gate_ids') or [o['gate_id']]))
            bookmarks.append({'label': label + ' × ' + str(len(op.get('gate_ids') or [op['gate_id']])),
                              'time': (op['start']+op['end'])/2})
    moves = [o for o in operations if o['kind'] == 'aod_move' and o.get('moving_count', 0) > 0]
    overlap = next(((a, b) for i, a in enumerate(moves) for b in moves[i+1:]
                    if a.get('aod_id', 'AOD_0') != b.get('aod_id', 'AOD_0') and
                    min(a['end'], b['end'])-max(a['start'], b['start']) > 1e-8), None)
    if overlap:
        a, b = overlap
        bookmarks.append({'label': '两台 AOD 同时运输',
                          'time': (max(a['start'], b['start'])+min(a['end'], b['end']))/2})
    bookmarks.append({'label': '实际提交终态', 'time': recording['duration']})
    comparison = ''.join('<tr><td>'+html.escape(kind)+'</td><td>'+str(counts[kind])+
                         '</td><td>'+str(pulse_counts[kind])+'</td></tr>' for kind in sorted(counts))
    write_bundle(directory)
    encoded_bookmarks = json.dumps(bookmarks, ensure_ascii=False).replace('<', r'\u003c')
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Shor15 · 并行物理前缀</title>
<style>body{margin:0;background:#f4f6fa;color:#20304c;font:15px system-ui,sans-serif}header,section.report{max-width:1240px;margin:auto;padding:20px 24px}h1{font-size:26px;margin:4px 0 12px}p{line-height:1.6}small{color:#53627b}.metrics{display:flex;flex-wrap:wrap;gap:12px}.metric{padding:14px;background:white;border:1px solid #dfe5ef;border-radius:12px;flex:1;min-width:135px}.metric strong{font-size:24px;display:block;margin-top:5px}button{padding:9px 12px;border:1px solid #b8c7dc;border-radius:8px;background:white;color:#20304c;cursor:pointer}button:hover{background:#eaf1ff}.bookmarks{display:flex;gap:8px;flex-wrap:wrap}table{border-collapse:collapse;width:100%;max-width:650px;background:white}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #dfe5ef}details{margin-top:14px}#error{color:#b42318;white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:500px){header,section.report{padding:15px}h1{font-size:22px}.metric{min-width:115px}button{font-size:13px}}</style></head><body>
<header><small>编码 Shor15 / d=3 / 实际 Executor 记录</small><h1>按码块编译，查看真正的并行操作</h1>
<p>这次编译选取完整线路的初始化与首次综合征提取。相同操作跨码块合批；每次装载、运动、CZ、读出和归还都进入同一物理时间线。</p>
<div class="metrics"><div class="metric"><small>源线路原生门</small><strong>__SOURCE_COUNT__</strong></div><div class="metric"><small>最大 CZ 同批</small><strong>__MAX_CZ__</strong></div><div class="metric"><small>独立 AOD</small><strong>__DEVICES__</strong></div><div class="metric"><small>模型物理耗时 / μs</small><strong>__TIME__</strong></div></div>
<p><small>平台：统一 COMPUTE + MZ；5 μm SLM 候选格点、稀疏占据；有限 CZ 半径并检查全部额外作用对。右侧资源的 Clifford 准备用于验证独立 AOD，完整魔态生产、T 消费和完整物理 Shor 尚未验收。</small></p>
<div class="bookmarks" id="bookmarks"></div><p id="error"></p></header>
<div id="physical-viewer"></div><section class="report"><details><summary>查看合批效果与验证证据</summary>
<p>下表比较原生门数量与实际提交的同类脉冲批次数。脉冲合批比例不代表整体物理加速比；运输、复位和读出仍计入总耗时。</p>
<table><thead><tr><th>门类型</th><th>原生门数</th><th>实际脉冲批次</th></tr></thead><tbody>__COMPARISON__</tbody></table>
<p>独立 Stim 核对原始报告、重排后的算法状态和实际提交终态；独立几何计算逐个 CZ 脉冲核对全局作用对。计划恢复和原初态重放结果见运行摘要。</p>
<p><a href="summary.json">运行摘要</a> · <a href="independent-audit.json">独立审计</a> · <a href="animation.html">单独打开共用回放</a></p></details></section>
<script src="atom-viewer.js"></script><script>
const bookmarks=__BOOKMARKS__;let viewer;
fetch('recording.json').then(r=>{if(!r.ok)throw new Error('记录加载失败');return r.json()}).then(data=>{
viewer=window.NeutralAtomViewer.mount(document.getElementById('physical-viewer'),data);window.physicalPrefixViewer=viewer;
for(const row of bookmarks){const button=document.createElement('button');button.textContent=row.label;button.onclick=()=>{viewer.setTime(row.time);document.getElementById('physical-viewer').scrollIntoView({block:'start',behavior:'smooth'})};document.getElementById('bookmarks').append(button)}
}).catch(error=>document.getElementById('error').textContent=error.message);
</script></body></html>'''
    replacements = {'__SOURCE_COUNT__': str(audit['source_native_gate_count']),
                    '__MAX_CZ__': str(audit['max_cz_batch']),
                    '__DEVICES__': str(len(recording['frames'][0].get('aods', {'AOD_0': {}}))),
                    '__TIME__': f"{audit['physical_time_us']:,.3f}",
                    '__COMPARISON__': comparison, '__BOOKMARKS__': encoded_bookmarks}
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    (directory/'index.html').write_text(page, encoding='utf-8')
    return directory/'index.html'
