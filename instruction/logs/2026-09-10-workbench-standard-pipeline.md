# 2026-09-10 · 固化工作台 pipeline 与交互调整

- 状态：COMPLETED（修改、逻辑/接口验收完成；浏览器视觉检查受工具连接限制）
- 用户要求：固化现有 pipeline；单比特光固定 1 μs 不作为选项；初始条件先于 gate 设置；播放最大 32×。
- 本轮范围：固定硬件时长/输入、页面顺序和回放倍率，保存为维护规范；不改变 M3 并行边界。
- 决策：1 μs 为本轮用户明确确认的项目参数，纠正上一轮自行使用 5 μs 的假设，不描述为新实验标定。

## 验证与交接

- HardwareConfig 固定 Raman 1 μs，拒绝不同值/布尔值；序列化字段保留审核。旧 5 μs checkpoint 不能继续按当前契约恢复，须重编译，不改历史 trace/recording。
- workbench 输入/输出和 UI 移除时长选项，旧线路导入丢弃废弃 raman_duration_us 字段；更新示例。初始条件 DOM 和视觉阅读顺序提前，编号改为 01 初始条件 / 02 量子线路 / 03 回放。
- 共用 viewer 增加 2×、8×、16×、32×（保留 0.25×/1×/4×）；两种模式共用原 tick，不改变实际时间/路径/指标。
- agent.md 明确固定 pipeline、默认启动与维护入口；docs/circuit_workbench、相关 instruction、README/handoff 同步。没有新增另一套动画路径或完成 M3 并行。

| 检查 | 本轮结果 |
| --- | --- |
| Raman/workbench/foundations/visualization/dynamic_traps 的 pytest | 90 passed，1 warning，43.60 s；未重跑全套 |
| examples/compile_workbench.py | 4 gates、26 ops、60 commits，wall 1163.2898987322333 μs，Raman 3 μs；3 LOAD/3 OFFLOAD，原子路程 181 μm、AOD 路程 279.99494936611666 μm，运输不变 |
| node tests/raman_controls.cjs | 当前生成数据的 Raman 参数、1 μs 时长、原位 holder、统计通过 |
| node tests/viewer_speeds.cjs | 0.25–32× 两模式真实时间/演示时间的独立预期、结束停止、数据不变通过；不是浏览器 FPS |
| Node JS 语法 | workbench.js 通过 |
| 本地 HTTP | 页面初始条件在门设置前、无 Raman 时长控件、bundle 含 32×；旧时长 5 的 U3 输入编译实际 1 μs，新规范输入无时长字段 |
| 真实浏览器 | 两次 cua.getState 均 nodeRepl.fetch request failed；本轮未完成视觉验收，不借用旧证据 |

warning 为既有 dateutil utcfromtimestamp 弃用提示。源码修改后重启 8766，当前服务 PID 22124；重启前核对旧进程 8160 的命令行及无运行的编译子进程。没有刷新或清空用户草稿；加载新 UI 前应先导出再刷新。

## 复现与下一步

```powershell
python examples/circuit_workbench.py --port 8766
python examples/compile_workbench.py
python -m pytest tests/test_raman.py tests/test_workbench.py tests/test_foundations.py tests/test_visualization.py tests/test_dynamic_traps.py -q --tb=short
node tests/raman_controls.cjs
node tests/viewer_speeds.cjs
```

产物来自源模块重建；仓库整体仍未跟踪，无提交/发布，未覆写已完成历史日志。后续沿用本 pipeline；M3-B 独立任务 IR、M3-C 持久续接和 M3-D 并行仍按原依赖推进。浏览器连接恢复后可补本轮外观检查。
