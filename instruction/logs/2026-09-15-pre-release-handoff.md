# 发布前交接摘要归档 · 2026-09-15

这是本次整理前的历史摘要，保留当时的状态；其中“未推送”、端口、PID、OPEN 不能作为当前状态。现状见 [handoff](../handoff.md)。新增 RL 工作未纳入此归档。

# 当前交接状态

**2026-09-15 测量清单12–14策略化完成：** http://127.0.0.1:8798/ （PID26368）。`ReadoutPlacementPolicy`显式注入有序QEC服务，自动/仅AOD/仅SLM、非平移目标候选、上层低成本评分→有限movement实现→实际成本反馈；配置`configs/strategies/readout_placement.json`，无物理核改动。Q019原初态服务2146.543→1662.379 μs，真实执行及逐字重放通过。完整483槽/66计划双方物理、量子、终态、重放PASS：贪心24337.381 μs，SMT24975.219 μs，8次测量服务自动选AOD，LOAD/OFFLOAD各35→27。43不同Python测试、139模块边界、HTTP编辑编译与离线32×完整回放PASS；真实GUI连接失败仍未验收。第12–14项旧限制在本工作台FIXED，旧未注入策略调用保持兼容流程；测量后返回等其他清单项不变。main未提交推送。[报告](../docs/readout_placement_policy.md)、[日志](logs/2026-09-15-readout-placement-policy.md)。

**2026-09-15 Q019 / 5241 μs 调查（OPEN）：** 8797 SMT第12计划为4辅助原子送MZ测量，Q019总需向左10 μm，当前拆为7.5+2.5；固定目标时2.5+7.5同样合法且同耗时。但`measurement_destinations`曼哈顿距离平局按坐标排序，`readout_service`首个合法即返回，漏掉更快落点。5候选实际编译中，目标(10,-180)比现用(5,-175)完整服务快26.704 μs，先提取2.5 μm；两方案分别真实Executor执行，量子态/测量结果/归位/AOD/开关终态一致。本轮仅调查，未改生产策略或替换整条动画，未做GUI验收。下一步应在测量落点层比较真实完整服务成本。[证据及日志](logs/2026-09-15-q019-measurement-target-audit.md)。

**2026-09-15 Q000 / 783 μs 策略修复与新交付：** http://127.0.0.1:8797/ （PID10936）。确认旧通道模板遗漏直接Y→X/分轴到位候选，原后端并不要求绕路。共享 `axis_hold` 路线已独立于硬件接入贪心、SMT及群组运输；新增 `row_column_orthogonal` 只约束正交原语。固定原8门/原落点/原后端，Q000出站13→8 μm，该批1036.065→787.172 μs。完整34原子/483槽双方66计划独立重放、终态、XX/ZZ与稳定子/测量协议PASS；贪心27990.467 μs，SMT28628.305 μs，仍17CZ批/最大9并行。54项Python检查、138模块边界、离线编辑与双模式32×完整回放PASS；HTTP五槽编辑电路双策略PASS。真实GUI验收未完成：内置连接失败，桌面工具因无法可靠识别URL终止。编辑器改为逻辑层分页、独立CZ连线、选中编辑/插入/删除。产物`artifacts/qec-axis-hold/attempt1`；main未提交推送。仍有限候选，不是完整高维最短路；下一步补GUI验收及目标选择的实际路线成本反馈。[报告](../docs/axis_hold_strategy_fix.md)、[日志](logs/2026-09-15-axis-hold-strategy.md)。

**2026-09-15 QEC GHZ / 有序行列 SMT 对照完成：** 新入口 http://127.0.0.1:8796/ （PID14996），完整34原子/483槽、105CZ、32测量/32复位与Y(Q013)恢复；双方同row_column后端、新2.5μm占据避障路线、共同SZ/EZ/MZ服务及终态。贪心32017.276μs，SMT32322.577μs；均17批CZ/最大9并行，SMT未改善本例物理时间。两者66计划独立重放checkpoint逐字一致、XX/ZZ及16稳定子+1、完整协议/归还PASS。修复关闭目标SLM的人工折返；物理核不变。可编辑UI支持阶段跳转、双策略动画、预算/依赖错误弹窗、每原子CSV；6新测试与24回归全部最终通过，架构137模块0违规。产物`artifacts/qec-ordered/attempt2-direct-transfer`，首轮保留；main未提交推送。仅当前frontier最大批次SMT，有限路线/空轴构造/每批归还，不是全局多阶段最优。[报告](../docs/qec_ordered_smt_comparison.md)、[日志](logs/2026-09-15-qec-ordered-smt.md)。

