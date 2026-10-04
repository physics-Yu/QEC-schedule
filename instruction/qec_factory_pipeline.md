# QEC 工厂供应与逐周期质量协议

版本：1。生效日期：2026-10-04。依据：用户要求以 Factoring15 为参照，固化标准化 QEC、MSC、MSD、magic factory、完整 T 消费与逐周期质量流程。

**本文件是该方向的共享实施协议。涉及 QEC/PBC、magic-state 生产或消费、编码库存、逐周期噪声或 Shor 集成的 agent，必须在设计、实现和验收前阅读并遵守。** 本协议规定目标、接口语义和验收要求；它不表示这些功能已经实现。当前实现状态与运行证据以 [handoff](handoff.md) 和对应阶段报告为准。

最新用户指令优先。本协议覆盖旧文档中与之冲突的实施顺序，尤其是“先完整 Shor native generator，再接工厂”；旧测试与运行证据保留其原日期和适用范围。物理硬约束、Executor 唯一提交、包边界与日志规则继续遵守 [agent.md](../agent.md)、[architecture](architecture.md) 和 [workflow](workflow.md)。

## 项目目标与标准流程

目标是在 QEC 保护下实现资源生产、接受、维护、交付和 T 消费，再基于同一实际时间线评估逻辑可靠性、成本与 Shor 成功率。算法、工厂、缓存和辅助 patch 必须共享物理资源与全局时间。

```text
逻辑电路 → signed adaptive PBC + magic 需求
                         ↓
固定码与协议模板 + 工厂/库存/反馈控制
                         ↓
native PhysicalCircuit / 有分支语义的任务图
                         ↓
placement / routing / scheduling → 合法计划 → Executor
                         ↓
实际 gate/move/idle/readout/reset 时间线
                         ↓
噪声 → syndrome/loss reports → decoder → frame/接受/库存
                         ↓
资源交付质量、完整 T 通道、算法成功率与时间
```

先固定可独立验证的 canonical 协议，再比较 placement、routing 和调度策略。启发式优化不得改变码、检查顺序、纠错边界、测量符号或资源合同；协议变体必须显式版本化，重新验证语义和噪声适用性。

## 码与协议库

从 rotated surface code 的 d=3 基线开始。每个标准 patch 有 9 个 data 和 8 个 syndrome 角色；工厂、cat、缓存和其他辅助资源另行计数。后续距离可配置，不把 d=3 或三轮 syndrome 当作已达到容错质量的证明。

每个协议模板必须声明以下内容，而不只给出 gate count：

| 项目 | 必需内容 |
| --- | --- |
| 身份 | 协议 ID/版本、来源版本、code、distance、朝向、输入/输出语义及前置条件 |
| 码语义 | stabilizer 支持、逻辑代表、sector、wire/check 编号和 endian 约定 |
| 操作 | 实际 native gates、测量/reset ID、角色、依赖、并行交互层和资源生命周期 |
| QEC | 安全的 extraction 边界、detectors/observables、decoder 与 hook/错误传播假设 |
| 反馈 | raw report 到解码量、接受条件、测量轴/符号和 frame 的完整关系 |
| 限制 | ideal/noisy/physical 范围、已验证错误集合、未覆盖噪声及失败行为 |

协议库包含初始化、parallel syndrome extraction、memory、逻辑读出、Clifford/CNOT、logical PPM、raw injection、MSC、MSD 和 T/T† 消费。Surgery 与 transversal 是可选择且需分别验证的实现；不能仅凭逻辑门名称互换。保护中的等待必须安排 QEC，但不能在 merge、代码切换等阶段盲目插入旧 patch 检查。

## MSC 与 MSD 工厂

MSC 指 magic-state cultivation，MSD 指 magic-state distillation。二者都属于目标协议库，是不同生产后端；是否串接取决于交付质量目标和协议适用条件。

```text
raw preparation → MSD → accept/reject
raw preparation → MSC → accept/reject
raw preparation → MSC → MSD → accept/reject   （可选）
accepted → 编码库存/持续 QEC → 运输/交付 → T/T† 消费
rejected → 实际 cleanup/reset → 补产或 exhausted
```

