# 可重构行列 AOD 后端

状态：COMPLETED（实现、物理与离线控制验收完成；新后端实际浏览器观感未自动验收）。日期：2026-09-10。

用户授权：查阅 Lukin 团队实现与约束，新增可选择的 AOD 运动后端，不要求逐字套用此前 lattice 抽象。

依据：Bluvstein et al., Nature 604 (2022), Optical tweezer generation；Nature 626 (2024), Shuttling and transfers。行列联动、顺序不交叉、伸缩平移、三次轨迹；保留实验与运动学简化的边界。

计划：配置/状态/操作与 backend 选择 → 全路径验证和计时 → compiler/Executor/checkpoint/指标 → 自动回放 → 压缩配对与负例 → 文档交接。

注意：开始时发现 agent.md 与源码已经包含 schema 5、M2 和旧审计修复，而 handoff 摘要仍停留旧状态；本轮以当前源码为基线，不回退这些变更。

## 已完成

- `domain/aod.py` 定义有序轴配置；AOD runtime 增加相对轴 offsets，position 仍从 holder/cell 派生。配置选择 rigid / row_column。
- `hardware/row_column_aod.py` 实现有序 Cartesian 行列运动、最小轴间距、世界范围、移动–静态与移动–移动两类整段 clearance，理想对齐捕获、共享卸载/门校验；保留原 rigid 后端。
- 三次 `u=3s²−2s³`，按整个阵列最长 trap 路径计算峰值速度/加速度/段内 jerk 的时长下限；未模拟段边界加速度连续性或光场动力学。
- compiler 新增同次捕获的同行/同列双 mobile pair 运输压缩/展开归还；原 mobile–static 路径按 backend 计时；不实现任意重排或 KEEP。
- Executor、runtime 验证、checkpoint codec、指标、Python/Canvas/PNG 轨迹均接入；schema 6 明确拒绝旧 schema。每个变形段保存目标轴，计划保存初始轴；原子路程逐颗求和。
- 同目录 M2 的多 plan/gate/frontier/capture 回放扩展已保留，并重新回归；不恢复旧单 G000 页面。
- 新配置 `configs/hardware/row_column.json`，新命令 `examples/run_reconfigurable_aod.py --backend row_column|rigid`，新规范 `instruction/aod_backends.md`；agent 路由、相关物理/视觉/状态/schema 文档与当前交接已同步。

## 文献与抽象分类

正式来源链接及映射见 [后端规范](../aod_backends.md)。行列联动、不可交叉、伸缩平移、三次轨迹和两种 pair 对应公开方法。具体三次公式、峰值参数、1 μm 轴间距、2 μm gate 阈值、固定装卸时长和 capture 模型是明确的项目简化/未标定参数，不是作者实验控制源码或设备校准复刻。

## 验证与独立结果

| 检查 | 结果 |
| --- | --- |
| `python -m pytest --visual -q` | 122 passed，M0 六组报告重建；1 个既有 dateutil 弃用警告 |
| 最后补充同列压缩分支后 `python -m pytest tests/test_row_column_aod.py -q` | 12 passed；增加的是测试，运行时代码未再改变；最终测试集合为 123 项，未重跑整个集合来重复取证 |
| `python examples/run_single_gate.py` | 5 个 M1 场景通过，312.3 / 156.3 μs、56/112 μm 不变 |
| `python examples/run_circuit.py` | 5 个 M2 场景通过，三门 1112.9 / 888.9 μs、256/216 μm 不变 |
| `node tests/replay_controls.cjs` | baseline、incidental、three_gate、join 四场景通过 |
| `python examples/run_reconfigurable_aod.py` | pair_compression、incidental、mobile_static 三场景通过 |
| `python examples/run_reconfigurable_aod.py --backend rigid` | 压缩/附带两例预期拒绝；mobile_static 成功且保持 312.3 μs |
| `node tests/replay_row_column.cjs` | 三场景通过：三次轴插值、实际空 trap 坐标、双时间模式、短门与源数据不变 |

物理专项覆盖：行列独立且共享交点、逆序/重合/轴间距/数目/越界拒绝、两端安全但中途过近的移动 pair、变形中途静态障碍、附带原子导致多余 pair、每个真实事件边界恢复、当前轴/目标配置篡改、峰值运动学上限、同行和同列的压缩门。

独立数值：压缩中 Q000/Q001 的 x 从 0/10 到 4/6；1/4 段时间下按三次 u=0.15625，应为 0.625/9.375。中列 Q002 的 x 保持 5，整个压缩段不位移，scene 显示 idle。包含该原子的总路程 166 μm，未包含时 116 μm；AOD envelope 都为 58 μm。周期 608.1182574079205 μs，门完成 304.20912870396023 μs。

静态查看 `artifacts/row_column/incidental/pulse.png`：两红色 mobile 原子位于 EZ、间距 2 μm；中列附带原子在另一行；空 trap 随列压缩，静态伙伴没有被伪造移动。这里只为有因果差异的压缩前/pulse/最终状态生成三张图，没有按每条低层测试重复截图。

## 剩余边界与交接

本轮检查了 16 份维护文档的 125 个相对链接，无缺失。关键文件 SHA-256：

```text
hardware/row_column_aod.py  d32a621dd94bc02caaa651110fabc5b0e7ee20d914758ab6d90e9eb420a04671
motion/row_column_compiler.py  f60d266dc81941811aab5dd7ee12c4b8b723afd4d6d22135a8181810c44cc86c
configs/hardware/row_column.json  13bb84373b0ecf7500d5b24bab41c5d36da873c33878d33f4e4daf56837e10c9
```

- row_column 的真实浏览器动画观感未自动验收；本轮仅执行离线 DOM/Canvas 控制检查和静态 pulse 图查看。
- 三次函数的段边界加速度可跳变；RF 波形、强度斜坡、温度/损失、量子态与实验保真度未实现。
- 当前编译器只覆盖限定同捕获行/列 pair 和原 mobile–static 路径；不存在任意 2D 重排、开关行列、独立原子移动或新站点 KEEP。
- M3–M6 顺序不变。后续变更需通过 get_backend 使用对应几何与计时，禁止把 rigid 的 `distance × atom_count` 或固定间距绘图直接用于变形阵列。
