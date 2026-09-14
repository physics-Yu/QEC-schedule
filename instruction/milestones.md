# Milestone 路线与下一步验收

保持 M0→M6 顺序；2026-09-10 按用户确认更新 M3 的调度接口与物理前置条件。M0–M2 完成记录保留其当时范围，不代表满足新增动态光阱规则。研究边界与接口以 [目标契约](compiler_contract.md) 为准；标记“基础已验证”不等于消除了 [审计问题](model_audit.md)。

| 阶段 | 原目标 | 当前状态 |
| --- | --- | --- |
| M0 | 架构骨架：domain/state/circuit/DAG/SLM/placement/queue/trace | 基础已验证；统一 Q 编号和可视化已落地 |
| M1 | 单 2Q gate、单 AOD、单刚性 footprint、单作用位、往返 | 受限 mobile–static 基准已实现；伙伴预置限制公开记录；两个 API/恢复缺口已修复 |
| M2 | 连续 circuit、多个 gate、成功后释放 successor、连续多个 plan，仍 eager return | 已完成声明的 mobile–static 电路族：连续调度、多周期、换伙伴/换源、恢复、诊断及报告 |
| M3 | 持久 placement、独立任务、动态光阱、参数化 1Q 与最小操作级并行 | M3-A–F 已在声明的单 trap 平台族实现；schema 13、两种构造、1Q/运输并行与 256 原子证据，见 [M3](../docs/milestone3.md)；浏览器复验限制见日志 |
| M4 | lookahead / greedy / critical path 与复用特征、基线比较 | 已在声明的单 AOD / 单 trap 有限线路族完成；四策略、同平台比较、复用收益与反例、独立重放和可编辑验收，见 [M4](../docs/milestone4_complete.md) |
| M5 | batch>1、多 pair 分配、额外作用检查 | 已按用户后续要求提前实现批量CZ与全EZ作用对检查，并用于受限QEC实验；完整M5范围未全部验收 |
| M6 | Gym、候选 observation/mask/reward、random/RL adapter | 未实现 |

## M0：完成标准与现状

初始化、逻辑 frontier、holder 不变量、确定性快照、稳定事件顺序、只读推演、结构化错误和代表性视觉验收。机器断言与六组场景分离，不再为每条 assert 复制默认布局图。

命令：`python -m pytest --visual`；入口 `artifacts/acceptance/index.html`。纯逻辑 reducer 不代表已经执行物理脉冲。

## M1：受限基准

输入一个 READY CZ；静态伙伴预置 EZ，移动原子在初始固定捕获范围。LOAD→MOVE→PULSE→MOVE BACK→OFFLOAD，所有附带原子参与校验和指标。

案例/参数/独立预期以 [M1 说明](../docs/milestone1.md) 为准。成功场景为 baseline/incidental；额外 pair、路径中途阻挡、两目标都在 storage 的场景明确拒绝。界面由模块自动生成。

正常事件边界可恢复；BUG-001/002 已修复并加入损坏边界回归。M1 不是“任意两个 storage 原子的完整运输方案”，不是任意 θ 的 CPHASE 实现。

## M2：施工顺序与完成记录

1. **先封住已知入口/恢复缺口**：为 BUG-001/002 写独立回归，修复后维持既有 M1 结果。
2. **明确多周期指标**：区分最后 pulse、最后单周期与累计 wall time；结束清理规则沿用 eager。
3. **新增连续调度循环**：读取 ready frontier，编译合法计划，单 AOD 串行执行，成功 pulse 释放 successor，返回卸载后再提交下一计划。
4. **扩展当前可行候选范围**：固定单伙伴/固定作用 pose 不能支持一般换伙伴。将作用点、源捕获和必要准备操作显式编译；未支持的情况返回原因，不能偷改初始布局。
5. **扩展报告为多 gate、多 plan**：去除 `G000` 和九段操作的单门假设，保留模板和符号规则，按真实 trace 生成 timeline/frontier。
6. **运行下面分层验收**，明确已覆盖的 circuit family；不以重复同一 pair 两次代替换伙伴验证。

上述六步已完成；实现与独立数字见 [M2 说明](../docs/milestone2.md)，本轮验证见 [日志](logs/2026-09-10-milestone2.md)。M2 完成限定在公开的 mobile–static 初始布局与可行通道候选，不宣称任意电路/任意布局可路由。下一里程碑为 M3。

