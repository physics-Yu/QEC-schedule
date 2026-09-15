# 2026-09-15 — 783 μs Q000 路径策略修复

用户提供 Q000/783 μs 精确定位，并强调修策略而非针对截图打补丁。

## 变更与证据

- 同原8对CZ、同落点、同row_column硬件反事实：原通道模板遗漏直接Y→X路径；新共享 `axis_hold` 规划器恢复直接/提前分轴保持候选，Q000出站13→8 μm，完整批1036.065→787.172 μs。
- 算法在strategies/motion，贪心/SMT/测量搬运共用。后端 `row_column_orthogonal` 仅限制正交原语，继承原有全部物理校验。硬件与路线选择分开；无原子ID/时刻/协议特判。
- 完整QEC新尝试 `artifacts/qec-axis-hold/attempt1`：两策略483槽/66计划与独立重放全通过，贪心27990.467 μs，SMT28628.305 μs；17CZ批、最大9并行；稳定子/XX/ZZ/完整协议/终态通过。对照数据详见 [报告](../../docs/axis_hold_strategy_fix.md)。
- 编辑器按逻辑层翻页，CZ原子对分轨，选中后编辑、单门条件/依赖、插入与明确删除，配置独立，手动编译。
- 入口8797，服务PID10936，输出attempt1；旧8796已打开页面保留。源码在main工作区，未提交推送。

## 检查与失败

- 35项专项/回归通过（test_axis_hold_routes、test_ordered_routes、test_ordered_axis_greedy、test_qec_ordered_comparison、test_environment_boundary）。
- 19项后端/回放/可视化回归通过（test_row_column_aod、test_visualization、test_replay_interaction）。架构138模块0违规。
- 首轮新增测试手抄伙伴编号Q005/Q014错误，精确作用对校验拒绝；核对原始决策后修正为Q001/Q010，同两后端验证通过。未放宽校验。
- 前期脚本默认GBK读取UTF8失败，改为显式UTF8；该工程错误没有触发物理改动。
- Node离线编辑控制器、完整两动画全部运动段三次插值、双模式32×终点通过。HTTP五槽编辑电路验证见api-acceptance.json。
- 内置浏览器连接失败；桌面Computer Use因无法可靠确定URL被终止。停止UI输入，无真实浏览器点击PASS声明。这是当前明确的验收缺口。

## 后续

先补真实浏览器阶段跳转、选门修改、编译与动画验收；算法后续应对多份同大小批次反馈实际路线成本，再评估联合行列构型图搜索。当前非完备高维最短路，非跨批驻留/全局SMT。
