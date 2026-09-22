# 2026-09-22 交互意图与运动编译边界

用户要求核实并补齐 `move(q1,q2) -> 2q zone` 的架构：上层不指定格点，由下层选择具体落点并编译成 AOD 运动，真实执行与动画保持一致。本次明确授权架构修正，未更改物理模型或默认算法选择。

## 原因与改动

审计当前工作区（已经包含 zoned_ids/QMAP 原生接入）发现：`LayerPlacement` 是已解析的 trap/坐标，PhysicalCodegen/NativeProgramAdapter 已存在，但没有统一的坐标无关交互请求。旧 TaskIntent/TaskTarget 保存的是物理效果授权与具体终态，不能替代这一语义层。

1. 新 `strategies/ir`：不可变 InteractionPair、MoveToInteraction、ApplyInteraction、InteractionBlock；严格序列化，拒绝未知坐标字段、重复/共享操作数及错配 Apply。
2. 新 `zoned/interaction.py`：resolver/lowerer 协议；READY/门操作数/区域检查；ResolvedInteraction 绑定起态指纹；下层才能生成具体 CompiledPlan。
3. `run_zoned` 实际迁入此调用链，接受日志新增 interaction_ir/resolved_interaction，与实际 cz_batches 对照。旧控制器恢复、读出、失败和有限前沿回退保留。
4. PhysicalCodegen 拆出 prepare_interaction/execute_interaction。准备只移动并检查真实作用对，不执行门；receipt 绑定版本、起态/当前态指纹和完整操作前缀。CZ 后仍执行原有稳定落地，失败私有回退。已有合法静态配对允许零移动准备。
5. 新可运行 examples/interaction_ir_demo.py 导出意图、落点、完整计划、状态、报告及共用 viewer 回放。
6. 更新 docs/interaction_ir.md、src/README 与 architecture/compiler_contract。

没有修改 Env 物理判据、默认 QMAP native 前端、已有作者 NAViz 决策、RL 或锁定 QEC 协议。保留工作区其他任务已有更改，未提交/推送。

## 验证

- 最终代码（含 receipt 完整前缀与静态配对零移动）执行 `python -m pytest tests/test_interaction_ir.py tests/test_interaction_lowering.py tests/test_zoned_compiler.py tests/test_environment_boundary.py -q`：56 passed，26.17s。
- 随后新增生产控制器三层日志覆盖：`python -m pytest tests/test_interaction_ir.py::test_production_controller_records_intent_and_resolved_binding -q`：1 passed，1.03s。合计57项分组验证，不将分组时间当同次性能基准。
- `python tools/check_architecture.py --output artifacts/interaction-ir-demo/final/architecture.json`：216 Python模块，0逆向依赖。
- `python examples/interaction_ir_demo.py --output artifacts/interaction-ir-demo/final`：passed。6原子、2CZ同一实际脉冲、13物理操作，Q004/Q005每事件保持原位；两门恰好一次，序列化计划独立重放快照相等，稳定终态。仿真1016.452414676μs；仅架构功能证据，非最优/性能对比。
- 保留示例初次观察器重复调用失败 `artifacts/interaction-ir-demo/attempt1-recorder-failure.json`；修正为只观察真实run事件，未放宽物理条件。
- 未执行真实GUI验收；replay.html为共用viewer生成物，不声称已查看。原生产可编辑工作台界面无修改。

## 剩余边界

当前新IR适配 CZ、entanglement 区域类型、SLM稳定/空AOD服务起态。批内可以按物理兼容性拆分；并非强制所有请求对同时打光。准备/执行在同一事务builder内分离，未新增跨独立Env提交的通用准备凭据恢复。Native作者已解析输出从下层接入，不反向丢坐标再运行IDS；不是所有历史编译器的统一迁移。QEC性能、任意多EZ、跨批AOD驻留和完整状态轻量化均未因本次接口完成而完成。

下一步：复现算法可明确选择输出抽象 Move/Apply 或保留作者的具体落点/移动程序；需要接入前者时替换 resolver，后者继续物理适配。新增优化在相同电路/平台/终态下比较，避免将接口重构当成编译速度提升。
