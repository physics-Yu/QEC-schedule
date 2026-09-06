# 步骤 4：Atom、Zone、HardwareState 与静态布局

## 当前交付

本步骤实现抽象 qubit 到 atom 的初始映射、二维硬件几何、四类 zone、
trap sites 和 entangling pair slots，并导出经过校验的状态快照与静态图。
不执行移动、量子门、readout、资源占用或时序仿真。

默认布局是用于调试的示例参数，不是经过实验标定的机器。
长度统一为 **um**，时间统一为 **us**。图的 x 向右、y 向下。

实验布局约束：激光沿直线传播，并平行于实验平台，因此默认区域采用线性布置。
Memory（内部 ID 为 storage）、Entanglement、Measurement 从上到下同列对齐，
x 范围均为 [0,45]；y 范围分别为 [0,45]、[52,77]、[84,99]。
Reservoir 位于 Memory 右侧，范围为 x=[55,100]、y=[0,45]。
图中使用 Memory/Entanglement 名称，配置中的 STORAGE/ENTANGLING 类型保留。
这项约束决定区域相对位置；具体光束宽度、入射方向和寻址能力尚未建模。

## 默认布局验收值

| Zone | 初始原子数 | 容量（atoms） | trap sites | pair slots |
|---|---:|---:|---:|---:|
| Storage | 17 | 17 | 17 | 0 |
| Measurement | 0 | 8 | 8 | 0 |
| Entangling | 0 | 8 | 8 | 4 |
| Reservoir | 4 | 6 | 6 | 0 |

初始 t=0。总计 **21 个 atom**，其中：

- 9 个 data atom，蓝色圆点；
- 4 个 X ancilla，橙色三角；
- 4 个 Z ancilla，紫色方块；
- 4 个未分配 qubit 的备用原子 R0–R3，灰色菱形。

Storage 中 17 个原子与 d=3 code 的 17 个 qubit 一一对应。
data 排列为 3×3，ancilla 位于面中心与边界附近。
Measurement 和 Entangling 的空心圆是可用 trap；虚线是预定义 pair slot，
不表示正在执行的纠缠门。Entangling 的容量 8 atoms 对应 4 个 pair slots。

## 模型接口

```python
from qec_schedule.qec import create_code
from qec_schedule.hardware import load_hardware_config, build_initial_state

config = load_hardware_config("configs/hardware_default.yaml")
state = build_initial_state(create_code(), config)

atom = state.atom_for_qubit("L0:d0")
assert atom.position.x == 10
assert atom.position.y == 12
assert state.zones_by_id[atom.zone].allows("LOCAL_1Q")
snapshot = state.to_dict()
```

`Atom` 保存 atom_id、assigned_qubit、atom_type、position、zone、site_id、
state、syndrome_basis，不保存量子态。Data/ancilla 必须分配 qubit；reservoir 不分配。
ancilla 的 X/Z/Y/MIXED 标签来自 code 的公开 stabilizer 接口。

`Zone` 通过 `ZoneKind` 表示 STORAGE、ENTANGLING、MEASUREMENT、RESERVOIR，
统一保存 bounds、capacity、allowed_operations、sites 和可选 pair_slots。
capacity 始终以 atom 计数，且不超过 trap 数量；可以小于 trap 数量。
Pair slots 引用两个不同的 trap，各 pair 不共享 trap。

`HardwareState` 是不可变快照。atoms、zones 是 tuple，查找映射为只读映射。
可使用 `dataclasses.replace(state, atoms=new_atoms, current_time=...)`
构造一个经过完整校验的新快照，原快照不变。它不推进时间，也不分配硬件资源。

提供 `atoms_by_id`、`zones_by_id`、`qubit_to_atom`、`atom_for_qubit()`、
`atoms_in_zone()` 和 `to_dict()`；未知 qubit/zone 查询抛出 KeyError。

## 几何与状态约束

- 坐标和时间必须是有限数字，禁止 NaN、Infinity、bool；时间不能为负。
- Zone 不允许正面积重叠；边界可接触。trap 必须位于所属 zone 的闭区间内。
- zone ID、atom ID、全局 trap ID 必须唯一，一个 qubit 最多分配一个 atom。
- 静止 atom 必须位于所声明 trap 的精确配置位置，并且 zone/site 一致。
- 一个 trap 只能有一个静止 atom；zone 占用不能超过 capacity。
- 所有 trap，以及所有未丢失 atom 的位置，均须满足配置的最小间距。
  检查空 trap 间距可以避免生成一个未来填满后必然碰撞的布局。
