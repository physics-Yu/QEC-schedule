# 意图编译、物理执行与指标

2026-09-12 测量扩展优先：schema19 新增 `MEASUREMENT` / `RESET` 同类批量效果、量子态、测量结果和可恢复 RNG。ProgramBuilder 只纯推演，scheduled audit 与 Executor 使用同一确定性投影规则并独立重放，真实结果仅由 Executor 提交。QEC runner 将读出原子显式运到 MZ 后测量/复位并返回，全部步骤计时。条件 X/Z 不满足时计控制时隙，不算 Raman 光照。详见[核心合同](../docs/quantum_readout_core.md)、[工作台](../docs/qec_workbench.md)。

2026-09-12：当前schema18，真实并行CZ采用单pulse多`gate_ids`，所有效果同刻原子化提交，资源忙时按一段pulse计，门数逐门计；完整集合与恢复校验见[batch合同](../docs/batch_cz_contract.md)。rigid现接受固定非均匀矩形axes。下文单效果/schema17等范围描述属于历史底座。

2026-09-11 补充：Raman 目标可在静止 AOD 上，脉冲期间锁 AOD_0；SLM 与 AOD 上同类型门可并行。目标与任意其他存活原子必须 ≥5 μm，移动邻居按实际重叠时间区间校验。详见 [AOD Raman](../docs/aod_raman.md)，本页历史稳定 SLM 范围不再限制当前目标资格。

**当前门规则（2026-09-11 最新）**：仅 H/X/Y/Z/T/CZ 可执行；仅同类型门可并行，异类型门（含 CZ/1Q）不得重叠。内部 U 参数仅记录固定门效果。checkpoint schema 17，拒绝旧 1–16；旧输入不自动转换。详见 [门规范](../docs/gate_contract.md)。本页旧门集和任意类型并行描述以该规范为准。

用途：修改 motion/simulation 或推进 M3 时读取。下列 M1/M2/当前单 trap 是串行实现说明；操作级任务与并发目标见文末及 [compiler_contract](compiler_contract.md)。先遵循 [物理契约](physics.md)，路线接口与复杂性先看 [motion_planning](motion_planning.md)。

当前 schema 为 **17**：支持动态 masks、独立任务、逐操作资源和 scheduled 并发运行时，并改为逐 qubit Raman 资源；拒绝旧 1–16。`RAMAN_ROTATION` 保存原参数与规范 U 效果，固定 1 μs，经统一 validator 和 Executor 开始/完成；不同 qubit 的稳定 SLM 同类型 1Q 可直接并行，也可与不相关原子的交接/移动重叠；异类型门（含 CZ/1Q）作用区间互斥。legacy 串行路径保留；下列 M1/M2 时序是历史实现说明。M4 greedy 在相同 IR 上选择双向 EZ 候选并按每原子连续窗口填充 Raman，见 [M4 API/边界](../docs/milestone4_greedy.md)。动态支撑历史见 [M3-A](../docs/dynamic_traps.md)。以下恒速/固定偏移数字针对 rigid 基准；row_column 的计时与几何见 [AOD 后端](aod_backends.md)。`get_backend(state.hardware)` 供编译器、执行器和 runtime 统一选择；计划不能跨 backend 直接复用。

## 1. M1/M2 编译契约

入口：[MotionCompiler.compile](../src/neutral_atom_env/motion/compiler.py)。

```text
输入：ExecuteGateBatchIntent({gate_id}, RETURN_AND_OFFLOAD), current state
要求：一个 READY CZ；无活动 plan/预约/待处理事件/已装载原子
      恰有一个目标为预置静态 EZ 伙伴，另一目标在区外静态 trap
输出：不可变 CompiledPlan；失败则结构化 ValidationError，原状态不变
```

优先保留能覆盖源原子的当前 footprint；否则将空 AOD 的 cell(0,0) 移至源位置。完整 capture closure 后装载，作用 pose = 静态伙伴位置 + `hardware.interaction_offset` − 移动目标 cell 的固定偏移。默认 interaction_offset=(-2,0) μm，与作用半径分开配置；缩小半径仍会拒绝既有 2 μm 配对，不自适应放宽。

默认可替换 planner 优先横移半格、沿纵向通道运输、对齐作用配置、pulse、逆路线回源卸载；必要时尝试左侧或横向连接通道；若先前有空载定位，再空载返回该 plan 起始 AOD pose。所有段都进入 operations 和计时，空载只增加 AOD 路程。每段用 backend 完整扫掠检查，pulse 检查全 EZ pair；附带原子始终参与。

