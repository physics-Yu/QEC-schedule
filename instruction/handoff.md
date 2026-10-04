# 当前交接状态

## 2026-10-05 独立双 AOD 运输模块

新策略 `AODTransportModule.compile → coordinate_aod_modules → bind_block(required geometry_guard)` 绑定完整初态/RF/profile和精确审核inputSHA；同设备END链、真实ATOM/AOD/显式共享资源占用分别协调，取消隐式跨设备归还等待。唯一scheduled KernelExecutor执行。真实34原子/左右各17、两台5×5完整RF（各8空活动交点）、68有限5μm SLM位；14ops/31journal，并发541.260859854213μs vs同profile串行992.6458955524499μs，减少45.472916%。resource451.385035698237μs已回home/SLM时data仍return MOVE，提前89.875824μs；双带载MOVE重叠190.692518μs。

独立Fraction/Bernstein连续证书42时间分区/51612配对（23562atom、28050Cartesian-spectator）、最小保守10μm；运输硬阈值仍1μm。并行/串行actual journal和原初态完整checkpoint重放PASS，两处在途coldrestore journal exact，recording开关语义一致。166不同pytest（85冻结回归＋81新/边界）、281模块0违规；真实8782书签、设备lane、缩放/窄屏和console检查见[验收](../references/qec_pbc_validation/modular_aod_2026_10_05.json)。attempt1物理PASS但浏览器发现QMAP默认caption误标，source观察器adapter修复后正式attempt2重新生成并绑定manifest；旧attempt不覆盖。

入口[模块合同/复现](../docs/modular_aod_transport.md)、[日志](logs/2026-10-05-modular-aod-transport.md)。当前只资格化分离包络/载荷union RF的纯运输，非通用跨域路由或动态Block追加；不改变RESET区域权限，不执行syndrome/factory/native编译/fullShor，原8778保持历史录制。下一项在共享S1–S3中把这些运输请求接入服务/资源controller，并分别审核全x CZ/报告/唯一token依赖；不得用本运输PASS替代服务资格。

## 2026-10-04 全体 MZ 汇集重编译


用户确认的初始化/末端ancilla统一服务已接入 rigid ENV 前缀兼容入口并真实重新编译。新profile声明221个关闭MZ SLM（含home共442），5μm格点/10μm停车；每设备完整home最近合法竖直平移分别(0,-320)/(0,-70)μm，EZ全world x。算法/资源AOD容量108/24；初始化60/48/48/48/17分5趟汇集→单RESET221，首轮syndrome48/48分2趟→单MEASURE96→单RESET96，两次服务都实际归还。全部3006原门/413投影/96报告、156plans、34.21438814875767ms，原初态完整plan replay与原源/Stim/全几何、patch、集合服务三独立审计PASS。新几何不作同profile加速比较，两AOD运输当前顺序执行；连续碰撞资格来自Executor和完整重放，不能仅凭端点audit宣称。

