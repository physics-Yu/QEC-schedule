# 2026-09-11 · 单台 AOD 多 trap 试验

- 状态：COMPLETED（本轮多 trap 试验交付；M4 整体仍在迭代）
- 用户目标：核对当前 trap 数；开放单 AOD 的更多格点并尝试真实编译。
- 起点：工作台 1×1 rigid、M4 单 trap，schema 17；底层已有矩形阵列及行列 masks。
- 本轮范围：工作台开放 1×1 / 1×2 / 1×4 rigid，尝试同排待用原子联合装卸与运输到 EZ，继续使用真实校验、Executor、可编辑工作台。保留单格点兼容输入和 M3 基线；不是多个独立 AOD 或并行 CZ。
- 计划：阵列正交路径、有限联合准备候选、输入/UI、独立重放和浏览器验收。所有源/目的支撑及活动空阱必须校验，容量不自动等于活动数。

## 已实现

- `motion/multi_trap.py`：1×2/1×4 rigid 阵列路径，保留全部轴固定间距、水平/垂直半格走廊；同排 READY CZ 所需原子的联合准备候选，比较完整实际服务成本。组内所有原子装到不同真实 cell，一起运输并卸到 EZ SLM，之后沿用 cell 0 门服务。终态恢复完整初始 axes/masks/holders。
- `simulation/m4.py` 按容量选构造器；`visualization/workbench.py` 验证 `aod_traps`，默认 1，仅多格点需要 greedy/adaptive；多格点右边界增加 10×(capacity−1) μm，但 SZ/EZ/SLM 几何保持。
- 编辑器有容量选择、新四门预设，viewer 的「查看联合运输」只在真实多原子 MOVE 存在时显示，定位实际区间中点。原编辑/随机/导入导出/失败报告/32× 保持。
- 捕获修正：初版 shuffled seed 13 在终态误报 CAPTURE_MISALIGNMENT，所有门已完成但归还失败，原输出 `artifacts/multi-acceptance.log` 保留。根因是 rigid 把关闭列之间的空隙当成完整捕获面。绑定动态 LOAD 改用 active_only，对活动 trap 近距/整段 sweep 不放宽；旧 planner 默认保守查询保留。L-002 更新范围与证据。
- 未增加 schema 字段，继续 schema 17。多 cell 非独立运动；没有长期多 cell 驻留、部分交接策略、2×2、batch CZ 或多 AOD。

## 本轮验证

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 初次新专项 | 14 passed，67.76 s | artifacts/multi-tests.log |
| M4/adaptive/正交/AOD Raman/workbench | 51 passed，223.68 s | artifacts/multi-regression.log |
| 新多 trap、动态支撑、rigid parking、row-column（捕获修正后） | 67 passed，240.30 s | artifacts/multi-physical.log |
| 六案例矩阵最终独立重放 | 全部 verified，含预期预算失败 | artifacts/multi-acceptance-final.log |
| 六份回放关键帧 1×/32× 与暂停续播 | PASS | artifacts/multi-playback.log |
| viewer 四移动原子、活动列、联合定位和完整终态 | PASS | artifacts/multi-controls.log |
| HTTP 实际编辑/随机/导入导出/撤销/重做/重编译 | PASS，使用独立 8766 服务 | artifacts/multi-editor-http.log |

51 项回归在捕获修正前启动，67 项专项在修正后运行；两者不是完整全套测试。未重复上一轮耗时约 14 分钟的全量回归。UI 接线时的两处字符串转义语法错误已在 Node syntax check 阶段修正，之后实际浏览器正常载入并完成编译。

同一四门输入（row，seed 7，完整归还）：

| 容量 | 峰值活动/携带数 | 总时间 μs | LOAD 次数 | 操作数 |
| --- | --- | --- | --- | --- |
| 1×1 | 1 / 1 | 2353.6 | 7 | 69 |
| 1×2 | 2 / 2 | 1983.6 | 6 | 59 |
| 1×4 | 4 / 4 | 1703.6 | 5 | 52 |

grid 的 1×4 容量例实际最多携带 2 原子，2023.6 μs；shuffled seed 13 选择单活动 trap 服务，2403.6 μs；预算 1 的记录仍真实携带过 4 原子，保留 1 门、386.3 μs 后报告预算耗尽。容量比较同时改变右侧容量留白，不能声称同硬件绝对加速或所有电路都更快。

## 浏览器与交付

8767 PID 8364，输出 `artifacts/workbench-multi-trap`；8766 PID 10880，复用前核实。保留用户原页面草稿，另开 tab 17。

真实浏览器已确认四门/4 trap 编译 1703.6 μs / 52 操作；联合阶段四个 Q 均显示 AOD·移动、不同真实列同时承载。新增 Q003 的 H 后实际 5/5 门，1704.6 μs / 53 操作，关键帧 32× 到终态。对同一五门草稿切到 2 trap 后实际重编译为 2274.6 μs / 68 操作。四 trap 随机线路实际 8/8 门、1055.3 μs / 38 操作，真实时间模式 32× 到终态。最终恢复四门预设重新编译通过，tab 17 停在四原子联合运输阶段，并已 markDeliverable。画布和四个 AOD holder 的截图均实际查看。

## 复现与后续

`python examples/validate_multi_trap.py`，配置 `configs/workbench/multi_trap.json`，产物 `artifacts/multi-trap`。关键源码指纹保存在 `artifacts/multi-trap/source-sha256.json`；新规范/日志/handoff 相对链接检查通过。详细契约见 [多 trap](../../docs/multi_trap.md)。本轮未创建 Git 提交或发布。

下一步可比较跨门保留多个 loaded cell、部分 PARK/RECAPTURE、行列扩展与更细组选择；在当前 finite greedy 范围内继续保持任意受支持线路编辑和实际成功/失败报告。未验证长时 FPS、量子态/保真度或实验波形。
