# 2026-09-13 · 外部中性原子编译器架构调研

- 状态：COMPLETED（调研交付；架构迁移待实施）
- 用户目标：研究其他人如何实现中性原子编译、AOD并行与QEC调度，以校正分层架构路线。
- 范围：论文、官方文档、公开源码只读核查与方案记录；不实施架构迁移，不改物理约束。
- 基线：四逻辑GHZ既有验收与交付保持；A0–A8均待实施。
- 相关 instruction：agent、handoff、research、workflow；沿用前轮architecture/编译合同审计。

## 已完成资料收集

ZAC、MQT QMAP routing-aware/IDS、Atomique、Enola、Weaver、Bloqade-Shuttle，以及作者托管的NEAT稳定子抽取稿。选取ZAC/QMAP/Shuttle源码留存，记录固定ref、文件摘要和LICENSE；没有安装或执行外部项目。

## 当前发现

批次与落点共同决定AOD并行；同轴运输约束不能用单原子最短路代替。QEC联合求解值得做离线小核，但不是无界交互搜索。当前小时级费用仍包含已实测的重放、重复审计和序列化，不能用论文纯编译计时直接比较。

## 交付与核验

交付[对比报告](../../docs/external_compiler_research.md)，在原架构方案、实施清单和research导航添加补充链接。没有替换原设计或启动架构迁移。

本轮脚本静态核验：3组固定ref均通过GitHub commit查询；32份来源文件SHA-256一致；报告本地链接和代码围栏检查PASS。证据`artifacts/compiler-research-2026-09-13/source-manifest.json`与`review-check.json`。选定源码可按清单固定URL重新取得，未安装或执行外部项目。没有运行生产测试、完整编译或GUI验收。

阅读范围：ZAC solve/匹配、MQT Compiler/PlaceAndRouteSynthesizer/HeuristicPlacer/IndependentSetRouter、Shuttle ScheduleToPath/RuntimeAnalysis/PathVisualizer等。不是完整代码审计。

## 限制与失败记录

NEAT匿名artifact地址浏览器检索工具未能读取；保留“论文证据、未核查代码”标签。一次GitHub commit元数据查询遇SSL中断，按固定ref重试后3项均成功；无项目行为受影响。一次文档补丁因标题上下文不匹配未应用，读取准确标题后重新应用。文献性能未复现，不能作本项目加速承诺。

## 下一步

架构方案获得实施授权后从A0/A1开始。首个算法适配应固定当前rigid平台与终态，对比既有策略和运输感知批次/落点候选；动态行列与QEC周期核另列能力验收，不隐含改变硬件条件。