- MEASURING 必须位于允许 MEASURE 的 zone；GATING 必须位于允许 gate 的 zone。

AtomState 包含 IDLE、MOVING、GATING、MEASURING、LOST。
默认布局全部 IDLE。MOVING 和 LOST 不占静态 site，zone/site 必须为 None；
MOVING 的当前位置仍参与间距检查。LOST 的 position 是最后已知位置，
不参与占位或碰撞；原 qubit 映射保留，调用方应检查 LOST 状态。
这些是数据表示约定，不代表已实现移动或丢失流程。
本步不检查连续轨迹、碰撞路径、Rydberg blockade、AOD field of view 或 laser 资源。
步骤 5 已增加 [ExperimentalIR 与 gate lowering](gate_lowering.md)，生成动作和资源需求，仍未执行调度。

## QEC 替换与布局配置

硬件映射只调用 QECCode 的公共接口，不读取 `RotatedSurfaceCode` 类型或 lattice coordinates。
默认按 `data_qubits() + ancilla_qubits()` 的顺序，依次填入 YAML 中的 Storage sites。
默认 YAML 的 site 顺序为 surface-code 示范选择；它不会自动为其他 code 优化几何。
已有独立 repetition-code 测试，证明替换 code 后可用同一映射接口构建状态。

自定义 code 可以提供自己的硬件 YAML；也可显式传入全量 qubit→site 映射：

```python
state = build_initial_state(code, config, placements={
    # 必须覆盖 code 中的每个 qubit；site 必须属于 Storage。
    # "my_qubit_0": "my_storage_site_0", ...
})
```

显式放置可以使用某 zone 中的任意已声明 trap，但实际 atom 数仍受 capacity 限制。
自动放置仅取每个 zone 的前 capacity 个 sites；备用原子同样按 reservoir site 顺序填入。
本阶段一次构建一个 code 实例；更大 code 或多 block 集成需提供足够的布局容量。

`configs/hardware_default.yaml` 使用安全 YAML loader，拒绝重复 key、未知字段、
缺失字段、错误单位和不支持的 schema。步骤 5 新增可选 timing 段，提供动作耗时和移动速度；
步骤 6 新增 [AOD tone、allowed_region 和 TRANSLATE 参数](aod_model.md)。
后续 laser 能力参数随对应实现加入 schema。仅创建容量或 pair slot 不代表已实现资源锁。

## 运行与验收

需要 Python 3.10+。核心配置依赖 PyYAML；绘图使用可选 Matplotlib extra。
本地已创建 `.venv`，PowerShell 中可以直接运行：

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[visualization]"
$env:MPLCONFIGDIR = "$PWD/results/.matplotlib"
.\.venv\Scripts\python.exe examples/demo_hardware_layout.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

在其他机器上，先使用 Python 3.10+ 执行 `python -m venv .venv`，再安装。
Linux/macOS 对应解释器为 `.venv/bin/python`。
MPLCONFIGDIR 指向项目结果目录，可以避免受限环境写入用户字体缓存目录的权限警告。

只需状态、不需绘图时：

```powershell
.\.venv\Scripts\python.exe examples/demo_hardware_layout.py --no-plot
.\.venv\Scripts\python.exe examples/demo_hardware_layout.py --block-id L1 --output-dir results/layout_L1
```

输出：`results/hardware_state.json` 和 `results/hardware_layout.png`。
图只读取 HardwareState，不读取 QEC 电路或推测运动。
输出由配置和 code 可重建，保持在 Git 忽略目录；GitHub Actions 为 Python 3.10/3.12
生成并上传这两个验收文件为 workflow artifact。

本步骤新增 11 项测试，累计 **26 项**，验证默认映射、替换 code、显式布局、不可变性、
边界、容量、重复占位、pair slots、间距、状态语义、安全 YAML 及实际 PNG 渲染。
另外已人工检查默认图片，确认标签、图例和各区域内容可读。

请验收默认区域位置、data/ancilla 排列、容量和占位图。
当前已继续实现 [步骤 5：ExperimentalIR 与 gate lowering](gate_lowering.md)。
