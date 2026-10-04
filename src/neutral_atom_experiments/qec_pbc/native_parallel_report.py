"""A report around the common committed-state spatial viewer."""
from __future__ import annotations

from collections import Counter
import hashlib
import html
import json
from pathlib import Path


def _readout_placement_details(directory, effects, audit):
    """Display compiler decisions, keeping lane cost apart from committed time."""
    path = directory/'decisions.json'
    if not path.exists():
        return ''
    raw = path.read_bytes()
    decisions = json.loads(raw)
    rows = [(decision, selection) for decision in decisions
            for selection in decision.get('readout_placement_decisions', [])]
    if not rows:
        return ''
    expected = audit.get('artifact_sha256', {}).get('decisions.json')
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('The MZ decisions differ from the independently audited artifact')

    def text(value):
        return html.escape(str(value), quote=True)

    def number(value):
        return '—' if value is None else text(f'{value:,.3f}')

    def point(value):
        return '—' if value is None else '('+', '.join(number(v) for v in value)+')'

    table, candidates = [], []
    for index, (decision, selection) in enumerate(rows):
        selected = selection.get('selected')
        if (selection.get('schema') != 'rigid-readout-placement-decision/1' or
                not selected or selected.get('status') != 'accepted' or
                selected not in selection.get('candidates', [])):
            raise ValueError('The MZ display requires a selected validated candidate')
        kind = selection['kind']
        gate_ids = set(selection['gate_ids'])
        pulse = next((op for op in effects if op.get('gate_type') == kind and gate_ids <=
                      set(op.get('gate_ids') or [op.get('gate_id')])), None)
        if not gate_ids or pulse is None:
            raise ValueError('The MZ decision has no corresponding committed pulse')
        time = (pulse['start']+pulse['end'])/2
        locator = (f'<button type="button" class="readout-locate" disabled '
                   f'data-readout-time="{text(time)}">定位实际 {text(kind)}</button>')
        committed_us = (decision['end_us']-decision['start_us']
                        if 'end_us' in decision and 'start_us' in decision else None)
        entries = selection['candidates']
        accepted = sum(entry.get('status') == 'accepted' for entry in entries)
        policy = selection.get('policy', decision.get('readout_placement', '—'))
        table.append('<tr>'+''.join('<td>'+value+'</td>' for value in (
            text(decision.get('decision', index)), text(kind)+' × '+str(len(gate_ids)),
            text(selection['aod_id']), text(policy), point(selection.get('source_origin_um')),
            point(selected.get('target_pose_um')), text(selected.get('zone_id', '—')),
            f'{text(selection.get("generated", "—"))} / {len(entries)} / {accepted}',
            number(selected.get('actual_us')), number(committed_us), locator))+'</tr>')
        candidate_rows = []
        for entry in entries:
            status = ('已选' if entry == selected else
                      {'accepted': '合法备选', 'rejected': '拒绝', 'timeout': '超时'}.get(
                          entry.get('status'), entry.get('status', '—')))
            diagnostic = ' · '.join(str(entry[key]) for key in ('code', 'message') if key in entry)
            candidate_rows.append('<tr>'+''.join('<td>'+value+'</td>' for value in (
                text(status), point(entry.get('target_pose_um')), number(entry.get('proxy_distance_um')),
                number(entry.get('estimated_us')),
                number(entry.get('actual_us')), number(entry.get('actual_distance_um')),
                text(diagnostic or '—')))+'</tr>')
        positions = ''.join('<tr><td>'+text(atom)+'</td><td>'+number(x)+'</td><td>'+number(y)+
                            '</td></tr>' for atom, (x, y) in selected.get('positions', []))
        rejected = ', '.join(f'{key}: {value}' for key, value in
                             selection.get('generation_rejections', {}).items()) or '无'
        candidates.append(
            f'<details class="readout-candidates" id="readout-selection-{index}"><summary>'
            f'决策 {text(decision.get("decision", index))} · {text(selection["aod_id"])} · '
            f'{text(kind)}：候选与载体坐标</summary>'
            f'<p class="readout-note">候选预算 {text(selection.get("candidate_budget", "—"))}；'
            f'合法服务短名单 {text(selection.get("top_k", "—"))}；生成阶段拒绝：{text(rejected)}。'
            f'选择范围：{text(selection.get("selection_scope", "—"))}。'
            f'同次包含的 RESET：{text(", ".join(selection.get("included_reset_gate_ids", [])) or "无")}。</p>'
            '<div class="readout-table-wrap"><table class="readout-table"><thead><tr>'
            '<th>候选状态</th><th>AOD 原点 / μm</th><th>几何去程距离 / μm</th><th>代理估算 / μs</th>'
            '<th>合法完整服务 / μs</th><th>AOD 路程 / μm</th><th>拒绝原因</th>'
            '</tr></thead><tbody>'+''.join(candidate_rows)+'</tbody></table></div>'
            '<details class="readout-carriers"><summary>所选落点的载体位置 / μm</summary>'
            '<div class="readout-table-wrap"><table><thead><tr><th>原子</th><th>x / μm</th>'
            '<th>y / μm</th></tr></thead><tbody>'+positions+'</tbody></table></div></details></details>')
    return ('<details id="readout-placement"><summary>MZ 落点选择与服务成本（按需查看）</summary>'
            '<p>下表来自这次编译的设备选择日志。自动模式先生成最近的 rigid 原点投影及有限邻近候选，'
            '再验证完整去程、读出／复位和归还，以合法服务时长、AOD 路程选择；固定模式是历史端点对照。'
            '几何最近的候选可能绕路更慢，因此所选原点可以带横向偏移。'
            '有限候选与合法服务短名单不证明连续空间或整个线路的全局最优。</p>'
            '<p class="readout-note">AOD 原点不是每个原子的坐标，载体位置可在下方展开。'
            '“合法完整服务”是候选校验后的单设备计划成本；“提交计划”来自实际提交起止区间。'
            '双 AOD 同次决策共享提交区间，两个单设备成本与重复区间均不能相加作总耗时。'
            '定位按钮只跳到录制中对应的真实脉冲。</p>'
            '<div class="readout-table-wrap"><table class="readout-table"><thead><tr>'
            '<th>决策</th><th>操作</th><th>AOD</th><th>模式</th><th>源原点 / μm</th>'
            '<th>所选原点 / μm</th><th>MZ</th><th>生成 / 检查 / 合法</th>'
            '<th>合法完整服务 / μs</th><th>提交计划 / μs</th><th>实际回放</th>'
            '</tr></thead><tbody>'+''.join(table)+'</tbody></table></div>'+''.join(candidates)+'</details>')


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
    if summary.get('placement_layout') in ('interleaved', 'enola'):
        layout_audit = json.loads((directory/'patch-parallel-audit.json').read_text(encoding='utf-8'))
        if (layout_audit.get('passed') is not True or
                layout_audit.get('artifact_sha256', {}).get('recording.json') !=
                hashlib.sha256(recording_bytes).hexdigest()):
            raise ValueError('Interleaved layout requires its recording-bound independent patch audit')
    collective = summary.get('mz_service') == 'collective'
    if collective:
        collective_audit = json.loads((directory/'collective-mz-audit.json').read_text(encoding='utf-8'))
        if (collective_audit.get('passed') is not True or
                collective_audit.get('artifact_sha256', {}).get('recording.json') !=
                hashlib.sha256(recording_bytes).hexdigest() or
                collective_audit.get('artifact_sha256', {}).get('decisions.json') !=
                hashlib.sha256((directory/'decisions.json').read_bytes()).hexdigest()):
            raise ValueError('Collective MZ requires recording-bound and decision-bound independent acceptance')
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
    collective_note = collective_details = ''
    if collective:
        services = [o for o in effects if o['kind'] in {'reset', 'measurement'}]
        decisions = json.loads((directory/'decisions.json').read_text(encoding='utf-8'))
        batches = [d for d in decisions if d.get('collective_mz_evidence')]
        sizes = [len(o.get('gate_ids') or [o['gate_id']]) for o in services]
        collective_note = ('<p id="collective-mz-result"><strong>集合 MZ 服务：'
            + ' → '.join(('MEASURE' if o['kind']=='measurement' else 'RESET')+' × '+str(n)
                         for o, n in zip(services, sizes))
            + '。</strong>分趟装载、真实运动并卸载到 MZ 的 SLM；全部目标到齐后统一作用，再分趟归还。'
              '当前是既有 rigid ENV 前缀的兼容实现；Enola SA 提供初始 placement。</p>')
        rows = []
        for d in batches:
            e = d['collective_mz_evidence']
            rows.append('<tr><td>'+html.escape(d['kind'])+'</td><td>'+str(e['service_cohort_size'])+
                '</td><td>'+str(len(e['collection_waves']))+'</td><td>'+str(len(e['return_waves']))+
                '</td><td>'+f"{d['duration_us']:,.3f}"+'</td></tr>')
        collective_details = ('<details id="collective-mz-details"><summary>集合服务与运输波次（按需查看）</summary>'
            '<p>每个目标使用预声明的真实 MZ SLM 位点。运输波次受 Cartesian 捕获闭包和设备容量约束；'
            '服务容量由稳定停放位点决定。测量结束才提交报告，随后全部辅助原子统一 RESET。</p>'
            '<table><thead><tr><th>操作</th><th>目标原子</th><th>汇集波次</th><th>归还波次</th>'
            '<th>完整服务 / μs</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table>'
            '<p><a href="collective-mz-audit.json">集合服务独立审计</a></p></details>')
        for service, label in ((services[0], '初始化汇集运输'),
                               (next(o for o in services if o['kind']=='measurement'), '综合征辅助原子汇集运输')):
            preceding = [m for m in moves if m['end'] <= service['start'] and
                         m['start'] >= max((o['end'] for o in effects if o['end'] <= service['start']), default=0)]
            if preceding:
                m = max(preceding, key=lambda m: (m['end']-m['start'], m.get('moving_count', 0)))
                bookmarks.append({'label': label, 'time': (m['start']+m['end'])/2})
        if len(services) > 1 and services[-1]['kind'] == 'reset':
            o = services[-1]
            bookmarks.append({'label': '综合征辅助原子统一 RESET × '+str(sizes[-1]),
                              'time': (o['start']+o['end'])/2})
    routing_note = ''
    if summary.get('routing_policy') == 'shortest-direct-or-halfgrid-v1':
        routing_note = ('<p id="routing-result">运输路径：优先验证直达；受阻时搜索 '
                        '2.5 μm 偏移、5 μm 间隔的半格通道。去程和归还分别按实际状态规划。</p>')
        def half_grid(value):
            return abs((value-2.5)/5-round((value-2.5)/5)) < 1e-8
        example = next((op for op in moves if any(
            half_grid(op.get('target_axes', {}).get(axis, [0])[0])
            for axis in ('x_um', 'y_um'))), None)
        if example:
            bookmarks.append({'label': '2.5 μm 半格绕障运输',
                              'time': (example['start']+example['end'])/2})
    overlap = next(((a, b) for i, a in enumerate(moves) for b in moves[i+1:]
                    if a.get('aod_id', 'AOD_0') != b.get('aod_id', 'AOD_0') and
                    min(a['end'], b['end'])-max(a['start'], b['start']) > 1e-8), None)
    if overlap:
        a, b = overlap
        bookmarks.append({'label': '两台 AOD 同时运输',
                          'time': (max(a['start'], b['start'])+min(a['end'], b['end']))/2})
    bookmarks.append({'label': '实际提交终态', 'time': recording['duration']})
    layer_note = ''
    if summary.get('placement_layout') in ('interleaved', 'enola'):
        layer_counts = []
        for layer in range(1, 5):
            pulses = [o for o in effects if o['kind'] == 'entangling_pulse' and
                      any(f'.layer{layer}.cz.' in gid and '.check.' in gid
                          for gid in o.get('gate_ids', []))]
            layer_counts.append(len(pulses))
            if pulses:
                op = max(pulses, key=lambda o: len(o['gate_ids']))
                bookmarks.insert(-1, {'label': f'稳定子第 {layer} 层 · {len(pulses)} 个实际脉冲',
                                     'time': (op['start']+op['end'])/2})
        total = sum(layer_counts)
        mode = ('Enola SA 布局 · 码内及码间合批' if summary.get('placement_layout') == 'enola' else
                '码内及码间合批' if summary.get('intra_patch_enabled') else '逐角色对照')
        pair_note = ('门伙伴使用 3 或 4.243 μm 的有限候选落点' if summary.get('pair_search_enabled') else
                     '门伙伴间距 3 μm')
        layer_note = (f'<p id="layout-result"><strong>{mode}：一轮稳定子提取 {total} 个真实 CZ 脉冲；'
                      f'最大同批 {audit["max_cz_batch"]} 对。</strong> 驻留与 CZ 时非配对原子至少 10 μm；'
                      f'{pair_note}，有限作用半径仍为 6 μm。四个协议层的顺序和 H 边界保持。</p>')
    comparison = ''.join('<tr><td>'+html.escape(kind)+'</td><td>'+str(counts[kind])+
                         '</td><td>'+str(pulse_counts[kind])+'</td></tr>' for kind in sorted(counts))
    readout_details = _readout_placement_details(directory, effects, audit)
    write_bundle(directory)
    encoded_bookmarks = json.dumps(bookmarks, ensure_ascii=False).replace('<', r'\u003c')
    page = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Shor15 · 并行物理前缀</title>
