# QEC 工厂与逐周期质量共享协议固化

日期：2026-10-04。状态：`COMPLETED`。完成范围为共享协议、发现入口和检索固化，不是工厂功能里程碑完成。

## 用户目标

将 Factoring15 对照后确认的标准化 QEC、MSC、MSD、magic factory、库存交付、T 消费与逐周期质量流程固化为其他 agent 可发现、阅读和遵守的项目协议。

## 完成内容

新增 [QEC 工厂供应与逐周期质量协议](../qec_factory_pipeline.md) v1，共171行，明确标准码/协议库、MSC/MSD 可选择路线、真实资源身份和库存生命周期、周期账本、噪声机制去重、质量指标、frame/Executor 和分层证据，以及 F1–F5 验收门槛。已有编码参考、普通物理 T 可排程和缺失 tracked 非 Clifford 执行之间的边界保持明确。

- [agent 导航](../../agent.md) 顶部与任务路由规定相关任务必读；[architecture](../architecture.md)、[research](../research.md)、[handoff](../handoff.md) 接入同一协议。AGENTS.md 的轻量发现入口保持原文。
- [Factoring15 对照](../../docs/qec_factoring15_integration_review.md) 与旧 handoff 下一步标注 Shor-first 已被覆盖，保留全部历史实现和验收正文。agent 的旧“项目不涉及保真度”概述明确为物理底座范围，并接入上层显式质量模型目标。
- RAG 的 sources.json 新增 L34 并同步 L33 normalized 文档指纹；knowledge.jsonl 新增 K55–K57，K54 标为历史方案；query_cases.json 加入3条当前协议检索用例。保留 L33 历史 raw hash 与 K52/K53 原事实，不把政策块标成已实现。

共涉及10份协议/导航/日志/语料文件；生产代码、物理参数、旧日志、旧运行包及 Factoring15 项目未修改。两个子 agent 完成科学/证据与发现入口独立审查；正文采纳机制级噪声去重、对易 frame 可不变、采样字段 not_applicable、按阶段实际依赖控制等修订，最终只读复核可交付。

## 本轮验证

| 检查 | 结果与范围 |
| --- | --- |
| Python 3.12 文档/入口检查 | PASS：22处正文与新增导航的本地链接存在，4个导航入口可发现协议，171行正文代码块闭合、无尾部空白 |
| 修改前文本对照 | PASS：AGENTS.md 未改；架构/研究/handoff/对照报告仅增加当前说明，旧正文完整；agent.md 仅增加入口/路由并替换一段项目范围概述 |
| git diff --check（本轮文档范围） | exit 0；Git 仅提示既有换行转换配置，无 whitespace error |
| RAG --check | 根 agent 最终复验 PASS：57 chunks、46 sources、0 errors |
| RAG --self-test | 子 agent 本轮执行 PASS：42/42 固定 top-5 检索用例，包含3条新协议用例 |
| RAG 定向检索 | 子 agent 本轮执行：factory-first、MSC/MSD 库存、逐周期质量分别 top-1 命中 K55、K56、K57 |

未运行生产回归、物理/带噪仿真或浏览器验收：本次改动为规范与检索。未沿用历史物理 PASS 作为本轮结果。新协议仅文本检查，不宣称图表或页面渲染已验收。

## 决策与仍待实现项

用户确认的主线为标准协议→工厂到单个 T 的参考闭环→Executor 实际反馈→逐周期带噪供给→MSC backend→连续 T/完整 Shor。MSC/MSD 均纳入能力但不强制串联；基础噪声标定与 MSC 协议设计可以并行，集成按前置证据验收。

工厂供应闭环、MSC、tracked 非 Clifford/Born 与周期噪声/逻辑质量仍为开放实现目标。d=3、三轮 syndrome、理想15-to-1公式和文献 erasure 数字均不构成本平台含噪容错证明。本轮未更改这些状态。

## 下一项可执行任务

从协议 F1 开始，选定具体15-to-1模板，建立 native raw preparation→实际检查参考→accept/reject→唯一资源库存/交付→同一资源的单 T 消费→frame 的可重放参考运行包。独立一般复振幅与纠缠 probe 核验完整 T 通道，并覆盖拒收、过早/重复消费与 cleanup。F2 实际 ENV 门禁另行验收，不以参考报告填入物理键。

## 复现入口

```powershell
& '.venv-qec-noise-modern/Scripts/python.exe' tools/query_qec_pbc_rag.py --check
& '.venv-qec-noise-modern/Scripts/python.exe' tools/query_qec_pbc_rag.py --self-test
& '.venv-qec-noise-modern/Scripts/python.exe' tools/query_qec_pbc_rag.py --query 'factory-first agent 必读共享协议和实施顺序' --top-k 5
```

RAG L34 固定协议 v1 的 normalized SHA256。后续修改协议时同步来源指纹、当前政策知识块和检索用例；版本/实施状态不得混淆。未提交或发布。
