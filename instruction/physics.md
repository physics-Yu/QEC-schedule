# 物理过程与调度抽象契约

2026-09-12 测量扩展：用户已授权两块/四块逻辑GHZ的稳定子读出与纠错。启用量子跟踪的计划支持 MZ 内稳定 SLM/静止 AOD 上的真实 MEASURE 与 RESET，500/100 μs 为显式模拟假设，非设备普适常量。读出保留原子并投影，复位到 |0>；测量位控制后续 X/Z。条件为假的固定 1 μs 控制时隙不发光，不计 Raman 忙时。运输、碰撞、全 EZ CZ 对及实际 Raman ≥5 μm 等约束保持。时域扩展显式支持三噪声轮中的至多一个数据Pauli或报告翻转事件，并执行一次完美闭合轮；报告翻转不会改变真实量子投影。不是全电路噪声容错证明。schema19，详见[量子读出合同](../docs/quantum_readout_core.md)。

2026-09-12修订优先于下方历史描述：AOD矩形是两组有序坐标的Cartesian积，不要求等间距；rigid可保持非均匀offset整体平移。四邻格保护按用户授权变为默认开启、可显式关闭的`ez_neighbor_guard_enabled`。一个真实CZ pulse现可同时作用于多个不共享qubit的READY门，整个EZ actual_pairs必须等于整批intended_pairs；见[批量合同](../docs/batch_cz_contract.md)。schema18。此处只扩展批量作用集合，不放宽支撑、碰撞、移动和单比特光条件。

状态：2026-09-10 更新。本文是用户确认的目标规范；标为“待实现”的规则不能由旧动画或旧测试证明已完成。证据分界见 [research](research.md)，当前缺口见 [model_audit](model_audit.md)。

## 1. 研究边界与结论类型

研究给定 PhysicalCircuit 到原子操作的完整调度：几何、持续 holder、光阱开关、交接、门依赖、资源和统一时间。不实现最底层光学场、RF/AWG 波形、原子波包、温度、损失率或保真度仿真；这些也不是本轮 milestone 的完成前提。

| 类型 | 含义 |
| --- | --- |
| 文献事实 | 对明确设备/协议成立，列出一手来源，不外推成通用能力 |
| 项目约定 | 用户选择的硬约束或研究简化，明确采用理由 |
| 当前实现 | 可在源码/测试中核对的行为 |
| 已确认待实现 | 必须补齐的契约；记录 OPEN，不能包装为已完成 |
| 待标定 | 缺少设备参数，保留配置接口，不杜撰数值 |

## 2. 原子身份、holder 与持续状态

