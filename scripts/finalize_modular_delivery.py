"""Publish the T044 evidence index only after the aggregate acceptance passes."""
from pathlib import Path
from datetime import datetime
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/demos/neutral-modular-20261007'


def read(path):
    return json.loads(path.read_bytes())


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def append(path, text):
    old = path.read_text(encoding='utf-8')
    if text.strip() not in old:
        path.write_text(old.rstrip() + '\n\n' + text.strip() + '\n', encoding='utf-8')


def main():
    acceptance = read(OUT / 'acceptance.json')
    assert acceptance['engineering_passed'] and acceptance['component_count'] == 70
    assert acceptance['window_sha256'] == hashlib.sha256((OUT / 'full-viewer.html').read_bytes()).hexdigest()
    evidence = ROOT / 'knowledge/roles/R0/evidence/modular'
    remote = read(evidence / 'protocol-completion-server.json')
    worker = read(evidence / 'protocol-worker-receipt.json')
    assert remote['job']['returncode'] == 0 and remote['summary']['status'] == 'passed'
    assert worker['source_snapshot_stable'] and worker['input_snapshot_verified']
    now = datetime.now().astimezone().isoformat()
    status = {
        'schema_version': 'ModularGalleryDelivery/0.1', 'status': 'passed', 'updated_at': now,
        'aggregation': 'completed upstream components, repaired clock and fixture, completed continuous protocols',
        'engineering_acceptance': 'acceptance.json', 'user_visual_acceptance': 'pending',
        'browser_rendering_verified': False, 'hardware_executed': False, 'quantum_state_simulated': False,
        'full_shor_executed': False,
        'upstream_job': '20261007T100134361090Z-t044-neutral-modular-full-v1',
        'consumer_job': '20261007T111456304696Z-t044-modular-protocol-resume-v4',
        'consumer_job_wall_seconds': remote['job']['elapsed_seconds'],
        'consumer_job_peak_process_tree_rss_bytes': remote['job']['peak_tree_rss_bytes'],
        'consumer_source_unchanged': True,
        'historical_failures_preserved': [
            'initial continuous protocol: relative plan carried absolute initial clock; fixed and rechecked',
            'historical placement test fixture omitted from snapshot; same-source local recheck passed',
            'guard-v3 exceeded 12 GiB after committed prefixes; restored matching 24-stage checkpoints with 48 GiB budget',
        ],
        'previous_status': 'revisions/before-protocol-clock-resume/upstream-status.json',
    }
    save(OUT / 'status.json', status)
    table = []
    for name in ('CX', 'CZ', 'H', 'S', 'SDG', 'PREPARE_Y_PLUS', 'PREPARE_Y_MINUS', 'PREPARE_A', 'SE_PAIR'):
        value = read(OUT / name / 'summary.json')
        table.append(f"| {name} | {value['action_count']} | {value['duration_us']} |")
    report = '''# T044 中性原子模块编译交付

owner R0；kb-0006 / plan-0008；组件接口0.2.0；编译模块接口0.1.0；工程检查通过，用户视觉pending。

[完整动画窗口](../../../artifacts/demos/neutral-modular-20261007/full-viewer.html)包含70个目录组件和1个双SE并行示例。点击组件后可播放、拖动时间、跳转阶段或模块，查看编译来源和动作。71条目、17项DOM功能检查、8090次位置比较通过。浏览器渲染未由工具验证；不能将DOM检查写成用户视觉确认。

## 本轮平台实现

Y±使用编码加态的稳定子投影制备，再执行同码S/S†-SE；反馈结果与修正保留，S不再消费另一个Y块。参考来源及码型边界见[中性原子制备研究](neutral-atom-preparation-review.md)。S-SE按本项目坐标同构移植，独立带符号稳定子/逻辑X/Z映射通过；错误相位反例被拒绝。现有设备模型允许独立单比特寻址，没有新增对角AOD假设，折叠CZ逐段接受完整运动约束检查。

CNOT九对原子进入同一原生CZ批；CZ使用实际代码位置换、九对原生CZ、实际位置换，消去中间物理H；H保留九个物理H和真实原子置换，零CZ。逻辑读出保留用户指定的无通道数量上限，同组整阵列一次往返。

联合ZZ枚举上下合法Z边界代表链及可复位探针，按当前几何选择较近组合；受影响的合并/拆分检查、修正与读出一起变换。它仍是当前固定支撑gauge-fixing仪器，没有取得局部lattice surgery噪声距离资格。原始A使用16-CX编码网络，任意种子逻辑映射通过，但不声明受保护注入或容错。

以下为最终冻结产物计数，替代进行中记录的中间统计：

| 组件 | 动作数 | 模型时长 μs |
|---|---:|---:|
''' + '\n'.join(table) + '''

## 模块构建与连续消费

build_dependencies先构建缺失的不可变叶子/连接变体，compose_recipe只绑定并链接已有产物；缺依赖明确报错，不能回退到完整stage编译。415个模块在时钟修复后经过30项原生规则及叶子生成AST核对，仅迁移索引，原动作模板哈希不变。每个新实例重新检查所有旁观原子、SLM占用、AOD捕获/扫掠/广播和资源；测量连接保持绝对MZ端口，不能盲目平移。

T和T†各39个stage、70268个动作，均到达token consumed并释放资源，各5856次模块绑定。拒收例26个stage、5391次绑定，拒收后清理并释放epoch0，进入epoch1初始化。三条协议的新增leaf/connector编译、placement和routing搜索均为零；实际编译/内核/调度/路由入口装有调用即失败的检查。恢复前缀另由逐阶段持久记录验证，恢复后的入口检查覆盖本次进程。

模块缓存不包含测量值、场景、接受判定、运行frame、token或epoch。连续运行由同一EventSession提供结果与控制状态，持久检查点与配套阶段记录一致，旧的更晚未提交到该检查点的产物保留在recovery-before-resume。

## 验收证据与恢复

65个物理目录条目和双SE示例通过源覆盖、几何与无丢失fake事件检查。全部66份源结构通过；SE/H/CX/CZ/S/S†独立源算符检查通过。服务器模块复用9项针对性测试全部通过，原始A/Y/边界/S-SE的针对性检查以及既有回归记录随作业保留。历史缺placement fixture的单例使用同冻结核心源码补验通过；依赖旧R4工件的跳过项未计为通过。

最初连续协议暴露相对计划初态混入绝对时钟的缺陷，已修复；12GiB进程树内存预算中止后，从匹配的24阶段检查点恢复。最终作业20261007T111456304696Z-t044-modular-protocol-resume-v4预算5400秒、48GiB、3worker，1503.124秒完成，峰值进程树RSS16760696832字节，exit0，输入及源码快照稳定。上游失败状态、恢复过程和旧产物保持原始含义，没有改成历史成功。

读取入口：[汇总acceptance.json](../../../artifacts/demos/neutral-modular-20261007/acceptance.json)、[最终交付status.json](../../../artifacts/demos/neutral-modular-20261007/status.json)、[源结构检查](../../../artifacts/demos/neutral-modular-20261007/source-structure-audit.json)、[服务器完成记录](evidence/modular/protocol-completion-server.json)、[源码回执](evidence/modular/protocol-worker-receipt.json)、[9项模块测试](evidence/modular/module-recheck-tests.log)。精确模块来源和原子轨迹可从窗口继续读取。

范围为当前设备模型下的编译、调度、算符代数与无丢失fake事件；未做量子态/噪声仿真或硬件执行，未完成容错资格验证，也没有运行完整Shor。工程验收与用户视觉验收分列。旧角色、完整Shor及heartbeat继续停止。
'''
    (ROOT / 'knowledge/roles/R0/modular-delivery.md').write_text(report, encoding='utf-8')
    for relative in ('knowledge/interfaces/compiled-modules.md', 'knowledge/interfaces/logical-component-catalog.md'):
        p = ROOT / relative
        t = p.read_text(encoding='utf-8').replace('status implementation_in_progress', 'status implemented_scoped_checks_passed')
        if relative.endswith('compiled-modules.md'):
            t = t.replace('依赖组件接口0.1.2', '依赖组件接口0.2.0')
            t = t.replace('全目录、完整协议、全场景负例和最终动画仍待本轮验收；不得继承旧工件的passed或用户视觉确认。', '本轮全目录、完整协议、全场景负例及最终71条目窗口已通过范围内工程检查；用户视觉pending，详见R0模块交付记录。')
        p.write_text(t, encoding='utf-8')
    workflow = ROOT / 'knowledge/roles/R0/modular-compilation-workflow.md'
    workflow.write_text(workflow.read_text(encoding='utf-8').replace('implementation in_progress_main_agent_integration', 'implementation implemented_scoped_engineering_verified_visual_pending'), encoding='utf-8')
    latest = '## T044 模块化最终交付（2026-10-07）\n\n[本轮实现与完整证据](modular-delivery.md)：70组件＋双SE，71条目17项功能检查/8090位置比较通过；T/T†各39stage、5856次模块绑定，拒收清理与新epoch初始化26stage、5391次绑定，新增原生编译/placement/routing均为零。最终服务器作业exit0、源码稳定。Y±/S-SE、CNOT整阵列、CZ及ZZ合法近边选择已实施，旧进行中说明以此为准；噪声容错/硬件/完整Shor未验证，用户视觉pending。旧角色/heartbeat不恢复。'
    for relative in ('knowledge/roles/R0/status.md', 'knowledge/roles/R0/logical-components.md', 'knowledge/roles/R0/neutral-atom-preparation-review.md', 'knowledge/roles/R0/modular-compilation-workflow.md'):
        append(ROOT / relative, latest)
    append(ROOT / 'knowledge/tasks/T044.md', '## 当前权威交付\n\n本轮模块化已完成范围内工程检查，状态pending_user_visual_review。见[模块化交付](../roles/R0/modular-delivery.md)及[71条目动画](../../artifacts/demos/neutral-modular-20261007/full-viewer.html)。上方旧缺口及仅研究状态为历史记录，当前实现与证据以新交付为准。')
    for relative in ('knowledge/INDEX.md', 'knowledge/task-board.md'):
        append(ROOT / relative, '## T044 模块化当前交付\n\n[工程结果与接口入口](roles/R0/modular-delivery.md)；[完整71条目动画](../artifacts/demos/neutral-modular-20261007/full-viewer.html)。本轮65物理条目、双SE及39/39/26阶段连续协议通过，新增原生编译/布局/路由搜索为零。状态pending_user_visual_review；前述进行中条目为历史进度，旧角色/完整Shor/heartbeat继续停止。')
    registry_path = ROOT / 'knowledge/registry.json'
    registry = read(registry_path)
    def update(value):
        if isinstance(value, dict):
            if value.get('id') in ('IF-COMPILED-MODULE-001', 'IF-LOGICAL-COMPONENT-001', 'R0-MODULAR-COMPILE-WORKFLOW-001'):
                value['status'] = 'implemented_scoped_checks_passed_visual_pending'
            for child in value.values():
                update(child)
        elif isinstance(value, list):
            for child in value:
                update(child)
    update(registry)
    if not any(x.get('id') == 'R0-MODULAR-DELIVERY-001' for x in registry['documents']):
        registry['documents'].append({'id':'R0-MODULAR-DELIVERY-001','path':'knowledge/roles/R0/modular-delivery.md','owner':'R0','version':'0.1.0','status':'engineering_passed_visual_pending','task_id':'T044'})
    registry['updated_at'] = now
    save(registry_path, registry)
    board_path = ROOT / 'knowledge/task-board.json'
    board = read(board_path)
    task = next(x for x in board['tasks'] if x['id'] == 'T044')
    task.update(status='pending_user_visual_review', verification='本轮65物理条目＋双SE、T/T†39/39stage及拒收26stage通过；17项DOM功能/8090位置比较通过；所有协议原生编译/placement/routing增量0。', next_action='用户查看新71条目动画；工程范围与未验证项见modular-delivery.md', dispatch_state='completed_exit0', updated_at=now)
    for path in ('knowledge/roles/R0/modular-delivery.md','artifacts/demos/neutral-modular-20261007/acceptance.json','artifacts/demos/neutral-modular-20261007/full-viewer.html','knowledge/roles/R0/evidence/modular/protocol-completion-server.json'):
        if path not in task['artifacts']:
            task['artifacts'].append(path)
    board['updated_at'] = now
    save(board_path, board)
    print(json.dumps({'status':'engineering_passed_visual_pending','components':71,'source_snapshot_stable':True}))


if __name__ == '__main__':
    main()
