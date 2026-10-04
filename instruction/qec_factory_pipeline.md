# QEC 工厂供应与逐周期质量协议

版本：2。生效日期：2026-10-04。依据：用户要求以 Factoring15 为参照，并最新明确 magic factory 与 processor injection 的当前任务是调度模拟，不要求实现量子态演化。

**本文件是该方向的共享实施协议。涉及 QEC/PBC、magic-state 生产或消费、编码库存、逐周期噪声或 Shor 集成的 agent，必须在设计、实现和验收前阅读并遵守。** 本协议规定目标、接口语义和验收要求；它不表示这些功能已经实现。当前实现状态与运行证据以 [handoff](handoff.md) 和对应阶段报告为准。

最新用户指令优先。本协议覆盖旧文档中与之冲突的实施顺序，尤其是“先完整 Shor native generator，再接工厂”；旧测试与运行证据保留其原日期和适用范围。物理硬约束、Executor 唯一提交、包边界与日志规则继续遵守 [agent.md](../agent.md)、[architecture](architecture.md) 和 [workflow](workflow.md)。

## 当前任务目标：纯调度模拟

**交付可复用的完整 magic factory 调度模块，能够接入完整 processor，在算法需要时供应资源并完成 injection 调度。** 单 T 用例是首个验收案例，最终模块必须通过统一资源接口接入 processor；不能以局部原子前缀或独立图示作为完整交付。

```text
processor 的 T/injection 请求
  → 库存查询/预约 → 无库存时排队并触发工厂生产
  → 全部15输入/检查 → 接受或拒收清理/补产/预算耗尽
  → 同token/载体/epoch的存储、运输和交付
  → injection 门/测量 → 经典反馈/frame → 消费一次并释放
```

当前任务必须实现并核验：

1. 完整冻结协议的 native 门、测量/reset、原子角色、依赖、保护边界及生命周期；完整15-to-1保留全部15输入与成本。
2. 通过现有物理约束完成 placement/routing/scheduling，并由 Executor 提交操作与事件；时间、资源占用、旁观者及终态可独立重放。
3. 明确的测量/分支报告源、seed或轨迹、版本及经典反馈时延模型；报告在对应测量模拟完成后才对控制器可用。缺报告不能当0，不直接改 measurement_results 或 live DAG。
4. 接受/拒收、cleanup、补产与最大预算；可用时间、排队等待、共享库存、预约/交付、唯一消费者及epoch重用。
5. processor通过统一接口表达资源类型/消费位置/依赖和需求时间；injection使用工厂交付的同一资源token与载体，按协议排程联合测量、读出、反馈/frame和释放。库存不足允许等待，不承诺即时供给。
6. 项目既有 Executor→VisualRecorder→共用viewer 展示完整实际调度事件，同时提供成功、拒收补产、等待、过早/重复消费及恢复的机器证据。

**不要求运行时追踪态向量、密度矩阵、稳定子叠加或精确非 Clifford/Born 投影。** 资源在调度层由类型/相位标签、code/distance、token、载体、epoch、frame/sector、holder、时间及provenance表示；state handle是可选的独立参考字段。预设轨迹或声明统计模型可供应报告，须标注来源和适用范围。小规模量子协议参考检查可保留，属于独立、可选验证；不阻止调度模块实现和交付。

“实际/真实执行”在当前任务中指经过物理校验并由 Executor 提交的**调度模拟操作与事件**，不表示真实设备量子实验或运行时量子态计算。若现有测量/reset实现绑定量子态，应解决调度模式报告源的接口解耦；不得将精确态后端强加为前置条件。此前 F1/F2 设计中的强制态/Born后端门槛已由本节覆盖，历史参考成果保持其原证据范围。噪声、fidelity与完整通道计算属于独立后续研究，未知质量为null。

## 项目目标与标准流程

目标是在 QEC 协议约束下完成资源生产、接受、维护、交付和 T/injection 调度，算法、工厂、缓存和辅助 patch 共享物理资源与全局时间。逻辑可靠性、fidelity与算法成功率可在独立质量模型中研究，不是当前调度交付的完成门槛。

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
声明的报告轨迹/统计模型 → reports → decoder/frame/接受/库存
                         ↓
资源供需、等待、产能、injection完成与实际调度时间
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

消费者必须使用工厂实际调度生产、接受并交付的同一资源token及其载体，不能在handoff或consumer中凭空创建可用资源。调度层无需存储量子振幅；禁止用改名替代运输、相位转换或编码转换的实际排程。T与T†所需资源标签必须匹配；A−不能直接改名A+，须完成协议规定的转换操作。

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
| 身份与资源 | token ID、资源类型/相位标签、code/distance、carrier atom IDs、epoch、frame/sector、角色与操作provenance；量子state handle仅为可选参考字段 |
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

本节是独立后续质量研究的合同，不是当前纯调度任务的必需实现或验收门槛。未使用质量模型时相关结果为null；声明的调度分支概率不能冒充fidelity或量子通道结果。

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

可选质量研究可采用多尺度模拟：小系统非Clifford态/通道参考验证Born分支和相位；Clifford QEC、运输及读出标定形成明确适用范围的逻辑核；再沿实际调度事件调用。质量研究中的surrogate须注明假设与独立参考资格，不能把调度统计模型当作量子态计算。校准核至少绑定码/距离/朝向、协议顺序、timeline类、noise/decoder版本和相关性范围；超出范围须重标定或拒绝。该研究路线不要求成为调度runtime的量子态后端。

