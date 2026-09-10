# 程序接入原子运动可视化

运动视图是 `neutral_atom_env.visualization` 中的只读组件。它观察已提交的状态，支持当前单 AOD 的 rigid 和 row_column 后端；不创建计划、不修改 holder，也不执行物理操作。

## Python 接入

```python
from neutral_atom_env.simulation.milestone2_factory import make_circuit_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.visualization import VisualRecorder

state = make_circuit_state('three_gate')
recorder = VisualRecorder(state)
result = EagerScheduler(state).run(on_event=recorder.observe)
recorder.write('artifacts/my-run/index.html')
recorder.write_json('artifacts/my-run/recording.json')
```

这是可直接嵌入运行入口的 observer。若手动使用 Executor，在每次成功提交事件后调用 `recorder.observe(state)`；状态版本必须递增，同一仿真时间可以有多个提交版本。初始化记录器只需一次，不要重复观察同一版本。记录器应在执行开始前接入，才能保留全部轨迹；从运行中状态接入只能展示观察到的后续窗口。

`write()` 输出无外部依赖的 HTML，可直接打开或嵌入 iframe。它记录运行后生成回放，不会自动向浏览器推送实时状态。

```powershell
python examples/visualize_circuit.py --scenario three_gate --output artifacts/visualization
```

该入口生成 `index.html`、`recording.json`、`atom-viewer.js`，不逐事件收集完整 checkpoint 或生成逐门图片。M1/M2 验收报告额外保留的 snapshots/trace 用于验证和调试，不是组件必需数据。

## 嵌入已有网页

`write_bundle(directory)` 可单独导出 `atom-viewer.js`。在已有页面加载该文件和 recording JSON 后：

```html
<div id="motion"></div>
<script src="atom-viewer.js"></script>
<script>
fetch('recording.json').then(r => r.json()).then(recording => {
  const view = window.NeutralAtomViewer.mount(
    document.getElementById('motion'), recording
  );
  view.setTime(156);
  view.selectAtom('Q000');
  // view.play(); view.pause(); view.getStatus();
  // 页面卸载该组件时：view.destroy();
});
</script>
```

此 fetch 示例应通过 HTTP 服务打开；直接打开本地文件使用 `write()` 的自包含页面。组件采用 Shadow DOM 隔离样式和控件，同页可挂载多个独立实例。同一个容器再次挂载会销毁旧实例；`destroy()` 释放动画帧、ResizeObserver 和页面监听器。`setTime()` 接受有限 μs 数值并限制在记录区间内。`debug` 仅供本仓库确定性检查，不属于稳定接入接口。

## 数据和统计口径

主要指标下的 schedule 表以真实仿真时间为横轴、固定七类操作为行，分别显示每次操作的起止区间与右侧累计耗时。点击色块可跳转运动回放，虚线游标随回放移动；短门脉冲使用最小 2 px 标记并保留真实时长。`summary.schedule` 是按起始时间排序的 `{start, end, category}` 列表，包含空闲间隙；它是显示格式的新增字段，物理 checkpoint 不变。

- `neutral-atom-view/1` 是可视化数据格式，与物理 checkpoint schema 8 分开。world 几何仅保存一次；每帧保存时间、设备轴、当前门和改变的 `atom_updates`，不重复 trace 和完整 world。已有快照可经 `VisualRecorder.from_snapshots()` 转换。
- 汇总固定七类：装载、载原子运输、载原子回程、卸载、门脉冲、空载移动、等待。回程指同一计划门脉冲之后的载原子移动。类别累计的是设备占用 μs，同一段不会按原子数重复加总。
- 移动模式抽象为整体平移和行列变形，另列段数、设备时间。`transport_atom_time_us` 为 MOVE 段时长乘以承载原子数，单位 atom·μs；包括行列变形中承载但原位不动的交点，不能解释成每颗原子实际移动时长。原子总路程仍取物理 metrics。
- 汇总窗口从本次观察开始与 episode 开始的较晚时刻到最后记录时刻；逻辑完成指标来自 episode metrics。若从中途接入，两者起点可能不同。当前只支持串行设备区间；重叠操作明确拒绝，未来并发必须增加资源维度。

## 规模与边界

列表每页最多 32 个原子、12 个操作；默认只标记悬停/选中原子，轨迹仅绘制选中原子的最多 128 个历史采样点。浏览器通过每 64 帧一个原子索引和最多 4 帧场景缓存进行随机定位，避免每帧复制完整静态世界。

512 原子、257 个 WAIT 状态帧的检查覆盖数据大小、搜索、分页和 DOM 上界；这不是 512 原子的真实运输基准，也不是浏览器 FPS 保证。每次观察仍遍历原子，画布仍绘制当前布局；全部原子每帧变化时数据仍随变化量增长。多 AOD、并发窗口、无限长流式记录和实时浏览器推送尚未实现。

视觉语义与维护要求见 [可视化规范](../instruction/visualization.md)。

## 路线与 SLM 避让显示

共享 recorder 按 plan 保存去程的逐原子途经点（`plans`），frame 用 plan_id 引用，operations 记录 planner_id 与 transfer_phase。共享 viewer 的“计划路线”默认开启，“SLM 避让区”可选。未选中时显示首个被运输门操作数，选择其他原子后切换对应路线；候选网格点不作实际 trap 障碍。两种回放时间模式只影响展示。物理契约、复杂性与重建命令见 [motion_planning](../instruction/motion_planning.md)。

## 当前画布显示分组与距离语义

所有开关收进默认折叠的“画布显示”，按“布局与陷阱”“编号与轨迹”“动效与安全边界”三组展示，并显示开启数量。可独立隐藏区域、网格、SLM/AOD 标记、路线、轨迹、操作动效和 SLM 边界。编号仍有三档。隐藏图层不修改 backend 约束。

SLM 灰蓝实线环为固定像素位置标记，SLM 中心排斥边界为按 μm 绘制的同心虚线；默认关闭，在开关旁解释其安全距离语义，不当作第二个 trap 或真实光斑。面板实时显示所有 AOD trap 的最小中心距（含空 trap）及严格 >1.01 μm 的硬约束，和 SLM 排斥半径分开描述。`scene.aod_minimum_spacing_um` 记录有效阈值。