新真实回放[8778](http://127.0.0.1:8778/#physical-viewer)读取同次recording，旧8777/8780及frozen轻量核保持。完成阶段及发布状态见[本轮日志](logs/2026-10-04-collective-mz-prefix-recompile.md)、[小型验收](../references/qec_pbc_validation/collective_mz_2026_10_04.json)。这是Enola SA初始placement＋当前rigid ENV兼容前缀；完整Enola+MZ轻量内核、单patch连续两轮E03、工厂/injection与完整physical Shor仍OPEN，继续共享S1–S3主线。

## 2026-10-04 批量 RESET 与终端 MEASURE 标准

用户确认 RESET/最后 MEASURE 应大规模并行联合运到 MZ。已在[唯一协议入口](../docs/qec_enola_mz_design.md#批量-reset-与终端测量用户确认的默认方法)及 E01/E04/E05 目录固化：同阶段跨 patch 合批，区分运输与服务容量，多趟汇集可保持一次服务，分别记录拆分原因。保留实际捕获/运输成本、全 M→R 屏障、测量轴与逐原子报告。PBC cat 终端只合并源依赖允许部分；普通 syndrome 仍只读辅助。此轮是标准与现有实现差异审查，无新编译/物理 PASS；new Enola＋MZ 接入仍 OPEN，冻结源码与旧回放不变。证据及下一项见[本轮日志](logs/2026-10-04-batch-mz-reset-terminal-standard.md)。

## 2026-10-04 协议与 demo 口径修正

用户指出协议/展示混乱。[现行协议入口](../docs/qec_enola_mz_design.md#当前协议入口与生效关系)归并同区、全 x、5/10/6 μm、routing、MZ、纯 syndrome 与独立 magic AOD；迁移路径和导航同步区分目标与已实现。8780 是分离 SZ/EZ 的 QMAP Z memory，16 辅助＋9 data 终端报告；新 Enola＋MZ 纯两轮 demo 仍 OPEN。另查出旧 rigid `nearest_mz` 实为候选内时间优先，新目标为距离优先，不能沿用旧名称声称符合。未改 frozen 源码/物理阈值或运行编译/工厂，原并行工作区不写。下一项只验 E02/E03/E05/E10 单 patch 往返与恢复；证据见[修正日志](logs/2026-10-04-protocol-demo-reconciliation.md)。

修正已发布为[c2db084](https://github.com/physics-Yu/QEC-schedule/commit/c2db0846f6cc6345fecb49915dfcc408c910dc37)；独立 fetch 的 parent/tree/15 blobs 精确一致，[回执](../references/qec_pbc_validation/protocol_demo_publication_2026_10_04.json)保存。RAG 72/62 指纹、84/84 召回通过；66 frozen source 和旧 replay/recording 原 SHA 保持，PR#3仍 draft 未合并。

## 2026-10-04 Enola + MZ 同区兼容设计

用户目标为COMPUTE=EZ=SZ、独立带外MZ。已整理[兼容设计](../docs/qec_enola_mz_design.md)和E01–E10[流程目录](../references/qec_pbc_validation/enola_mz_flow_catalog_2026_10_04.json)：作者2Q规划、5μm硬件适配、MZ/1Q服务、轻量唯一Executor与controller。OPEN：作者空活动轴与当前载荷推导mask不等价、固定19×15/paired4几何需版本化适配、full-band CZ资源须覆盖旁观移动、原memory helper含data末测不能直接循环；返程从当时RF重新绑定。最短路径范围区分rigid图与row/column伸缩。单patch普通两轮/MZ分波/恢复→两patch→四patch/143背景→factory同token单T；本轮只固化设计，未运行native、未切换默认或修改freeze-v4。检查与发布见[日志](logs/2026-10-04-enola-mz-design.md)，RAG新增K72/L49/L50。

## 2026-10-04 全 x EZ 与事件内核当前资格

最终d3-global-ez-attempt5、v2 world x −20…200/EZ y50…80 μm，全部holder/旁观者有限CZ pairs及单独trap域审核。17atoms/2rounds/218gates/1123ops/25reports，48CZ对/8pulse/max6，82,554.39152192436μs；66source/14artifact、7blocks/196alignment、inflight/final checkpoint及2261journal独立几何/精确重放PASS。显式relative start/end/依赖/资源与scheduled事件、共同cubic当前pose、多inflight coldrestore通过；原生END链仍串行，[]同步batch保留，一般重叠由runtime专项验证。

最终171pytest/5.95s、277modules0违规，两Node及8780 default视窗/请求390×844窄屏全xcaption/报告/console0通过。recording off/on0.226/0.377s、strict offline0.148s、两C++call8.824ms、coldimport另计；未测同输入legacyratio。attempt3一ULP假依赖失败保留并已修复；attempt4真实PASS但在最终batch-report身份修复前，当前资格只用attempt5/source-freeze-v4，v3 superseded。旧v1能力[ff9ab421](https://github.com/physics-Yu/QEC-schedule/commit/ff9ab421a6450eff5610aabe11aabf6f304f3000)与历史回执保持。本轮v2能力[a947f0b](https://github.com/physics-Yu/QEC-schedule/commit/a947f0bf338f40bd7583e762ecc95c9ce264fb62)已独立fetch核对parent/tree/30blobs，[发布回执](../references/qec_pbc_validation/global_ez_kernel_publication_2026_10_04.json)保存；PR#3仍draft/open/unmerged，pushurl=DISABLED。RAG71chunks/60sources/205paths、81召回及11portable检查通过。

freeze-v4已交协作工厂薄controller；完整factory/injection/processor、native多AOD、fidelity/FT/physicalShor继续S1–S3独立验收，先W4完整依赖/唯一token-carrier与有界warmnative/fullRF/MZ续接。仅managedcheckout更新，原并行目录不覆盖。见[全带合同](../docs/qec_global_ez_contract.md)、[API/复现](../docs/native_kernel_migration.md)、[小摘要](../references/qec_pbc_validation/global_ez_kernel_2026_10_04.json)、[日志](logs/2026-10-04-global-ez-scheduled-kernel.md)。


## 2026-10-04 独立原生内核首阶段通过（历史 v1 快照）

用户授权迁移内核，已交付独立 `neutral_atom_kernel`：QMAP C++ → mandatory源请求/完整依赖 → 统一指令流 → 紧凑executor → 增量日志/反馈。日常推进移除旧ProgramBuilder、SimulationState、候选搜索和全trace审核，旧ENV仅兼容/历史。实际17原子d3两轮218门、1123操作、25完成报告；48对CZ/8脉冲/max6并行、82.554ms模型时间。独立全RF/Cartesian/有限作用对几何PASS、7block持续位置、196次真实alignment操作及inflight/finalcheckpoint/2261journal重放exact。录制off/on同流推进0.154/0.261s，strict离线0.119s；native两调用9.72ms、首次导入另计。123pytest与277modules零违规；两Node缩放/报告倒放/fit，真实1280/390px、报告完成边界及零console error通过；新回放本机8780。

Source/接口已冻结并用白名单/raw SHA交给协作工厂任务接143原子薄controller；小写W4.d/x/z角色兼容，core SHA保持。主checkout并行dirty未覆盖，旧六长跑未恢复。完整工厂/injection/processor与native双AOD、量子质量及physical Shor待独立资格；首个native profile是单AOD有序全RF/selective-transfer，不能当历史双AOD资格。见[迁移合同](native_kernel_migration.md)、[小摘要](../references/qec_pbc_validation/native_kernel_2026_10_04.json)、[复现](../docs/native_kernel_migration.md)、[日志](logs/2026-10-04-native-kernel-migration.md)。

## 2026-10-04 并行码块自动MZ选点恢复

用户确认的自动选点接回parallel_patch，standard默认nearest_mz；实际载体求nearest clamp/邻域，16尝试/3合法完整服务按真实μs/距离选择，完整全world/轴spares/两设备/运输归还保持。single/full12同各自固定端点baseline的六输入字节及原门/effect批次相同，30055.938183→22195.938183/27955.938183μs，减少26.1512%/6.9870%；各161plans、7选点覆盖50/413投影。完整原初态replay及三层独立审计PASS，185不同pytest/267modules0违规。

fixed_translation与legacy保留旧计划四组合canonical字节一致；8777共用页新增默认折叠的所选原点/候选/载体表，7定位按钮只跳实际pulse，12书签与390/320px/统计缩放保持。见[合同](../docs/qec_rigid_readout_placement.md)、[小型验收](../references/qec_pbc_validation/auto_mz_placement_2026_10_04.json)、[日志](logs/2026-10-04-auto-mz-placement.md)。此轮仍首T前Clifford，未新增factory/injection/FT/fullphysical Shor完成；后续共享S1–S3复用policy/router。能力[e8e7abe](https://github.com/physics-Yu/QEC-schedule/commit/e8e7abe49f40dd5009b91ccce7d55aad1ed6448a)与[发布回执](../references/qec_pbc_validation/auto_mz_publication_2026_10_04.json)已独立fetch核对parent/tree/20blob精确一致；沿用draft PR#3不merge，pushurl=DISABLED保持。

## 2026-10-04 最短合法直达与2.5 μm标准 routing

后续自动MZ绕过问题已FIXED，修复及独立新运行证据见上方选点阶段；本节30.055938ms保持固定测量端点以隔离routing。

码块编译默认standard：直达先完整验证，受阻用既有2.5 μm偏移半格图内最短距离；脉冲后归还重新规划。设备身份、全world旁观者、活动Cartesian空trap与关闭spare轴envelope完整检查，物理阈值不变。同初态单块/12块均161plans，33409.196973→30055.938183μs（减10.0369%）、MOVE479→338；完整原初态replay与两层独立审计通过，原门/合批顺序相同。128不同pytest、266modules零违规，legacy五计划逐字复现。

实际8776共用空间页新增半格运输书签、共12功能入口；“计划路径”消除MZ全程误称去程。缩放/XZ/统计折叠保持，浏览器与源码/输入SHA证据见[小型验收](../references/qec_pbc_validation/routing_standard_2026_10_04.json)、[规范及实施顺序](../docs/qec_routing_standard.md)、[日志](logs/2026-10-04-routing-standard.md)。图内distance最优不等于连续/非线性时间/整线路最优；后续工厂S1–S3复用路由API，现Clifford runner不是工厂运行时。能力提交[011d361](https://github.com/physics-Yu/QEC-schedule/commit/011d361edf09764e1db7a379c403df4fed36654f)及[发布回执](../references/qec_pbc_validation/routing_publication_2026_10_04.json)已独立fetch核对parent/tree/22blob，沿用draft PR#3不merge；pushurl=DISABLED保持。

2026-10-04 最新共享目标已同步原工作区的用户固化协议v2：后续是可复用完整工厂调度→单injection→完整processor（S1–S3），不强制运行时量子态/Born后端；下方旧F1/F2主线陈述保留历史范围并由[当前权威目标](qec_factory_pipeline.md#当前任务目标纯调度模拟)覆盖。本轮只验收布局与Clifford前缀，没有新增工厂/injection完成声明。

## 2026-10-04 单码块并行、Enola placement 与12块物理验收

能力[c272356](https://github.com/physics-Yu/QEC-schedule/commit/c272356ff913a561dc6e28708ca691b0483ce5ef)已发布到draft [PR#3](https://github.com/physics-Yu/QEC-schedule/pull/3)，独立fetch核对parent、完整tree与31blob/staged bytes精确一致，pushurl=DISABLED保持、不merge。[发布回执](../references/qec_pbc_validation/patch_parallel_publication_2026_10_04.json)与本轮日志另作追加；RAG最终67/56/160、67检索与11portable全部通过。

新增显式interleaved/enola布局及READY码内CZ/MZ服务合批，canonical四层/H/hook/CSS原门和物理核不变。同初态标准single从84.684→40.504ms（服务合批减52.1699%）；作者固定初始SA另生成10μm homes提案、经本项目路由复制到12块。新full12真实3006门/413投影/221原子/2AOD、161plans，52CZ共816对/max36，每块四层各2pulse，终态33409.1969726μs；原初态完整replay、独立signed Stim/几何/9401依赖与patch audit通过。标准full12 CZ-only另实测54CZ/max72/79207.8551294μs，布局/服务/search共同变化，不写纯Enola speedup。

实际8774共用空间页11功能书签、同步缩放/XZ/主统计/390与320px/console0errors通过，旧8773页保留；174不同pytest、265modules0违规、5旧默认plans逐字兼容。见[复现与边界](../docs/qec_patch_parallel_layout.md)、[六run摘要](../references/qec_pbc_validation/patch_parallel_layout_2026_10_04.json)、[本轮日志](logs/2026-10-04-patch-parallel-layout.md)。只复用作者初始placer，不用其完整codegen。驻留/非partner-CZ≥10μm，伙伴3/4.243、finite6，运输保持原连续1μm。

未来跨块中心配对存在固定四旁观位+单移动端几何障碍，需interaction staging/辅助位搬移；当前已验收prefix不受影响。范围仍首资源T前Clifford，完整工厂/injection调度、noise/decoder/FT及完整physical Shor未由本轮实现；后续按共享v2的S1–S3。所有实现留attached managed checkout，本任务未写原目录；末次观察原214基线文件209字节相同、5由并行任务更新，原HEAD9e28b2e保持，未覆盖这些变化。RAG K66/K67、L42–L44与draft PR#3阶段发布记录于日志回执，不merge。

## 2026-10-04 QEC 回放同步缩放与统计层级

已按用户要求固化[呈现合同](../docs/qec_viewer_presentation.md)：原子/trap半径比1.15，SLM/AOD、线宽、选择与门/交接动效按同一投影缩放；算法48X/48Z辅助角色持久标识，资源八位明确未编码模板。全宽画布后主统计/类别时间/五设备lane默认展开，逐项和653资源明细默认折叠。实际8773重新展示同一3006门/221原子/12patch前缀，物理录制与原审计SHA保持；七书签、X/Z/resource角色、按钮缩放及390/320px真实浏览器通过。31不同本轮pytest、full12 Node缩放/fit、独立653时间并集及263模块0违规通过。详见[日志](logs/2026-10-04-qec-viewer-scale-hierarchy.md)、[小摘要](../references/qec_pbc_validation/qec_viewer_presentation_2026_10_04.json)。RAG新增K65/L41。此轮只改观察器，未新增物理/工厂/完整Shor验收；factory-first F1主线保持。原目录并行工厂设计demo交接更新保留，其余35dirty与HEAD相同；全部实现留attached managed worktree，沿用draft PR#3，不merge。

## 2026-10-04 同码块并行前缀与真实双 AOD

用户授权统一COMPUTE+MZ、5μm候选格点稀疏放置、取消逻辑最近邻但保持有限6μm全局CZ，并在右侧使用实际独立资源AOD。首24算法functions加同源首T前资源17RESET/H共3006native、413投影、221原子、12d3码块+17资源、196plans已全部真实Executor执行及原初态完整replay；68CZ脉冲含816对/max12，H max72、RESET max29、M max12，终态69927.725855μs。独立Stim/全局几何/trace时序全部通过，234不同本轮pytest通过、3历史artifact缺失skip另计、263modules0违规；单台旧HEAD真实7ops全plan/trace/snapshot bytes兼容。真实共用空间页本机8773，七功能书签、实际双带载运输与390px通过；旧8772仍为native reference index。

边界：固定分离envelopes、Clifford切片；资源停于首T前未编码+，无magic工厂/库存、tracked T/Born、noise/FT或完整physical Shor。本次原worktree核心已有其他dirty，全部新stage留attached managed checkout，原HEAD9e28b2e与36dirty bytes保持。详情与失败档案见[日志](logs/2026-10-04-native-prefix-parallel-physical.md)、[复现](../docs/qec_native_parallel_prefix.md)、[小摘要](../references/qec_pbc_validation/native_parallel_physical_2026_10_04.json)；沿用draft PR#3且不merge。RAG新增K62–K64/L38–L40；下一主线仍按factory-first协议做F1同资源供给→单T闭环，再接真实tracked反馈与完整算法。


能力[2b6a763](https://github.com/physics-Yu/QEC-schedule/commit/2b6a76391f33b20bc2ca76fa20a4a71bbbacc6c8)已发布，独立fetch核对60blob与tree精确相同；PR#3仍draft/open/unmerged，[发布回执](../references/qec_pbc_validation/native_parallel_publication_2026_10_04.json)。RAG64/52/140、58检索与11portable均通过。

## 2026-10-04 QEC 工厂供应与逐周期质量协议固化

用户要求已固化为 [必读共享协议](qec_factory_pipeline.md)，agent 导航/任务路由、architecture 和 research 均已接入。主线为固定 d=3 码/协议 → MSD 工厂到单个 T 的同一资源闭环 → Executor 实际反馈 → 周期带噪供给 → MSC backend → 连续 T/完整 Shor；MSC/MSD 均纳入能力，但不强制串联。唯一载体/epoch/库存、committed 报告、frame、噪声去重及接受/交付/T/算法质量分层必须遵守。旧 Shor-first 下一步已被覆盖，历史运行证据保留。本轮仅规范与导航固化，工厂/MSC/带噪能力保持待实现；验证与下一项可执行任务见 [日志](logs/2026-10-04-qec-factory-pipeline-protocol.md)。

## 2026-10-04 完整编码Shor原生生成与逐功能视图

完整N15/a2、12wire d3编码native／理想reference验收完成：最终seed0 phase128失败→12patch实际读出RESET→phase64验证order4与3/5，两shot11,243,634门／2,402,810投影／7000资源；完整独立流、phase敏感复幅及真实终端Born审计通过。215不同本轮测试（65新＋150旧）及259modules架构零违规，8功能浏览器／32门每秒播放／报告分页／frame下一轴／390px通过；真实操作页本机8772。详见[生成器](../docs/qec_encoded_shor_native.md)、[逐操作视图](../docs/qec_encoded_native_visuals.md)、[可移植摘要](../references/qec_pbc_validation/full_encoded_shor15_native_2026_10_04.json)、[日志](logs/2026-10-04-full-encoded-shor15-native.md)。

这是285声明身份池／qualified kernels的完整编码独立参考，非全原子dense、完整physical Executor或FT。未实现工厂、tracked非Clifford/Born、物理峰值／μs及噪声质量。下一主线按用户最新工厂优先协议先做15-to-1生产→接受／拒收／cleanup／补产→同一载态唯一库存／交付→单T完整channel参考闭环，再接committed Executor、逐周期噪声、MSC和完整physical Shor。历史913／58不加入本轮215；原HEAD／其他dirty保留。能力checkpoint已发布为[`dc2723d`](https://github.com/physics-Yu/QEC-schedule/commit/dc2723dfe4fc2d3ae5570f3341ad5537be65afcb)，独立fetch核对29blob及tree相同，沿用draft PR#3，不merge；[发布回执](../references/qec_pbc_validation/full_encoded_shor15_publication_2026_10_04.json)。RAG最终61chunks／49sources／110paths／53检索与11portable均通过。

## 2026-10-04 Factoring15对照与完整编码Shor集成路线

本节下一步属于此前审查方案，已由上方factory-first协议覆盖；以下实现与测试陈述保留原快照范围。

本轮只读审查Factoring15工厂/库存/原生计划与当前QEC代码，旧G1四套58不同测试复验通过、三冻结包21artifact SHA匹配；不加入历史QEC913计数。普通原生T物理排程已支持，缺口是tracked非Clifford态＋真实投影反馈；单patch消费/16cat全raw/6logical exhaustive限制仍需扩展。Factoring15可复用15-to-1、拒收补产、载体和唯一库存，但其物理报告仍null，G1.1正在其他任务修改，未以旧证据宣称新通过。RAG新增K52–K54；下一交付为12wire编码native generator＋4096逻辑态/qualified kernels，再做预声明Clifford committed cat接受/abort小闭环，之后接真实T/工厂和完整平台。无生产代码/物理参数改动。见[对照](../docs/qec_factoring15_integration_review.md)、[日志](logs/2026-10-04-factoring15-integration-review.md)。

## 2026-10-03 d=3 Shor15自主推进与阶段提交

截至10-04，十一能力checkpoint已提交至 `344d09d` / [PR #3](https://github.com/physics-Yu/QEC-schedule/pull/3)，本轮阶段成果已验收发布并独立fetch逐字核对。完整N15理想PBC/frame真实恢复3/5；编码资源制备→联合测量→9data X读出→frame/消费参考链已验，双资源3641native/51declared/666投影/L2约1.77e-15。clean36new＋35oldY联合71通过，总913=912clean＋1original，256modules0违规；RAG51/44/36检索及11portable通过。

三轮ZZ/XX各51原子1860native、294模拟CZ pulses/max3，完整Executor/originalinitial重放、14＋4审计与保留coherence均通过，legacy terminal268091.2/268092.2μs。XX新recovery session49799真正exit0/1454.117s，全snapshot bytes/EOF一致且完整导出；两失败档案/未知底层机制保留，152captured守护/唯一316→EB580例外保持，3uncaptured/decisions unknown。tracked ENV仍拒T，完整physical Shor/FT未实现；下一步有限Clifford cat controller读取实际committed核验后才允许data coupling，再接显式非Clifford表示/Born及合法线路续接，不写live state或伪造XOR键。原硬约束/HEAD/其他dirty保持。见[阶段入口](../docs/qec_shor15_stage.md)、[日志](logs/2026-10-03-shor15-autonomous-stage.md)。

## 2026-10-02 QEC/PBC GitHub 发布验证

QEC/PBC已上传到`physics-Yu/QEC-schedule` main，主提交[`3b0cde1`](https://github.com/physics-Yu/QEC-schedule/commit/3b0cde11db7fd18d1b0a52135270fd798c9ecc9e)。基于远端04dc69b仅增加18个相关文件/导航，GitHub API与独立fetch核对18个blob全部一致，原远端研究和24个其他本地dirty文件保持。**干净快照274项回归与223模块架构扫描通过；单check物理smoke为3726.6μs/158事件、7门/2CZ/8计划，完整测量/终态/效果/独立重放通过。** 10月1日本地3221.711190μs/150事件对应未发布Enola默认参数，不能用作此次远端默认计时。详见[发布日志](logs/2026-10-02-qec-pbc-publication.md)；完整memory/容错/noise边界保持。本地HEAD保留9e28b2e及原未提交工作，发布通过connector，pushurl=DISABLED未改。

## 2026-10-01 QEC / PBC 上游架构与 d=3 原型完成

用户确认 PBC=Pauli-based computation；新增 `experiments/qec_pbc` role-based 协议 IR、signed Pauli、固定 d=3 syndrome/memory/logical PPM、X/Z parity→PhysicalCircuit、measurement/detector/observable/frame sidecar 与现有平台适配。**Z/X memory 为17 roles、416/434槽、各96CZ；35-role logical PBC Bell 理想语义通过。274专项/回归测试、架构扫描通过。** 单 `Z0Z3` check 已经既有 Executor 真实执行：7门/2CZ/8计划/150事件、**3221.711190μs** 含最终归还，效果各一次、测量/复位/终态/独立 plan replay 一致；两次证据均保留。**完整memory/Bell尚未物理验收，裸ancilla不承诺容错；Y measurement、标准Clifford+T→PBC、magic state、通用时域decoder与fidelity尚未实现。** [架构/入口](../docs/qec_pbc_architecture.md)、[日志](logs/2026-10-01-qec-pbc-architecture.md)。下一步先完成17原子memory平台适配和完整物理重放，再选择容错logical PPM backend；原物理核/硬件/旧未提交工作保持，未提交推送。

截至 2026-09-22，当前源码在 `main`。本轮整理的主变更 `8cb547b` 已推送 GitHub并核对远端 SHA，发布验证与确认补录见 [本轮日志](logs/2026-09-22-repository-release.md)。[发布前交接原文](handoff-2026-09-22-archive.md) 按原字节保留；其中旧端口/PID、默认算法、未推送表述只对应当时快照。

## 当前入口与已实现能力

- 当前自定义默认 `qmap_native`：作者 QMAP 3.5.0 原生内核 → 本地显式成对 SLM / AOD 适配 → Env 执行与共用回放。先运行 `python tools/setup_qmap_native.py`，再 `python demo/launch.py --port 0`。普通 H/X/Y/Z/T/CZ 已接入，测量/反馈 QEC 保持旧协议。
- 同工作台保留本地 `zoned_ids`、`ordered_greedy`、`smt_ordered`；锁定 demo 不自动迁移。各策略的几何、终态和候选族不同，不能直接排名。详见 [当前版本](../docs/current_version.md)。
- 初态 `placement/` 支持合法 SLM 域的站点/占据形状搜索、真实编译反馈、并行评估。工作台默认关闭搜索；本地三策略可选，QMAP 使用作者映射。当前默认 pool256 / evaluations16 / workers4 / stable；stable 与 fixed 终态必须分开比较。
- Parking 朴素版保留已匹配轴、跳过无目标行/列；兼容优化及方向选择已实现，最优范围是声明模板中的抓取批数。离线分享模板与真实 Env 执行的证据分开。
- 交互 IR 已接本地 zoned：Move/Apply 不携带具体 trap，resolver 选择落点，lowerer 展开物理计划；准备不打门、显式 pulse、状态/前缀绑定。仍为完整事务提交，未统一迁移所有策略。见 [IR](../docs/interaction_ir.md)、[实现日志](logs/2026-09-22-interaction-ir.md)。
- 发布审查修复 IR-001（IDS 部分前沿阻断缩小批次回退）及实验 RL 摘要的 NumPy ABI 依赖；最终229项不同专项用例通过，216模块架构、134文件bundle与11项HTTP检查通过。完整1889项压力套件未跑完，717通过/1失败的初次记录及失败修复分别保留；发布总验收见本轮日志，不能宣称全量通过。
- ZAC 固定/SA × reuse、QMAP/Enola 原生规模实验、隔离 RL 源码一并收录；来源、依赖、失败和验证边界在专题报告。模型权重/完整运行 artifacts 不上传。独立 `QEC-scheduler-next` 实现在仓库外，本仓库仅保留 [迁移日志](logs/2026-09-22-qec-next-bootstrap.md)。

## 必须保留的边界

环境只拥有状态、硬件判据和执行，不导入策略；只有 Executor 提交真实下一状态。策略控制完整活动行×列、附带捕获、空阱扫掠和连续轨迹，不得以可行性为由放宽物理。单比特门固定 1 μs；EZ 四邻停车保护是可配置实验合同。

本地 Env 重放、原生离散指令审计、Parking 浏览器模板和 RL 离散见证是不同验证范围。大型历史结果与本轮源码回归分别记账；原生编译时间不等于本地适配/审核/回放耗时。QEC 当前是声明 Clifford 协议及有限故障验收，不是一般噪声阈值证明。

## OPEN 与下一步

1. **Constraint 重构未实施。** 当前检查分散于落点、捕获、运动、完整计划与 runtime；EZ reservation 仍在 env 扫描下一 CZ。建议显式上层预约、阶段化错误、寻路前目标预筛、可靠绑定下复用审核结论。先冻结合法/非法语料和 profile，再做等价改造。见 [本次审计](../docs/constraint_placement_audit.md)。
2. 动态 placement 尚未统一：初态优化、zoned CZ 落地、readout、ZAC 各有入口。完整服务仍多为串行，任意 AOD 跨批带载续接/统一全局调度未完成。
3. `zoned_ids` QEC 性能退化仍 OPEN（历史 17→81 CZ 批次、约 3.57 倍物理时间），不替换旧 QEC。原生 QMAP 未迁移测量/反馈，同几何公平比较与本地执行性能仍待优化。
4. Enola/QMAP 2000/5000 三正则图双方在 300 s 预算内失败；QMAP 5000 GHZ 链成功仅为原生离散验收，不能代替高并行图或连续物理验收。
5. RL 尚无稳定超越启发式的结论；自由初态优化有成功与无收益案例，不能假定 surface QEC 普遍获益。
6. 当前发布补齐依赖提示；ZAC/Enola 等研究工具尚非跨平台一键安装。物理模型或整体架构需变更时请用户确认，普通工程修复自主执行并保留失败证据。

## 证据导航

- [框架总览](../docs/general_framework_summary.md) · [源码职责](../src/README.md) · [环境/策略边界](../docs/environment_strategy_boundary.md)
- [QMAP 与本地执行](../docs/qmap_native.md) · [运动修正](logs/2026-09-22-qmap-motion.md) · [Enola scaling](../docs/enola_scaling_benchmark.md)
- [初态搜索](../docs/compiler_initial_placement.md) · [统一编译流程](../docs/unified_compilation_workflow.md) · [Parking](../docs/parking_compatibility.md)
- [ZAC 复用](../docs/zac_reuse.md) · [ZAC SA](../docs/zac_initial_placement.md) · [RL 初态](../docs/rl_initial_placement.md)
- [QEC 有序对照](../docs/qec_ordered_smt_comparison.md) · [历史发布](logs/2026-09-15-stable-release.md)

收尾更正：原目录另一任务在发布期间追加了单工厂到单T设计交接；早先36dirty全字节相同是当时捕获值，最后重验其余35文件与HEAD仍相同。该handoff并行更新完整保留，本任务没有回写任何原目录tracked文件。当前实现仍全部在managed worktree；工厂设计说明不新增F1/F2运行PASS。