当前仅枚举有限通道候选，不承诺完备搜索，不把两个 storage 目标隐式布置为伙伴。边界/障碍/额外 pair/捕获不对齐会拒绝；有限路径失败不证明物理全局无解。参数化门和 MEASURE 物理调度返回 UNSUPPORTED_GATE。支持的初始布局与独立算式见 [M2 案例](../docs/milestone2.md)。

## 2. 计划与精确验证

`CompiledPlan` 保存 `state_version`、全快照 `state_fingerprint`、intent、bindings、requested/incidental 集、operations、resources、预计时长/路程与 predicted_placement。

`captured_atom_ids` 从 bindings 派生。绑定中的 `static_trap_id` 表示该次装载来源及 M1 回程目标，不是永久 home。plan 在执行中不可修改。

`exact_validate` 在入队前校验最新状态，并独立推演实际 operations，验证资源、装卸、路线、时间和最终状态；不重新编译默认路线。不同合法 planner 的结果可被接受。当前 PLAN_STARTED 处理时会恢复入队前的空队列视图做 fingerprint 校验；该设计依赖单 start event，不可未经改造用于并发提交。

## 3. 事件状态机

```text
submit(plan)
  -> PLAN_STARTED：门 RESERVED，建立资源预约
  -> OPERATION_STARTED：验证；设置移动或门 RUNNING；排入 completion
  -> OPERATION_COMPLETED：重新验证；提交 holder/pose/DAG/指标
  -> 下一 OPERATION_STARTED
  -> PLAN_COMPLETED：核对最终 placement，释放预约
```

M1 成功基准有 9 个 operation，20 个已提交事件：1 plan start + 9×2 + 1 plan complete。LOAD/OFFLOAD 在开始事件建立目标支撑、保存 transfer，在完成事件同时改变 holder 和撤去源支撑；MOVE 结束提交 pose；PULSE 开始 RUNNING、结束 COMPLETED 并释放 successors。

同时间事件用队列插入序号稳定排序。状态与 trace 版本只在成功提交时增加。校验失败不能消费该事件或安装部分字段；真正的“硬件操作失败后的恢复策略”仍未实现，不能把验证抛错当成原子损失事件。

## 4. 基准的独立时间核算

几何与参数详见 [M1 案例说明](../docs/milestone1.md)。初始 Q000=(0,0)，静态伙伴 Q001=(5,-25)。

| 操作 | 终点/效果 | 时长 μs | 累计时间 μs |
| --- | --- | ---: | ---: |
| LOAD | Q000 改由 AOD 承载 | 100 | 100 |
| Depart | (2.5,0) | 5 | 105 |
| Corridor | (2.5,-25) | 50 | 155 |
| Align | (3,-25) | 1 | 156 |
| Pulse | Q000/Q001，2 μm | 0.3 | 156.3 |
| Return 1 | (2.5,-25) | 1 | 157.3 |
| Return 2 | (2.5,0) | 50 | 207.3 |
| Return 3 | (0,0) | 5 | 212.3 |
| OFFLOAD | 回到本次来源 trap | 100 | 312.3 |

单程长度 `2.5+25+0.5=28 μm`，往返 56 μm；按 0.5 μm/μs 计移动共 112 μs。附带原子同载时 AOD 路程不变，原子总路程乘运输原子数量。

## 5. 资源与持续位置

当前 plan 整体独占 `AOD_0`、`ENTANGLING_LASER_0`、作用 slot、相关原子与回程 trap。预约作用是阻止冲突计划，不代表激光在整个运输期间开启。

相邻几何 slot 是规划离散化，不是天然的物理设备：不同 slot 名称不能保证互不串扰。未来资源模型需要时间窗口和实际 footprint/光束覆盖检查，不能只比较字符串 ID。

M1 在移动中只有 observer 插值，实时 pose 仍是该段起点；整个 plan 不允许外部插入物理操作，因此不在中途用陈旧 pose 处理另一个计划。开放并发或任意时刻事件前，必须统一可查询的 trajectory(position,time) 与时空验证。

## 6. M2 指标契约（schema 5）

