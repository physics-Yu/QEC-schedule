"""Record the bounded T044 correction after its frozen-artifact acceptance."""
from pathlib import Path
from datetime import datetime
import hashlib, json, re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/demos/aod-held-cz-20261007'


def read(p):
    return json.loads(p.read_bytes())


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def append(p, text):
    previous = p.read_text(encoding='utf-8')
    if text.strip() not in previous:
        p.write_text(previous.rstrip() + '\n\n' + text.strip() + '\n', encoding='utf-8')


def main():
    a = read(OUT / 'acceptance.json')
    assert a['engineering_passed'] and a['component_count'] == 70
    assert a['window_sha256'] == hashlib.sha256((OUT / a['window']).read_bytes()).hexdigest()
    now = datetime.now().astimezone().isoformat()
    tests = []
    for n in ('qec', 'backend', 'device', 'runtime', 'validation'):
        text = (OUT / (n + '-tests.log')).read_text(encoding='utf-8')
        assert '\nOK' in text
        total = int(re.search(r'Ran (\d+) tests', text)[1])
        skipped = re.search(r'OK \(skipped=(\d+)\)', text)
        tests.append({'suite': n, 'total': total, 'skipped': int(skipped[1]) if skipped else 0})
    delivery = {'schema_version': 'HeldCZGalleryDelivery/0.1', 'status': 'engineering_passed_visual_pending',
        'updated_at': now, 'entry': 'animation-library.html', 'acceptance': 'acceptance.json',
        'logical_source_changed': False, 'physical_lowering_recompiled': True,
        'tests': tests, 'regression_passed': sum(t['total'] - t['skipped'] for t in tests),
        'regression_skipped': sum(t['skipped'] for t in tests),
        'job_id': read(ROOT / 'knowledge/roles/R0/aod-held-cz-dispatch-v2.json')['job_id'],
        'browser_rendering_verified': False, 'user_visual_acceptance': 'pending',
        'quantum_state_simulated': False, 'hardware_executed': False, 'full_shor_executed': False,
        'old_gallery': '../neutral-modular-20261007/animation-library.html'}
    save(OUT / 'delivery.json', delivery)
    table = '\n'.join(f"| {r['component']} | {r['previous_duration_us']:g} | {r['duration_us']:g} | {r['saved_us']:g} |"
        for r in a['physical_components'] if r['component'] in ('CX', 'CZ', 'SE', 'S', 'SE_PAIR', 'MEASURE_Z'))
    note = ROOT / 'knowledge/roles/R0/aod-held-cz.md'
    previous = note.read_text(encoding='utf-8')
    previous = previous.replace('status implementation_in_progress', 'status engineering_passed_visual_pending')
    previous = previous.replace('## 活动作业', '## 重编译作业')
    previous = previous.replace('完整目录与协议正在重新编译/验收，尚未交付新窗口，不能将旧passed继承为本轮通过。',
        '以上为开发阶段的小例检查；完整目录、协议和新窗口的最终结果见下节，不继承旧passed。')
    note.write_text(previous, encoding='utf-8')
    report = f'''## 当前交付与独立核对

[动画目录](../../../artifacts/demos/aod-held-cz-20261007/animation-library.html)包含70组件＋双SE。65物理条目及双SE重新编译，66份输入PhysicalDAG与旧版逐字节相同。独立载体审计覆盖4406次CZ脉冲、11524对耦合及11784个MOVE，均保持门时AOD–SLM承载，CZ搬运周期只在原SLM位置放回。全部源结构检查通过，SE/H/CX/CZ/S/S†算符检查通过；其他仪器/工厂的source-semantics未覆盖项仍原样记录，不将结构检查当作量子协议证明。

| 组件 | 旧模型时间 μs | 新模型时间 μs | 减少 μs |
|---|---:|---:|---:|
{table}

T和T†各39阶段，拒收清理/新epoch初始化26阶段，均使用本次重新生成的415个静态模块并完成连续事件验证。三条协议的原生编译/连接编译/placement/routing增量全部为0，实际编译入口保护覆盖整个本次运行。每个阶段另作carrier审计；源结果与条件分支、token及epoch只来自本次fake会话。

五组服务器回归{delivery['regression_passed']}通过、{delivery['regression_skipped']}跳过；跳过项明确依赖未随快照携带的旧R4完整世界工件，不计为通过。最终服务器exit0，用时{a['job']['elapsed_seconds']:.2f}秒，峰值进程树RSS {a['job']['peak_tree_rss_bytes']}字节；48GiB/9000秒预算未耗尽，源码快照稳定、输入/回收输出逐文件哈希验证。失败v1作业及其日志保持原样。

71条目{len(a['viewer_checks']['checks'])}项DOM功能检查通过，{a['viewer_checks']['position_comparisons']}次位置比较；全量XY检查{a['path_audit']['moves']}个MOVE / {a['path_audit']['atom_paths']}条原子路径，回退{a['path_audit']['original_fallback_count']}。检查覆盖抓取/放回进度、结束时载体提交、倍速倒计时、CZ精确时间段红色背景、全x测量带、缩放/导航和资源时间表。XY间距仍只是展示模型，不继承硬件路线资格。

新界面保留用户参考浅色风格和100μs/屏幕秒。1μsCZ在此比例下显示0.01秒，关键帧与下一CZ可停留查看；没有拉长脉冲或删除必要200μs交接。读出仍用已声明的SLM接收阵列，因此读出端交接保留并在侧栏标明。光场渐变/百分比为示意，不是标定功率。

读取接口：[验收](../../../artifacts/demos/aod-held-cz-20261007/acceptance.json)、[上游载体/源比较](../../../artifacts/demos/aod-held-cz-20261007/held-cz-upstream-audit.json)、[交付](../../../artifacts/demos/aod-held-cz-20261007/delivery.json)、[设备时间表投影](../../../artifacts/demos/aod-held-cz-20261007/viewer-resource-export.json)、[区域来源](../../../artifacts/demos/aod-held-cz-20261007/viewer-regions.json)。同目录各组件和协议保留原始动作、验证、事件及carrier-audit。

浏览器file协议限制未绕过，DOM检查不等于实际浏览器渲染或用户视觉确认；user_visual_acceptance=pending。范围仍是无丢失fake场景编译/调度，无量子态/噪声仿真、硬件执行或完整Shor；旧角色、完整Shor和heartbeat继续停止。
'''
    append(note, report)
    for rel in ('knowledge/interfaces/motion-presentation.md', 'knowledge/interfaces/compiled-modules.md'):
        p = ROOT / rel
        p.write_text(p.read_text(encoding='utf-8').replace('status implementation_in_progress', 'status implemented_scoped_checks_passed'), encoding='utf-8')
    link = '## T044 AOD承载CZ与全x测量带交付\n\n[修正、时长与验收](roles/R0/aod-held-cz.md)；[新71条目动画](../artifacts/demos/aod-held-cz-20261007/animation-library.html)。物理编译已重建，源电路字节相同；工程检查通过，用户视觉pending。旧neutral-modular窗口保留历史数据，当前入口以此为准；旧角色/全Shor/heartbeat保持停止。'
    for rel in ('knowledge/INDEX.md', 'knowledge/task-board.md'):
        append(ROOT / rel, link)
    append(ROOT / 'knowledge/tasks/T044.md', '## 当前载体修正交付\n\n[保持AOD的CZ与全x测量带](../roles/R0/aod-held-cz.md)已完成新65组件、双SE和39/39/26连续协议验收；新入口为aod-held-cz-20261007/animation-library.html。状态pending_user_visual_review。旧交付窗口按其原设备/编译配置冻结，不作为本轮验收。')
    append(ROOT / 'knowledge/roles/R0/status.md', '## 当前T044载体修正交付\n\n[新窗口、时长和证据](aod-held-cz.md)：71条目工程检查通过，物理编译重建、源电路未改；去除CZ门位多余交接，测量区覆盖x轴，载体进度/剩余时间/红色CZ背景已接入。user_visual_acceptance=pending；本轮服务器作业exit0，旧全Shor、角色和heartbeat不恢复。')
    rp = ROOT / 'knowledge/registry.json'; registry = read(rp)
    updates = {'IF-COMPILED-MODULE-001': '0.2.0', 'IF-MOTION-PRESENTATION-001': '0.5.0', 'R0-AOD-HELD-CZ-001': '0.1.0', 'ADR-0009': '1.2.0'}
    for d in registry['documents']:
        if d['id'] in updates:
            d['version'] = updates[d['id']]
            if d['id'] != 'ADR-0009':
                d['status'] = 'engineering_passed_visual_pending'
    registry['updated_at'] = now; save(rp, registry)
    bp = ROOT / 'knowledge/task-board.json'; board = read(bp)
    task = next(t for t in board['tasks'] if t['id'] == 'T044')
    task.update(status='pending_user_visual_review', dispatch_state='aod_held_cz_completed_exit0', updated_at=now,
        verification=f"本轮66物理示例及39/39/26连续协议通过；377回归通过、1旧R4依赖跳过；71条目{len(a['viewer_checks']['checks'])}项功能检查与完整XY检查通过；源电路字节相同。",
        next_action='用户验收aod-held-cz-20261007/animation-library.html，检查抓取/放回、保持AOD的CZ和全x测量带')
    task['viewer_update'] = {'status': 'engineering_passed_visual_pending', 'version': 'aod-held-cz/1',
        'circuit_recompiled': True, 'logical_source_changed': False, 'functional_checks': len(a['viewer_checks']['checks']),
        'evidence': 'artifacts/demos/aod-held-cz-20261007/acceptance.json', 'entry': 'artifacts/demos/aod-held-cz-20261007/animation-library.html'}
    for rel in ('acceptance.json', 'animation-library.html', 'delivery.json'):
        value = 'artifacts/demos/aod-held-cz-20261007/' + rel
        if value not in task['artifacts']:
            task['artifacts'].append(value)
    board['updated_at'] = now; save(bp, board)
    print(json.dumps({'status': delivery['status'], 'regression_passed': delivery['regression_passed'], 'regression_skipped': delivery['regression_skipped']}))


if __name__ == '__main__':
    main()
