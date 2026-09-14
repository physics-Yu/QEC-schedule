# 中性原子编译器：外部实现与本项目架构选择

日期：2026-09-13。状态：调研完成，建议待实施。本文补充[架构路线](architecture_evolution_plan.md)与[A0–A8清单](architecture_evolution_backlog.md)，不修改当前物理模型、编译行为或既有验收结论。

## 1. 结论

最值得借鉴的组合是：**ZAC的任务与复用抽象，MQT的运输感知布局与有界搜索，Bloqade的分层程序表示，QEC专用联合优化作为可选前端。** 没有证据支持直接换成某个公开项目，就能原样满足本项目全部物理合同与带反馈GHZ验收。

我们应把两个问题分别解决：

1. **计算机为什么编译得慢**：前轮已实测重复审计、全量状态编码、历史扫描及几何/量子内核的费用。[性能分析](compile_performance_analysis.md)
2. **编译结果为什么原子搬得多、并行不够**：批次、落点、驻留、门重排与装卸构造之间缺少有效的联合代价。下面的外部工作主要帮助解决这一类问题。

改善第二项不能自动消除第一项；先让候选评估便宜，才有余量比较更好的候选。

## 2. 证据层级与筛选

本轮阅读原论文相关算法/评估章节和官方文档，并静态检查三个项目的选定源码。没有运行外部编译器，没有复现论文速度或保真度成绩，也没有在本项目上做适配后的性能实验。论文报告、源码观察和我们的设计建议分别陈述。

| 工作 | 核心做法 | 对我们的用途 | 本轮证据 |
| --- | --- | --- | --- |
| ZAC，HPCA 2025对应预印本 | 复用分析、分层落点分配、rearrangement job | 首个通用运输任务基线 | 论文＋选定源码 |
| MQT QMAP，routing-aware及2025-12 IDS预印本 | 布局代价考虑运输冲突，限制搜索规模 | 主要算法对照与可替换模块参考 | 论文＋官方文档＋选定源码 |
| Atomique，ISCA 2024 | 阵列映射、原子映射、frontier批次贪心 | 构造合法并行集合 | 论文＋作者项目页、artifact入口 |
| Enola | 门分层、运输冲突图、独立集 | 运输分批的轻量候选算法 | 官方仓库说明；未复现 |
| Weaver，CGO 2025 | 物理指令表示、优化、反推逻辑门核验 | 独立验证接口 | 论文＋官方仓库说明 |
| Bloqade/Kirin/Shuttle | 多种IR、分析与降级pass、执行/可视化解释器 | 分层架构和反馈表示 | 官方文档＋选定源码 |
| NEAT，作者托管DAC ’26稿 | 稳定子门序和辅助原子运输联合约束求解 | QEC离线优化核 | 论文；源码入口本轮未能读取 |

这不是性能排名。Atomique与分区编译器的设备模型不同；NEAT的输入问题又不同于任意门序电路。

## 3. 最接近的三个工程参考

### 3.1 ZAC：先形成搬运任务，再生成控制动作