普通 unitary encoding 加初始化 syndrome 不等于 MSC；raw producer 不等于 MSD factory。完整 factory 包括输入生产、全部检查、接受/拒收、清理、补产、库存和交付。15-to-1 必须保留全部 15 个输入的实际来源和成本，不隐藏预置资源。raw 制备可在声明的非保护阶段使用有噪物理 T；这不等于在 surface-code data 上提供受保护的 transversal T，也不能绕过后续工厂与消费协议。

首个 MSD 基准采用有一手来源、可独立核验的 15-to-1 协议。Factoring15 的冻结五工作块与 RM16 并行候选是不同物理实现：必须选定具体模板并声明资源、门序和保护边界，不能混用两者计数或以旧串行通过证明新并行平台通过。

MSC 必须另外选定与 surface-code/现有 native 门集相容的协议，展开实际多比特检查及编码/距离变换。原始 MSC 的 color-code 阶段、专用操作、erasure 假设不能隐含导入当前平台；多比特操作分解后的门、运输、测量和噪声需重新核验。

## 资源身份与库存合同

消费者必须使用工厂实际接受并交付的同一份资源态及其载体。禁止在 handoff 或 consumer 内重建理想态，禁止用改名替代运输、相位转换或真实编码转换。T 与 T† 所需资源必须显式匹配；A− 不能直接改名 A+。

当前 PBC 消费协议的最小生命周期如下。库存中的 reserve/handoff 顺序由控制器声明；其他已验证消费协议可显式声明不同读出/传态顺序，但交付完成、唯一所有权和消费门禁必须满足。

```text
raw_created → allocated_to_attempt → checking
  → rejected → discarded/reset_released
  → accepted → available/stored → reserved/handed_off
      → joint_measured → destructively_read_out → consumed → reset_released
```

拒收态不得入可用库存。接受前、交付完成前、该消费阶段实际需要的报告/decoder/frame 依赖未完成时不得启动对应操作；已验证的延迟解码/frame 可按其明确依赖运行。一次输出只能被一个消费者消费一次；重复消费、错误 epoch、错误类型、未知必需报告和接受前消费必须明确失败。原子重用须有实际 reset/重新制备及新 epoch。

每份资源记录下列语义；这些是待实现数据合同，不表示已有同名 API：

| 记录 | 必需字段 |
| --- | --- |
| 身份与载态 | token ID、资源类型/相位、code/distance、carrier atom IDs、epoch、frame/sector、实际 state handle 或载态演化来源 |
| 来源与接受 | factory/attempt ID、raw parent IDs、协议版本、实际 check/report IDs、decoder 输出、接受决定及其证据来源 |
| 可用与交付 | accepted/available/handed-off 时间、位置/holder、唯一所有者、库存/运输区间、consumer ID |
| 质量 | 接受与交付质量的对象、条件样本集合、模型/版本、相关性标签、方法、shots/置信区间；未知为 null |
| 消费与复现 | joint/resource reports、frame before/after、consumed 时间、释放/reset 证据、circuit/plan/trace hashes、RNG/checkpoint 与单位 |

跨项目接入必须实际映射 wire/endian、check 编号、资源符号和 native gate 综合；仅修改显示标签不算转换。Factoring15 的 reference 驱动物理计划不能冒充 ENV committed feedback，详见[源码对照](../docs/qec_factoring15_integration_review.md)。

## 周期与联合时间线

QEC round、factory attempt、logical operation 和 physical pulse 是不同单位。cycle 必须注明所属 patch/协议阶段与 round ID，并绑定实际起止时间（μs）；不得用固定“若干 d 轮”或论文常数替代实际排程。不同 patch 可以并行，不要求人为全局轮次屏障。

每周期保留实际执行操作、data/ancilla/库存身份、门/测量/reset、运输/idle、光照与 spectator 暴露、syndrome/loss、decoder、frame、接受/拒收和库存变化。经典解码/反馈 ready 时间要进入依赖；未实现或未标定的时延/成本记 null，并注明统计范围。

拒收按实际执行前缀计成本；补产和等待期间，算法数据及库存继续演化并在协议允许的边界进行 QEC。清理、补原子、reset、运输、终态恢复仅在实际执行或有明确模型时计入；未实现项不能默认为零。最大尝试次数和 exhausted 行为必须声明。