| 字段 | 定义 |
| --- | --- |
| `simulation_time_us` | 绝对事件时间 |
| `episode_start_us` | 首次 PLAN_STARTED 的绝对时间；尚未开始为 null |
| `episode_wall_time_us` | 当前时间减 episode_start；包含尾部返回、卸载和空载归还；初始等待不计 |
| `last_pulse_time_us` / `circuit_makespan_us` | 最近物理 pulse 完成的绝对时间；后者为兼容字段，不是累计周期时间 |
| `last_pulse_elapsed_us` | 最近 pulse 相对 episode_start 的耗时；尚未 pulse 为 0 |
| `logical_completion_elapsed_us` | 整个 DAG 完成时的逻辑耗时；电路尚未完成为 null |
| `last_cycle_duration_us` / `cycle_makespan_us` | 最后一个已完成 plan 的时长；后者为兼容字段，不累计 |
| `completed_plan_count` | PLAN_COMPLETED 次数，必须完成尾部清理 |
| trace `plan_duration_us` | 每条 PLAN_COMPLETED 记录本 plan 的实际时长及 gate_id |
| `total_aod_distance_um` | 全部实际 MOVE 长度，包括空载 |
| `total_atom_distance_um` | 每段长度 × 该段实际已装载原子数；空载为 0 |
| load/offload count | 完成的装载/卸载次数 |
| captured/incidental totals | 各次装载原子数量累加，不是去重人数 |
| `aod_busy_time_us` | 所有已完成 operation 的时长，包含 pulse 和空载 |
| `laser_busy_time_us` | 已完成 pulse 的时长 |
| `aod_utilization` / `laser_utilization` | 相应已完成 busy time / episode_wall_time；零窗口为 0 |
| `throughput_gates_per_us` | 已完成门数 / episode_wall_time；零窗口为 0 |

legacy 保留串行执行；M3 scheduled program 支持一条 AOD 与一条 Raman 资源，区间互斥校验保证各自无重复占用，观察汇总按资源并集计时。跨资源合计可以大于 wall time。运行中指标不包含尚未完成 operation 的部分耗时/路程；最终窗口可用于本模型内的基线比较。

schema 5 将绝对 `interaction_pose` 配置改为相对 `interaction_offset`，加入 episode_start 和 plan count。旧 schema 1–4 显式拒绝，必须重建；不把旧快照静默解释为新语义。

## 7. 连续 eager 调度

`simulation.scheduler.EagerScheduler.step()` 先检查 committed runtime，再推进一个已有事件；无事件且 DAG/清理完成则返回 completed，否则 `EagerBaseline.compile_first` 按稳定 gate ID 顺序检查整个 READY frontier，选首个可编译计划，经 Executor.submit/step 执行。`run()` 循环至 completed/stalled；可传 on_event 只读观察回调保存每次事件后的 snapshot。

后继在 pulse 完成时 READY，但必须等整个当前 plan 结束才提交下一计划。无需 scheduler 私有恢复数据：checkpoint 恢复后重新实例化 EagerScheduler 即可继续。

无候选返回 `ScheduleResult('stalled', diagnostics)`：包含 holders、各 gate 状态、候选失败原因、队列数量与有限搜索说明。backend 不支持返回具体错误码；损坏 runtime 抛 ValidationError，不当作路由 deadlock，更不静默成功。`Executor.run()` 仍仅清已有队列。

## 8. 物理入口与恢复校验

BUG-001 已修复：普通 Executor.schedule/step 拒绝 GATE_* 注入；测试侧 `LogicalTestExecutor` 保留 M0 纯逻辑/区域演示，并拒绝 submit(plan)。物理调用必须使用 Executor.submit(plan)。

BUG-002 已修复：`runtime_validation.validate_runtime` 在 restore、step 前、下一状态提交前和 run 入口检查 plan/trace、cursor、start/completion 时间、预约、唯一下一事件、placement/pose、移动标志、pulse/DAG 状态。允许 pending PLAN_STARTED、每个 operation 前/中/后、待 PLAN_COMPLETED 和空闲边界；不静默补造事件或释放资源。backend/compiler 的临时推演状态不调用该 committed-boundary 检查。

证据与限制见 [本轮日志](logs/2026-09-10-milestone2.md) 与 [审计问题表](model_audit.md)。

集成说明：路线契约最初升级到 schema 7；rigid 部分交接随后新增 transfer_bindings 等字段并升级 schema 8。两项工作已完成集成与完整回归，证据见 [交接日志](logs/2026-09-10-rigid-pair-parking.md)。legacy 策略仍用 RETURN_AND_OFFLOAD；通用 Program 已验证 KEEP_LOADED 终态执行/恢复，尚无通用跨计划 KEEP 选择和退出。


## rigid 联合运输与局部交接

硬件显式开启 `selective_transfer_enabled` 且两目标都在 SZ 时，编译器可选择 `rigid_parking_compiler.py`：完整 LOAD → EZ 共同运输 → PARK → 局部靠近 → PULSE → 恢复构型 → RECAPTURE → 共同返回 → 完整 OFFLOAD。仍为一个门的 RETURN_AND_OFFLOAD 计划，绝不靠改写 holder 制作动画。

