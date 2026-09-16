# 当前交接状态

**2026-09-16 原通用工作台已接入新版：** 自定义继续保留 1–128 原子、row/grid/shuffled、AOD 非均匀偏移及配置保存，新增 ordered_greedy / smt_ordered 和行列后端；外部通用 Ordered Controller 复用实际有序/axis-hold/测量策略，无固定34原子替换。旧策略及限制保留，环境与RL不变。完整480槽QEC/64计划及独立逐字重放通过；相关145测试最终分组通过，实际JS事件+HTTP双策略编辑编译通过，GUI连接仍失败未验收。新入口 http://127.0.0.1:63791/?job=8b98c4f10f154241ae11c6b32ca6cf06 ，PID36940；旧8797保留。[说明](../docs/ordered_workbench.md)、[日志](logs/2026-09-16-current-workbench.md)。

## 当前非 RL 发布基线

2026-09-15，main；主实现 `1d49cc0` 已推送 GitHub 并核对远端 SHA。本轮整理发布进度见 [发布日志](logs/2026-09-15-stable-release.md)，当前功能、复现及固定/计算/可选配置见 [版本说明](../docs/current_version.md)。早期逐轮摘要已移至 [发布前归档](logs/2026-09-15-pre-release-handoff.md)，追溯时按需读取。新增 RL 工作留在本地，本次不纳入 GitHub 提交。

- **分层**：环境只负责物理模拟/约束/执行；外部算法在 strategies，协议在 experiments，控制与 UI 在 app。不得为了候选可行而放宽环境约束。
- **最新功能**：有序行列贪心与独立 SMT、2.5 μm 占据格预筛选、正交运动及 axis-hold、测量支撑/落点策略、含测量/条件门的编辑器。Q000 绕路已在共享策略修复；Q019 旧测量目标首个合法即接受已在显式注入的新策略中修复，旧调用保留兼容路径。
- **入口**：`python demo/launch.py` → 有序 AOD · QEC；最新两份完整动画在 `demo/qec/replays.html`。开发机原 8798 服务保留；新克隆不依赖这个端口或旧 artifacts。
- **完整案例证据**：34 原子、483 槽、105 CZ、32 测量、32 复位；同初态双方 66 计划独立重放/效果/量子/终态通过，17 批 CZ / 最大 9 对。贪心 24337.381 μs，SMT 24975.219 μs；各 8 次 AOD 测量，LOAD/OFFLOAD 各 27 次。是既有完整执行结果，本轮不重新大规模编译。
- **物理范围**：固定 QEC 平台、Clifford 理想量子态和声明故障；不是完整噪声容错。M0–M4 及 QEC 分步的历史验收限于声明平台族，不宣称通用二维最优规划。

## OPEN 与下一步

1. 最新 GUI 真实浏览器验收尚未完成，前轮连接失败；HTTP、离线 DOM/Canvas 和完整物理重放不能替代真实交互。
2. 有限目标/路线/SMT 搜索、每批 CZ 归还、测量后归还、完整服务串行仍限制性能；优先拆分这些策略组织规则，再评估跨批驻留与并发。测量第 12–14 项已替换，其余规则未隐式修改。
3. `ReadoutPlacementPolicy` 当前从 SLM 源位/空 AOD 开始，不支持任意混合 holder 服务起点。环境允许静止 AOD 测量不代表真实光学串扰已验证。
4. 物理条件或整体架构需变更时向用户报告；普通工程修复自主执行并保留失败证据。

## 证据入口

- [测量落点合同/结果](../docs/readout_placement_policy.md)；[Q000 根因修复](../docs/axis_hold_strategy_fix.md)。
- [有序 QEC 与 SMT](../docs/qec_ordered_smt_comparison.md)；[有序贪心](../docs/ordered_axis_greedy.md)；[路线 V2](../docs/ordered_routes_v2.md)。
- [当前发布核验](logs/2026-09-15-stable-release.md)；[环境边界](../docs/environment_strategy_boundary.md)。
