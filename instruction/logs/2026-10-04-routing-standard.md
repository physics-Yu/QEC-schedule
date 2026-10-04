# 2026-10-04 标准 routing 修复与固化

用户要求最短合法移动或既有2.5 μm偏移协议成为标准。所有改动位于attached managed checkout的codex/d3-shor15-stages，parent=8dfe02e；没有写原工作区。范围是策略路由、码块编译入口、观察器文字、规范与RAG；物理核/硬阈值/架构未改。

## 实现

- 新validated_rigid入口先由既有device backend验证直达；否则复用AStarHalfGridPlanner的x/y=2.5+5k通道图最短距离。图域只限制搜索，不裁world/foreign atom；with_aod保留magic身份。单设备额外检查完整spare轴envelope。
- parallel_patch默认standard，空载/CZ/MZ/dual RESET及脉冲后归还共用API；真实depart/approach分别保留。旧固定5μm路线用explicit legacy_5um保留，旧五plans逐字相同。
- CLI summary/provenance绑定policy和实际模块；legacy不得声称distance最优或固定半格图。老prefix/布局文档共六条历史CLI补flag。
- report增加2.5 μm半格书签与路径规则；共用viewer把“去程”改为“计划路径”，避免MZ去回程叠加误称。同步缩放、X/Z和主统计优先保留。
- 规范落到agent、motion_planning、compiler_contract及qec_routing_standard。工厂未来复用两个路由API，并先解决真实staging端点；不直接复用tracked Clifford runner作为纯调度S1–S3运行时。

## 实际验收

本地artifacts/routing-standard-2026-10-04/逐attempt保留。单块attempt1在单设备守卫补齐前完成；最终single-enola-attempt2使用最终router。完整12块attempt1启动后仅加不进入的len(aods)==1守卫和legacy-only CLI metadata修正；实际producer hashes与当前差异明确记证据，不回填原录制。


### 同初态对照

新旧各组的 initial/source/circuit/phases 原始字节、效果合批顺序与原生 ID 均相同，只替换路由。全部原门、有限 CZ 与依赖保持。

| 规模 | 原门 / 投影 / 原子 | 旧总时间 μs | 标准总时间 μs | MOVE 段数 | 证据 |
| --- | --- | --- | --- | --- | --- |
| 1 块 | 267 / 50 / 34 | 33409.196973 | 30055.938183 | 479 → 338 | 完整原初态 replay、两层独立审计通过 |
| 12 块 | 3006 / 413 / 221 | 33409.196973 | 30055.938183 | 479 → 338 | 完整原初态 replay、两层独立审计通过 |

两组总时间均减少 **10.0369%**，仍为161 plans、52次CZ脉冲、其中稳定子四层各2次；最大实际CZ批次分别3对与36对。时间是含归还的模型物理时间，执行/重放的机器wall time另记，不混用。

128项不同专项pytest通过，包含16项新路由行为测试与11项既有A*测试；独立手建Dijkstra oracle、真实装卸/Executor/replay、双设备身份/旁观者、活动空Cartesian交点、关闭备用轴域边界、失败纯度和预算分类已验收。266模块架构扫描零违规；显式legacy五份计划与历史字节一致。

完整输入、录制、实际生产模块指纹及审计摘要见[可移植验收证据](../references/qec_pbc_validation/routing_standard_2026_10_04.json)。最终单块使用最终router字节；12块启动后新增的单设备envelope守卫在其双设备运行中不进入。两组运行后CLI仅更正legacy metadata，独立AST检查证明standard合同与实际summary一致；所有实际producer hash保留。viewer的“计划路径”不再把MZ全程叠加统一误称“去程”。

实际[12块空间回放](http://127.0.0.1:8776/)保留同步缩放、X/Z标识和统计折叠，新增2.5 μm半格运输书签；本地12项书签、窄屏和console验收详见该证据的browser项。旧8774及历史录制保留。只证明相同Clifford前缀路由改进，不新增工厂、injection、FT或完整physical Shor完成结论。

验证命令：本轮九test modules合跑128 passed in20.55s；新route16+旧A*11包含其中，不累计先前126/42等重复。python tools/check_architecture.py为266modules/0violations。两组完整run均未skip replay；各自tools/audit_native_parallel_physical.py与tools/audit_patch_parallel_layout.py --mode enola --proposal ...实际通过。比较额外逐字检查四份输入及recording效果批次顺序；端点几何审计不代替连续Executor/replay。

命令复现见标准文档，两组加--intra-patch --intra-services --pair-search --routing-policy standard，12块--wall-budget1800。每attempt新目录，固定source packet和Enola proposal未变。legacy probe与CLI AST metadata检查为额外独立检查，不计pytest。

## 工具失败与处理

1. 单块audit错误使用--baseline oldEnola；现有该flag限定role-mode，改为独立audit后用精确输入/效果比较，不放宽断言。
2. 一次猜错tests/test_parallel_prefix.py无测试运行，改为真实test_qec_parallel_prefix.py。一次rg glob作为Windows字面路径失败，改rg --files发现；均不是物理失败。
3. 一次apply_patch heading不匹配，整包未应用；读准确上下文后重做。
4. single attempt2摘要未写完时提前audit报FileNotFound；待真实exit0后重新audit，两层PASS，首次诊断保留。

## 范围与下一步

本轮RAG实际68chunks/57sources/168paths；source/schema检查、70/70固定检索和11/11 LF/CRLF/CR portable checks通过。实际full12共12书签/390与320px无横向溢出/console0errors；两项Node fit/scale检查通过。浏览器一次display exact-text定位失败后按shadow DOM实际summary定位；一次body Control+Home超时后用完整页面截图保存，无修改物理数据。

用户在验收期间追加“编译器应自动选择MZ内最近合法测量位置”。确认旧ReadoutPlacementPolicy仍在，而parallel_patch绕过它采用固定-400/-300 translation。本轮两组同初态结果刻意保持原测量端点、仅隔离routing变更；这份已验收里程碑不声称自动测量选点已恢复。该选点缺口仍OPEN，正在继续实现设备感知rigid候选→完整合法服务反馈→选中位置/候选决策展示；通过后另作追加证据，不覆盖本轮录制。

本工作树rigid恒速；直达达到Euclidean下界，受阻只保证有限图距离最短。不是连续空间绕障、非线性Enola计时或整线路全局最优。CZ6μm/非partner10μm/transport1μm/Raman5μm保持。未运行全仓库suite，没有新增完整factory/injection/noise/FT/physical Shor能力。

下一条可执行任务：先完成上述MZ自动选点恢复及单块→12块完整验收，再按共享v2在完整工厂背景声明interaction staging，验收一对跨块中心CZ+分离后H+归还；每段调用标准router并完整重放。固定旁观位或15μm设备域间隙导致端点非法时上层改真实staging设计，不放宽物理或用token替代运输。

## 阶段发布

能力、规范和小型证据待本轮GitHub Git data发布；核对parent/tree/每blob与staged bytes后在追加回执登记。沿用draft PR#3，不merge，pushurl=DISABLED保持。大型trace/checkpoint与截图留本地。

能力提交[011d361](https://github.com/physics-Yu/QEC-schedule/commit/011d361edf09764e1db7a379c403df4fed36654f)已发布到draft [PR#3](https://github.com/physics-Yu/QEC-schedule/pull/3)。独立Git fetch核对parent、完整tree与22个blob/staged bytes精确一致，工作树HEAD在核对后安全前移；不merge，不git push，pushurl=DISABLED保持。[发布回执](../../references/qec_pbc_validation/routing_publication_2026_10_04.json)与本段另作追加，不改原录制。