### M2 必须能回答的问题

| 场景 | 独立验收点 |
| --- | --- |
| 重复同一可行 pair | 多 plan 累计时间/距离/计数正确；仅作为管线冒烟 |
| `CZ(Q000,Q001)` 后 `CZ(Q000,Q002)` | 真实伙伴不同；能展示必要源/作用点变化和完整实际轨迹 |
| 原设计 `CZ(a,b),CZ(a,c),CZ(b,d)` | 至少在声明可支持的初始布局上端到端执行，或明确列出尚不支持哪步；不能标 M2 全面完成但跳过这一类 |
| 独立门汇合依赖 | 不因物理阻塞篡改 DAG；后继仅在所有 predecessor 成功后 READY |
| 无可执行 plan | 报告当前 holders、候选失败原因、是否还有事件；不能无限 WAIT 或静默成功 |
| 第二计划前/中途保存恢复 | 与不中断执行的 trace/final/metrics 一致 |

从全 storage 出发若需要把伙伴预先放入 EZ，必须明确作为计时的准备操作或公开受限初始条件。一次 single-gate plan 内的必要准备不等于已经实现 M3 的跨计划持久 KEEP 策略。

M2 不引入 batch、KEEP 策略、RL 或多 AOD；物理结果依旧可使用既定无噪声运动学模型。

## M3：Dynamic Placement 与操作级调度

已有底座：独立 circuit/platform/placement 输入、可替换 GateCompiler、逐次装卸 bindings、initial/predicted placement 分离、KEEP_LOADED 终态执行/恢复。已有 rigid 联合停车与 single_trap 两种受限运输实现。**M3-A–F 已实现：动态光阱、独立任务、单 trap 持久构造与显式退出、真实操作级并发、两种 compiler 和规模证据**。M3-B 的 exact holder/axes/mask 目标和串行依赖范围见 [任务 API](../docs/task_program.md)，其余差距见 [审计](model_audit.md)。

用户选择的 basic：所有原子从 SZ 开始，一个活动 AOD trap 运 a 到 EZ SLM，再运 b 到旁边执行 CZ，最后逐颗归还。新实现必须显式包含关灯定位、重新开阱和安全交接；不能仅复用旧动画的 holder 变化作为证据。basic 可每门完整往返，通用接口不得固化这一限制。

以下是 M3 内部施工依赖，不新增或重排里程碑。每项完成后同步源码、schema、测试、观察端和交接。M3-A 当前实现与验收见 [动态光阱](../docs/dynamic_traps.md) 和 [本轮日志](logs/2026-09-10-m3-dynamic-traps.md)。

| 顺序 | 工作包与依赖 | 可检验的完成条件 |
| --- | --- | --- |
| M3-A（已验收） | 动态光阱状态与硬件合法性，schema 10 | 分离容量/几何/启用/占据；SLM 逐点与 AOD 行列启用；稳定 cell ID；完整交接状态机；检查活动空阱扫掠及所有新开启交点；安全关闭与计时；恢复覆盖切换边界 |
| M3-B（串行 IR 已验收） | 参数化 circuit 与任务/操作 IR，依赖 A；schema 12 | CZ+U3/别名参数校验；任务可无 gate；准备/pulse/清理可分开；显式 holder/axes/mask 目标、原子/站点/时长约束、操作依赖/资源区间、唯一效果与边界恢复；[2026-09-11 证据](logs/2026-09-11-m3-task-ir.md) |
| M3-C（已验收） | 单 trap 构造基线与持久状态，依赖 A/B | 定义可支持平台族，串行完成混合电路并满足显式终态；支持 EZ SLM、loaded、空 AOD 异位起点；KEEP 后继续、RETURN_ONLY、新站点卸载和退出；全部附带原子可安置 |
| M3-D（已验收） | 统一时间与最小并行，依赖 A/B，使用 C 场景 | 稳定 SLM 1Q 与另一原子运输重叠；交接未完成不得 1Q；按资源区间释放；逻辑完成不等待门后归还；冲突拒绝、同时间事件和并发恢复确定性 |
| M3-E（已验收） | 替换接口与失败出口，依赖 B/C/D | 同一输入在两个实质不同 compiler 下运行，共用 validator/Executor/viewer；候选拒绝与最终运行失败区分；失败可见、终止且保留诊断，无静默跳门 |
| M3-F（运行与离线交互已验收） | 端到端证据与可扩展视图，依赖前述全部 | 混合多伙伴电路、数百原子声明规模、trace 回放；开关/交接动画真实；按资源/类别展示先后与重叠；独立校验门覆盖、物理、时序、终态 |

