# 2026-09-15 — 清单12–14测量支撑/落点/评分策略化

用户授权替换当前有序QEC工作台的三项固定规则，保持“上层先评分，movement后规划，必要时反馈”的分层。

## 实施

- 新 `scheduling/readout_placement.py::ReadoutPlacementPolicy`：AOD/SLM支撑、入口附近与有序变距候选、非平移SLM轴窗口、低成本评分、有界候选尝试、实际计划成本反馈及失败回退。
- `motion/ordered_transfer.py::move_loaded` 仅实现给定构型目标的已承载阵列路线，不选择测量用途；所有实际操作仍经原物理后端、ProgramBuilder与Executor。
- `qec.readout_service`新增显式策略注入；当前`qec_ordered_comparison`注入并导出readout_log。旧未注入调用保留兼容SLM流程。
- 配置`configs/strategies/readout_placement.json`：adaptive、candidate_budget16、top_k3；UI支持自动、仅AOD、仅SLM，预算独立于电路，显示选中支撑数与诊断。
- 环境物理代码本轮未改；仍500/100 μs理想读出/复位。测量后返回及其他清单项未隐式更改。

## 验收

- Q019固定初态三模式各真实执行并独立重放：legacy2146.543 μs，slm_only2119.839 μs，adaptive1662.379 μs。自动选择(12.5,-150)/(12.5,-170)及另一列，省MZ内卸载/装载；量子态、测量结果、placement、AOD与开关终态一致。`examples/audit_readout_policy.py`及`artifacts/qec-readout-policy/q019`可复现。
- 完整两逻辑QEC，双方相同初态SHA：贪心24337.381 μs，SMT24975.219 μs；483槽、105CZ、32测量/32复位、8次AOD测量服务。双方66计划独立重放及量子/终态校验PASS。LOAD/OFFLOAD各35→27。
- 26项readout/QEC/边界与17项轴/路径回归最终PASS，共43项；最终新增8项重验PASS（重叠）。首轮测试删除MZ却保留MZ traps，遭世界合法性验证拒绝；修正为显式注入候选耗尽，未改物理规则。
- 架构139模块0违规；Node编辑器测量配置隔离、导出动画全部移动段三次插值与物理/关键帧32×完整终点PASS，均明确是离线验收。
- HTTP实际编辑电路H/MEASURE/RESET/条件X双策略完成，AOD支撑/逐字重放/终态PASS；`attempt1/api-acceptance.json`，job00750734f996497398f0fe2b23c4086d。
- 真实GUI缺口仍在：本轮内置浏览器调用报`nodeRepl.fetch request failed`，没有声称点击验收通过。

## 交接

新入口 http://127.0.0.1:8798/ ，PID26368，输出`artifacts/qec-readout-policy/attempt1`；8797保留供对照。main工作区未提交推送。详细接口、默认值与范围见[策略报告](../../docs/readout_placement_policy.md)。

Q019调查中的首个合法SLM落点限制已在本工作台FIXED；不是全局最优、任意混合holder服务或任意AOD驻留策略。后续可优化候选评分、拓展完整构型搜索；真实浏览器可用后补点击配置/编辑/编译/回放验收。