**2026-09-15 ROUTES V2：** 用户明确“关格点”是把SLM原子占据格标记为搜索障碍，不是物理关阱。8794已更新至PID21508和attempt4-discrete-grid：2.5μm离散路线、占据格预筛选、同向直行合并、拐弯/反向保持停点，全段重新物理审核；修复ProgramBuilder浮点sum与interval终点差1ULP导致完成事件过早。5例10运行及独立重放全通过，71不同专项最终通过，134模块边界PASS，十计划正交/无多余直行停点；真实编辑编译与双模式32×终点验收。仍有限候选，不是完备高维A*。未提交推送。[报告](../docs/ordered_routes_v2.md)、[日志](logs/2026-09-15-ordered-routes-v2.md)。

**2026-09-15 有序行列贪心扩展：** 新实验 http://127.0.0.1:8794/（PID20892），同一 row_column 后端比较同位移与独立有序行列合批。保留全部物理校验与环境边界；5例10次真实执行/完整终态/逐字重放通过，三列3批→1批、二维4批→1批，物理时间分别减少59.0%/70.5%。发现扩大beam空间使闭包退化，已用同位移incumbent保护修正并保留attempt2失败性能证据；attempt3为正式结果。39不同专项测试、133模块架构检查、真实内置浏览器编辑编译/32×终点/失败弹窗/四对CZ核验。限16原子16门、每批归还、有限通道搜索，非通用最优或跨批驻留。未提交推送。[报告](../docs/ordered_axis_greedy.md)、[日志](logs/2026-09-15-ordered-axis-greedy.md)。

**2026-09-14 对外 README / Demo 发布：** README 已按新用户的项目目标、已实现能力与限制、快速启动、实验和架构重写。`demo/` 为精选对外入口，含完整可编辑工作台、SMT 编辑对照与12条参考动画、历史四逻辑GHZ完整回放（约41MB）；`python demo/launch.py` 动态配置后端端口，新任务写 `artifacts/demo-runs`，不依赖旧 artifacts/job。全新 Git 暂存树导出目录（含空格中文）、新venv仅安装 `.[smt]`，真实浏览器18项通过；60项回归、131模块边界检查通过。修复导出提示转义和GHZ旧本机链接，内嵌执行不变。Windows实机验证，macOS/Linux未实机；无本轮完整QEC重编译。用户授权发布当前实现到GitHub main，详见 [发布核验](../docs/demo_delivery_validation.md)、[日志](logs/2026-09-14-public-demo-entry.md)。

**2026-09-14 SMT 联合批次实验完成：** 用户授权按 OLSQ-DPQA 讨论实施小规模对照；新增策略包 SMTBatchPlanner 和独立实验应用 http://127.0.0.1:8793/（PID3188），支持编辑 H/X/Y/Z/T/CZ 并手动重编三个策略。固定 EZ/10μm/单 rigid AOD/每批回原SLM，同初态同终态；四案例两轮24次真实执行与逐字重放通过。矩形闭包：贪心1366.9μs(3+2+1)、SMT单步984.6(5+1)、多阶段874.6(2+4)，物理时间降36%；交叉依赖多阶段降15.9–16.6%但编译更慢；其余两例无物理收益。64项核心+7项显示回归、131模块依赖审计、26项Edge UI检查通过；UNKNOWN与物理失败区分、失败弹窗及证据保留。修正viewer按序号误标区域的问题；物理规则未改。未接通用变距/任意EZ落点/跨批驻留/RL，未改原工作台策略，未提交推送。[完整报告](../docs/smt_batch_experiment.md)、[日志](logs/2026-09-14-smt-batch-experiment.md)，证据artifacts/smt-batch/。下一步优化模型复用/安全horizon下界，再比较同预算质量。

**2026-09-14 全demo电路核查完成：** 用户质疑连续X/Z与缺失transversal CNOT，后续要求保留现有显示只明确定位。五份保存门列表与生成器一致；两逻辑CNOT为显示39列目标块Q009–Q017的9H、40列QEC0302–QEC0310的9CZ，原末尾9H与后续同wire H相消。连续X/Z为互斥条件分支；完整Pauli作用、缺CZ负例、HH消去、三个QEC demo的seed0/7/29 raw/optimized完整量子态与报告位对照通过。[定位/范围](../docs/demo_circuit_audit.md)、[日志](logs/2026-09-14-demo-circuit-audit.md)，复现tools/audit_demo_circuits.py。未改生成器/JSON/UI/物理、未重编运输动画；现有8792入口保持。

