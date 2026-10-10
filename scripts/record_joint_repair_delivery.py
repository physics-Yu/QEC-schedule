"""Publish the scoped repair result without changing other project tasks."""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'artifacts/demos/joint-factory-repaired-20261008'


def read(p):
    return json.loads(p.read_bytes())


def write(p, value):
    p.write_bytes((json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))


def append(p, heading, text):
    old = p.read_text(encoding='utf-8')
    if heading not in old:
        p.write_bytes((old.rstrip()+'\n\n'+heading+'\n\n'+text+'\n').encode('utf-8'))


def main():
    acceptance = read(OUT/'acceptance.json'); library = read(OUT/'library-manifest.json')
    evidence = read(OUT/'joint-delivery-evidence.json'); cohort = read(OUT/'cohort-acceptance.json')
    assert acceptance['status'] == 'engineering_passed_visual_pending' and evidence['passed']
    job = ROOT/'scripts/outputs/T704/server'/library['server_job_id']
    state = read(job/'held-cz-receipt/job/status.json')
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    report = f'''# T044 已选批修复与模块库封存

id R0-JOINT-REPAIR-DELIVERY-001；owner R0；version 0.1；status scoped_engineering_passed_visual_pending；updated_at {now}；applies_to T044；dependencies kb-0006 / plan-0008、compiled-modules0.8.2、joint-frontier0.1、logical-frame0.1；supersedes 本次剩余修复的进行中状态。

本次修复完成并已封存。用户最新要求优先基础完整 Shor pipeline，进一步并行优化已延期，不作为基础 pipeline 交付门槛。本对话没有恢复旧长期角色或 heartbeat，也未修改主对话的 component_pipeline / component_strategy / basic_shor 文件。

## 读取接口与固定来源

- 新动画：[82入口](../../../artifacts/demos/joint-factory-repaired-20261008/animation-library.html)。
- [库清单](../../../artifacts/demos/joint-factory-repaired-20261008/library-manifest.json)：{library['module_artifacts']} 个动作模块、{library['immutable_frontier_proofs']} 份不可变前沿证明，另记录可替换 lookup 索引；逐文件字节哈希可检查。
- [验收](../../../artifacts/demos/joint-factory-repaired-20261008/acceptance.json)、[每块/每批/关键路径与比较](../../../artifacts/demos/joint-factory-repaired-20261008/joint-delivery-evidence.json)。
- 稳定接管入口：`knowledge/roles/R0/joint-repair-library-status.json`；库目录 `artifacts/demos/joint-factory-repaired-20261008/compiled-modules`。
- 固定服务器作业 `{library['server_job_id']}`，exit 0；wall {state['elapsed_seconds']:.3f} 秒，采样进程树峰值 RSS {state['peak_tree_rss_bytes']} 字节。原预算 9000 秒、48 GiB、4 workers；叶子1800秒、beam192、赋值20000。没有追加重编或优化搜索。
- 原生规则身份 `{library['native_rule_hash']}`；完整源/输入清单哈希 `{library['frozen_source_inventory_sha256']}`。源归档及596文件清单位于该作业的 `source.tar.gz` / `source-inventory.json`，服务器首尾均校验一致。

`LogicalComponentCompiler(device, module_directory=目录)` 读取静态库；`compose_recipe(dag, complete_world, execution_context=...)` 只绑定已建叶子和前沿，缺失明确拒绝。源形状、设备、原生身份和完整场景入口/出口必须符合资格；新 Shor world 不因库存在而自动通过。测量结果、frame、token、epoch、运行状态和验收不能缓存。

## 修复与验证

共同前沿选择仍保留开放 ready 域的方向/cohort 策略；已经提交的纯2Q叶子按完整门数降层，不再二次按SE方向拆批。entangling_layer 组合强制一个 CZ，否则 COMMITTED_BATCH_RESERIALIZED。12对/137原子回归精确保留旧11+1反例、新单12对CZ和24目标H；没有删除门、减少SE轮数、改变100μs抓放或放宽审计。

冻结服务器版本410项回归全部通过、无跳过。65物理组件＋双SE、T/T†各39阶段、拒收重试26阶段、7帧、4并行例通过完整世界检查。三个协议组合时原生编译/布局/路由/前沿搜索均为零；H→T也为零新增原生编译。CNOT审计{cohort['plans']}计划/{cohort['cohorts']}组/{cohort['magic_readouts']}次magic读出；补充审计{evidence['plans_checked']}计划，逐一核对已选批单脉冲和所有物理CX的H–CZ–H。

三个连续协议的全部源DAG及DeviceSpec与冻结预览一致。如下均为相同100μs抓放、原3轮SE的模型时间，不是硬件测量：

| 路径 | 冻结预览 μs | 本次 μs | 较早cohort基线 μs |
|---|---:|---:|---:|
| T | 201475.5 | 198573.5 | 447575 |
| T† | 201475.5 | 198573.5 | 447575 |
| 拒收清理/新epoch初始化 | 166567 | 162993 | 419932 |

本次工厂到READY为188758 μs。单块/四块原始A编码均1246 μs、每块9 CX、源CX依赖深度4、实际6次CZ；混合编码/SE为2689 μs、8次CZ、6次跨阶段共同脉冲；六块双AOD SE为1877 μs、5次CZ和48辅助同波读出。这是有界实例结果，不是可达最优深度证明。

82入口DOM、帧及XY检查通过，104042条显示原子路径无回退；浅色、100μs/屏幕秒、AOD亮/SLM暗、关键帧和设备schedule保留。浏览器实际渲染未由工具验证，用户视觉仍pending。Windows长路径只在取回/整合工具中处理，原证据字节未修改。

## 保留的范围限制

静态场景的不同运动模块仍有编译器顺序约束；未选候选分别报告当前赋值冲突、搜索/路由未资格化和排程偏好，不把它们统称硬件不可行。驻留仅支持已有相同阵列/home连接规则，H→T保留物理H兑现。本次不证明全局最优、噪声容错、量子态模拟、硬件执行或完整Shor运行。

封存时当前工作区原生身份匹配：{library['current_workspace_native_identity_matches']}。共享工作区的 `validation/strategy_groups.py`、`validation/stream_factory.py` 已有另行改动；不回滚，410回归与几何/事件资格明确绑定本次冻结快照，不宣称覆盖这些后续验证器改动。现有指纹扫描backend/*.py，未来增加component_strategy.py也会改变身份；需要显式核对兼容性，不能盲改旧缓存hash。

旧 joint-factory-accepted-20261008 预览及 frame-cnot-cohorts-20261008 基线均保留。
'''
    (ROOT/'knowledge/roles/R0/joint-repair-delivery.md').write_bytes(report.encode('utf-8'))
    status_path = ROOT/'knowledge/roles/R0/joint-repair-library-status.json'; status = read(status_path)
    status.update(status='sealed_scoped_engineering_passed',full_library_qualified=True,
                  local_seal_complete=True,server_returncode=0,updated_at=now,
                  manifest='artifacts/demos/joint-factory-repaired-20261008/library-manifest.json',
                  acceptance='artifacts/demos/joint-factory-repaired-20261008/acceptance.json',
                  report='knowledge/roles/R0/joint-repair-delivery.md',
                  module_artifacts=library['module_artifacts'],immutable_frontier_proofs=library['immutable_frontier_proofs'],
                  plans_checked=evidence['plans_checked'],user_visual_acceptance='pending',
                  local_source_drift_from_frozen_build=library['local_source_drift_from_frozen_build'])
    write(status_path,status)
    heading='## T044 已选批修复完成与库封存（2026-10-08）'
    note='已封存新库与82入口动画：artifacts/demos/joint-factory-repaired-20261008。冻结版410回归、221计划审计、完整协议和7帧/4并行例通过；303动作模块＋303不可变前沿证明，用户视觉pending。详见 knowledge/roles/R0/joint-repair-delivery.md 和 joint-repair-library-status.json。用户已将进一步优化延期，基础Shor pipeline由主对话接入；旧角色/heartbeat未恢复，旧预览保留。'
    for rel in ('knowledge/roles/R0/status.md','knowledge/roles/R0/joint-repair-progress.md','knowledge/INDEX.md','knowledge/task-board.md','knowledge/tasks/T044.md'):
        append(ROOT/rel,heading,note)
    p=ROOT/'knowledge/interfaces/compiled-modules.md'; content=p.read_text(encoding='utf-8')
    content=content.replace('version 0.8.2；status implementation_under_validation','version 0.8.2；status scoped_engineering_verified_visual_pending')
    p.write_bytes(content.encode('utf-8'))
    append(p,'### 0.8.2 冻结验收','本次全量已通过，303动作模块/303不可变前沿证明，410回归/221计划，完整T/T†/拒收/7帧/4并行例；源/设备与冻结预览同配置，用户视觉pending。证据见 [本次交付](../roles/R0/joint-repair-delivery.md)。进一步优化按用户最新决定延期，不作为基础pipeline门槛。')
    p=ROOT/'knowledge/registry.json'; raw=p.read_bytes(); registry=json.loads(raw)
    for item in registry['documents']:
        if item['id']=='IF-COMPILED-MODULE-001':item.update(version='0.8.2',status='scoped_engineering_verified_visual_pending')
        if item['id']=='R0-JOINT-REPAIR-002':item['status']='completed_with_further_optimization_deferred'
    if not any(item['id']=='R0-JOINT-REPAIR-DELIVERY-001' for item in registry['documents']):
        registry['documents'].append({'id':'R0-JOINT-REPAIR-DELIVERY-001','path':'knowledge/roles/R0/joint-repair-delivery.md','owner':'R0','version':'0.1','status':'scoped_engineering_passed_visual_pending','task_id':'T044'})
    assert p.read_bytes()==raw,'REGISTRY_CHANGED_CONCURRENTLY';write(p,registry)
    p=ROOT/'knowledge/task-board.json';raw=p.read_bytes();board=json.loads(raw);task=next(t for t in board['tasks'] if t['id']=='T044')
    task.update(status='pending_user_visual_review',updated_at=now,dispatch_state='committed_batch_repair_sealed_exit0',
                verification='冻结版410回归、221计划、全部组件与连续协议/7帧/4例通过；82入口DOM和104042条显示路径通过，用户视觉pending。',
                next_action='基础完整Shor pipeline由主对话按新授权接入；进一步优化延期；本修复库供固定身份与完整world绑定核对。')
    task['joint_frontier_rebuild'].update(status='sealed_scoped_engineering_passed',
                 entry='artifacts/demos/joint-factory-repaired-20261008/animation-library.html',
                 library_manifest=status['manifest'],acceptance=status['acceptance'],report=status['report'],
                 selected_batch_parallelism_passed=True,parallel_compilation_goal_met=False,
                 broader_parallel_optimization='deferred_by_user_not_basic_pipeline_gate',user_visual_acceptance='pending')
    task['performance_review'].update(status='committed_batch_repair_verified_further_optimization_deferred',
                 current_factory_duration_us=188758.,full_T_duration_us=198573.5,
                 evidence=status['acceptance'],report=status['report'])
    for rel in (status['manifest'],status['acceptance'],status['report']):
        if rel not in task['artifacts']:task['artifacts'].append(rel)
    board['updated_at']=now;assert p.read_bytes()==raw,'TASK_BOARD_CHANGED_CONCURRENTLY';write(p,board)
    p=ROOT/'knowledge/task-board.md';lines=p.read_text(encoding='utf-8').splitlines()
    lines=['| [T044 逻辑组件与工厂已选批修复](tasks/T044.md) | R0 | 工程通过、视觉待验 | 冻结版410回归/221计划；新82入口及303模块库已封存 | 基础pipeline接入由主对话推进；进一步优化延期 |' if line.startswith('| [T044 ') else line for line in lines]
    p.write_bytes(('\n'.join(lines)+'\n').encode('utf-8'))
    print(json.dumps({'status':status['status'],'modules':library['module_artifacts'],'proofs':library['immutable_frontier_proofs'],'report':status['report']},ensure_ascii=False))


if __name__=='__main__':
    main()
