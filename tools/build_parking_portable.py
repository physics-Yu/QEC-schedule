"""Build a standalone, editable Parking Lab. Node is needed only by the maintainer."""
import json
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build(destination=None, *, delivery=False):
    destination = Path(destination or ROOT / 'demo/parking/index.html')
    ui = ROOT / 'src/neutral_atom_app/visualization'
    engine = ROOT / 'src/neutral_atom_strategies/motion/parking_template.js'
    result = subprocess.run(
        ['node', '-e', 'const e=require(process.argv[1]);process.stdout.write(JSON.stringify(e.compile(e.preset())));', str(engine)],
        check=True, capture_output=True, encoding='utf-8')
    plan = json.loads(result.stdout)
    inline = lambda value: json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    html = (ui / 'parking_portable.html').read_text(encoding='utf-8')
    viewer_dir = ROOT / 'src/neutral_atom_env/visualization'
    viewer = (viewer_dir / 'viewer.js').read_text(encoding='utf-8').replace(
        '__SHELL_JSON__', json.dumps((viewer_dir / 'viewer-shell.html').read_text(encoding='utf-8'), ensure_ascii=False))
    for token, value in {
        '__INPUT__': inline(plan['input']), '__PLAN__': inline(plan),
        '__ENGINE__': engine.read_text(encoding='utf-8').replace('</script', '<\\/script'),
        '__APP__': (ui / 'parking_portable.js').read_text(encoding='utf-8').replace('</script', '<\\/script'),
        '__ADAPTER__': (ui / 'parking_recording.js').read_text(encoding='utf-8').replace('</script', '<\\/script'),
        '__VIEWER__': viewer.replace('</script', '<\\/script'),
    }.items():
        html = html.replace(token, value)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(html, encoding='utf-8')
    if delivery:
        folder = ROOT / 'artifacts/parking-portable'
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'Parking-Lab.html').write_text(html, encoding='utf-8')
        readme = ('QEC Schedule · Parking 工作台分享版\n\n'
                  '解压后用现代桌面浏览器打开 Parking-Lab.html，无需安装、Python、服务器或联网。\n'
                  '沿用原工作台：实验参数 → 格点编辑 → 原子执行回放，复用QEC共用可视化组件。\n'
                  '选择画笔，点击/拖动格点修改空位、固定原子和移动目标；点击“生成动作并回放”。\n'
                  '朴素版保留匹配轴；兼容批量优化自动比较按行/按列的最少抓取批数。\n'
                  '空位不约束，无目标行列不开；可载入“兼容行 + 空位示例”查看9行合成2批。\n'
                  '新组停车 → 一次统一终态 → 集体搬远；动画可暂停、拖动和调速。\n'
                  '点击“下载可编辑分享版”会把当前示例和完整工作台保存为新的独立 HTML。\n'
                  '如聊天软件不允许直接打开 HTML，请先保存到磁盘再用浏览器打开。\n\n'
                  '这是隔离规则 patch 的构造式方法演示，不是完整物理仿真器。\n'
                  '没有任意外部障碍或真实设备光学模型；参数与适用条件在页面内列出。\n')
        (folder / '使用说明.txt').write_text(readme, encoding='utf-8-sig')
        with zipfile.ZipFile(folder / 'Parking-Lab.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(folder / 'Parking-Lab.html', 'Parking-Lab.html')
            archive.write(folder / '使用说明.txt', '使用说明.txt')
    return destination


if __name__ == '__main__':
    print(build(delivery=True))
