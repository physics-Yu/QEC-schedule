# 可编辑 GHZ₂ 测量与纠错工作台

2026-09-13 界面已按 [独立配置合同](workbench_configurations.md) 整理。线路区展开模板载入协议与配套平台，编译配置保持独立；初态和量子结果默认折叠，只有线路卡片内的编译按钮启动运行。旧 `compiler` 输入仍兼容；当前推荐 `circuit_profile` + `compilation`。

沿用初始条件 → 可编辑线路 → 物理编译 → Executor → recorder → viewer。
专用入口为 `?example=surface-qec-ghz2`，仅载入草稿，不自动编译。

输入采用 `layout="surface_qec_ghz2"`、`compiler="qec_ghz2"`、
`qec_enabled=true`，34 原子中 Q000–Q017 为数据原子、Q018–Q033 为
测量辅助原子。平台角色由实验布局生成，回放 scene 保存 `atom_roles`。
AOD 为 7×14、98 个交点；行列坐标和开关仍可编辑，实际可行性由后端验证。

QEC 模式支持 H/X/Y/Z/CZ/MEASURE/RESET。普通模式保留 H/X/Y/Z/T/CZ；
T 不属于此 Clifford tableau 模型，QEC 输入明确拒绝。测量 500 μs、
复位 100 μs 是本次仿真假设，不代表设备标定。单比特门仍固定 1 μs。

`PhysicalGate.condition` 保存测量位等值条件的 AND；`depends_on` 保存
显式阶段依赖。编辑器应用参数修改及 JSON 导入导出均保留这些字段。
条件与依赖在门详情中展示，可通过 JSON 修改。把门移到前置依赖之前会
由线路/DAG 校验拒绝，不会暗中重排或重建原协议。

故障选择器修改实际 `QEC_FAULT` 门，可选数据原子上的 X/Y/Z 或无故障。
它保留其他手工编辑，只更新相关依赖；故障列来自 `qec_protocol` 的
元数据，不写死列号。该元数据只服务编辑，不触发隐藏故障或隐藏纠错。
清空、添加、删除或导入的实际门列表传给 runner；任意改写不保证仍制备 GHZ₂。

完成后页面展示实际提交的 syndrome 位、真正触发的条件纠错和终态
逻辑 XX/ZZ 以及码稳定子校验。编译完成与逻辑验证通过分别展示。
回放只在测量结束后显示已提交的结果；条件为假的 1 μs 控制时隙
不显示 Raman 光，并作为独立控制类别统计。测量/复位分别计时。
32× 仅改变屏幕播放，不改变仿真时间。

服务器保存 `input.json`、`qec_result.json`、`checkpoint.json`、
`trace.jsonl`、`recording.json` 和回放 HTML。`?job=<id>` 恢复原输入与
实际结果，仍能继续编辑及编译。结论限于理想投影测量、完美读出和
实验声明的单数据 Pauli 故障恢复，不宣称通用电路噪声下容错。

## 2026-09-12 本轮界面验收

`tests/test_workbench_qec.py tests/test_workbench.py tests/test_workbench_patch.py`：
44 passed / 13.43 s。`tests/workbench_qec_controls.cjs` 与旧 large-controls
通过实际 JavaScript handler 检查；其 DOM/HTTP 为替身，不作为浏览器证据。

真实 headless Microsoft Edge 通过 `examples/accept_qec_browser.py` 载入
无故障模板，编辑 seed=7、Y(Q000)，增加 H 后撤销，再点击编译。
唯一作业 `55831b7d3be24c56ada3cd4958460db2` 完成 481 个实际门/控制槽，
编译耗时 189.438 s，总物理时间 22055.9 μs。32 个 syndrome 位来自提交
的测量结果；实际触发 Z(Q011)、Z(Q000)、X(Q000) 三次条件纠错。
终态 XX=ZZ=+1，16 个码稳定子均 +1，测量协议完整。

测量中点未显示尚未提交的读出，操作结束才出现对应位；条件为假的
控制槽显示“未施加激光”。32× 真实比例/关键帧全程分别 28.766/26.765 s，
均无停滞并抵达精确终态，34 原子回到静态承载；页面无异常。
运行期间所有 src Python/JS/HTML 的 SHA256 未变化。证据位于
`artifacts/surface-qec-ghz2/browser`。此浏览器运行未替代独立物理重放，
后者由主验收流程另行执行。服务为 8781，旧 8769 服务保持。


## 重复综合征与四块扩展

`qec_temporal`搭配34原子`surface_qec_ghz2`，`qec_temporal_four`搭配68原子`surface_qec_ghz4`。四块含36data/32ancilla，默认四原点(0,0)/(40,0)/(0,40)/(40,40)，同7×14=98交点AOD；四原点可编辑，输入需满足相同平台几何校验。模板API为`/api/examples/surface-qec-temporal-four`；三噪声轮与完美闭合轮的报告历史分别为64/128位，总MEASURE/RESET分别80/160次。

两时域profile允许MEASURE上的严格bool `readout_flip`，真实投影和报告分别保留，条件纠正只能读报告历史。普通及旧理想读出profile不接受报告翻转。时域profile关闭旧单数据故障选择器，防止它隐式改写新的历史协议；实际门列表仍可编辑、导入导出并重新编译。四块展示XXXX与AB/BC/CD三条ZZ、32码稳定子。短编辑可以完成物理执行而不满足完整GHZ协议，界面必须分别显示。

4B完整物理/重放/UI已PASS；4C完整物理/515计划独立重放/双32×UI及六门实际编辑编译均PASS，最终入口与证据见handoff。以上仍是声明单事件噪声实验，不把三轮报告翻转模拟称作全电路噪声容错或设备保真度证明。