**2026-09-14 环境/策略/控制应用分离完成：** 67模块迁移、3个混合模块拆分，`neutral_atom_env`承载模拟平台，算法在`neutral_atom_strategies`，工作台/作业在`neutral_atom_app`，协议与场景在`neutral_atom_experiments`。统一`NeutralAtomEnv`与外部`Strategy/ControlProgram`；128模块依赖审计、六策略完整checkpoint逐字对照、真实UI编辑/手动编译/32×终点通过。全仓1585项执行：首次1572过13败（旧fixture/guard适配器/前端测试宿主），最终13项精确补验全部通过，再验边界与工作台27项通过；详见[本轮日志](logs/2026-09-14-environment-strategy-separation.md)。新入口 http://127.0.0.1:8792/?job=526d214eb69a4aff990e4a58621cab96 ，4门954.3μs/38操作，PID14084；物理/schema19保持。旧Python算法导入路径迁移，无反向兼容壳；缓存删除被自动审批拦截，仅保留忽略的pyc。下一步统一候选决策接口并收紧PlanningView；未实施RL/通用二维搜索、未重编完整历史GHZ。见[现行包边界](../docs/environment_strategy_boundary.md)。main工作区未提交推送，前轮配置改动保留。

**2026-09-14 配置文件固化完成：** 通用算法/预算/初态/电路目录统一读取 `configs/studio/workbench.json`，五份完整锁定 demo 读取 `configs/studio/demos/*.json`；前后端共用，启动校验。57项相关回归通过，最终6项配置专项重验通过（重叠），五份 demo 规范化输入迁移前后逐字一致。新入口 http://127.0.0.1:8791/?job=679c19d84cd444c680517fdd71dedec9 ，既有结果恢复、真实UI加载及无脚本错误通过。自动审批拦截停止8790服务，故旧服务保留，新配置在8791运行。修改JSON后重启服务、刷新页面；旧草稿不被默认值覆盖。物理/schema19不变，main工作区未提交推送。见[配置说明](../configs/studio/README.md)、[日志](logs/2026-09-14-studio-config-files.md)。

**2026-09-14 最新配置减法与分层已交付：** http://127.0.0.1:8790/?job=679c19d84cd444c680517fdd71dedec9 （PID19496）。顶部完整demo锁定、自定义仅六种通用策略（含单原子搬运），纯电路示例仅写gates；GHZ专用设置不再混入用户通用选项。AOD字段为相对偏移，容量/绝对位置派生。发现旧通用多交点规划器只支持1×N、10μm等间距，已前移能力检查，非均匀可预览保存但禁编译，原失败保留。76项回归+19项边界重验（重叠）通过；真实UI自定义4门954.3μs/38操作及32×完整播放，四H锁定demo1μs，GHZ4锁定/草稿恢复通过，无console errors。新源码位于main工作区，未额外提交推送。详见[配置归属与路线](../docs/studio_configuration_layers.md)、[日志](logs/2026-09-14-studio-layers.md)。输入v2/通用二维运输/QEC协议解耦仍待实施，未重编完整GHZ；旧服务未动。

**2026-09-14 最新：独立逐原子统计已完成，用户要求唯一分支统一为 `main`。** `statistics.AtomStatistics` 从已提交 trace 增量统计每原子路程、装卸、实际门数、忙碌与等待；VisualRecorder/工作台 worker/离线 CLI 输出 JSON+CSV，schema19 与物理模型不变。最终29项专项通过，现有四逻辑68原子/8360记录独立补算：62282μm、853/853原子次装卸，实际门计数与旧审计一致，347未触发槽排除；未重新完整编译或量子重放。接口与限制见[统计合同](../docs/atom_statistics.md)、[本轮日志及Git核对](logs/2026-09-14-atom-statistics.md)。GUI逐原子表未新增；旧服务需重启加载。后续从main继续，以下snapshot默认分支记录为本次规整前历史。

**2026-09-14 分支规整完成：** GitHub `physics-Yu/QEC-schedule`仅保留`codex/snapshot-2026-09-14`并设为默认。已删除main、旧execution-refactor及revert分支；当前完整文件基线37012c4保留，历史bundle仅存本地。见[清理日志](logs/2026-09-14-branch-cleanup.md)。后续从此默认分支继续，架构迁移仍未开始。

