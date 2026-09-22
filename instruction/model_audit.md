# 模型审计与待处理问题

2026-09-22 发布审查（物理模型不变）：

| ID | 状态 | 范围与证据 |
|---|---|---|
| IR-001 | FIXED | IDS 的合法部分前沿被新 IR 完整性检查当作整个服务错误，导致控制器未尝试较小请求。`zoned/controller.py` 内置适配器延后精确前缀候选，按原宽度回退重新建立完整 Move/Apply；不改变独立 IR 验证或环境。回归 `test_controller_retries_smaller_intent_for_partial_placement` 验证单门真实执行、余门 READY 与独立重放；[发布日志](logs/2026-09-22-repository-release.md) |
| CONSTRAINT-001 | OPEN | 目标/抓取/路径/整计划/runtime 判据调用与错误分类尚未统一；EZ 预约仍从环境扫描下一 CZ 推导。审计与分层方案见 [constraint/placement](../docs/constraint_placement_audit.md)，尚未实施重构或性能验收 |

2026-09-21 分层编译器适配（物理模型不变）：

| ID | 状态 | 范围与证据 |
| --- | --- | --- |
| ARCH-003 | FIXED（新通用入口） | 新增独立 `strategies/zoned` 的调度、驻留、落点、分组、物理展开及控制层；抽出共享 motion 工具，原 Studio/初态搜索接通。旧策略保留作对照，198 模块依赖检查通过；见[实现](../docs/zoned_compiler.md)与[本轮日志](logs/2026-09-21-zoned-compiler-refactor.md) |
| ZONED-001 | FIXED | 搜索中未完成矩形被过早按完整捕获闭包拒绝；部分组合可补全，最终执行仍严格检查。16 原子四轮均 8 对真实 CZ，独立重放通过；`tests/test_zoned_compiler.py` |
| ZONED-002 | FIXED（新控制器） | EZ 边缘读出因闲置 AOD 轴单侧填充越界而候选全空；读出策略增加显式 bounded_spares 选项，新控制器开启；保留旧调用默认。回归及完整 480 槽 QEC/量子态/独立重放通过 |
| ZONED-003 | OPEN | 启发式落点评分与完整路线代价存在偏差，多轮 syndrome 分组碎片化；QEC 同输入同终态从 17→81 个 CZ 脉冲、23472.44→83766.54 μs，性能验收未通过。负例、耗时与复现命令见上述日志；原 QEC demo 保持原策略，不关闭校验规避退化 |

2026-09-14工程边界更新（物理模型不变）：

| ID | 状态 | 范围与证据 |
| --- | --- | --- |
| ARCH-001 | FIXED | 环境混入算法/应用/实验：迁移到独立strategies/app/experiments，生产策略经NeutralAtomEnv操作；依赖审计与六策略完整checkpoint逐字一致，见[日志](logs/2026-09-14-environment-strategy-separation.md) |
| TEST-001 | FIXED | 旧M0集成fixture违反后加EZ四邻保护；迁移前同样失败，仅修正fixture为合法10μm布局，保留硬约束；证据与重验见上述日志 |
| ARCH-002 | OPEN | 旧编译器仍经env.state读取完整冻结状态；Observation已排除量子态/RNG/trace，但完整PlanningView与RL信息隔离尚未实施，见[合同](../docs/environment_strategy_boundary.md) |

审计日期：2026-09-10。此页是“已实现”和“应当实现”的分界，不是新的物理功能。2026-09-10 M2 更新：BUG-001/002、EXT-001、EXT-002 的物理别名问题与 META-001 已修复；能力限制继续保留。复现步骤与原始输出见 [审计日志](logs/2026-09-10-audit.md)。

## 简化、限制、错误

