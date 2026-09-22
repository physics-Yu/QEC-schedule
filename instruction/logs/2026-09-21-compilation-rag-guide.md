# 2026-09-21 · 线路编译与执行文献指南

- 状态：COMPLETED。
- 用户目标：基于 RAG，提供与初始化指南配套的线路编译执行文档。
- 范围：文档与源码/原文核对；不改算法、物理规则或默认配置，不运行性能实验。
- 相关指引：agent.md、handoff.md、compiler_contract.md、architecture.md、workflow.md。

## 内容

新增 [线路编译与执行指南](../../docs/circuit_compilation_execution_rag_guide.md)：五步文献流程、逻辑与物理调度区别、状态与接口、动态placement/reuse、兼容运输/parking、资源时间、独立验证、四比特例、当前普通有序与ZAC实验的分支、CLI及实验设计。

读 RAG P02/P03/P05/N002/N105/P01 相关证据；重点原文包括ZAC第6/13页、Enola第5页、Weaver第4/9页。核对ordered_controller、ordered_greedy、smt_ordered、environment、workbench、placement_worker及离线脚本。

## 验证与边界

内联Python检查PASS：指南407行，UTF-8、代码/公式围栏、本地链接均通过；26个完整图谱证据/断言ID存在；四条关键锚点 `E_P02_R06_02`、`E_P05_C10_02`、`E_P03_A12_01`、`E_N105_A06_01` 由show_evidence.py恢复通过。CLI入口/输入存在，引用函数名由AST静态检查确认。

不运行物理测试与GUI；示例和命令明确标注未执行。文档中的通用任务/操作图结构是建议，不冒充普通有序路径已支持跨批驻留或通用并发。Mermaid仅提供可渲染源码，本轮未作浏览器渲染验收。

## 下一步

若后续实施，先统一候选记录与验证合同，再比较动态终态与操作级资源调度。保留现有工作树改动，未提交或推送。
