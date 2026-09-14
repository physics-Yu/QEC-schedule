# M4 物理核查：CZ 方向与调度边界

核查日期：2026-09-11。用途：本轮调研 agent 的一手来源结论与工程建议；不替代设备标定。只修改本文件，代码、里程碑和交接由主 agent 统一维护。

## 结论

**没有查到“EZ 中 CZ 只能左右配对、不能上下配对”的硬件通则。当前项目可以保留左右/上下四方向候选，但应明确这是区域照明、各向同性距离判据的调度模型，不能称为 Qiuniu 真机上下方向已经完成实验标定。**

这里“上下 2 μm”指两个原子的相对位移为 `(0, ±2 μm)`。若一个在中心上方 2 μm、另一个在中心下方 2 μm，两原子距离是 **4 μm**，不满足项目的 2 μm 作用阈值。横向同理。

光束传播方向、光束覆盖范围、两原子的连线方向是三件不同的事。图中一条水平光线不能作为“只有同一水平线上的原子能做 CZ”的证据。

## 一手来源及其支持范围

### P1：本项目直接硬件来源

[Qiuniu ISA v0.2.1](../instruction/references/isa-qiuniu-near-self-contained.pdf)，2026-04-21，§1.2、§2.1.1、§2.2.2；本轮读取原 PDF 全部四页文本。

- §1.2 写出 `V_ij = C6 * |r_i - r_j|^-6`，使用标量距离，没有角度因子。
- §2.1.1 以 y 区间定义功能区；§2.2.2 以 2Q 区内同参考 site 的 static/mobile 双占据定义门，没有指定真实连续坐标偏置必须左右。
- 原件没有给出同一 site 内上下/左右偏置的标定表、量化轴方向、光束边缘条件或每个方向的 CZ 保真度。占据标签不能证明两个真实原子重合，也不能证明任意 site 内布局均已实验实现。

[AAM 原件](../instruction/references/aam_original.md) 同样使用全局纠缠光和参考 site 双占据抽象，没有左右方向限制。它没有作者/版本元数据，证据强度不能高于具体实验测量。

### P2：区域照明与 2 μm 配对的真实实验

Bluvstein 等，*Logical quantum processor based on reconfigurable atom arrays*，Nature 626 (2024)，[作者预印本 v1](https://arxiv.org/html/2312.03982v1)，Methods → Zone parameter choices / Shuttling and transfers，Extended Data Fig. 1。

作者的 420/1013 nm Rydberg tophat 光覆盖约 35 μm 高、250 μm 水平范围；门内原子距离约不超过 2 μm，门站点之间的原子至少隔 10 μm。它支持“光覆盖二维区域中的近邻原子对”，而不是零宽水平射线。文章还报告 AOD–AOD 与 AOD–SLM 配对执行门。

**边界：** 本轮未找到同一对原子从水平旋转到垂直、固定其他参数比较 CZ fidelity 的数据，因此不能用该文宣称两方向真机表现完全等价。该文站点间 10 μm 也不能偷换成项目的 2 μm 外所有作用严格为零。

### P3：Rydberg 态、偏振和非共线实验

Evered 等，*High-fidelity parallel entangling gates on a neutral atom quantum computer*，Nature 622 (2023)，[作者预印本 v1](https://arxiv.org/html/2304.05420v1)，Methods → Rydberg excitation，Fig. 4，Extended Data Fig. 1。

该实验使用 `53S1/2`、420 nm / 1013 nm 双光子激发和选定圆偏振，场强 8.5 G；门参数还依赖光场均匀度和标定。其三角形原子组的全局 CCZ 演示说明该光学体系并非只支持共线相互作用。

**边界：** 三角形 CCZ 不能直接作为垂直 2 μm CZ 的独立 fidelity 验收；不把 S 态近似、偏振选择或一组实验参数解释成所有原子种类和 Rydberg 态都严格各向同性。

### P4：为何仍须保留角度与设备标定边界

Ravets 等，*Measurement of the Angular Dependence of the Dipole-Dipole Interaction Between Two Individual Rydberg Atoms at a Förster Resonance*，Phys. Rev. A 92, 020701(R) (2015)，[作者预印本 v2](https://arxiv.org/abs/1504.00301v2)。实验测量了外场选定通道中相互作用随原子连线与量化轴夹角的变化。

这是一项不同相互作用条件的反例：不能笼统地说“Rydberg 相互作用一定与方向无关”。它不是证据表明本项目 53S 类 CZ 必须限定水平。

## 已实现模型与本轮建议

当前 `hardware/rigid_aod.py::actual_pairs` 使用 EZ 内所有存活原子的欧氏距离，`validate_pulse` 检查实际 pair 集与请求集完全相同。`motion/greedy.py::interaction_poses` 提供四方向及当前合法姿态。两者说明当前软件行为，**不构成外部实验依据**。

建议 M4 沿用以下固定合同：

1. 保留 `(±2, 0)` 与 `(0, ±2)` 候选，所有原子均处在已声明的 EZ 照明范围内；靠近后仍须显式 CZ pulse。
2. 四方向执行完全相同的碰撞、静止、支撑、资源、额外作用对和区域检查；不为垂直配对放宽距离或移动边界。
3. 以“全 EZ 照明 / 各向同性距离代理”标明模型。可视化用区域照明和受作用对标记，若保留水平光束线，不能让线条暗示只允许水平配对。
4. 未标定的真实设备能力保持未标定。以后接入真机，应由 backend 提供照明覆盖、允许 pair 几何、量化轴/原子态与脉冲校准约束，scheduler 不自行推定。
5. 不在本轮因外部论文的站点间距、关阱波形或 fidelities 改写用户已经确认的研究模型。需要真实保真度研究时另立标定任务。

建议独立验收用例：同一 EZ 内 anchor `(x,y)`，伙伴 `(x,y+2)`、`(x,y-2)`、`(x+2,y)`、`(x-2,y)` 均按相同条件判定；伙伴距离 2 μm 以上、两原子分别位于中心 ±2 μm、伙伴越过 EZ 边界、有额外近距原子时拒绝。安全移动路径另验，不以 pulse 正例证明可到达。

## 调研 request 记录

| 问题 | 结论 | 状态 |
| --- | --- | --- |
| EZ 中上下相距 2 μm 能否做 CZ？ | 当前模型允许；物理上无普适左右限定；Qiuniu 方向保真度未提供，不能冒充已标定 | 已核查，设备标定边界保留 |
| 原始 AAM / ISA 是否规定左右偏置？ | 两份本地原件均未规定；ISA 给的是各向同性距离 Hamiltonian 与 site 双占据抽象 | 已核查 |
| “上 2 / 下 2”能否当作 2 μm pair？ | 实际距离 4 μm，当前模型拒绝 | 已核查 |

本文件是定向核查，不是系统性综述。外部检索只引用作者论文和本地用户提供原件；浏览器搜索结果中的自动“发布日期”未用来覆盖论文版本日期。未向论文作者或其他外部人员发送消息。