**2026-09-14 Git阶段快照：** 用户指定仓库`physics-Yu/QEC-schedule`，本次分支`codex/snapshot-2026-09-14`基于远端main的`dcc849f`，范围为源码/配置/测试/文档/复现脚本，artifacts沿用忽略规则。README同步当前门集、手动编译与schema19；62项专项测试、248个Python语法及13个JSON检查通过，未跑全仓suite或新完整GHZ。远端提交结果以Git分支为准；[日志](logs/2026-09-14-github-snapshot.md)。架构A0–A8仍待实施，建议下一步先统一计时和减少重复计算。

**2026-09-13 外部编译器调研完成，尚未适配/跑分：** [对比报告](../docs/external_compiler_research.md)、[日志](logs/2026-09-13-external-compiler-research.md)。核查ZAC/MQT/Shuttle选定源码32文件及论文，建议补充TransportJob、落点与运输批次的双向代价、有限候选搜索和可选QEC离线周期核。原A0–A8仍待实施；物理模型、生产编译器与动画未改。NEAT仅论文核查，不能宣称外部方案已在本平台验收。

**2026-09-13 分层架构路线已交付，迁移待实施：** [目标架构](../docs/architecture_evolution_plan.md)、[A0–A8工作包](../docs/architecture_evolution_backlog.md)、[日志](logs/2026-09-13-layered-architecture-plan.md)。设计拆分program/run/verification产物、静态/当前/历史数据、报告位与仿真私有真值；保留物理核与唯一Executor，通过兼容适配逐层替换。111文件只读import审计及源码哈希在artifacts/architecture-review-2026-09-13。B0字节/B1语义/B2策略验收分开；新schema/核验边界/反馈合同为PROPOSED，未改生产源或动画。建议先实施A0+A1，不能把设计文档当作新API/性能已落地。

**2026-09-13 编译性能分析完成，尚未实施优化：** 当前四块输入四邻guard已False，路线已有A*与部分合法矩形构造。新只读统计发现466MB trace中约415MB/88.97%来自各计划initial_dag；当前Executor前三保存计划68事件逐字PASS，43H单脉冲样本含cProfile耗时4.527s、3次完整计划审计，说明重复状态/审计与量子构造成本独立于搜索。生产源码与动画未改；方案含兼容缓存/空间索引、动态合法域、路线复用与需另审的状态/hash分层。[分析报告](../docs/compile_performance_analysis.md)、[日志](logs/2026-09-13-compile-cost-analysis.md)。下一步P0阶段计时+P1字节兼容复用；不得将分析结果写成已加速或完整编译基准。

**2026-09-13 完整动画交付：** http://127.0.0.1:8789/animation.html ，静态服务PID27044；离线文件`artifacts/deliveries/ghz4-animation/animation.html`约41MB，另有circuit.json与带来源哈希的delivery.json。复用当前链接已编译四逻辑68原子/1868槽完整记录，默认关键帧32×，本轮真实Edge完整播放124.75秒PASS，68原子归还初始holder/坐标、终点105285.60000000036μs、无page errors，离线打开PASS。没有重新物理编译；可编辑8788仍保留。[本轮日志](logs/2026-09-13-compiled-animation-delivery.md)。

**2026-09-13 回放交互最新修复：** 用户指定两个agent（设计审查+真实GUI）；已确认并修复播放按钮屏外、画布普通滚轮吞页面滚动、批H/CZ/测量/复位定位禁用。8788同实例源已更新：顶部吸顶播放/时间轴、暂停状态、μs跳转/终点、Ctrl+wheel缩放、空格/左右键、聚焦原子、专注回放；静态预览禁用播放且不冒称周期完成。12项专项及Node检查PASS；真实GUI全动作PASS，最终1440×900播放和完整画布同屏、吸顶有效，无脚本错误/无编译请求（仅favicon404已记录）。证据`artifacts/replay-interaction-layout-final/review.json`，[日志](logs/2026-09-13-replay-interaction.md)。没有改物理/编译；旧已打开页面需重新载入新静态UI，未替用户刷新或丢弃草稿。