`Operation.transfer_bindings` 对局部操作声明 atom/cell/SLM trap；`plan.bindings` 保留共同运输来源。PARK/RECAPTURE 完成事件分别计 offload/load，时长复用对应硬件参数。两步无逻辑 gate 状态副作用。runtime 逐操作推导部分 holder；独立 validator 检查恢复构型、完整返回及 EZ trap 预约。完整规则见 [rigid parking](../docs/rigid_pair_parking.md)。


## 可替换单 trap 编译策略

`simulation.pipeline` 提供独立 circuit/platform/placement 输入，`planning.compilers.GateCompiler` 为编译插件协议。`motion.single_trap.SingleTrapCompiler` 使用一个活动 AOD trap，先运 a 到 EZ SLM，再运 b 做 CZ，依次送回；不使用选择性部分交接能力。新 `motion.program` 审核逐操作 bindings，不要求固定装卸次数和 EZ 驻留模板。initial_placement 与 predicted_placement 分离，runtime 从前者推导 holder；同一程序接口已验证 KEEP_LOADED 终态，但当前策略不自动生成跨门驻留或清理动作。详见 [管线契约](../docs/circuit_pipeline.md)。

## M3 操作执行目标（M3-A 已完成，其余待实现）

以 [目标契约](compiler_contract.md) 和 [physics](physics.md) 为准：程序可由准备、移动、开关、交接、1Q/CZ、清理等独立任务组成。没有 pulse 的任务不预约/完成一个虚构 gate；同一 CZ 的准备与归还可以分开，只有真实 pulse 完成提交 gate 效果。

M3-A 已使动态 masks 和 transfer 阶段进入操作、预测、精确验证、实时状态、checkpoint 与 trace；SLM 格点对齐交接先建立目标支撑，结束切换 holder，不能因部分关闭一条 AOD 轴令其他原子失去支撑。启用时检查全部新交点；活动空 AOD 的整段扫掠必须验证。转移预设时长包含稳定余量，计时不另加一份稳定操作。

一个全局时钟分别记录逻辑完成、每资源释放、含终止条件的程序完成。操作按资源区间和持续占位预约，SLM 1Q 可与他原子运输重叠；目标原子未卸载完成则不可 1Q。原子承载/SLM 占位不会在两个操作之间自动释放。并发区间与碰撞依赖真实 trajectory(t)，不依赖只在 MOVE 末更新的旧 pose。

第 3/8 节的单 plan、唯一下一事件、全局 fingerprint 是现有串行约束，须一起扩展为可验证的并发运行时，保留失败原子性。相同时间完成先于受其释放条件约束的开始；冲突写入不允许靠队列顺序任意通过。提交需基于最新状态合并合法效果，不能覆盖其他已提交工作。选中计划非法应终止并报告，而不是执行半段后假装成功。

第 6 节指标名称和数字是 M2 历史兼容口径。新增并发统计按资源占用区间并集计时，区分 Raman、运输、交接、CZ 及持续占位；跨资源时间可重叠，不相加为 wall。程序总时间从统一 episode 起点计入必要初始准备/等待及尾部终止条件，逻辑完成单列。不得未经 schema/报告迁移把旧 aod_busy 字段解释成新的并发定义。

2026-09-14 新增独立只读 `statistics.AtomStatistics`：消费完整已提交 trace，按原子统计路程、LOAD/RECAPTURE、OFFLOAD/PARK、实际各类门次数与等待时间。等待=运行 elapsed 减该原子实际移动/交接/已触发效果区间并集；支撑保持、资源预约和未触发控制槽不等于忙碌。批量 CZ 两个原子各计一次，装卸为原子次，不覆盖旧批次指标。支持增量观察、checkpoint 完整历史重建及独立 JSON/CSV；不修改 Atom/Executor/checkpoint。详细口径、部分执行及导出见 [统计合同](../docs/atom_statistics.md)。

## M3 scheduled program（schema 13）

完整实现见 [M3 API](../docs/milestone3.md)：operation_program.audit 审核整个候选；transition 按最新状态纯归约，Executor 独占提交。running_operations/completed_operation_ids 保存并发进度，预约随各操作释放；同时间完成优先、再按 op ID 开始，恢复检查完整事件后缀。Raman 固定 1 μs，稳定 SLM 可与另一个原子的 MOVE 重叠；2026-09-11 M4 已取消全局 HANDOFF_GUARD/RAMAN_0，独立 qubit 的稳定 SLM 同类型旋转可直接并行并与他原子的交接/运输重叠；目标 atom/trap 资源保护同原子冲突。当前 schema 17，Raman busy time 取时间并集。