## 噪声与质量统计

按实际时间、位置、操作和可观测历史建立物理噪声，再经过测量、decoder 和 frame 得到逻辑结果。保留 controller 可知报告与仿真真值的边界：不能让 decoder 知道未被检测的 loss 或实际错误。

| 指标 | 统计对象与条件 |
| --- | --- |
| 物理噪声/相干性 | gate、idle、move、readout、reset、loss/leakage 等已声明通道和曝光 |
| 纠错后逻辑错误 | 给定码、协议、decoder、时间线与噪声后的 logical error/channel |
| 工厂接受率 | 接受次数/尝试次数；拒收阶段、耗材与实际成本另记 |
| 接受资源质量 | 条件态 ρ(out\|accept) 对目标资源态的质量 |
| 交付资源质量 | 同一资源经历库存 QEC、等待和运输后的质量 |
| 完整 T 通道 | 交付态、联合测量、读出和反馈/frame 恢复共同构成的逻辑通道 |
| 算法结果 | 有效因子成功率、失败类型、尝试次数及成功所需时间 |

纯目标态 fidelity 约定为 F=〈ψideal\|ρ\|ψideal〉，必须声明 frame 恢复、参考态和条件集合。单次 trajectory overlap、接受资源 fidelity 与完整 T-channel fidelity 不能互换；X/Z memory 两种失败率不能自动重建完整逻辑通道。

必须遵守以下统计规则：

- 同一物理机制的同段曝光只计一次。同一时段可组合退相干、loss 等不同机制的通道；使用包含完整 gate/readout/QEC 噪声的逻辑标定核时，不再叠加核内同一错误；已含门期间退相干的 gate model 不再加同段同机制 idle。
- 库存老化通过对应 logical memory channel 或显式物理演化推进。不能给每个 atom 扣一个 fidelity，再相乘；不能用裸比特 exp(−Ttotal/T2) 代替受保护逻辑信息。
- 明确相关错误、共模噪声及跨 patch/工厂输出相关性的表示或近似；不能默认独立乘积。参数必须注明来源、单位、适用范围及近似。
- 纠错与条件接受可提高恢复后的质量。图表同时展示接受率、条件质量、产能和成本，不强制画单调下降曲线，不跨不同条件样本直接连线。
- 15-to-1 的 35p³ 只作为特定独立输入错误与理想操作模型下的校验；文献 erasure 结果和物理门 fidelity proxy 不能直接当本平台 logical fidelity。
- Monte Carlo/实验采样报告 seed、shots、失败次数和置信区间；零观测失败报告上界，不能宣称零错误。解析、精确枚举或密度矩阵结果报告方法与数值精度，采样字段为 not_applicable。区分工厂拒收、物理 abort、decoder failure、算法无有效因子、补产 exhausted 和编译/软件拒绝。

采用多尺度模拟：小系统非 Clifford 态/通道参考验证 Born 分支和相位；Clifford QEC、运输及读出标定形成适用范围明确的逻辑核；完整运行按实际事件调用这些核。Stim/Clifford surrogate 必须注明替代假设并由真实非 Clifford 参考校验，不能当作原生 T 仿真。校准核至少绑定码/距离/朝向、协议顺序、timeline 类、noise/decoder 版本和相关性范围；超出范围必须重标定或明确拒绝。

## 模块与证据边界

码、PBC、factory、inventory、decoder 和质量标定属于 experiments 上层；调度/路由属于 strategies；界面与组装属于 app；environment 不导入这些协议/策略。模型扩展必须遵守现有包边界，不直接写 live state、append 未授权 live DAG 或伪造 measurement_results。只有 Executor 提交实际状态。

Pauli/Clifford frame 是经典控制的一部分。延迟纠正必须按 frame 共轭正确解释或变换后续相关 PPM 的轴/符号、接受 checks 和依赖；对易时可保持不变。若选择实际物理纠正，应执行并计成本，不能同时按另一种未执行方案记账。

实现和交付必须分别声明以下证据，不能相互替代：

