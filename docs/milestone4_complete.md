# M4 策略合同与可编辑交付

本页定义本轮实现边界；最终验收数据见 [统一比较](m4_acceptance.md)，本轮状态和验证记录见 [日志](../instruction/logs/2026-09-11-m4-completion.md)。不以有限搜索结果宣称全局最优或任意布局完备路由。

后续 2026-09-11 编译升级已将 M4 rigid 路径替换为固定状态的 [A* 图最短路](astar_routes.md)，并复用独立验证前缀；四策略的排序/评分/预算未改。旧统一比较是升级前证据，最新同输入性能和物理复验见 [编译器升级](m4_compiler_upgrade.md)。

## 同一物理动作空间的四种策略

工作台 `compiler` 可选 `basic`、`greedy`、`critical_path`、`lookahead`。它们共用单台 AOD、GreedyCompiler / MultiTrapGreedyCompiler、独立 validator、Executor、recording 和 viewer，不用不同硬件或初态伪造策略优势。旧 `resident` / `returning` / `legacy` 仍是 M3 历史对照，不是本轮公平比较的四策略矩阵。

| 策略 | 实际选择规则 | 限制 |
| --- | --- | --- |
| basic | READY CZ 优先，稳定 gate ID；从有限合法候选中选择包含真实归还的低成本实现，每服务恢复起态 | 不是全局最短逐门往返；正常从初态运行时各服务均返回初态 |
| greedy | 保留原策略：READY CZ 优先，按当前服务时长、装卸、路程选择，允许持续驻留 | 不预测后续阻塞，可比 basic 更慢 |
| critical_path | 对全部 READY 门计算最长剩余依赖链，按实际脉冲时长加权，优先较长链，再按物理成本选择 | 权重为脉冲时长，不含尚未编译的未来运输 |
| lookahead | 全部 READY 门的有限候选，先跨 gate 覆盖再覆盖不同终态；根节点显式 KEEP / RETURN，私有状态中真实执行后续服务 | 深度、宽度、节点和路径搜索均有限；不保证比 greedy 更快 |

`next_use_distance` 为沿 DAG 到下一次使用当前操作数的最少依赖边数；`reuse_count` 计入有后续使用且终态仍在 EZ/AOD 的操作数。真实后续服务体现主要复用收益；预测分数相同时，以该驻留特征破平局，不添加无标定的“时间奖励”。

## 前瞻评分与预算

每个根分支获得相同节点配额。分支由私有 checkpoint 恢复，经实际 `fill_raman → validator → Executor` 执行，不写 live state。叶节点评分：

```text
已推演服务的真实耗时
+ 从叶终态满足声明 terminal 的真实清理计划耗时
+ 未搜索逻辑门的脉冲关键路径下界
```

最后一项不包括未搜索运输，清理是叶状态的端点评价，不是整条未来电路的精确成本。记录 `horizon_complete`、实际 horizon、cleanup 和 remaining lower bound，避免把估计混成执行指标。有限视野可能偏爱短期便宜的动作或错过未来复用。

`run_m4` 默认参数：`strategy='greedy', lookahead_depth=2, beam_width=3, rollout_budget=12, ready_limit=16, site_limit=4, max_decisions=10000`。Python API 上限 depth 4、beam 16、rollout 256；交互工作台采用更小上限 depth 3、beam 8、rollout 128、READY 32、site 16。后者防止误填无界搜索，不保证 90 秒内可完成大线路。

决策记录提供选中候选/特征、合法与被拒候选、站点/READY 截断、推演节点和根节点遗漏、评分分解、编译 wall time、真实操作时间。达到推演预算可选择已验证分支，明确记录截断；最终找不到合法分支、决策预算耗尽或不能完成 terminal 才报告 stalled。HTTP 超过 90 秒独立终止并显示失败摘要。

## 并行窗口与物理合同

固定 H/X/Y/Z/T/CZ、单比特 1 μs、只同类型门重叠；不同 qubit 的稳定 SLM / 静止 AOD 目标允许并行。移动邻居的禁光区通过直线与半径 5 μm 圆盘的交点解析求解，再转换为真实时间区间；恰好 5 μm 允许。可使用 MOVE 的安全早段或后段，不再因为整个 MOVE 曾靠近就一律禁光。独立执行校验仍检查脉冲的实际重叠轨迹，AOD 目标保留 AOD 资源锁。只提供更细可用区间，不保证全局最大并行。

EZ 日志只推演支撑变化，不能在移动末态重验被追加的早段 Raman。真正逻辑、邻距和资源校验由实际时间表负责。

CZ 上下/左右相对位移 2 μm 均保留；它是全 EZ 照明、各向同性距离代理，不是 Qiuniu 真机各方向保真度标定。中心上 2 / 下 2 的原子相距 4 μm，当前阈值拒绝。详见 [一手资料核查](m4_physics_research.md)。

## 可编辑界面与重建

```powershell
python examples/circuit_workbench.py --port 8768 --output artifacts/workbench-m4-complete
python examples/validate_m4_complete.py --help
python -m pytest tests/test_m4_policies.py tests/test_raman_windows.py tests/test_workbench_m4_policies.py tests/test_m4_direction_contract.py -q
```

保留“初始条件 → 可编辑线路 → 编译 → 验证/Executor → 回放”，支持随机载入、修改任意受支持门、撤销/重做、导入/导出与 32×。新增四策略选择、预算和评分详情；编译失败不换成成功动画。`M4 对比 · 重复配对与后继` 示例提供小预算前瞻入口，可继续任意编辑，示例不是编译器专用路径。

## 完成边界与后续

M4 的交付是声明平台族内可复现的四策略和比较，不是优化已经没有空间。非抢占单 AOD 服务、有限路线、启发式叶评分保持；任意障碍布局或 32 原子/64 门不保证在交互预算内成功。

1/2/4 trap 为同一 rigid AOD 的固定间距联合运输试验，四策略均可调用此能力；正式四策略主矩阵固定 1 trap。任意多 cell 跨门驻留、部分 PARK/RECAPTURE 优化不是本轮完成的能力。批量 CZ、多个独立 AOD、量子态/噪声和 RL 保持后续范围。