ZAC把预处理、placement、scheduling分开；复用关系使用二分匹配，门与候选作用站点使用最小权匹配。ZAIR中的rearrangement job记录一批原子的起点和终点，再降级为AOD操作。其逐行装载与parking处理不希望捕获的矩形交点。复用指留在EZ，不等于一直保留在AOD上。[论文§IV–VI、IX](https://arxiv.org/html/2411.11784v3)

源码核查：`zac/zac.py::solve`按调度、复用、初始/中间布局、路由执行；`vmplacer.py`确实调用SciPy最小权满匹配。尤为关键的是，`runtime_analysis["total"]`在写文件及后续verification之前结束，不能与我们的编译＋Executor＋完整记录费用直接比较。[solve固定版本](https://github.com/UCLA-VAST/ZAC/blob/e5083362f99e6915f20c2bd0eaa88b6d1cdcecac/zac/zac.py#L208)、[匹配实现](https://github.com/UCLA-VAST/ZAC/blob/e5083362f99e6915f20c2bd0eaa88b6d1cdcecac/zac/placer/vmplacer.py#L165)

**本项目建议**：在门和细粒度操作之间稳定一个TransportJob接口，携带捕获集合、附带原子、目标holder、可用资源与终态。先比较“驻留/归还”的轻量预测，最终候选再进入精确构造。匹配只保证其编码问题的合法性，不能替代全局CZ作用对或空AOD交点扫掠校验。

### 3.2 MQT：分层不意味着布局不知道运输

MQT的官方接口区分routing-agnostic与routing-aware编译器，后者保留复用分析而替换placer。源码中scheduler、reuse analyzer、layout synthesizer、code generator有独立接口；placement与routing分别计时。[官方说明](https://mqt.readthedocs.io/projects/qmap/en/latest/na_zoned_compiler.html)、[Compiler](https://github.com/munich-quantum-toolkit/qmap/blob/78de4584b570c4c624c9f9c949ae6e9737fcd520/include/na/zoned/Compiler.hpp)、[布局接口](https://github.com/munich-quantum-toolkit/qmap/blob/78de4584b570c4c624c9f9c949ae6e9737fcd520/include/na/zoned/layout_synthesizer/PlaceAndRouteSynthesizer.hpp)

后续IDS工作优先沿最有希望的子节点走到完整落点候选，再从候选队列继续；队列容量与完整候选次数可限制。它是Iterative Diving Search，不是通常所说的迭代加深DFS。论文还研究分阶段装载/卸载带来的relaxed routing；并非允许同时激活的行列互相穿越。该研究的A*搜索对象是整层placement，不是二维通道路径。[论文§3–4](https://arxiv.org/html/2512.13790v1)

源码确实有`IDS`/`ASTAR`分支和`trials`、`queueCapacity`参数；router实现strict/relaxed冲突图与群组调整。以上是代码存在的证据，不是我们复现了其加速。[HeuristicPlacer](https://github.com/munich-quantum-toolkit/qmap/blob/78de4584b570c4c624c9f9c949ae6e9737fcd520/src/na/zoned/layout_synthesizer/placer/HeuristicPlacer.cpp#L619)、[IndependentSetRouter](https://github.com/munich-quantum-toolkit/qmap/blob/78de4584b570c4c624c9f9c949ae6e9737fcd520/src/na/zoned/layout_synthesizer/router/IndependentSetRouter.cpp)

**本项目建议**：底层保留半格通道A*；上层维护有限个完整、可执行的候选，并把“预计分几批搬、几次装卸”反馈给落点评分。现有固定offset刚性策略不能直接照搬其动态行列routing。先在当前能力内比较，再把动态变距作为独立适配与验收课题。

### 3.3 Bloqade：程序表示与解释器是不同层

Bloqade使用Kirin表示和转换程序；Shuttle面向显式布局与运输，官方仍标注开发中。[数字电路与dialect](https://queracomputing.github.io/bloqade/latest/digital/dialects_and_kernels/)、[Shuttle状态](https://queracomputing.github.io/bloqade-shuttle/dev/)

源码可核实：`ScheduleToPath`将schedule表示降级为path表示，并执行公共子表达式与死代码清理；`RuntimeAnalysis`分析分支、循环是否含量子运行操作；`PathVisualizer`是独立的调试解释器。不能因为文件名叫`auto_scheduler.py`就宣称已有自动通用布局器——本轮固定版本中该文件为空。[降级pass](https://github.com/QuEraComputing/bloqade-shuttle/blob/847651eb46b1f6f3571eb2b99500f40cdead0341/src/bloqade/shuttle/passes/schedule2path.py)、[运行分析](https://github.com/QuEraComputing/bloqade-shuttle/blob/847651eb46b1f6f3571eb2b99500f40cdead0341/src/bloqade/shuttle/analysis/runtime.py)、[可视化解释器](https://github.com/QuEraComputing/bloqade-shuttle/blob/847651eb46b1f6f3571eb2b99500f40cdead0341/src/bloqade/shuttle/visualizer/interp.py)

**本项目建议**：采用可分析、可降级的程序接口，继续保持viewer只消费结果。无需现在引入完整Kirin依赖。含测量分支的程序和某个seed的已执行轨迹必须区分；看到框架有measure或if也不等于我们的decoder、读出误差与恢复合同已经可直接迁移。

## 4. 并行与QEC的算法启发

### 4.1 Atomique与Enola：集合构造优先

Atomique从DAG frontier出发，逐步扩充可并行2Q门集合；加入候选时检查额外相互作用、行列顺序和行列重合。它还优化qubit到阵列/原子的映射，而不是只在给定映射上找路径。[论文§III](https://arxiv.org/html/2311.15123v3)、[作者与artifact入口](https://hanlab.mit.edu/projects/atomique)

Enola官方实现提供门调度与基于独立集的运输路由，动画生成是可配置的独立工作。独立集可以帮助分批，但“极大”集合不保证“最大”集合，更不保证最终完成时间最短。[官方仓库](https://github.com/UCLA-VAST/Enola)

**本项目建议**：给每项运输意图建立冲突摘要，用贪心独立集或有限局部交换生成批次。但冲突图只做筛选：三个角上的原子两两看似相容，全部启用却可能在第四个交点产生附带捕获。完整批次仍必须执行Cartesian closure检查。同型1Q的分组必须沿用我们的光学资源规则，不能照搬其他设备的“所有1Q同时执行”。

### 4.2 NEAT：QEC不应只接收被写死的门序

这份作者托管稿从校验矩阵出发，联合安排稳定子门时序、固定数据原子位置及辅助原子移动；实验使用OR-Tools CP-SAT，设置7200秒超时，并用Stim与decoder评估声明噪声下的逻辑错误率。正文仍标Anon，本轮无法读取其匿名源码入口，故不把它视为已复现的成熟组件。[论文§3–5及artifact脚注](https://fangmingliu.github.io/files/dac2026.pdf)

**本项目建议**：增加可选的ProtocolIR前端，保留data/ancilla角色、校验关系、轮次、报告位与允许重排的边界。普通编辑电路仍走CircuitIR，不能强制带surface标签。

联合优化宜先用于一轮、一个小patch或少数相邻轮的离线合成。得到的周期模式必须附适用前提，并经物理与协议检查后才能复用；修改线路、角色、布局、硬件模型或相关噪声合同后重新匹配/核验。不能把“几个方向移动的漂亮模式”硬编码成所有输入的答案。

理想稳定子结果相同仍不足以证明容错等价。门顺序变化可能改变故障传播、hook error和detector关系；测量报告与纠正依赖也不能随意跨越。先维持本项目当前声明的单事件合同。扩展为全电路噪声或新的容错合同，需要单独评审与验收。

### 4.3 Weaver：检查物理程序实际实现了什么

Weaver的wQasm表达运输和光操作；wChecker先根据移动后的布局将脉冲反推为门，再做功能等价检查。其示例与优化涉及本项目没有的3Q能力；酉等价路线也不能直接覆盖测量、reset和反馈。[论文§4、6](https://franciscoromao.github.io/files/Weaver_cgo25.pdf)、[公开artifact](https://github.com/TUM-DSE/weaver)

**本项目建议**：独立检查器应从操作、位置和激光覆盖恢复实际作用集，再与输入语义对照，不仅相信compiler自报的requested gates。对带测量的QEC使用读出/条件/稳定子合同；不要尝试构造68比特完整酉矩阵来验证。

## 5. 我们应怎样组织联合优化

以下是本项目建议，不是上述论文已经提供的统一系统：

```text
可编辑CircuitIR ────────────────┐
可选ProtocolIR → 合法合成/重排 ─┤
                              ↓
                    依赖与经典反馈边界
                              ↓
             门批次 ↔ 落点/驻留 ↔ 运输分组与成本
                              ↓
                  有界候选集 + 已验证可行方案
                              ↓
        TransportJob → 装载/通道/卸载 → OperationIR
                              ↓
              资源调度 → 独立核验 → Executor
                              ↓
                执行记录 → 回放 / 协议评估
```

中间三项需要交互反馈，但通过明确接口交换代价与约束，不共享整份trace或仿真私有真值。分层边界是职责边界，不应成为“一次性选错落点后不能回头”的硬隔断。

**为什么最短路径仍可能得到慢结果？** 设两个合法方案都搬8个原子：甲路径更短但要分4批，乙稍远却只需1批。若每批装卸耗时为正，乙可能更快。应比较整批关键路径、装卸、等待与终态费用，不能仅比较8条路径的距离之和。这是说明性例子，不是本项目实测数字。

评分先满足硬约束，再优先最小化包含声明终态的预测makespan；装卸次数、距离、后继可用性用于估价或打破平局。除非有校准模型，不把不同论文的保真度乘积或运输时间公式当作本项目精确物理代价。

## 6. 对A0–A8路线的具体补充

| 工作包 | 本轮补充 | 可审查的完成条件 |
| --- | --- | --- |
| A0 | 固定“纯规划/验证执行/记录导出”计时口径；建立外部模型差异表 | 每个比较标明计时范围；相同输入、硬件、初态、终态与预算 |
| A1–A3 | 继续先降低候选评估与历史编码费用 | B0/B1通过；无搜索的已保存H计划也显著减少重复工作，数值由实测给出 |
| A4 | 明确TransportJob、捕获闭包、可复用路径服务；保留合法构造基线 | 任意支持门集输入可尝试编译；族外明确报告限制，不伪造成功 |
| A5 | 补充落点—批次双向代价接口，比较匹配/冲突分批/IDS式有界候选 | 公平基准记录结果质量、失败率、首次可行解时间和峰值内存 |
| A6 | 把ProtocolIR与离线周期核作为可选前端；与反馈可见性合同衔接 | 编辑破坏模式后自动退回通用路径；理想与声明故障合同分别通过 |
| A7–A8 | 编译产物与某次执行动画分别交付 | 仍能手动编辑→编译→播放；失败可定位到具体阶段 |

A0–A8的既有依赖和审批边界不变；本轮没有把这些建议标为已实施。

建议首次算法试验选**当前rigid平台的小型同布局对照**：保留既有策略，新增“运输感知批次＋落点”候选，独立规划后由同一个Executor验证。先测普通随机电路、规则CZ层、打破对称的CZ层，再测小patch抽取。动态row/column能力另做适配，不能为提高论文对标成绩而隐含启用。

对于重复QEC轮，后续单独比较“已验证周期模式”“通用贪心”“有限联合优化”。周期模式作为一个可行候选参与比较；接口相容且剩余任务相同时可保留最佳完整方案。不能声称逐步贪心总能beat对称基线，也不能只挑成功案例。

## 7. 复用与核验边界

- 当前5μm单比特间距、1μs时长、2μm CZ几何代理、半格正交通道、SLM开关及全部活动AOD交点校验均保持。其他编译器采用的数值或能力不自动覆盖本项目设置。
- ZAC/MQT的分阶段parking可启发更强装载器，但路线、空阱扫掠、支撑交接与活动行列顺序仍须逐项验证；本轮没有验证这些外部构造在当前backend上可执行。
- “带QEC示例”不等于完整实时decoder、所有测量分支或容错证明。通用电路编译能力和特定协议认证是两件不同的验收。
- 本轮不宣称其他项目都不做碰撞校验，也不宣称它们存在和我们相同的逐事件全量验证成本。源码只支持已经明确列出的观察。
- 复用代码前核对具体文件许可证与依赖。留存的ZAC为BSD-3-Clause、QMAP为MIT、Shuttle为Apache-2.0；本轮保留原LICENSE，未将源码并入生产包。

## 8. 可复查资料

三个源码快照及逐文件URL/SHA-256在[来源清单](../artifacts/compiler-research-2026-09-13/source-manifest.json)。固定refs：ZAC `e5083362f99e6915f20c2bd0eaa88b6d1cdcecac`；QMAP `78de4584b570c4c624c9f9c949ae6e9737fcd520`；Shuttle `847651eb46b1f6f3571eb2b99500f40cdead0341`。快照只包含选定模块与许可证，不是完整可运行发行包；可按清单URL重新取得。

相关记录：[本轮日志](../instruction/logs/2026-09-13-external-compiler-research.md)。本轮未运行外部benchmark、生产测试或GUI验收，因为交付范围是调研与方案。
