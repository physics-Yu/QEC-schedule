# 分层架构深入思考与实施路线

状态：COMPLETED（设计交付）；全部架构迁移为PROPOSED/待实施。

用户要求：从既有分层架构出发进行更详细的架构思考，给出详细计划路线。只分析和写方案，不修改生产架构。

阅读agent/handoff及相关architecture/compiler_contract/state_circuit/validation，核对当前pipeline、workbench、QEC/M4/patch runners、program/audit、量子/条件逻辑、hardware Raman和IR结构。前轮性能样本作为历史证据引用，未重跑或冒称本轮性能测量。

新增只读脚本 `examples/audit_layer_dependencies.py`，运行 `C:/python312/python.exe examples/audit_layer_dependencies.py artifacts/architecture-review-2026-09-13` exit0；覆盖111 Python源文件，记录源码哈希与静态跨层import。hardware→simulation 2处、motion→simulation 9处、simulation→motion 52处、simulation→visualization 1处、visualization→simulation 13处。是静态语句计数，包含局部import，不是调用图或全部判错。

交付 `docs/architecture_evolution_plan.md` 与 `docs/architecture_evolution_backlog.md`：明确模块化单体；Circuit/Task/Operation/Scheduled IR；program/run/verification三类产物；静态/当前/历史/缓存分离；报告可见性与私有量子/RNG；纯语义核/独立审计/唯一Executor；合法域/时间资源合同；vNext兼容与分阶段作业/回放。A0–A8列依赖、具体工作包、输出、B0字节/B1语义/B2策略验收和回退。

主要待评审设计：新状态身份与schema19迁移、增量核验信任边界、QEC条件程序/报告驱动滚动合同。当前代码允许planner得到完整simulation state，这是接口耦合；没有声称现有策略已利用未来结果。新方案不扩大物理约束或完备性，动态变距/多AOD/RL等另立未来范围。

本轮只写文档与静态审计工具。生产源/现有动画未改，未执行完整编译、GUI或物理测试套件。文档本地链接和生产源清单一致性校验另存review-check.json。下一条建议实施任务为A0+A1，先做兼容基准和分析复用，再逐步迁移。