| ID | 分类 | 判定与后续动作 |
| --- | --- | --- |
| A-001 | 有条件简化 | rigid 恒速直线段 + 固定装卸时长、row_column 三次运动学可以用于同模型的时间成本基准；不预测加热/最短实验波形 |
| A-002 | 有条件简化 | 硬距离阈值 + 全区 pair 检查用于确定性资格判断；不保证真实 gate fidelity 或旁观原子无相位误差 |
| A-003 | 有条件简化 | 唯一 holder 是粗粒度承载状态；不表示装卸期间绝无重叠势 |
| A-004 | FIXED（M3-A 串行） | `hardware/dynamic_traps.py` 全活动交点 sweep/enable；rigid 和 row_column 空阱中途碰撞负例通过，见 [本轮日志](logs/2026-09-10-m3-dynamic-traps.md)。光斑/RF/波包仍不在范围内 |
| L-001 | 当前能力限制（已扩展） | M2 支持多个预置 EZ 伙伴、空载寻找静态源与相对作用 pose；仍为有限可替换通道规划；另有 row_column 同捕获行/列配对、rigid 联合停车及 single_trap 全 SZ 准备；单 trap 持久起态已由 M3 支持；任意布局完备路由仍不承诺 |
| L-002 | 动态 LOAD 已修正，旧 planner 查询仍保守 | `rigid_aod.capture_closure(active_only=True)` 与 `dynamic_traps.begin_transfer` 按实际活动列捕获；间隙远处原子不再误报，活动 trap 近距与 sweep 保持。`tests/test_multi_trap.py` 覆盖间隙接受/近距拒绝，物理专项 67 passed；[证据](logs/2026-09-11-multi-trap.md)。默认 footprint 查询保留用于旧 planner，不等于连续矩形吸附模型 |
| L-003 | 当前能力限制 | legacy 路径保留整计划串行；M3 scheduled program 已支持最小 SLM 1Q/运输重叠与逐操作资源释放；多 AOD 仍未实现 |
| U-001 | 未标定参数 | 2 μm 作用距离、1 μm clearance、数值对齐容差不来自本设备标定；不擅自换成论文参数 |
| BUG-001 | FIXED | 普通 Executor 拒绝 GATE 注入；显式 LogicalTestExecutor 保留逻辑测试 |
| BUG-002 | FIXED | 恢复与执行检查 plan/cursor/reservations/queue/trace/placement/DAG |
| BUG-003 | FIXED（M4 独立 1Q 并行） | 旧 RAMAN_0 / HANDOFF_GUARD 及单门填充循环错误串行化不同 qubit；改逐 qubit 资源与连续可用窗口，4 门 1 μs、两层 8 门 2 μs、短 CZ/1Q 同时开始、同原子冲突拒绝/全部边界恢复；`tests/test_parallel_orthogonal.py`，323 项完整回归与真实浏览器四脉冲/四资源行；[证据](logs/2026-09-11-m4-parallel-orthogonal.md) |
| EXT-001 | FIXED | 新增 episode wall、逻辑完成、last pulse、last cycle、plan count 与每计划 trace duration |
| EXT-002 | FIXED（限制执行类型） | 物理门集现为 CZ + 稳定 SLM 的 U3/别名；CPHASE/MEASURE 等仍拒绝，见 GAP-004 与工作台日志 |
| META-001 | FIXED | M0/M1/M2 factory 按真实位置派生 grid（包括负 y）；position 仍是几何真值 |

## BUG-001

**状态：FIXED。** 修复文件：`simulation/executor.py`、`testing/logical_executor.py`；负例 `test_physical_executor_rejects_public_logical_shortcuts` 覆盖 schedule 和预注入队列 step；M1 保持既有结果。以下是原始复现背景，当前证据见 [M2 日志](logs/2026-09-10-milestone2.md)。

位置：[Executor.step](../src/neutral_atom_env/simulation/executor.py)。没有 active_plan 时，`GATE_RESERVED/STARTED/COMPLETED` 兼容路径只做 DAG 与区域校验；不检查作用对、硬件 pulse 时长和物理资源。

复现：将 Q000/Q001 放在 EZ 内相距 5 μm 的两个静态 trap，对同一 gate 在 t=0 依次排入三个 GATE 事件。现有代码完成了门，仿真时间和 laser busy 都是 0。这不是“硬半径模型”的合理简化，而是绕过该模型。

修复方向：将纯逻辑演示与物理执行入口明确分离；普通物理调度拒绝直接注入 gate transition，或统一转为经硬件验证的操作。不能把几何规则塞进 DAG。验收要求：上述复现被拒绝且不部分提交；`Executor.submit(plan)` 的合法 M1 仍通过；纯 DAG reducer 测试保留。

## BUG-002

