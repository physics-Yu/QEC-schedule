# M3：持久布局、操作级并行与可替换构造基线

M3-A–F 的运行时已实现，当前 checkpoint **schema 13**。验收记录和限制见 [本轮日志](../instruction/logs/2026-09-11-m3-completion.md)。本阶段限定单 rigid AOD trap、CZ + U3/别名、稳定 SLM 的 Raman 与另一个原子的运输重叠；多 AOD、批量 CZ、全局最优、测量反馈和 RL 不在本阶段。

**M4 返修点（用户明确保留）：详细设计 M4 时，需要重新审视任务选择、候选接口、目标分配、时间窗口和跨门复用决策。当前确定性启发式是可执行基线，不是永久架构。** 验收时保持同输入、同终态、同物理约束、同 validator/Executor；不能为改善策略成绩修改旧 trace 或物理参数。

## 复现

```powershell
python examples/run_m3.py --output artifacts/m3-resident
python examples/run_m3.py --compiler returning --output artifacts/m3-returning
python examples/run_m3.py --atoms 256 --output artifacts/m3-scale-256
python examples/verify_m3.py artifacts/m3-resident
python examples/verify_m3.py artifacts/m3-scale-256
python examples/circuit_workbench.py --port 8766
```

默认输入 `configs/workbench/m3_mixed.json`：6 原子、4 CZ 与 4 单比特门，包含 `CZ(a,b), CZ(a,c), CZ(b,d)`、不同伙伴和旁观原子。`--serial` 关闭重叠用于比较；`--max-decisions` 限制有限决策数。CLI 支持 4–256 原子规模场景；工作台保留 1–32 原子、64 门的交互预算。

每次 CLI 输出 input、family、run_options、terminal、result、candidate_rejections、diagnostics、recording、trace.jsonl、checkpoint 和共用 viewer HTML。completed 的退出码是 0，stalled 是 1。`verify_m3.py` 从输入重新初始化，读取 trace 中的原始 plans，经共享校验器和 Executor 重放，不调用任何 compiler；比较完整 checkpoint，并独立检查门覆盖、Raman/CZ 时长、资源冲突、装卸数和完整归还终态。

## 构造性平台族与保证范围

`motion/family.validate_family` 检查 `m3-grid-10um-v1` 的几何、容量和参数：

- 一个 rigid trap；世界 routing grid 为 5 μm、原点 (0,0)。SZ 的 SLM 在非负 10 μm 格点上，数量至少等于原子数；EZ 至少两个停车点，y = −35 μm、x = 5 mod 10 μm；各站点与世界边界有 5 μm 余量。
- 不变的项目参数：atom/SLM clearance 1 μm，CZ 半径 2 μm，移动伙伴相对静态锚点偏移 (−2,0) μm；单比特固定 1 μs。支持门仅 CZ 与实际 U3/别名执行。
- 构造保证从全体原子位于不同 SZ 站点开始，扩展到这些构造实际到达的持久状态及合法异位空 AOD。几何识别不是任意 loaded 坐标可路由的证明。具体自定义状态/终态仍逐候选执行全部 backend 校验。

构造理由：10 μm 站点间的半格走廊离 SLM 中心至少 2.5 μm，大于 1 μm clearance；EZ 停车点彼此至少 10 μm，局部 (−2,0) 作用对与其他停车原子分离。关空阱后可直接定位；装载后通过显式离开、半格转弯和最后接近到达空位。需要卸载/换伙伴时，SZ 可容纳全部原子且额外有至少两个 EZ 站点，因此可用空位暂存阻挡者；每次搬移都计时并保存绑定。终态置换用一个明确的临时空位打破环，不能直接改 holder。

逐门归还构造对任意一个支持的 READY 门，显式准备、作用、归还所有参与者及 AOD 到本次起态；恢复了下一门所需的不变量。有限无环电路总存在 READY 节点，逐门归纳得到有限电路的串行构造。驻留策略从真实 EZ/loaded 状态复用、清理或换伙伴；不承诺每次驻留都优于归还，也不把一次有限搜索失败解释为物理无解。对族外障碍/参数，最多检查 64 个路线候选，失败有明确诊断。行列阵列仍用旧 backend 的独立约束，不能冒充本构造支持。

## 任务与两个 compiler

`PersistentTargetCompiler.compile(TaskIntent, state)` 支持零门准备/归还、loaded 起点、新站点卸载、holder 置换、空 AOD 重定位和显式 holder/axes/mask 终态。未写入 TaskTarget 的字段表示不约束；backend 合法性始终适用。目标冲突、站点不足、原子/站点/时长限制失败时，不提交任何实时状态。

`ResidentCompiler.compile_gate(gate_id, state)` 保留 EZ 静态锚点和已装载伙伴；重复同一 CZ 可以只包含脉冲，换伙伴时显式卸下旧伙伴再装新伙伴。`ReturningCompiler.compile_gate` 每门构造完整起态归还。二者共用基础运输原语，生成的操作序列与装卸数实质不同；validator、Executor、codec 和 viewer 不按 compiler 名字放行。最终由相同 `initial_terminal` 要求全体 holders、AOD axes 和 masks 回到初始状态。

```python
from neutral_atom_env.simulation.m3 import initial_terminal, run_m3
terminal = initial_terminal(state)  # 在第一次执行前保存；恢复时继续传同一个目标
result = run_m3(state, compiler='resident', terminal=terminal,
                overlap=True, max_decisions=10000, on_event=recorder.observe)
```

恢复示例：`restored = SimulationState.restore(saved_checkpoint)` 后，使用原始输入初始化得到原 terminal，或保存的 TaskTarget，再调用 `run_m3(restored, terminal=terminal, ...)`。它先完成已提交在途程序，再对最新状态决策，不重做已完成门。未传 terminal 时默认取当前起态，不能将中途状态的新默认目标误当原程序的归还要求。

