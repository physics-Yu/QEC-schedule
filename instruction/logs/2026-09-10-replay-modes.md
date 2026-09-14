# 双模式回放与交接动画

日期：2026-09-10。状态：COMPLETED（实现与离线验收完成，浏览器实际动画观感未自动验收）。

## 目标

同一页面选择真实时间比例或关键帧演示；让装载/卸载的原位交接和短 CZ 可见。保持真实时间、holder 提交、轨迹与指标不变。

## 验收计划

- 基准与附带原子场景：仅完整捕获集参与交接，静态门伙伴不被动画搬动。
- 两种时间映射下事件顺序、边界、暂停/续播、跳转、切换与结束一致；关键帧模式完整显示短 CZ。
- 既有编号、trap 图层、选择、缩放与拖动回归；离线 Canvas 检查不冒充浏览器视觉验收。
- 重建 M1 报告，对比修改前后 snapshots / trace / plan / metrics；更新可视化规范和交接摘要。

## 实现

- `src/neutral_atom_env/testing/replay.html`：同页模式选择，默认关键帧；分段单调时间映射，关键帧进度条，演示/仿真双读数，阶段进度与 1× 展示时长。切换模式保留当前仿真时间并暂停；隐藏页面暂停，续播不补算后台时间。
- 真实比例 1× 为 25 μs / 屏幕 s；关键帧 LOAD 1.8 s、OFFLOAD 1.6 s、PULSE 1.8 s、MOVE 每段 0.8–2.2 s。本基准演示共 12 s，物理周期仍 312.3 μs。
- 装卸时在原位显示收拢/散开弧线与平滑圆点/菱形预览；侧栏 holder 在真实完成边界提交。门真实 running 期间显示 pair 连线强调和进度弧线。新增“操作动效”开关，不改变已有等尺寸 trap 与图层规则。
- `milestone1_report.py` 仅增加 `captured` 展示元数据，来自完整计划捕获集；基准 Q000，附带场景 Q000/Q002，静态伙伴 Q001 不参与交接。
- `tests/replay_controls.cjs` 为可留存的 Node 离线控制检查，从生成 HTML 执行模板逻辑；不调用浏览器、不生成额外重复截图。
- 同步 `instruction/visualization.md`、`validation.md`、`handoff.md`、日志索引及 `docs/milestone1.md`。

## 验证结果

| 命令 / 检查 | 结果 |
| --- | --- |
| `python examples/run_single_gate.py` | 5 个 M1 验收场景通过，baseline/incidental 回放已重建 |
| `node tests/replay_controls.cjs` | 两场景通过：原控件、两种时间映射、拖动/切换/事件跳转、装卸边界、暂停/续播/结束/页面隐藏 |
| 短门独立预期 | 关键帧 900 ms 后仿真从 156 到 156.15 μs，仍 running；再 900 ms 后到 156.3 μs，completed；1×/4× 下完整经过全部九段，静态伙伴保持 `(5,-25)` |
| 交接独立预期 | t=50 μs 标记预览为中间形状，但 holder 仍 STATIC；100 μs 才 MOBILE；262.3 μs 卸载中仍 MOBILE；312.3 μs 才 STATIC；原位不位移 |
| 不变性 | 界面操作后整个输入 payload 未改；重建前后 14 份 JSON/JSONL 物理产物 SHA-256 全部一致 |
| `python -m pytest -q` | 80 passed；一个既有 dateutil 弃用警告 |

重建入口仍为 `python examples/run_single_gate.py`；产物 `artifacts/milestone1/baseline/animation.html` 与 `incidental/animation.html`。Node.js 用于独立 UI 控制检查，不新增 Python 运行时依赖。

## 限制与下一步

- 未进行本轮实际浏览器绘制、字体、触控或动画观感验收。离线 DOM/Canvas 替身只证明控制行为和绘制代码可执行，不代替用户实际播放检查。此前浏览器本地页面访问受策略限制，未改用其他入口绕过。
- 交接形状/弧线、门连线是呈现效果，不是光场或量子动力学模拟；真实比例模式的极短脉冲仍可能在屏幕帧间被跳过，这是该模式的时间比例结果，可用关键帧模式观察。
- BUG-001/002 及其他既有 OPEN 项未在本任务修复。下一步先由用户在现有回放页确认视觉体验；物理开发仍按 handoff 中 BUG-001/002 → M2 的顺序执行。