**状态：FIXED。** 修复文件：`simulation/runtime_validation.py`、`simulation/executor.py`、`replay/checkpoint.py`；`test_corrupt_active_boundaries_rejected` 覆盖全部 M2 活动边界的 12 类损坏，`test_empty_queue_active_runtime_cannot_silently_finish` 重现缺失 LOAD completion。以下是原始背景；证据见 [M2 日志](logs/2026-09-10-milestone2.md)。

位置：[checkpoint.restore](../src/neutral_atom_env/replay/checkpoint.py)、[SimulationState](../src/neutral_atom_env/simulation/state.py)。当前验证字段、trace、DAG 与可序列化性，但未完整验证 active plan/cursor/reservations/pending completion 的关系。

复现：执行 PLAN_STARTED 和 LOAD_STARTED 后，删除 checkpoint 的 pending completion，保留其他字段。restore 成功，`Executor.run()` 因队列为空直接返回，但 active_plan 存在，DAG 未完成。

修复方向：定义每种 runtime 阶段允许的 pending event、游标、时长和 reservation 集；拒绝缺失/重复/错属事件。验收包含所有合法边界恢复和对应损坏变体；不允许恢复时静默补造完成结果或释放资源。

## EXT-001：指标在多个周期中的含义

**状态：FIXED。** `simulation/state.py`、`domain/operations.py`、`physical_executor.py` 实现 schema 5 的明确指标口径，见 [motion_execution](motion_execution.md#6-m2-指标契约schema-5)；`test_independent_multicycle_expectations` 与非零起点测试验证。以下保留原始审计背景。

重复执行两次当前可行的相同 CZ，得到：`simulation_time_us=624.6`、`circuit_makespan_us=468.6`、`cycle_makespan_us=312.3`、`aod_busy_time_us=624.6`。原子/AOD 路程与计数已累加，但 cycle 字段在每个 PLAN_COMPLETED 覆盖。

M2 应区分 episode 起点到最后逻辑完成、包含尾部归还的总 wall time、最后周期时长、每个 plan 的时长。若决定改名或改变累积语义，要同步 schema/报告，不能让不同口径都叫 makespan。重复同一可行 pair 的实验不证明已支持连续换伙伴电路。

## EXT-002 与 META-001

**状态：FIXED。** `motion/compiler.py` 拒绝非 CZ 物理执行；`milestone1_factory.py`、`milestone2_factory.py`、`world/config.py` 修正真实 grid。验证：`test_parameterized_gate_is_rejected_without_aliasing_cz`、`test_grid_metadata_matches_factory_world_coordinates`。以下是修复前的问题记录：

- `PhysicalGate` 无 θ，`MotionCompiler` 将 CPHASE 用同一个 CZ pulse 标签处理。当前只做结构调度可保留名称级支持；接入参数化物理电路时必须修正，否则会把不同门混同。
- `milestone1_factory.py` 使用 `GridCoord(i,0)` 给实际 `(5,-25)` 等位置编号。当前校验/渲染用 `position`，所以图与运输不受影响；未来代码若使用 grid 推导实际坐标会出错。应派生真实 grid 或将该字段定义为不同类型的非几何标签。

## 已排除的错误方向

- 不放大作用半径解决刚性配对困难。
- 不让 gate/measure 完成事件搬动原子。
- 不让 measurement 在其他区合法。
- 不只检查 requested 原子或运动段端点。
- 不把“两个目标均在 storage 被当前 compiler 拒绝”写成物理不可能。
- 不把未模拟温度/波函数本身列为必须在 M1 补齐的 bug。

每项关闭时，在这里保留 ID 并改为 FIXED + 日志链接；不要删除历史问题，使下一位 agent 无法判断为什么接口改变。

## 2026-09-10 新契约缺口（M3-A 实现后更新）

以下按 [目标契约](compiler_contract.md) 与 [物理规则](physics.md) 审核。既有 FIXED 仅对应原问题，不能扩展成新能力已经完成。

| ID | 缺口与风险 | 关闭所需证据 |
| --- | --- | --- |
| GAP-001 | FIXED：动态 masks、容量/活动数分离、开关和交接恢复 | 修复 `domain/operations.py`、`world/world.py`、`simulation/state.py`、checkpoint/codec；`test_dynamic_traps.py` 的 masks/交接损坏、全部边界恢复及独立开关测试；[日志](logs/2026-09-10-m3-dynamic-traps.md) |
| GAP-002 | FIXED（串行）：活动空阱扫掠、全新交点和共享轴关闭影响已检查 | 修复 `hardware/dynamic_traps.py`、`rigid_aod.py`、`partial_transfer.py`、`physical_executor.py`；M3-A 专项 16 passed，标准十二 CZ、Node 及真实浏览器核对关灯定位/支撑提交；[日志](logs/2026-09-10-m3-dynamic-traps.md) |
| GAP-003 | FIXED（M3 声明单 trap 范围）：独立任务、KEEP 续接/退出、RETURN_ONLY、新站点与终态置换 | motion/persistent.py、tasks.py、task_validation.py；tests/test_m3.py 的持久复用/换伙伴/归还/置换与恢复，test_task_ir.py 的零门 DAG/唯一效果；[证据](logs/2026-09-11-m3-completion.md) |
| GAP-004 | FIXED（串行）：U3/别名参数、RAMAN_ROTATION、稳定 SLM 资格、独立 Raman 资源/计时和门效果 | 修复 domain/models.py、hardware/raman.py、motion/program.py、physical_executor.py、runtime_validation.py；test_raman.py 的混合执行、独立矩阵预期、原子性和全部 1Q 边界恢复，Node/浏览器真实脉冲；[日志](logs/2026-09-10-circuit-workbench.md)。并行仍属 GAP-005 |
| GAP-005 | FIXED（M3 最小并行，M4 已扩展）：SLM Raman 与 AOD_MOVE 重叠，操作结束即释放资源 | motion/scheduled.py、simulation/operation_program.py、runtime_validation.py；test_m3.py 的真重叠、同时间顺序、冲突原子性、所有边界恢复/未来损坏/hashseed；M3 当时的交接/Raman 保守串行现已由 BUG-003 修正为不同原子可重叠，多 AOD 未实现；[原证据](logs/2026-09-11-m3-completion.md) |
| GAP-006 | FIXED（正常验证/搜索失败）：有限候选与决策预算、stalled 非成功退出、保留原输入/状态/诊断 | simulation/m3.py、examples/run_m3.py、workbench_server.py；test_m3.py 的预算出口/无效终态/恢复续接，CLI 失败目录及退出码；操作系统杀进程/超时不承诺最终 checkpoint；[证据](logs/2026-09-11-m3-completion.md) |
| GAP-007 | FIXED：两个实质不同构造，共用 backend/validator/Executor/viewer | motion/persistent.py 的 ResidentCompiler 与 ReturningCompiler；test_m3.py 验证同输入/同终态及不同装卸数，6 原子 8 门对照由 verify_m3.py 独立重放；[证据](logs/2026-09-11-m3-completion.md) |
| GAP-008 | FIXED（声明平台族）：10 μm SZ/分离 EZ/半格通道/足够空位 | motion/family.py 识别几何和容量，[构造与归纳说明](../docs/milestone3.md)，test_m3.py 覆盖 row/grid/shuffled、多伙伴、持久终态与族外参数拒绝；不证明任意 loaded 坐标或障碍布局完备；[证据](logs/2026-09-11-m3-completion.md) |
| GAP-009 | FIXED（记录/资源统计/离线交互）：真实并行活动集合、统一回放映射、资源并集和 256 原子分页 | visualization/recording.py、summary.py、viewer.js；tests/m3_controls.cjs、viewer_speeds.cjs 和 256 原子物理复验；本轮浏览器工具中止，真实浏览器视觉复验单独待恢复；[证据](logs/2026-09-11-m3-completion.md) |

旧 single-trap 和 rigid-parking 产物仅证明当时模型；本轮 standard single_trap 已重新验收，旧四原子六门 rigid-parking 只能完成前四个合法门，两个对角门按共享轴安全规则拒绝。失败搜索不证明物理无解；不要求通过实现低层动力学关闭这些缺口。施工顺序见 [milestones](milestones.md)。

## M4 返修点（2026-09-11 用户确认）

上述 FIXED 只关闭声明 M3 范围的实现缺口。M4 详细设计时返修候选/成本接口、驻留/退出策略和时间窗口决策；不把当前 gate-ID 顺序、单额外 Raman 或 program 事务边界固化为最终优化架构。保持相同物理约束与完整终态对照，见 [M3 后续清单](../docs/milestone3.md)。
