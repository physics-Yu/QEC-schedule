# 2026-09-10 · 时间占用的时序视图

- 状态：COMPLETED
- 用户要求：主要指标与时间占用显示类似 schedule 的表，既保留占用量，也表达操作发生的先后时间。
- 范围：固定类别行、真实 μs 横轴、操作区间和门标记、累计列；共用组件及静态图，不修改物理执行。


## 实现

- `visualization/summary.py` 增加按时间排序的 schedule 区间，裁剪未完成操作并补齐空闲；设备累计口径不变。PNG 改用实际 start/end 绘制固定类别行，右侧保留总 μs/占比。
- `visualization/viewer.js` 将横向累计条替换为 SVG schedule：真实 μs 横轴、七类固定行、逐区间色块、门 ID、累计列；悬停显示时长，点击或 Enter/Space 跳转真实起点，虚线游标与播放器同步。短脉冲最小 2 px，并在页面明确其为显示标记。
- 不改变原子坐标、holder、硬件参数、编译器、调度器、物理 checkpoint 或 metrics。显示数据为原有格式的新增 schedule 字段，支持既有 operations 回退。
- 文档和 handoff 同步更新。现有程序导出与 M1/M2/row_column 报告均从共用源码重建。

## 本轮验证

| 检查 | 结果 |
| --- | --- |
| `python -m pytest tests/test_visualization.py -q` | 6 passed；增加 156/488.3/888.6 μs 三脉冲、区间裁剪和空闲区间检查 |
| `node tests/schedule_controls.cjs` | PASS；29 段位置/宽度、0.3 μs 脉冲最小标记、第三门 Q001/Q003、点击与键盘、游标和源数据不变 |
| `node tests/replay_controls.cjs` | 4 场景 PASS |
| `node tests/replay_row_column.cjs` | 3 场景 PASS |
| `node tests/viewer_component.cjs` | PASS；512 原子显示、隔离/清理、行列采样 |
| `python examples/visualize_circuit.py` | completed；65 帧，56382 bytes |
| `python examples/run_single_gate.py` | 5 PASS |
| `python examples/run_circuit.py` | 5 PASS |
| `python examples/run_reconfigurable_aod.py --backend row_column` | 3 passed |
| 查看 `artifacts/milestone2/three_gate/timeline.png` | 已完成；各阶段真实位置与右列累计清晰 |

## 限制与后续

浏览器 URL 安全策略拒绝自动访问本地 HTML，未绕过该限制，本轮不声明真实浏览器验收；可刷新当前页面人工查看 SVG 外观。Node 是控件逻辑替身，不是视觉浏览器。物理代码无变化，未重复全量 pytest。大量门的色块会在有限宽度下变密集，保留固定行和详情定位；尚无局部时间轴放大功能。

下一步按用户对时序表的反馈调整显示密度；物理后续仍按 handoff 的 M3 范围。产物被忽略，按上述命令重建，源码是正式维护入口。
