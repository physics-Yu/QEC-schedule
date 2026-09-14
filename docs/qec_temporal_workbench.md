# 多轮 QEC 编辑界面

2026-09-12，4B 接入开发。当前已通过界面控件工程测试，尚未完成真实物理与浏览器验收，不能据此宣称多轮纠错已交付。

`qec_temporal` 使用现有 QEC Clifford 编辑器、可编辑 patch 原点及 AOD 配置。模板按钮和 `?example=surface-qec-temporal` 从真实 API 载入输入，关闭自动编译，保留手动编辑后编译的流程。选择策略不会暗中重建现有 QEC 草稿；新模板按钮是显式载入操作。

MEASURE 详情增加 `readout_flip` 复选框，应用修改仅影响该门的报告位翻转字段，保持真实量子投影、其他门、条件依赖及几何输入。可以撤销、导入、导出；线路中带翻转的测量门显示标记。未显式使用翻转的旧门不强行写入该字段。当前通过门详情选择具体测量事件，不提供会覆盖整张门表的噪声重建控件。

多轮模板由 `qec_protocol.noisy_rounds` 识别，旧单轮 `QEC_FAULT` 控件被禁用，事件处理器也拒绝用其改写多轮协议。测量详情读取 `qec_protocol.readouts` 标明所属轮；闭合轮保持完美是声明协议要求，任意改写不保证仍在可纠错范围内。

实际结果区区分 `true_measurement_results` 与 `reported_measurement_results`，显示提交报告位数量（标准协议预期80位，包括制备）、历史齐全性和是否受译码支持。逻辑GHZ、测量协议完整性分别判定。`corrections` 是实际已执行纠错；`decoded_corrections` 只是历史译码建议，不冒充执行。明确限制为三噪声轮加完美闭合轮、声明的单数据或单报告位事件，不声称任意多错或门内噪声容错。

本次工程检查：

- `node tests/workbench_temporal_controls.cjs`：通过。小型明确标注的 DOM/HTTP 替身输入，检查翻转编辑、撤销、JSON、原点/AOD/其他门保持、旧控件防护及真实位/报告位/未知历史显示。
- `node tests/workbench_qec_controls.cjs artifacts/qec-roadmap/step4b-ui-tests/legacy-input.json`：通过。使用由既有生成器产生的旧模板，保留单轮编辑、条件、故障门和导出行为。

以上不包含物理编译或真实浏览器可视化证明；这些等待核心与协议验收后执行。
