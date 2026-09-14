# 文献证据与工程取舍

2026-09-13编译架构专题补充：[外部实现调研](../docs/external_compiler_research.md)，包含ZAC、MQT routing-aware/IDS、Atomique、Enola、Weaver、Bloqade与NEAT的适用边界及三组固定版本源码核查。以下2026-09-10历史条目保留原日期；不要把旧“尚未实现”描述覆盖到最新handoff。

用途：核对物理假设或扩展 backend 时读取。检索/核对日期：2026-09-10。只采用研究作者论文及用户提供的一手硬件资料；这是一份面向当前架构的定向核查，不声称穷尽最新实验或给出平台性能排名。

每条分为“资料支持什么”和“本项目如何使用”。后者是工程判断，不是文献原句。文献中的图示半径、单台设备参数和性能提升不能直接成为代码默认值。

## R1：相干运输与运动波形

**Bluvstein et al., A quantum processor based on coherent transport of entangled atom arrays.** Nature 604, 451–456 (2022)。[论文 DOI](https://doi.org/10.1038/s41586-022-04592-6)；[作者预印本 v1](https://arxiv.org/html/2112.03923v1)。核对主文相干运输段及 Methods 的移动轨迹说明。

- 证据：量子信息可随光镊中原子运输；实验使用平滑轨迹及相干保护，运输质量受运动协议影响。
- 采用：持续维护同一个 Q 身份与 placement，不把移动等同于量子 SWAP 或重新初始化原子。
- 限制：本项目恒速折线未复现实验运动波形，不能从无随机损失推出真实运输无误差。

## R2：分区、AOD/SLM 转移与测量

**Bluvstein et al., Logical quantum processor based on reconfigurable atom arrays.** 在线发表 2023-12-06，Nature 626, 58–65 (2024)。[论文 DOI](https://doi.org/10.1038/s41586-023-06927-3)；[作者预印本 v1](https://arxiv.org/html/2312.03982v1)。核对 Fig. 1、Methods 的 Shuttling and transfers、Local Raman rotations、Mid-circuit readout。

- 证据：SLM 可配置静态位置；AOD 阵列受行列运动约束。文章区分 storage、entangling、readout，并讨论转移对齐及对未测量原子的保护。
- 补充证据：Local Raman rotations 明确支持在 AOD 与 SLM 原子上局域单比特操作；Raman 寻址使用额外 AOD，不等于运输 AOD。转移方法通过对齐、相对阱深 ramp 和位移完成，不是普遍要求逐点关闭 SLM。
- 采用（2026-09-11 复核作者预印本 Methods）：开放稳定 SLM / 静止 AOD 上的单比特目标，Raman 资源独立；AOD 目标脉冲期间锁住运输设备。不开放运输途中或交接中的门。并行仅同类型，不能推导无限个不同旋转可同时执行。
- 数值边界：作者预印本描述低串扰邻距约 ≥6 μm、每行局部旋转 5–8 μs，并讨论更快约 1 μs 方案。本项目采用用户指定 ≥5 μm、每门固定 1 μs，属于研究简化，不声称论文已验证这一精确组合的实验保真度。
- 限制：固定方格 SLM、固定间距 AOD 和上下三区是本项目选定配置；不是所有实验的普适几何。分区只能作为屏蔽噪声的抽象，不能证明串扰为零。

## R3：Rydberg 门不是“距离内自动 CZ”

**Evered et al., High-fidelity parallel entangling gates on a neutral-atom quantum computer.** Nature 622, 268–272 (2023)。[论文全文](https://www.nature.com/articles/s41586-023-06481-y)；[作者预印本](https://arxiv.org/abs/2304.05420)。核对 Neutral-atom entangling gates 与门误差讨论。

- 证据：CZ 依赖受控 Rydberg 激发和脉冲设计；温度、散射、衰减和激光不完美影响操作。
- 采用：将“作用对资格判据”与“执行门操作”分开。只有脉冲事件才能完成门，静止靠近不自动完成。
- 限制：当前硬距离阈值只用于几何合法性；未算脉冲波形、条件相位、单比特相位与保真度，也未按实验推导 2 μm 阈值。

## R4：转移也有动力学，空 trap 仍有光势

**Cicali et al., Neutral atom transport and transfer between optical tweezers.** arXiv:2412.15173v1，2024-12-19。[作者全文](https://arxiv.org/html/2412.15173v1)。核对 II Atom transport in an external potential、III Transport pulses；使用 arXiv 版本日期，不把 HTML 渲染页日期当发表日期。

- 证据：文章将静态与移动光镊势一起建模，研究位置/深度随时间变化、转移和运输期间的加热；不是只追踪原子之间的距离。
- 采用：装卸有时长，恒速轨迹是调度简化。用户已将“开启空 AOD trap 不扫过静态原子”指定为硬约束；当前缺少该几何检查是 OPEN，不能再以不做光场模拟为由略去。该硬规则不是本文证明的普适失稳定理。
- 限制：不能照搬该文特定原子种类和势阱参数到当前配置；几何 clearance 不是光学转移成功率模型。

## R5：复用、分区与 IR

**Lin, Tan, Cong, Reuse-Aware Compilation for Zoned Quantum Architectures Based on Neutral Atoms (ZAC).** arXiv:2411.11784v3，2024-12-06。[作者全文](https://arxiv.org/html/2411.11784v3)。核对 III（硬件行列）、IV（CZ/U3 预处理）、V-B（复用）与 IX。

- 证据：采用 CZ/U3 门基底；AOD 活动交点由行列控制产生；编译考虑放置、任务依赖、运输与复用，保留原子会改变后续成本。
- 采用：CZ+参数化通用 1Q 作为项目输入基底；候选返回预计终态、资源区间与成本，驻留选择归 scheduler。目标/约束到局部候选的具体接口是本项目设计。
- 限制：文献的“保留在作用区”不等同于本项目 `KEEP_LOADED`，前者也可能继续在静态 trap 中。不能直接移植其 IR、复用规则或保真度倍率。

## R6：逻辑独立不等于硬件可并行

**Wang et al., Atomique: A Quantum Compiler for Reconfigurable Neutral Atom Arrays.** arXiv:2311.15123，本文核对 [v3 全文](https://arxiv.org/html/2311.15123v3) III-C 与 IV。

- 证据：router 从逻辑 frontier 选择 gate，还要验证额外作用对、行列顺序与重叠等硬件约束；论文另有运输误差模型。
- 采用：DAG 与物理 compiler 分层；候选先编译验证，再给策略选择。
- 限制：当前固定间距整体平移比该类可重配置行列模型更受限，不将其动作能力或误差公式直接当作现有 backend。

## R7/R8：本地来源

- **R7**：[Qiuniu ISA 原件](references/isa-qiuniu-near-self-contained.pdf)，v0.2.1，2026-04-21，4 页。核对第 2 节的移动周期、作用区域、测量和成本估计。其格点“双占据”是描述抽象，当前采用连续位置解释；不把其终端测量范围默认为任意中途测量能力。
- **R8**：[AAM 原文](references/aam_original.md)，无版本/作者元数据，存在单调性公式缺损；保留原文，解释写在 [aam](aam.md)。固定间距 QN 限制用于本项目 backend，但矩形覆盖区域不是连续光阱。

## R9：行列转移与有条件的可完成构造

**Tan et al., Compiling Quantum Circuits for Dynamically Field-Programmable Neutral Atoms Array Processors.** Quantum 8, 1281 (2024)。[期刊原文](https://quantum-journal.org/papers/q-2024-03-14-1281/)；[作者预印本 v5](https://arxiv.org/html/2306.03487v5)。核对 Appendix A5、A6 及 Figure 6。

- 证据：按行列调整光强参与 SLM/AOD 转移；通用性示例在足够空间和特定分离布局下逐颗运输、做门、返回。
- 采用：关闭轴必须审核整行/列的受影响原子；为本项目定义可验证的安全布局族和逐门恢复构造，再声明该族内有限电路可完成。
- 限制：其构造不是任意有限 SZ/EZ、障碍和新增空阱排斥约束下的完备性证明；预算内没找到路线不等于物理无解。

## R10：独立原子操作 IR

**Weaver: A Retargetable Compiler Framework for FPQA Quantum Architectures.** CGO 2025。[作者所在机构论文](https://dse.in.tum.de/wp-content/uploads/2025/01/Weaver-CGO-25.pdf)。核对 §4 wQasm 的转移、shuttle、local/global Raman 与 Rydberg 操作及前后条件。

- 证据：中间表示可将运输、交接、单比特控制和纠缠作为不同原语。
- 采用：任务无需绑定唯一 gate；gate 准备/pulse/后处理可通过依赖组合，共用执行与回放。
- 限制：Weaver 的非门动作使用与逻辑门关联的顺序 annotations；本项目允许独立目标任务是进一步的设计选择，不声称直接复用了其调度接口。这是编译框架设计，也不是实验安全性证明。

## 已确认决策与证据的分界

| 问题 | 采用的项目约定 | 依据及边界 |
| --- | --- | --- |
| 最底层物理 | 不模拟光场/波包/保真度；保留几何与时间硬约束 | 用户研究范围；不是论文要求 |
| SLM 与 AOD 开关 | SLM 逐点、AOD 按行列，交点影响全量验证 | SLM 逐点是平台假设；R2/R5/R9 支持行列及转移背景 |
| 转移与稳定 | 对齐格点，先建立目标支撑，完成后提交 holder | R2 转移背景；二值状态机与预设时间包含稳定余量是项目抽象 |
| 空阱扫掠 | 活动空 AOD trap 对静态原子实行硬避让 | 用户要求；R4 为物理背景，精细场仍不在范围 |
| 单比特门 | CZ+U3；暂限稳定 SLM，独立 Raman 资源 | R5 门基底、R2 AOD/SLM 1Q 能力；SLM 限定和默认单通道是项目选择 |
| 任务与计划 | 可仅移动；prepare/pulse/cleanup 可分开 | R5/R10 提供设计参考；具体接口见 compiler_contract |
| 可完成性 | 支持门集和已验证布局族下给构造保证 | R9 启发；不承诺任意障碍布局 |
| 优化 | scheduler 优化含声明清理的总完成时间 | 用户研究目标；compiler 的局部距离是候选成本 |

## 参数来源与使用边界

| 参数/概念 | 当前值/规则 | 证据与判定 |
| --- | --- | --- |
| LOAD/OFFLOAD、门时长、运输速度 | 见 `configs/hardware/milestone1.json` | 与原架构示例及 R7 的成本量级一致；仍是演示配置，未对本模拟器进行实验标定 |
| 速度单位 | 0.5 μm/μs = 0.5 m/s | 单位换算；不是 0.5 μm/ms |
| 作用距离 | 2 μm | 继承项目配置，不能由 R3 的任何保真度数字反推出合法性保证 |
| 最小原子间距 | 1 μm | 项目几何阈值；不等于光腰或 Rydberg 半径 |
| 对齐容差 | 1e-7 μm | 理想模型中的数值容差；不是设备定位精度 |
| 5 μm SLM/AOD 间距、三区间隔 | 场景配置 | 可测试的规则化布局，不声称实验普适要求 |
| 作用区无额外 pair | exact pair-set 相等 | 有用的确定性拒绝规则；不能排除孤立旁观原子的相位/散射误差 |

继续研究时按“问题 → 原始资料 → 本项目假设 → 可证伪验收”记录。新增结论落到 [physics](physics.md) 或 [model_audit](model_audit.md)，避免把论文摘要堆进常驻 agent 提示。
