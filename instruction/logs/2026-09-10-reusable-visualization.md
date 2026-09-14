# 2026-09-10 · 可复用运动视图与汇总统计

- 状态：COMPLETED
- 用户要求：默认用主要时间占用与抽象运输模式统计；把运动可视化复用进程序，而不是只输出具体门的 schedule 长图。
- 范围：可视化组件、只读 recorder、固定类别摘要、报告接入与规模检查。保留正在并行开发的 row_column backend，不修改物理执行或参数。
- 基线：M2 eager 电路已实现；同目录 row_column 后端任务使用 schema 6。本轮保留其物理实现，并迁移其回放检查到共用组件。
- 相关规范：[可视化](../visualization.md)、[架构](../architecture.md)、[验证](../validation.md)、[接入文档](../../docs/visualization.md)。

## 完成内容

- 新增 `src/neutral_atom_env/visualization/`：记录器、固定统计、独立 HTML/bundle 输出、Canvas 组件与 Shadow DOM 外壳。`EagerScheduler.run(on_event=recorder.observe)` 直接观察执行，无需逐帧完整 snapshot。
- world 几何仅记录一次，原子只记录差量；浏览器按时间二分、每 64 帧索引和 4 个场景缓存定位。列表最多 32 原子/12 操作，支持搜索和分页，选中轨迹采样最多 128 点。快速圆/菱形绘制保留装卸 morph；密集坐标刻度按屏幕间隔抽样。
- `NeutralAtomViewer.mount(container, recording)` 可在已有网页挂载多个独立实例；提供时间/原子选择、播放/暂停、状态与销毁接口。清理 RAF、resize 和 visibility 监听器。同容器重挂自动销毁旧组件。
- 固定七类统计取代 29 行及更长的操作图；归类整体平移/行列变形。设备 μs、承载 atom·μs、物理原子路程分别统计。三门总时长 1112.9 μs：装载 300、运输 216、回程 216、卸载 300、门 0.9、空载 80、等待 0。
- M1/M2 报告显示主要指标并直接嵌入同一运动组件；统计图片和操作细节按需展开。旧 animation/timeline Python 接口保留为适配器；`testing/replay.html` 标记为历史参考。
- `examples/visualize_circuit.py` 是实际程序接入示例，输出独立页面、JSON 和脚本。更新 package data、README、接入文档、规范与 handoff。
- 浏览器检查发现并修复纯等待误标“空载平移”；行列变形的原位交点仍显示 idle，完整轴采用三次轨迹。

## 验证

| 命令/检查 | 结果 | 证据 |
| --- | --- | --- |
| `python -m pytest -q` | 129 passed | 一个既有 dateutil deprecation warning，33.38 s |
| `python -m pytest tests/test_visualization.py -q` | 最终微调后 6 passed | 分类别独立预期、区间裁剪/重叠拒绝、observer 不写状态、差量规模、同时间版本、真实行列运动 |
| `python examples/run_single_gate.py` | 5 PASS | `artifacts/milestone1/index.html` |
| `python examples/run_circuit.py` | 5 PASS | `artifacts/milestone2/index.html` |
| `python examples/run_reconfigurable_aod.py --backend row_column` | 3 passed | `artifacts/row_column/index.html` |
| `python examples/visualize_circuit.py` | completed | 65 帧，recording.json 54957 bytes |
| `node tests/replay_controls.cjs` | 4 场景 PASS | 原控制语义、两种时钟、配对、装卸、空载、最终状态与数据不变 |
| `node tests/replay_row_column.cjs` | 3 场景 PASS | 改用共用 harness；三次轴、空 trap、静止交点、时钟、脉冲 |
| `node tests/viewer_component.cjs` | PASS | 搜索/分页、组件隔离和销毁、同页数据不变、三门分页、行列插值 |
| 512 原子 × 257 WAIT 帧 | PASS | 仅初始 512 条 atom_updates，JSON 小于 600000 bytes，无 snapshot 调用，DOM 少于 160 节点；120 次替身重绘最终约 504 ms，不是浏览器 FPS |
| 静态图片查看 | 已完成 | seven-category `artifacts/milestone2/three_gate/timeline.png` |
| 真实浏览器 | 已完成烟雾检查 | 独立视图首门定位 156 μs、红色作用对；512 原子 16 页，搜索选择 Q511 显示 155,-75 μm/SLM S511；重绘后刻度无重叠、等待说明正确；M2 报告统计与 iframe 已加载 |

测试夹具 `artifacts/visualization-scale/` 与 `artifacts/visualization-row-column/` 由 Python 专项测试生成，Node 组件检查随后读取。所有产物从源码生成。

## 决策、限制与下一步

- 用户要求把移动抽象成统计并复用可视化；本轮未改变 world、硬件参数、holder、计划、CZ 判据或物理 metrics。
- `neutral-atom-view/1` 为显示格式，不是 checkpoint。加载/卸载动画仅表达交接进度，实际承载仍在事件提交时改变。未实现新的物理能力。
- 单 AOD 串行时间分类可以相加，未来并发要增加资源维度。承载 atom·μs 包括变形中静止的交点；不解释为实际移动 atom·μs。
- 记录器每帧仍遍历原子，画布仍渲染当前场景；全部原子持续变化时存储增长，未实现无限长流或实时浏览器推送。规模夹具只有 WAIT，不能当成 512 原子运输性能证据。
- 未做全屏宽、长时间真实浏览器 FPS 与 row_column 真实浏览器专项验收；后者本轮有 Python/Node 几何与插值检查。后续按实际性能证据决定空间索引、增量流或并发资源视图；物理里程碑仍按 handoff 的 M3 路线推进。

## 可复现信息

Windows PowerShell；Python 项目当前环境，Node.js 24.19.0。上述示例使用现有 factory 默认配置，不增加随机扰动。浏览器烟雾检查使用临时 localhost HTTP 服务，工作结束关闭。源代码尚处于项目初始未跟踪状态，不以不存在的提交号标识版本；产物跨机器按表中命令重建。