<style>__READOUT_STYLE__</style>
<style>body{margin:0;background:#f4f6fa;color:#20304c;font:15px system-ui,sans-serif}header,section.report{max-width:1240px;margin:auto;padding:20px 24px}h1{font-size:26px;margin:4px 0 12px}p{line-height:1.6}small{color:#53627b}.metrics{display:grid;grid-template-columns:repeat(auto-fit,minmax(135px,1fr));gap:12px;margin-top:12px}.metric{padding:14px;background:white;border:1px solid #dfe5ef;border-radius:12px;min-width:0}.metric strong{font-size:24px;display:block;margin-top:5px;overflow-wrap:anywhere}button{padding:9px 12px;border:1px solid #b8c7dc;border-radius:8px;background:white;color:#20304c;cursor:pointer}button:hover{background:#eaf1ff}.bookmarks{display:flex;gap:8px;flex-wrap:wrap}table{border-collapse:collapse;width:100%;max-width:650px;background:white}th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #dfe5ef}details{margin-top:14px}summary{cursor:pointer;font-weight:600}#error{color:#b42318;white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:500px){header,section.report{padding:15px}h1{font-size:22px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.metric strong{font-size:21px}button{font-size:13px}}</style></head><body>
<header><small>编码 Shor15 / d=3 / 实际 Executor 记录</small><h1>按码块编译，查看真正的并行操作</h1>
<p>这次编译选取完整线路的初始化与首次综合征提取。相同操作跨码块合批；每次装载、运动、CZ、读出和归还都进入同一物理时间线。</p>
__LAYER_NOTE__
__ROUTING_NOTE__
__COLLECTIVE_NOTE__
<details id="experiment-metrics"><summary>实验规模与合批指标（按需查看）</summary>
<div class="metrics"><div class="metric"><small>源线路原生门</small><strong>__SOURCE_COUNT__</strong></div><div class="metric"><small>d=3 算法码块</small><strong>__PATCH_COUNT__</strong></div><div class="metric"><small>实际物理原子</small><strong>__ATOM_COUNT__</strong></div><div class="metric"><small>独立 AOD</small><strong>__DEVICES__</strong></div><div class="metric"><small>最大 CZ 同批</small><strong>__MAX_CZ__</strong></div><div class="metric"><small>模型总耗时 / μs（含归还）</small><strong>__TIME__</strong></div></div>
<p><small>主要指标与真实时间占用见回放的统计区。此处规模与合批计数不作为完整物理 Shor 或整体加速比的证据。</small></p></details>
<p><small>平台：统一 COMPUTE + MZ；5 μm SLM 候选格点、稀疏占据；有限 CZ 半径并检查全部额外作用对。右侧资源的 Clifford 准备用于验证独立 AOD，完整魔态生产、T 消费和完整物理 Shor 尚未验收。</small></p>
<div class="bookmarks" id="bookmarks"></div><p id="error"></p></header>
<div id="physical-viewer"></div><section class="report">__COLLECTIVE_DETAILS____READOUT_DETAILS__<details id="report-evidence"><summary>查看合批效果与验证证据</summary>
<p>下表比较原生门数量与实际提交的同类脉冲批次数。脉冲合批比例不代表整体物理加速比；运输、复位和读出仍计入总耗时。</p>
<table><thead><tr><th>门类型</th><th>原生门数</th><th>实际脉冲批次</th></tr></thead><tbody>__COMPARISON__</tbody></table>
<p>独立 Stim 核对原始报告、重排后的算法状态和实际提交终态；独立几何计算逐个 CZ 脉冲核对全局作用对。计划恢复和原初态重放结果见运行摘要。</p>
<p><a href="summary.json">运行摘要</a> · <a href="independent-audit.json">独立审计</a>__LAYOUT_EVIDENCE__ · <a href="animation.html">单独打开共用回放</a></p></details></section>
<script src="atom-viewer.js"></script><script>
const bookmarks=__BOOKMARKS__;let viewer;
fetch('recording.json').then(r=>{if(!r.ok)throw new Error('记录加载失败');return r.json()}).then(data=>{
viewer=window.NeutralAtomViewer.mount(document.getElementById('physical-viewer'),data);window.physicalPrefixViewer=viewer;
__READOUT_BINDINGS__
for(const row of bookmarks){const button=document.createElement('button');button.textContent=row.label;button.onclick=()=>{viewer.setTime(row.time);document.getElementById('physical-viewer').scrollIntoView({block:'start',behavior:'smooth'})};document.getElementById('bookmarks').append(button)}
}).catch(error=>document.getElementById('error').textContent=error.message);
</script></body></html>'''
    replacements = {'__SOURCE_COUNT__': str(audit['source_native_gate_count']),
                    '__PATCH_COUNT__': str(summary['patch_count']),
                    '__ATOM_COUNT__': str(summary['physical_atom_count']),
                    '__MAX_CZ__': str(audit['max_cz_batch']),
                    '__DEVICES__': str(len(recording['frames'][0].get('aods', {'AOD_0': {}}))),
                    '__TIME__': f"{audit['physical_time_us']:,.3f}",
                    '__COMPARISON__': comparison, '__BOOKMARKS__': encoded_bookmarks}
    replacements['__LAYER_NOTE__'] = layer_note
    replacements['__ROUTING_NOTE__'] = routing_note
    replacements['__COLLECTIVE_NOTE__'] = collective_note
    replacements['__COLLECTIVE_DETAILS__'] = collective_details
    replacements['__READOUT_DETAILS__'] = readout_details
    replacements['__READOUT_STYLE__'] = ('.readout-table-wrap{overflow-x:auto;max-width:100%;margin-top:12px}'
        '.readout-table{max-width:none;min-width:780px}.readout-note{font-size:13px}'
        '#readout-placement td{overflow-wrap:anywhere}' if readout_details else '')
    replacements['__READOUT_BINDINGS__'] = ('''for(const button of document.querySelectorAll('.readout-locate')){
button.disabled=false;button.onclick=()=>{viewer.setTime(Number(button.dataset.readoutTime));document.getElementById('physical-viewer').scrollIntoView({block:'start',behavior:'smooth'})};
}''' if readout_details else '')
    replacements['__LAYOUT_EVIDENCE__'] = (' · <a href="patch-parallel-audit.json">布局与码内批次审计</a>'
        if summary.get('placement_layout') in ('interleaved', 'enola') else '')
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    (directory/'index.html').write_text(page, encoding='utf-8')
    return directory/'index.html'
