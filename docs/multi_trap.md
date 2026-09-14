# 单台 AOD 的多 trap 试验

> 当前工作台容量输入已扩至单台 rigid 二维阵列、行×列≤128，可编辑固定非均匀行列偏移，M4 与新增行实验策略均需 adaptive EZ。下方原 M4 物理验收覆盖 1/2/4 trap，主策略比较固定1 trap；扩大输入容量本身不证明所有 N 的电路可完成，也不表示批量 CZ。

2026-09-11。当前可编辑工作台可设置 **行×列，总容量≤128**；旧1×N输入（含1×9、1×36）保持，仍是 **一台 AOD**，不是多个独立运输设备。默认及缺失 `aod_traps` 的旧输入仍为 1×1；多格点输入用于 M4 四策略或 `row_symmetric` / `row_greedy` 行实验，并要求 `adaptive EZ`。

## 当前实现

`aod_traps` 为 1–128 的整数。1×1 保留原 5 μm 参考间距；N≥2 使用 **10 μm 固定列间距、1 行**，匹配现有 SZ 同排站点。全阵列刚性平移，允许按列开关；活动数量与容量分开。关闭列仍保留坐标和身份，不绕过世界边界和 trap 间距检查。

`motion/multi_trap.py` 包含阵列正交路径和有限联合准备候选。编译器在 READY CZ 操作数中寻找同排、跨度能放入阵列的一组原子，尝试联合 LOAD → 正交运输到一排空 EZ SLM → 联合 OFFLOAD，再执行所选 CZ。可顺带准备其他 READY CZ 的操作数，全部列入任务和成本。比较完整服务的实际时间、装卸及路程，不隐含瞬移。

组内所有已装载原子同步移动，仍走 `2.5+5k μm` 主通道与短正交接入；10 μm 列偏移使各 cell 保持同一通道族。每段对实际阵列完整校验，空活动 trap 也参与扫掠。各次 LOAD/OFFLOAD 按现有粗粒度交接成本计时，一次可交接多个对齐原子；这是现有硬件成本模型，不是经过标定的实验波形。

组准备后全部卸到 SLM，再沿用 cell 0 的门服务；当前并非多原子长期驻留/任意 cell 接续，也未实现批量 CZ、行列伸缩或 2×2 阵列。并行 CZ 仍受单作用槽约束。单比特门仍固定 1 μs、只有同类型可并行，静止 AOD/SLM 目标与其他存活原子间距需 ≥5 μm。

为了让固定容量的最右列始终在世界内，多格点世界边界右侧显式增加 `10×(capacity−1) μm` 的运输空间；SZ/EZ 寻址区域和 SLM 位置不扩大。比较容量时需同时说明这一几何配置差别。

## 捕获修正与安全条件

旧 rigid `capture_closure` 把整个矩形 footprint 内的未对齐原子都拒绝，即使附近列关闭。随机映射例在最终归还时因此误报 `CAPTURE_MISALIGNMENT`。实际动态 LOAD 现在以即将开启的列为准：离所有活动 trap 足够远的间隙原子不在捕获集中；靠近活动 trap 的未对齐原子仍拒绝。所有活动 trap 对全部静态原子的建立支撑与运动扫掠校验保留，未降低安全距离。旧 planner 的默认 footprint 保守查询接口保留，只有绑定 LOAD 使用 `active_only=True`。

四颗原子承载时关闭共享行会失败，不能因只关一条控制轴就忽略另外三颗。交接完成前 holder 不变；checkpoint 中途恢复先执行完联合任务，再让 compiler 决策。现有 schema 17 已记录完整轴、masks、bindings 和运行时，本次不新增 checkpoint 字段。

## 编辑与验收

在「初始条件 → 单台 AOD · trap 容量」选择 1、2、4；「载入示例 → 多 trap 验收 · 4 原子联合运输」载入四门输入。可继续修改门、原子数、layout、随机载入、导入导出及真实重编译。回放新增「查看联合运输」，只在实际存在多原子 MOVE 时出现，点击定位该段中点。活动数/容量和原子 holder 均来自真实状态。

```powershell
python examples/circuit_workbench.py --port 8767 --output artifacts/workbench-multi-trap
python examples/validate_multi_trap.py
python -m pytest -q tests/test_multi_trap.py tests/test_dynamic_traps.py
```

配置 `configs/workbench/multi_trap.json`；矩阵 `artifacts/multi-trap` 保存原输入、决策、诊断、trace、checkpoint、recording、HTML 和独立重放。完整结果见 [本轮日志](../instruction/logs/2026-09-11-multi-trap.md)。

有限候选不是全局最优；并非每个布局都能联合 4 颗，网格每排只有两颗时可能只用 2 个 trap。输入现在支持 128 原子/4096 门，HTTP 编译默认 90 秒，可显式配置每任务时限至 86400 秒；失败时保留实际报告。旧 1/2/4 trap 验收数字不作为更大容量的完成证据。未来可再比较长期驻留、部分 PARK/RECAPTURE、更多轴布局和更精细联合调度。


2026-09-12 新二维实验通过 `aod_rows` / `aod_columns` 及两组 `aod_*_offsets_um` 使用固定非均匀几何，surface模板为6×6、每轴0/10/20/40/50/60μm。四patch二维布局、guard开关和接口定义见 [工作台合同](circuit_workbench.md)。旧1/2/4/9/36列联合运输结果不替代新二维或批量CZ验收。