M3 只需明确的确定性调度规则和有限局部候选，不先追求全局最优。最小 1Q/运输重叠在本阶段完成；多 CZ 同 pulse 的 batch 与多个 AOD 协同仍属于后续范围。全部持久动作在所声明能力与布局范围内验收，不承诺任意障碍布局完备路由。

M3-C–F 的实现入口、声明平台族、独立复验命令与浏览器限制见 [M3 说明](../docs/milestone3.md) 和 [2026-09-11 日志](logs/2026-09-11-m3-completion.md)。

## M4：Lookahead / Greedy

2026-09-11 已完成原 M4 在声明的有限线路/布局族内的验收：同动作空间 basic / greedy / critical_path / lookahead、next-use / 驻留特征、显式 KEEP / RETURN 端点评分、MOVE 内安全 Raman 子窗口、预算/失败诊断、可编辑重编译与回放。见 [策略合同](../docs/milestone4_complete.md)、[20组同平台比较与25份独立重放](../docs/m4_acceptance.md)、[本轮日志](logs/2026-09-11-m4-completion.md)。

主矩阵固定单 AOD / 单 trap、同初始snapshot和完整terminal。已有1/2/4trap联合运输可接入四策略，仍不是任意多cell跨门驻留。前瞻有限，部分CLI案例编译超过HTTP90秒；不保证任意布局可路由、全局最优或最大并行。CZ上下/左右2μm使用全EZ照明的各向同性距离模型，真机方向保真度未标定，见 [物理核查](../docs/m4_physics_research.md)。M5/M6保持未实现。

**用户要求保留返修点：M3 先实现正确、可运行的基线；详细设计 M4 时返修当前任务选择、候选/成本、目标分配和时间窗口接口。不得把当前确定性策略视作永久设计。**

在 M3 已验证的同一动作空间上比较 basic、greedy、critical-path、有限 lookahead。scheduler 选择准备/驻留/归还、目标约束与开始时间；compiler 只优化给定任务的局部实现。总完成时间为首要目标，逻辑完成、路程、装卸、资源利用率为辅助；初始状态与终止条件必须一致。

必须有跨门复用收益与反例：留下原子可能节省搬运，也可能占据 EZ/轴并拖慢后续。报告候选数、搜索预算、编译耗时与实际执行成本；相同局部距离但不同终态需可比较。有限搜索没有最优性证明时，不宣称全局最优。

## M5：Batch 与更广并发

开放 batch>1、多 pair 站点分配及同时 CZ，继续验证全激光作用域的 actual/intended pair 完全一致；保留三原子近邻和旁观 pair 负例。逻辑独立不足以判并行，须满足几何、启用状态、光束覆盖和资源时间约束。

M3 的 1Q/运输重叠不是 batch 完成证明。多 AOD、并行运输或更复杂激光并发须分别声明能力并增加时空校验；不得用多个 AOD 绕开单阵列的行列约束后声称原基线能力已实现。

## M6：RL

复用同一任务候选与验证执行接口，提供 observation/mask/reward 和 random/RL adapter。策略选择合法候选与调度决策，不直接输出 RF 波形或逐原子自由移动。首要目标仍为总完成时间；奖励和截断语义见 [planning_rl](planning_rl.md)。比较同一工作负载与终态条件的 basic/greedy/lookahead，记录 seed、配置和 trace，不把噪声/保真度或 QEC 测量模型作为默认范围。

## 共同完成门槛

实现范围、平台族及搜索限制明确；独立预期与相关机器断言通过；CLI 可复现；trace/metrics、可复用动画和时间表来自同一真实操作程序；失败/恢复可检查；日志与 handoff 同步。文档任务只更新设计和证据，不能关闭运行时 OPEN 项；历史 PASS 与本轮结果分列。真实浏览器验收与离线控制检查分别记录。


2026-09-12补充：四步扩展的4A/4B通过，4C完整1868槽物理执行、独立重放与可编辑UI均通过；以handoff及持久验收账本为准。原M0–M4历史通过范围不被自动扩张为任意电路最优或全噪声QEC。