原子 Q 身份在运输中保持不变；移动不隐含 SWAP、reset 或量子门。相干运输的实验依据见 [R1](https://arxiv.org/html/2112.03923v1)。每个存活原子恰好一个已提交 holder；没有永久 home。返回某个格点、来源位置或 storage 区域是任务终态要求。

初始基线全部原子在 SZ 的已开启 SLM 格点。后续任意合法持久状态均可成为下一任务起点，包括 EZ 中 SLM 持有、AOD loaded 和空 AOD 停在别处。basic 的“每门回源”仅是策略，不约束通用编译接口。

交接的光势可以重叠；唯一 holder 是粗粒度承载真值，不表示转移期间只存在一束光。实时 holder、开关及几何只由 Executor 提交，compiler/backend 只能只读推演。

## 3. 静态几何与活动光阱

SLM 候选点位置在 episode 内固定；**逐点开关**是用户选择的平台能力，必须作为运行状态维护，不能由 occupancy 推断。SLM enabled 与 occupied 是不同概念。论文中的转移协议不普遍要求逐点二值 SLM 关灯，来源区别见 [R2](research.md#r2分区aodslm-转移与测量)。

AOD 容量、行列坐标、行列启用状态分别建模。设列 c 的启用值为 C[c]、行 r 为 R[r]：

```text
active_trap(r,c) = R[r] AND C[c]
active_count = enabled_row_count * enabled_column_count
rigid: position(r,c,t) = pose(t) + (c*spacing, r*spacing)
```

两行两列开启得到四个光阱，不能只把对角两处当作活动阱。关闭一行/列影响全部交点；有承载原子时必须先完成所有受影响原子的安全交接，不能仅卸一颗后切断其他原子的支撑。活动阱可以为空，所有轴关闭时活动数可为零；硬件容量无需变零。轴和 cell 身份保持稳定，切换不能重新编号或瞬移原子。

rigid 保持相对几何，只允许整体平移；row_column 允许有序行列伸缩，同轴联动且不能交叉。动态启用与变距是两种独立能力；本次基线继续 rigid，**不需要开启 non-rigid 才能改变活动 trap 数**。详细轴间距与路径约束见 [aod_backends](aod_backends.md)。关闭状态下的轴控制仍服从所选 backend，不能借关灯绕过行列顺序或传送坐标。

M3-A 已在 `SimulationState.slm_enabled`、`AODRuntimeState.enabled_rows/columns` 实现动态启用状态；固定轴集合表示容量，默认 AOD 全关。SLM 配置 enabled 仅作为初始值。独立 TRAP_SWITCH 和交接内开关均计时并可恢复；详见 [动态光阱](../docs/dynamic_traps.md)。

## 4. 交接硬逻辑与完整受影响集

所有 SLM↔AOD 交接发生在合法 SLM 候选格点，对齐、静止、源 holder、目标容量、行列影响集和时长必须通过校验。

| 操作 | 必须表达的过程 | 完成时提交 |
| --- | --- | --- |
| LOAD / RECAPTURE | 原子原由 SLM 支撑；对齐后建立目标 AOD 支撑，再撤去源 SLM 支撑 | holder 改 MOBILE，提交最终开关状态 |
| OFFLOAD / PARK | 原子原由 AOD 支撑；对齐后开启目标 SLM 支撑，再撤去源 AOD 支撑 | holder 改 STATIC，提交最终开关状态 |
| 关闭空轴后定位 | 确认整条受影响轴没有失去支撑的原子，关闭后移动；重新开启前重新检查全部交点 | 提交轴状态/几何，绝不隐含捕获 |

这里的支撑建立/撤去是项目的粗粒度转移协议，不求解光强曲线。进行中的 transfer 保存源、目的和阶段，允许重叠光势；完成前 holder 仍归源，源支撑不得提前撤掉。切换完成与 holder 更新一致提交，不出现无阱承载或双 holder。实际实验常用相对阱深 ramp；不把这张二值协议表冒充通用实验波形。[R2 Methods 的 Shuttling and transfers](https://arxiv.org/html/2312.03982v1)

装载检查**全部活动交点的受影响集**：非请求原子也可能被对齐的光阱影响。按明确捕获/交接策略纳入完整 bindings，或拒绝该操作，不能漏记。2026-09-11 多 trap 试验将动态绑定 LOAD 精化为实际活动交点：离所有活动 trap 足够远的间隙原子不算捕获对象，靠近活动 trap 的未对齐原子仍拒绝；建立支撑和活动空阱扫掠继续完整验证。旧 rigid planner 的默认 footprint 保守查询保留，见 [多 trap 规范](../docs/multi_trap.md)。矩形内部不是连续吸附面。

M3-A 的 selective_transfer_enabled/PARK/RECAPTURE 已验证对齐、双支撑与整行列关闭影响。它不是任意单 cell 独立控制的证明。已停在 SLM 的 a 不随随后空 AOD 运动而走，必须来自明确关闭/重新开启与安全路线，不能仅由 holder 标签或动画决定。

配置的 LOAD/OFFLOAD 时间已经包含 ramp/稳定余量，不额外重复增加 settling。开关和关灯定位都有显式成本约定；若某次开关包含在交接时长中须标明，不能再双计或暗中省略。具体数值由平台配置给出，不照搬论文设备参数。

## 5. 路径安全与关闭状态

**M3-A 已实现的硬条件：开启的空 AOD trap 不得扫过静态原子。** 这是用户指定的保守几何安全规则，不需要先实现完整光场。R4 支持移动势也会影响原子的物理背景，不证明每一种空阱穿越都必然失稳。[光镊转移模型 R4](https://arxiv.org/html/2412.15173v1)

对每段活动轨迹，校验所有活动 AOD trap（有载与空载）、全部存活原子、行列/阱间距和世界边界。rigid 线段到静态点 p 的解析最短距离为：

```text
u = clamp(dot(p-s,e-s) / |e-s|², 0, 1)  # 零长度另处理
minimum_distance = |p - (s + u*(e-s))|
```

阈值使用明确配置并标单位；装卸对齐的例外只限有绑定、有时限、已验证的实际交接对象。不能把整条运输段标成 transfer 就跳过扫掠。开启操作自身也要检查全部新出现的交点，避免“关着穿过去再在原子旁随意打开”。

关闭的 trap 没有该束缚场，可在 backend 允许的控制路径上重定位，仍计时；不能携带原子。开关区间必须参与编译、独立验证、执行和回放，不能仅在 renderer 隐藏圆圈。光斑尾部、频谱拍频、空 SLM 势的精细扰动和运动量子态仍在范围外，与必须补齐的空 AOD 几何扫掠不同。

当前 loaded 原子的整段避让、完整建模 AOD trap 间距、活动空 AOD 对静态原子的整段扫掠均有检查；GAP-001/002 已按 M3-A 验收。并发时需比较共同时间区间的真实轨迹，不能沿用串行端点或静态旧 pose 证明安全。

## 6. CZ 与单比特门

2026-09-11 新增用户硬规定：EZ SLM 中还有未完成 CZ 的原子，为其唯一下一次 CZ 伙伴保留上下左右一个 world 网格间距的四个 EZ 格点（工作台5 μm）。其他存活原子可经过，但不能停驻或卸载占据；SLM/AOD占据均检查，不是整圆禁区，不因空邻阱关闭而取消。OFFLOAD建立、LOAD解除、CZ完成更换伙伴或结束保护，所有中心独立生效；[完整合同](../docs/ez_neighbor_reservation.md)。这是用户给定的离散排布约束，不是额外实验保真度结论。

CZ 需要显式受控 pulse；靠近不会自动完成门。[R3](https://arxiv.org/abs/2304.05420) 提供脉冲实验依据。保留本项目的确定性代理规则：

```text
eligible = 纠缠区内存活原子
actual_pairs = 所有 distance <= interaction_distance_um 的无序原子对
pulse 合法要求 actual_pairs == intended_pairs，并满足静止与资源条件
```

涵盖 SLM–SLM、AOD–SLM、AOD–AOD 及附带原子；不得只枚举 requested 集。激光作用域和旁观原子限制属于 backend，槽位名字不同不表示物理独立。2 μm 作用距离、1 μm 原子 clearance 等是项目参数，不是保真度保证；显示圆环半径不是物理半径。刚性平移不能改变同载两原子的相对间距，禁止放大作用距离来通过编译。

当前单比特只执行 H/X/Y/Z/T，内部使用标准 U 参数记录其效果。依据 R2 Methods 的局域单比特操作说明，目标可由开启的 SLM 或静止 AOD 支撑，必须存活、未测量、完成相关交接并位于有效寻址区。与任意其他存活原子 **≥5 μm（含 5）允许，<5 μm 禁止**，不区分目标/邻居 holder；空 trap 不算邻居原子。≥5 μm 与固定 1 μs 是用户模型参数，不是论文对该组合保真度的证明。详见 [AOD Raman 规范](../docs/aod_raman.md)。

2026-09-11 最新用户规范：只执行 H/X/Y/Z/T/CZ；不同 qubit 上同一种单比特门可直接并行，不同门类型的作用区间互斥，包括 CZ 与单比特门。每个单比特操作固定 1 μs。详见 [门规范](../docs/gate_contract.md)。资源使用 `RAMAN:Qxxx` 加目标 atom/trap，不再有跨 qubit 的 RAMAN_0 互斥。另一个原子的交接/运输不阻止稳定 SLM 目标的 Raman；正在交接、移动或与其他门共享同一目标的操作仍互斥。此前单通道与全局 HANDOFF_GUARD 是错误地限制当前目标模型的简化，不能继续当硬件约束。此并行能力是用户指定的研究模型，不外推为任意实验设备的事实。

Raman busy time 使用实际区间并集，不把四个并行 1 μs 脉冲记成 4 μs 的设备忙时。AOD 目标还锁定 AOD_0，脉冲期间不允许运动或支撑切换；SLM 与 AOD 上同类型门可合法并行。邻居运动按整个实际脉冲区间校验，不只看运动端点。逐 qubit 资源时序分别记录，逻辑依赖和固定 1 μs 保持，Z 仍为真实 1 μs 操作。checkpoint schema 17，旧 1–16 从原输入重编译。

## 7. 分区、测量和未承诺能力

storage、entanglement、measurement 表示权限；上下排布是场景选择。zone 不是隐含墙，具体运输通道必须验证。测量/重置是独立操作，不属于 U3 别名；单独的measured标记不代表量子读出；当前显式QEC模式已实现上方声明的结果、原子保留、时间、reset和反馈语义。

不凭完成门数宣称 QEC、量子态仿真或真实 fidelity。当前研究只需验证逻辑效果映射、几何与资源合法性、时间一致和终态；若将来研究读出/噪声，另立范围和标定契约。

## 8. 实现状态与验收入口

| 要求 | 当前状态 | 跟进 |
| --- | --- | --- |
| 唯一 holder、对齐交接、全作用对、刚性/有序行列运动 | 已有受限实现及测试 | 保留独立验证与失败原子性 |
| 动态 SLM/行列 masks，安全交接开关 | M3-A 已实现并验收 | GAP-001/002 FIXED，见动态光阱文档 |
| 活动空 AOD 对静态原子全轨迹避让 | M3-A 已实现（串行） | A-004 / GAP-002 FIXED |
| 非 gate 任务与通用持久起态 | 部分底座已有，通用接口待实现 | GAP-003 |
| 参数化 1Q、SLM 资格和操作级并行 | 1Q 参数/SLM 资格与串行执行已实现；并行待实现 | GAP-004 FIXED / GAP-005 OPEN，见 [工作台](../docs/circuit_workbench.md) |

上述 M3-A 条目按本轮源码和运行证据关闭；其他缺口保持 OPEN。具体计划见 [M3](milestones.md#m3dynamic-placement-与操作级调度)，验收见 [validation](validation.md)，历史基线见 [单 trap 说明](../docs/circuit_pipeline.md)。


## M4 CZ 方向核查（2026-09-11）

保留左右/上下相对位移 `(±2,0)`、`(0,±2)` μm；两原子均须在 EZ 内、静止、受合法支撑，且 actual pair 与 intended pair 完全一致。项目采用全 EZ 照明和各向同性距离代理。Qiuniu ISA 的标量 `C6/r^6` 与区域照明论文没有水平限定，但不构成 Qiuniu 真机上下/左右保真度等价的标定。中心上2与下2是相距4 μm，当前阈值拒绝。来源与边界见 [定向核查](../docs/m4_physics_research.md)，独立模型测试 `tests/test_m4_direction_contract.py`。