| 范围 | 必需证据 |
| --- | --- |
| 理想参考 | 独立态/通道 oracle、真实 Born 分支、相位与所有正常分支校正 |
| Native 电路 | 实际门/测量/reset、完整依赖、provenance、载体与分支合同 |
| 合法物理计划 | 平台、placement、routing、全部作用对/spectators、资源/连续轨迹校验 |
| Executor 闭环 | 实际 committed reports 决定控制、非 Clifford 表示与投影、RNG/checkpoint、独立初态重放 |
| 带噪质量 | 具体噪声/decoder、条件集合、标定适用域、shots/区间与相关性 |
| 完整算法 | 上述组件联合运行、真实资源供应、失败 shot、有效因子与时间统计 |

tracked ENV 尚缺非 Clifford 表示/Born 接口时，原生 T 可排程不代表 T 资源与反馈已在 ENV 执行。reference 报告不得填入物理键；关闭量子跟踪不得绕过 measurement/reset 合同。保持原 AOD 行列/矩形、支撑、移动碰撞、空阱 sweep、实际 CZ 对、光照和测量区域硬约束；失败证据保留，不放宽约束换通过。

## 实施顺序与验收门槛

优先完成资源供应的小闭环。完整 Shor generator 可作为已有参考或独立工作，但不得代替此主线验收。

| 阶段 | 交付与验收 |
| --- | --- |
| F1 标准协议与单 T 参考闭环 | 固定 d=3 QEC/15-to-1 模板；native raw 制备合同与理想 Born 参考执行检查→接受/拒收→库存→交付→同一资源消费→frame。独立一般复振幅与纠缠参考核验完整 T 通道、资源类型和分支；此阶段不称 Executor 已完成 |
| F2 Executor 实际反馈 | 解决受限非 Clifford 状态/Born/合法续接前置条件；读取同一运行的 committed 报告，验证 accept/reject/cleanup、库存、唯一消费、原初态独立重放 |
| F3 逐周期带噪供给 | gate/idle/move/readout/QEC 标定；加入补产、缓存老化和数据等待；输出接受率、交付/T 质量、产能、耗材、abort/exhausted 与区间 |
| F4 MSC backend | 固定 surface-code 适用协议和实际门分解，独立检查并接同一库存/消费合同；比较 MSC 直接供给与 MSC→MSD 的质量和成本 |
| F5 连续 T 与完整 Shor | 联合工厂、库存、辅助和算法调度；多次资源唯一消费、峰值/时长、失败 shot、因子与成功所需时间 |

F3 的基础噪声标定和 F4 的文献/协议设计可与 F1/F2 并行；其集成交付依赖前置证据，不能提前声明完成。任何阶段必须保留失败尝试、版本/config/circuit/trace 来源和独立反例。

验收至少覆盖拒收不入账、当前供应协议拒收前不耦合算法数据、重复消费/过早消费拒绝、等待影响交付质量、所有正常注入分支校正、实际 cleanup 与原子重用。MSD 加入协议适用的低权输入错误检查与已知接受错误反例；不得仅以理想通过、图形完整或最终输出 3/5 宣称完整容错。

本协议固化不改变实现状态。任务结束按 workflow 更新本轮日志和 handoff，只将有本轮对应证据的条目改为完成。

## 来源与按需阅读

- [Factoring15 源码对照](../docs/qec_factoring15_integration_review.md)：实现快照、库存与资源符号、endian/check 映射、reference/ENV 边界；其旧下一批顺序由本协议覆盖。
- [编码资源参考](../docs/qec_encoded_resource_reference.md)、[编码注入参考](../docs/qec_encoded_injection_reference.md)、[Clifford frame](../docs/qec_conditional_clifford_frame.md)：已有受限能力，按 handoff 选择对应源码，不默认加载全部资料。
- [Magic State Distillation Not as Costly as You Think v3](https://arxiv.org/html/1905.06903v3)：MSD 协议和逻辑操作噪声分析；本项目采用模板与噪声参数需分别声明。
- [Magic state cultivation v1](https://arxiv.org/html/2409.17595v1)：原始 MSC 的 injection/cultivation/escape、条件接受及 surrogate 验证；不能把其码与噪声假设当当前平台事实。
- [High Rate Magic State Cultivation on the Surface Code v4](https://arxiv.org/html/2502.01743v4)：surface-code MSC 候选的一手协议；实际门分解、连接与噪声模型须在本项目单独验收。