## 模块与证据边界

码、PBC、factory、inventory、decoder 和质量标定属于 experiments 上层；调度/路由属于 strategies；界面与组装属于 app；environment 不导入这些协议/策略。模型扩展必须遵守现有包边界，不直接写 live state、append 未授权 live DAG 或伪造 measurement_results。只有 Executor 提交实际状态。

Pauli/Clifford frame 是经典控制的一部分。延迟纠正必须按 frame 共轭正确解释或变换后续相关 PPM 的轴/符号、接受 checks 和依赖；对易时可保持不变。若选择实际物理纠正，应执行并计成本，不能同时按另一种未执行方案记账。

实现和交付必须分别声明以下证据，不能相互替代：

| 范围 | 必需证据 |
| --- | --- |
| 理想参考 | 独立态/通道 oracle、真实 Born 分支、相位与所有正常分支校正 |
| Native 电路 | 实际门/测量/reset、完整依赖、provenance、载体与分支合同 |
| 合法物理计划 | 平台、placement、routing、全部作用对/spectators、资源/连续轨迹校验 |
| Executor 调度闭环 | 声明报告源在读出完成事件中产生committed reports并决定控制、完整门/运输/反馈时序、RNG/控制器checkpoint、独立初态重放；无需非Clifford态表示与投影 |
| 带噪质量 | 具体噪声/decoder、条件集合、标定适用域、shots/区间与相关性 |
| 完整算法 | 上述组件联合运行、真实资源供应、失败 shot、有效因子与时间统计 |

原生T可排程不代表完整工厂/反馈已调度完成；需全部操作、资源和分支证据。纯调度模式允许不跟踪量子态，但测量/reset仍须经过合法操作、占用和计时，由Executor在完成事件提交声明报告源的结果，不能直接拷贝reference位到live物理键。保持原AOD行列/矩形、支撑、移动碰撞、空阱sweep、实际CZ对、光照和测量区域硬约束；失败证据保留，不放宽约束换通过。

## 实施顺序与验收门槛

优先完成资源供应的小闭环。完整 Shor generator 可作为已有参考或独立工作，但不得代替此主线验收。

| 阶段 | 交付与验收 |
| --- | --- |
| S1 完整工厂调度模块 | 固定d=3完整15-to-1模板；全部输入/检查、报告源、接受/拒收、cleanup、补产/预算、库存及交付；合法原子调度与完整时间线 |
| S2 工厂到单injection调度闭环 | 同一运行committed报告驱动分支；同token/carrier/epoch供给与一次消费、反馈/frame、释放、原初态重放和控制器恢复；不要求量子态后端 |
| S3 完整processor按需接入 | 统一请求/供应接口、多个T需求与共享库存、排队等待/供需竞争、资源唯一消费、算法/工厂/QEC共同排程及可视化 |
| 后续：噪声与质量 | 独立gate/idle/move/readout/QEC标定、缓存老化与逻辑质量模型；输出声明适用范围的质量和统计，不阻塞S1–S3 |
| 后续：MSC backend | 固定surface-code适用协议和门分解，接入同一库存/消费接口；比较后端成本及可选质量 |
| 后续：完整Shor工作负载 | 使用processor接入能力联合调度完整算法需求；调度指标与可选量子参考/算法成功率证据分别报告 |

上述S1–S3是当前任务完成条件。后续质量/MSC研究可独立进行；旧F1参考结果可保留辅助协议检查，旧F2的强制非Clifford/Born后端门槛不适用于本任务。任何阶段保留失败尝试、版本/config/circuit/trace来源与独立反例。

当前调度验收至少覆盖拒收不入账、接受/交付前不耦合算法、重复/过早消费拒绝、等待与资源冲突成本、声明轨迹中的所有正常注入分支/反馈、cleanup与原子重用、预算耗尽、缺报告、原初态重放和恢复。独立MSD量子参考可检验低权错误与接受错误反例；量子质量或完整容错声明需另有对应证据。

本协议固化不改变实现状态。任务结束按 workflow 更新本轮日志和 handoff，只将有本轮对应证据的条目改为完成。

## 来源与按需阅读

- [Factoring15 源码对照](../docs/qec_factoring15_integration_review.md)：实现快照、库存与资源符号、endian/check 映射、reference/ENV 边界；其旧下一批顺序由本协议覆盖。
- [编码资源参考](../docs/qec_encoded_resource_reference.md)、[编码注入参考](../docs/qec_encoded_injection_reference.md)、[Clifford frame](../docs/qec_conditional_clifford_frame.md)：已有受限能力，按 handoff 选择对应源码，不默认加载全部资料。
- [Magic State Distillation Not as Costly as You Think v3](https://arxiv.org/html/1905.06903v3)：MSD 协议和逻辑操作噪声分析；本项目采用模板与噪声参数需分别声明。
- [Magic state cultivation v1](https://arxiv.org/html/2409.17595v1)：原始 MSC 的 injection/cultivation/escape、条件接受及 surrogate 验证；不能把其码与噪声假设当当前平台事实。
- [High Rate Magic State Cultivation on the Surface Code v4](https://arxiv.org/html/2502.01743v4)：surface-code MSC 候选的一手协议；实际门分解、连接与噪声模型须在本项目单独验收。