**2026-09-13 策略预设补充：** 同一8788工作台「配置管理 → 内置策略配置」已补回M4四策略、二维patch两策略、单轮QEC三策略，带既有搜索默认值并保留编译时限；推荐/基线保留。预设仅改compilation，不改门/初态/协议；不适用项可见但禁用，多轮QEC仍使用带历史校验的联合优化。真实Edge验证九项后端派发和线路隔离，手动lookahead四H实际并行1μs，无自动编译或page error。[日志](logs/2026-09-13-compilation-presets.md)，证据`artifacts/workbench-presets/acceptance.json`。

**2026-09-13 最新工作台界面交付：配置分层与精简已完成并验收。** 使用 http://127.0.0.1:8788/?job=87eef4dc58e467e0e6b423bfda158c43 ，PID23976，输出 `artifacts/workbench-configurations`，旧8787保留。主页面为线路与回放，平台/编译分别命名保存与导入导出；AOD容量由行列派生；自动编译已删除，只有线路区按钮启动。`circuit_profile` 与 `compilation` 独立，模板保留编译配置，legacy精确兼容，未支持的多轮基线明确拒绝。关闭SLM为淡点，空/关闭可分开隐藏，实际原子/全部活动AOD交点保持。157项workbench测试及5项viewer专项通过；真实Edge配置隔离、4H并行1μs、读取完整1868槽、实际六门4006.6μs（真实0/报告1）通过，无page errors；1440/720无水平溢出。证据 `artifacts/workbench-cleanup/acceptance-attempt5/browser-acceptance.json`；[本轮日志](logs/2026-09-13-workbench-configurations.md)、[配置合同](../docs/workbench_configurations.md)。没有重跑历史小时级完整编译/重放，没有改变物理模型。新API请用8788（旧进程只更新静态UI，Python resolver仍旧）。

**当前状态：四步1–4及4A/4B/4C均按声明合同PASS。** 最新可编辑四逻辑GHZ工作台 http://127.0.0.1:8787/?job=87eef4dc58e467e0e6b423bfda158c43 ，PID28532，输出`artifacts/workbench-qec-temporal-four`；保存实例来自`artifacts/qec-roadmap/step4C-resumed-attempt3`。68原子/1868门与控制槽，完整物理105285.6μs，515计划/8360事件独立重放逐字PASS（2393.463秒），32码稳定子及XXXX/三ZZ为+1；双32×完整UI及六门真实编辑编译4006.6μs通过，全部68原位归还，无page errors。后缀续编译631.276秒/47服务已明确标注，原1588槽/468计划前缀及工程超时均保留。没有运行中的验收worker，服务继续提供编辑与回放。用户审批边界保持：工程缺陷自行修复记录重验；物理事实/硬约束或整体架构调整才请求批准。范围为三轮声明单事件噪声与完美闭合轮，不是全电路噪声容错、任意布局最优或大型电路性能问题已解决。见[最终报告](../docs/qec_temporal_four_acceptance.md)、[本轮日志](logs/2026-09-12-engineering-retry-policy.md)。

4B底层57项、接口/调度26项和时域协议222项（含211事件）均PASS。完整916槽/80MEASURE/80RESET/249CZ为46463.3μs、88装卸；编译1235.164秒，独立256计划重放641.370秒、checkpoint逐字一致。真实UI双32×完整归还34原子，测量真0/报告1提交后才显示；另六门实际编辑编译2586.6μs通过。证据`step4B-attempt1/verification.json`及`step4b-ui-attempt1/browser-acceptance.json`。4C使用独立四块布局、同7×14=98交点AOD、超高群组分批运输；最终状态已见上方。契约[4B物理验收](../docs/qec_temporal_attempt1.md)、[四块协议](../docs/surface_qec_temporal_four_protocol.md)。

历史attempt1漏参、attempt2撤销测试失败及审批已保留在账本和[旧失败报告](../docs/qec_step4_attempt2_failure.md)。attempt3修测试自然Tab后4A全PASS，不重跑已通过矩阵。错开布局36861.8μs/65装卸性能退化详见[布局分析](../docs/qec_generalization_layout_analysis.md)。

