"""Export curated UI and selected verified recordings; never compile or alter physics."""
import hashlib
import json
import re
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from neutral_atom_app.visualization.studio_config import catalog
from neutral_atom_env.visualization.viewer import javascript


def main():
    target = ROOT / 'demo'
    ui = ROOT / 'src/neutral_atom_app/visualization'
    workbench = target / 'workbench'
    workbench.mkdir(parents=True, exist_ok=True)
    offline = r'''<script>if(location.protocol==='file:'){document.addEventListener('DOMContentLoaded',()=>{document.body.innerHTML='<main style="font:18px/1.8 system-ui;max-width:760px;margin:70px auto;padding:24px"><h1>启动可编辑工作台</h1><p>编译由本地 Python 后端执行。请在仓库根目录运行：</p><pre>python -m pip install -e ".[smt]"\npython demo/launch.py</pre><p>然后从自动打开的 Demo 首页进入此工作台。</p><a href="../index.html">返回 Demo 首页与离线动画</a></main>';});}</script>'''
    html = (ui / 'workbench.html').read_text(encoding='utf-8')
    html = html.replace('<head>', '<head>' + offline).replace('src="/', 'src="')
    (workbench / 'index.html').write_text(html, encoding='utf-8')
    (workbench / 'workbench.js').write_text("if(location.protocol!=='file:'){\n" + (ui / 'workbench.js').read_text(encoding='utf-8') + '\n}', encoding='utf-8')
    # Server URL spelling differs from the maintained Python-adjacent filename.
    shutil.copyfile(ui / 'studio_model.js', workbench / 'studio-model.js')
    (workbench / 'atom-viewer.js').write_text(javascript(), encoding='utf-8')
    (workbench / 'studio-catalog.js').write_text('window.AtomStudioCatalog=' + json.dumps(catalog(), ensure_ascii=False) + ';', encoding='utf-8')
    smt = target / 'smt'
    smt.mkdir(exist_ok=True)
    smt_html = (ui / 'smt_experiment.html').read_text(encoding='utf-8')
    # No fetches to a nonexistent backend when opened from a filesystem URL.
    smt_html = smt_html.replace('<script>', '<script>if(location.protocol==="file:"){location.replace("replays.html");}else{', 1)
    smt_html = smt_html.replace('</script>', '}</script>', 1)
    (smt / 'index.html').write_text(smt_html, encoding='utf-8')
    source = ROOT / 'artifacts/smt-batch/attempt2'
    reference = smt / 'reference'
    # A fresh clone already contains references; UI can be re-exported without artifacts.
    if source.exists():
        selected = {'suite.json', 'comparison.json', 'animation.html', 'result.json', 'input.json',
                    'rejections.json', 'plans.json', 'trace.jsonl', 'atom_statistics.csv', 'atom_statistics.json'}
        for path in source.rglob('*'):
            if path.is_file() and path.name in selected:
                dest = reference / path.relative_to(source)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, dest)
    suite = json.loads((reference / 'suite.json').read_text(encoding='utf-8'))
    cards = []
    labels = {'greedy': '二维分组贪心', 'smt_single': '单步 SMT', 'smt_multi': '多阶段 SMT'}
    for key, report in suite.items():
        rows = ''.join(f'<tr><td>{labels[r["strategy"]]}</td><td>{r["metrics"]["simulation_time_us"]:.1f}</td><td>{" + ".join(map(str,r["cz_batch_sizes"]))}</td><td><a href="reference/{key}/{r["strategy"]}/animation.html">播放</a> · <a href="reference/{key}/{r["strategy"]}/atom_statistics.csv">逐原子 CSV</a></td></tr>' for r in report['results'])
        cards.append(f'<section><h2>{report["input"]["name"]}</h2><table><tr><th>策略</th><th>物理时间 / μs</th><th>CZ 批次</th><th>记录</th></tr>{rows}</table></section>')
    (smt / 'replays.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SMT 已编译对比</title><style>body{font:16px/1.7 system-ui;background:#f2f5f1;color:#203b34;max-width:960px;margin:40px auto;padding:20px}section{background:white;padding:22px;border-radius:12px;margin:20px 0;overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap}td,th{text-align:left;padding:10px;border-bottom:1px solid #dde6df}a{color:#17684e}</style><a href="../index.html">← Demo 首页</a><h1>SMT · 已编译对比</h1><p>同初态、同终态的四组真实执行。可直接离线播放；编辑和重编译请运行 <code>python demo/launch.py</code>。SMT 的最少阶段与代理成本优化不保证真实物理总时间最优。</p>' + ''.join(cards) + '</html>', encoding='utf-8')
    ghz = target / 'ghz4'
    ghz.mkdir(exist_ok=True)
    for name in ('animation.html', 'circuit.json', 'delivery.json', 'playback-check.json'):
        original = ROOT / 'artifacts/deliveries/ghz4-animation' / name
        if original.exists():
            shutil.copyfile(original, ghz / name)
    # Replace the historical machine-specific editor link in the exported wrapper.
    # The embedded execution payload and viewer remain the delivered recording.
    ghz_html = ghz / 'animation.html'
    data = ghz_html.read_bytes()
    data = re.sub(rb'href="http://127\.0\.0\.1:\d+/\?job=[a-f0-9]+"', b'href="../index.html"', data)
    ghz_html.write_bytes(data)
    delivery_path = ghz / 'delivery.json'
    delivery = json.loads(delivery_path.read_text(encoding='utf-8'))
    delivery.setdefault('source_animation_sha256', delivery['animation_sha256'])
    delivery['animation_sha256'] = hashlib.sha256(data).hexdigest()
    delivery['portable_wrapper_change'] = 'Historical editor URL replaced by ../index.html; embedded execution unchanged.'
    delivery.pop('url', None)
    delivery.pop('server_pid', None)
    delivery_path.write_text(json.dumps(delivery, ensure_ascii=False, indent=2), encoding='utf-8')
    entries = {str(p.relative_to(target)).replace('\\', '/'): {'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in sorted(target.rglob('*')) if p.is_file() and p.name not in {'manifest.json'} and '__pycache__' not in p.parts}
    (target / 'manifest.json').write_text(json.dumps({'schema': 'curated-demos/v1', 'files': entries,
        'sources': {'smt': 'artifacts/smt-batch/attempt2', 'ghz4': 'artifacts/deliveries/ghz4-animation'},
        'note': 'UI exported from maintained src; recordings copied without recompilation. Source paths are provenance, not runtime dependencies.'}, indent=2), encoding='utf-8')
    print(f'Exported {len(entries)} files, {sum(e["bytes"] for e in entries.values()) / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