## 操作级执行与恢复

`motion/scheduled.scheduled_program(base, state, ((gate_id, start_us), ...))` 接收已验证局部计划和策略选择的 Raman 相对开始时间，形成 `execution_mode='scheduled'` 的程序；不自行选门或路径。TaskIntent 的 `phase='program'` / `gate_effects` 授权效果集合，每个 effect 只能实现一次。Operation 保留 gate_id、depends_on 和 task_phase，OperationInterval 保留真实时间、原子和资源需求。

`simulation/operation_program` 独立重放整个计划和所有未来操作，校验依赖、动态支撑、完整轨迹、作用对和终态。只有 Executor 安装 reducer 返回的完整下一状态；每个操作结束针对最新状态合并，不安装编译时的旧预测快照。

- 统一绝对时钟；相同时间先完成再开始，同组按 operation ID 稳定排序。
- 一个 program envelope 内保存多个 running_operations 和 completed_operation_ids；每个操作开始获取资源、结束释放，Raman 1 μs 后释放 RAMAN_0，即使 AOD 仍在运输。
- 门在实际 effect 开始时才进入 RUNNING，结束时完成并释放 successor，不等待门后清理。SLM 1Q 不改变坐标/holder。
- M3 的保守 HANDOFF_GUARD 使任意装卸交接与 Raman 串行；支持的重叠是稳定 SLM Raman + AOD_MOVE。一个 AOD、一个 Raman 通道，所有占用原子/站点也参与冲突检查。
- 保留一个 active_plan 作为原子程序的事务封装；其内部已经有真实并发，旧串行 cursor 仅用于兼容观察端。M3 策略每次只加入一个额外 Raman，program 运行中不注入新候选；M4 可返修更细的决策边界与候选接口。

schema 13 保存原始时间/指标/DAG、全部在途操作、已完成操作、资源和完整待发生事件。恢复独立审核未来计划并重建已提交前缀；缺失/重复/改时长/错资源/未来轨迹损坏均拒绝。旧 schema 1–12 明确拒绝，从原输入重编译；旧 viewer 记录仍保留其历史时间。

## 可视化与工作台

沿用初始条件 → 可编辑线路 → 真实编译/校验 → Executor → VisualRecorder → viewer。初始条件区增加 resident / returning / legacy 选择；无 compiler 字段的旧导入保留 legacy 行为，新的默认草稿选 resident。anchor_order 只用于 legacy，M3 按持久状态确定锚点。原子数/layout、随机载入、导入导出、取消、草稿版本隔离保持。

同一帧显示全部实际活动原子：Raman 原子保持 SLM，运输原子沿同一运动段继续。关键帧模式用全局分段时间映射，不能把两条并行轨迹拼成串行动画；物理比例模式和最高 32× 都只改变显示时间。类别时序与 AOD/Raman/CZ 资源时序共用真实横轴；资源 busy 为区间并集，跨类别百分比可超过 100%。执行中 metrics 只累计已结束操作，观察端 summary 可显示已经发生的部分区间，最终口径一致。旧无 OperationInterval 的 legacy 记录按整计划预约汇总资源区间，不等同于激光实际脉冲忙时。

原子列表每页 32、操作每页 12；大世界仍画出全部原子并可搜索、缩放和逐原子查看。256 原子证据是在完整世界中真实执行 8 门、97 operations、212 commits，包含旁观原子的路径/作用区校验；它不表示 256 个原子都参加运输，也不是浏览器 FPS 或大规模稠密电路性能证明。

## 实际结果

| 相同 6 原子、8 门、完整归还 | resident | returning |
| --- | ---: | ---: |
| 总完成时间 / μs | 4577.884560 | 4902.918266 |
| 逻辑完成时间 / μs | 3258.305552 | 4292.760535 |
| LOAD / OFFLOAD | 11 / 11 | 12 / 12 |
| AOD 总距离 / μm | 1187.842280 | 1248.859133 |
| Raman / 重叠时间 / μs | 4 / 4 | 4 / 4 |

256 原子总完成时间 11981.276814 μs，逻辑完成 8758.725737 μs，10 LOAD / 10 OFFLOAD，4 μs Raman 全部与运输重叠。编译墙钟、文件大小、专项/回归以及浏览器验收结果见本轮日志；这些宿主指标不计入模拟时间。

## M4 必须回访

1. 将当前 gate-ID 顺序和“有 Raman 则先归还 loaded 原子”的规则改为可比较 policy；保留会节省搬运，也可能占据 EZ。
2. 明确目标区域/候选集合与 exact TaskTarget 的接口、驻留和退出的成本估计、编译候选数和预算；避免 compiler 内藏全局决策。
3. 评估 program 内进一步决策、多个 Raman 窗口和候选失效范围；保留操作级资源/holder 真值、确定性提交和恢复验证。
4. 在同 circuit/platform/初态/终态下比较 greedy、critical-path、有限 lookahead；首先优化完整程序 wall time，单列逻辑完成和运输成本。

本次浏览器工具连接失败，备用 Windows 工具因无法可靠判定当前 URL 中止；未继续浏览器操作，未声称真实浏览器视觉 PASS。离线 DOM/Canvas 控制检查与物理执行验证分别记录。


M4 首版在双 EZ 驻留 + SZ 置换实验中修正了 PersistentTargetCompiler 的终态临时停车范围：允许使用尚空闲的后续目标站点，全部动作显式计时和验证。M3 物理能力/schema 不变；最小反例、32 原子及完整回归证据见 [M4 日志](../instruction/logs/2026-09-11-m4-greedy.md)。
