# 编译耗时与合法域优化分析

状态：COMPLETED（分析交付；优化未实施）。

用户要求：分析是否因为黑名单而非白名单导致编译久，把精力用于思考可优化路径。

已按 agent/handoff 路由阅读 motion_planning、compiler_contract、motion_execution，并核对当前 QEC、A*、Executor、trace、snapshot、DAG、Clifford 内核。四邻 guard 在当前 68 原子输入已经 False；A* 与部分矩形构造/preflight 已存在，不能描述为完全盲搜。当前多轮 QEC 是保留 reference 顺序的 first-valid+cohort reuse，不是全候选最优搜索。

新增 `examples/analyze_compile_costs.py`：只读统计原 trace，当前 Executor 执行前三个保存计划并 cProfile，68 个事件逐字一致。命令 `C:/python312/python.exe examples/analyze_compile_costs.py --output artifacts/compile-cost-analysis-2026-09-13 --plans 3`，exit0。生产 Python 源码前后哈希一致。没有更改已有源文件或交付产物，没有运行完整编译/GUI/全测试套件。

新证据：trace 466,038,649 bytes，其中各计划 initial_dag 字段值 JSON 合计 414,614,676 bytes（88.97%）；515计划/3665操作/8360事件。首准备16操作34事件10.482s；43H一脉冲1操作4事件4.527s；CZ14操作30事件5.155s。计时含 cProfile，不可外推成全程百分比。43H样本3次完整计划审计、3次fingerprint；热点含DAG编码/恢复和每门tableau全量合法性检查。当前已有运行前缀重建cache，分析没有误报为每事件无缓存全历史物理重放。

报告 `docs/compile_performance_analysis.md` 区分工程去重、索引化精确几何、批量量子变换、分层状态/增量审计、动态合法动作域、可复用A*边与小窗口调度。新schema/hash/信任边界改变仅提出方案，未实施；具体实施前按既有审批边界另行评审。外部算法机制参考 OMPL LazyPRM、配置空间课程、OR-Tools 官方job-shop，不改变本项目物理模型。

下一步：P0互斥阶段计时+P1字节兼容不可变数据复用，短样本先验收；之后再安排完整矩阵及1868槽对照，不承诺未经测量加速倍数。