**四步路线最新成功结果（2026-09-12）**：步骤1/2/3及后续第四步正式PASS，第四步见上方。最新联合策略481槽为19255.9μs、37轮装卸（原基线22055.9μs/51轮），同分支/纠正/终态、120计划独立重放、真实编辑及双模式32×全通过，编译206.696s。可编辑新结果 http://127.0.0.1:8784/?job=03a43acfc3a55199bc9ce6d971d37a92 ，PID28316；[详细比较](../docs/qec_joint_acceptance.md)。第四步按上方恢复点执行；[预先合同](../docs/qec_generalization_attempt1.md)。见[本轮日志](logs/2026-09-12-qec-four-step-roadmap.md)、[总验收合同](../docs/qec_four_step_acceptance.md)。只读看板 http://127.0.0.1:8782/ ，PID26780，持久账本`artifacts/qec-roadmap/status.json`为当前状态。以下GHZ₂仍是有效已通过基线，所有旧服务和产物保留。

更新：2026-09-12。最新已完成用户要求的**两个逻辑 surface qubit 的测量制备、GHZ、稳定子抽取和单数据错误纠正**，保留可编辑线路→物理编译→Executor→共用viewer。checkpoint **schema19**（旧18从input重编译），viewer /2。范围为理想读出下的单数据Pauli错误恢复，不能称完整噪声容错或完整M5/M6。

## 最新交付

- 先读[本轮日志](logs/2026-09-12-surface-qec-ghz2.md)、[完整实验与证据](../docs/surface_qec_experiment.md)，接口见[量子读出核心](../docs/quantum_readout_core.md)、[测量协议](../docs/surface_qec_protocol.md)、[工作台](../docs/qec_workbench.md)。此前“只核验未授权测量扩展”已由用户最新请求取代。
- 当前可编辑结果：http://127.0.0.1:8781/?job=55831b7d3be24c56ada3cd4958460db2 ，新模板 `?example=surface-qec-ghz2`。服务PID28100、输出`artifacts/workbench-surface-qec`；正式离线产物`artifacts/surface-qec-ghz2/browser`。旧8769服务未动。job内存有时效，input/离线HTML持久。
- 两块二维[[9,1,3]]，18data+16ancilla；AOD7×14=98交点、非均匀列、真实捕获闭包/空阱扫掠/2.5+5k正交通道/全CZ作用对保持。QEC门集H/X/Y/Z/CZ/MEASURE/RESET，T在QEC明确拒绝，普通编辑器仍支持T。单比特固定1μs、同类并行、≥5μm；MEASURE/RESET必须MZ，500/100μs是仿真假设。
- 正式实际编辑seed7、Y(Q000)：481门/控制槽全部执行，105CZ→33pulse，最大9并行；32次目标测量和32次reset，各8批。实际prepare纠正Z(Q011)，final根据非零syndrome执行Z(Q000)+X(Q000)。184条件槽中181不打光。全程22055.9μs，编译189.438s（本机单次观测），51轮装卸仍有优化空间。
- 物理重放中纠正前XX/ZZ=-1/-1，纠正后+1/+1且16码稳定子全+1；32位读出真实提交，协议完整。93plan compiler-free重放及schema19checkpoint逐字一致，481效果exactly once，34原子归还原SLM。真实Edge编辑→编译、测量中点无预读、false条件无光、两种模式32×全程通过，无page error，正式运行源码未变。
- 本轮74项量子协议（含54单data故障与12随机seed）、109项核心及最后30专项、44项工作台、root5项集成/几何/序列化通过；有交叉不相加。**未跑全仓库suite**。HH及DAG传递约简、不可变运行节点复用和等价序列化快路径减少重复工作；没有放宽校验。
- 下一步：先以正确QEC协议评估辅助附带捕获集中读出、减少51轮装卸，再做重复纠错轮、测量噪声时域decoder和四逻辑GHZ。当前不是全电路噪声容错；旧36data无测量实验9.23%比较不能套到新QEC。完整M4仍是受限平台族验收，不能据此宣称任意布局最优。

## 旧二维无测量实验（历史对照）

历史[电路范围审计](logs/2026-09-12-surface-circuit-scope-audit.md)：36data无测量酉编码的理想GHZ正确，但不是完整surface-code syndrome过程；找到28对HH可消去、194→138门，未给这份旧优化输入重做物理成绩。此后用户已授权并完成上方新的GHZ₂测量扩展。下方9.23%只适用于旧36data输入；“未实现测量”的旧范围表述不代表最新QEC模式。

