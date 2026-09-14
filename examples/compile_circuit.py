"""Compile external circuit/platform/placement inputs with an interchangeable strategy."""
import argparse
import html
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.simulation.pipeline import Platform, load_circuit, initialize
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.planning.eager_baseline import EagerBaseline
from neutral_atom_env.planning.compilers import make_compiler
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.visualization import VisualRecorder, write_bundle, render_summary
from neutral_atom_env.testing.renderer import render_layout, render_dag
from neutral_atom_env.testing.theme import VisualTheme
from neutral_atom_env.testing.artifacts import page


def build(circuit_path, platform_path, placement_path, output, *, strategy='single_trap', anchor_order='forward'):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    def write(name, value):
        (output/name).write_text(canonical_json(value), encoding='utf-8')
    write('result.json', {'status': 'building'})
    (output/'index.html').write_text(page('编译中', '<h1>正在编译输入电路</h1>'), encoding='utf-8')
    (output/'report.html').write_text(page('编译中', '<h1>正在编译输入电路</h1>'), encoding='utf-8')
    try:
        circuit = load_circuit(circuit_path)
        platform = Platform.load(platform_path)
        placement = json.loads(Path(placement_path).read_text(encoding='utf-8'))
        state = initialize(circuit, platform, placement)
        initial = state.snapshot()
        options = {'anchor_order': anchor_order} if strategy == 'single_trap' else {}
        compiler = make_compiler(strategy, **options)
        recorder = VisualRecorder(state)
        plans = {}
        frames = {'initial': initial}
        def observe(s, event):
            recorder.observe(s, event)
            if s.active_plan:
                plan = s.active_plan.plan
                plans[plan.id] = plan
                if len(plans) == 1 and event.operation_id:
                    op = next(o for o in plan.operations if o.id == event.operation_id)
                    if event.event_type.value == 'operation_completed' and op.label == 'Park anchor in EZ SLM':
                        frames['parked'] = s.snapshot()
                    if event.event_type.value == 'operation_started' and op.operation_type.value == 'entangling_pulse':
                        frames['pulse'] = s.snapshot()
        result = EagerScheduler(state, policy=EagerBaseline(compiler=compiler)).run(observe)
        frames['final'] = state.snapshot()
        write('result.json', result)
        write('circuit.json', circuit)
        write('platform.json', json.loads(Path(platform_path).read_text(encoding='utf-8')))
        write('placement.json', placement)
        write('compilation.json', {'strategy': strategy, 'options': options, 'hardware_backend': platform.hardware.backend})
        write('plans.json', list(plans.values()))
        write('metrics.json', state.metrics())
        (output/'initial.json').write_text(initial, encoding='utf-8')
        (output/'final.json').write_text(state.snapshot(), encoding='utf-8')
        (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n', encoding='utf-8')
        recorder.write(output/'index.html')
        recorder.write_json(output/'recording.json')
        write_bundle(output)
        summary = recorder.payload()['summary']
        write('summary.json', summary)
        theme = VisualTheme.load()
        render_summary(summary, output/'timeline.png', theme)
        render_dag(initial, output/'circuit.svg', theme)
        for name, saved in frames.items():
            render_layout(saved, output/f'{name}.png', theme, show_aod=True)
        figures = ''.join(f'<figure><img src="{name}.png"><figcaption>{name}</figcaption></figure>' for name in frames)
        diagnostics = html.escape(canonical_json(result.diagnostics))
        description = ('单 AOD trap：a 先送到 EZ SLM，b 随后到达执行 CZ，b 和 a 依次回到本次来源位置。'
                       if strategy == 'single_trap' else '使用选择的编译策略，根据实际输入平台生成物理计划。')
        body = f'''<h1>电路编译与实际执行</h1><p>{html.escape(result.status)} · {len(state.atoms)} 原子 · {len(circuit.gates)} 个输入门</p>
        <p>电路、平台与初始布局由独立 JSON 输入。{description}所有装卸、空载移动和尾部返回都计时。</p>
        <p>编译策略：{html.escape(strategy)} · 物理后端：{html.escape(platform.hardware.backend)}</p>
        <nav><a href="index.html">完整动画与时序表</a> · <a href="circuit.json">输入电路</a> · <a href="platform.json">平台</a> · <a href="placement.json">初始布局</a> · <a href="plans.json">物理计划</a> · <a href="result.json">编译结果</a></nav>
        <pre>{diagnostics}</pre><img src="circuit.svg" alt="电路依赖"><img src="timeline.png" alt="真实操作时序">{figures}'''
        (output/'report.html').write_text(page('Circuit compiler', body), encoding='utf-8')
        return result
    except Exception as error:
        write('result.json', {'status': 'failed', 'error': str(error)})
        failure = page('编译失败', f'<h1>编译失败</h1><pre>{html.escape(str(error))}</pre>')
        for name in ('index.html', 'report.html'):
            (output/name).write_text(failure, encoding='utf-8')
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--circuit', type=Path, default=Path('configs/circuits/single_trap.json'))
    parser.add_argument('--platform', type=Path, default=Path('configs/platforms/single_trap.json'))
    parser.add_argument('--placement', type=Path, default=Path('configs/placements/eight_atoms.json'))
    parser.add_argument('--strategy', choices=['single_trap', 'legacy_eager'], default='single_trap')
    parser.add_argument('--anchor-order', choices=['forward', 'reverse'], default='forward')
    parser.add_argument('--output', type=Path, default=Path('artifacts/single-trap'))
    args = parser.parse_args()
    result = build(args.circuit, args.platform, args.placement, args.output, strategy=args.strategy, anchor_order=args.anchor_order)
    print(result.status, (args.output/'index.html').resolve())
    return 0 if result.status == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
