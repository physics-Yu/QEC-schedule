# AOD trap 严格中心间距与画布分组

状态：COMPLETE。

用户指出旧 x=(4,5,6) μm 压缩案例虽然两侧原子相距 2 μm，但中间空 trap 依然存在，相邻 trap 仅 1 μm。原先允许等于 1 μm 的轴检查不足；这是模型硬约束错误，不是路线合并或画面插值问题。

本轮要求：所有 AOD trap（包含空 trap）整个操作过程中中心间距严格大于 1.01 μm；rigid 与 row_column 同样适用。1.01 μm 来自用户的模型要求，不是从论文推导的普适共振阈值。真实 RF/光场共振尚未模拟。

实现：共享 `hardware/trap_spacing.py` 硬下限为 1.01，配置只能提高有效下限；浮点近似等于边界也保守拒绝。SimulationState 初始构建/恢复以及两个 backend 的 pose/整段校验都接入。共享单调进度下，各相邻行列间距是起终值的凸组合；检查两端可保证全段所有 Cartesian trap 的间距，包含空交点。

旧外侧双列案例改为 `outer_pair_blocked` 拒绝用例，数学限制：两个间隙各 >1.01，则目标距离 >2.02，与原有 2 μm 门半径不相容。合法演示明确改为相邻列 Q000=(0,0)、Q001=(5,0)，门时轴 x=(4,6,8)，最小中心距 2 μm；不扩大门半径、不隐去空 trap。

UI：折叠“画布显示”，分为布局与陷阱、编号与轨迹、动效与安全边界。SLM 边界同心但与位置标记有不同语义：实线固定像素环表示 trap，虚线按 μm 绘制表示安全半径；默认关闭，解释放在相关开关旁。显示开关不影响硬约束。面板实时显示所有 AOD trap 的最小中心距与 >1.01 μm 条件。

物理参考：
- [Bluvstein 2022 Methods](https://www.nature.com/articles/s41586-022-04592-6)：行列不交叉，避免驱动频率分量相交相关加热/损失；不是 1.01 μm 数值依据。
- [Bluvstein 2024 Methods](https://www.nature.com/articles/s41586-023-06927-3)：行列运输和驱动相位/干涉处理；本项目仍只做几何与运动学检查。

## 本轮验证

| 检查 | 结果 |
| --- | --- |
| `python -m pytest -q --disable-warnings` | 171 passed, 1 个既有 warning；输出 artifacts/trap-spacing-regression.txt |
| `python -m pytest tests/test_trap_spacing.py -q --disable-warnings` | 14 passed；在全量测试启动后补充的专项，未把两次数量冒称一次全量结果 |
| 边界与完整轨迹 | 1.00/1.01 拒绝，1.010001 接受；空行列、初始态、两个 backend、降低配置绕过、加严配置、旧三列目标、提交/恢复损坏拒绝；独立枚举 201 个三次进度下所有 Cartesian trap 对 |
| Node `display_settings.cjs` | 两种 backend 记录的分组结构、开关计数、最小间距读数、零图层下物理不变性通过 |
| Node `replay_controls.cjs` / `replay_row_column.cjs` | M1/M2 四例与 row_column 三例通过，包括两个时间模式与门状态 |
| Node `motion_controls.cjs` / `viewer_component.cjs` / `schedule_controls.cjs` | 路线、开关、组件规模/隔离/分页/清理与时序联动通过 |
| 报告重建 | motion-planner 三例、row_column 三个成功例 + 一个旧外列拒绝例、M1/M2 各五例与三门独立 viewer 通过 |
| 静态图 | 查看新 incidental/pulse.png：Q000/Q001 在 x=4/6，第三个空 AOD trap 在 x=8，全部间距满足新下限 |

当前 row_column 正例使用相邻列，不能与旧外侧目标案例混为同一初始条件。AOD 最长 trap 单程位移 `2.5+25+4.5=32` μm，往返 64 μm；两个目标各 58 μm，incidental 另加 58 μm，所以 atom=116/174 μm。三次 profile 周期为 `200.3+2*(sqrt(1500)+sqrt(15000)+sqrt(2700))=626.6316896565988` μs，门完成 313.4658448282994 μs。

SLM 排斥半径保持独立的 1 μm 项目简化。AOD–AOD 严格间距没有装卸豁免；AOD–SLM 的实际交接仍允许经验证的对齐端点。不可把这两项参数或像素圆环半径混为一谈。

共享目录的 rigid 部分交接实现已保留；本轮全量测试包含其既有测试。当前 checkpoint 仍为 schema 8，老快照如果含不合法的 AOD 间距，将在状态构建/计划推演时拒绝。安全阈值变化需要重建演示。

本地 HTML 自动浏览的 URL 策略限制仍在，本轮未新增真实浏览器视觉验收；Node doubles 和静态 PNG 检查分别记录，不能代替真实浏览器截图。后续如要调整 1.01 μm 模型下限，必须有用户明确修改要求；不得为让旧外列用例通过而放宽它。