- [本轮日志](logs/2026-09-12-surface-2d-parallel.md)、[二维交付合同](../docs/surface_2d_experiment.md)、[二维研究](../docs/surface_2d_research.md)、[批量合同](../docs/batch_cz_contract.md)、[失败与排序分析](../docs/patch_ordering_analysis.md)。
- 四块真实3×3旋转[[9,1,3]]，36数据原子，4块原点(0,0)/(40,0)/(0,40)/(40,40)，局部10μm。完整194门（135H+59CZ）理想编码和4逻辑GHZ保持；32码稳定子+4逻辑稳定子以及实际效果顺序均验证。
- AOD两组非均匀axes=(0,10,20,40,50,60)，**6×6=36容量**；rigid只保持相对几何，不再强制等间距。开行×开列决定全部活动交点，可隔原子抓；空交点、捕获闭包、完整运输扫掠仍检查。本轮策略尚不搜索运输中的动态变距。
- 四邻格保护按用户授权可关闭：`ez_neighbor_guard_enabled`默认True，surface模板显式False；关闭不影响其他物理硬条件。门集H/X/Y/Z/T/CZ，1Q固定1μs、同类型并行、邻距≥5μm；CZ整批actual==intended。
- 相同二维输入/同原始归还终态：**patch_symmetric 8978.2μs → patch_greedy 8149.2μs，省829μs/9.23%**。两者194/194，保留真实9+18门并行批。AOD路程1864→1449μm；装卸仍26/26。编译109.70/112.23秒为并发本机单次观测，不是统计性能加速比或90秒保证。
- 保留初版错误贪心`artifacts/surface-2d/patch_greedy_initial`：14082.1μs、最大4CZ，跨块27门被拆为14批而非2批。额外13轮装卸2600μs+移动2486μs+CZ3.9μs+Raman14μs=5103.9μs损失。新策略按几何分量优先块内READY工作、增加同源行/列闭合子组；局部平均成本仍不是全局最优。
- 当前可编辑成功结果：http://127.0.0.1:8769/?job=35d259897145482e86032c24ed54a591 。模板：http://127.0.0.1:8769/?example=surface-ghz 。服务PID15860，输出`artifacts/workbench-surface-2d`。报告入口http://127.0.0.1:8780/，PID13488，目录`artifacts/surface-2d`。
- 真实headless Edge（不是操控用户当前tab）完成194→加H195→撤销194→点击编译、9/18对绘制、32×物理11.282s/关键帧17.406s全程、终态与深链接恢复，无page error。正式运行源码py/js/html起止稳定。基线独立离线Edge核对36红原子/18连接线、坐标等比例。

## 接口与后续

- 工作台：`visualization/workbench.py`、`workbench.js`，支持rows/columns、aod_row_offsets_um/aod_column_offsets_um、guard开关；128原子、4096门/列、总AOD容量≤128。surface模板只给36数据原子；可任意编辑受支持门，具体几何仍可能有限搜索失败，不能保证所有布局可行。
- 新策略：`simulation/patch_greedy.py::run_patch`，组装运：`motion/patch_array.py`；新pulse接口`ProgramBuilder.add(...,gate_ids=...)`，单pulse多效果恢复和记录见batch合同。`examples/verify_m3.py`展开批量效果做逐门exactly once。
- 验证：patch/row/量子16项；修订后patch4项+三角闭包子组1项；batch/M3专项43项；API/guard/shape/旧输入63项；其他有交叉专项见日志，不重复相加。**未重跑全量suite**。最终两正式产物已用最终代码做compiler-free物理重放，checkpoint逐字一致，结果在各目录verification.json。另真实编辑H/X/Y/Z/T+跨patchCZ六门1137.3μs验收通过，证据在edited-smoke。
- 限制：空间分量按占据点最小距离推断，异构各向异性布局可能识别为多个行组，仅是启发式。动态轴重构、多个独立AOD、测量/复位/连续QEC和全局最优仍未完成。已补“本地候选全失败→剩余预算跨分量回退”，4项故障注入通过，正式成功路径保持；最终代码物理重放在补丁后完成。
- 下一步优先：在固定正确物理模型下做多种编辑电路/非对称二维布局矩阵；再研究按依赖同步cohort、减少恢复次数、动态非均匀轴重构。离线balanced_closed预测不得冒充执行成绩。

## 历史

旧单行GHZ保存在`artifacts/surface-ghz`及[旧实验合同](../docs/surface_ghz_experiment.md)，不能用其3.12%或单行图当本轮二维成绩。原8769旧job因服务重启失效，离线文件保留。原handoff全文已归档[修订前交接](logs/2026-09-12-pre-surface-2d-handoff.md)，不默认重读。8766/8767/8768旧服务未修改。
