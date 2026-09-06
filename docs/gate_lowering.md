# 步骤 5：ExperimentalIR 与 gate lowering

## 当前能力与边界

`GateLowerer` 消费 PhysicalCircuit 和初始 HardwareState，将每个 physical gate
展开成显式实验动作请求。它不访问具体 QECCode、不生成 syndrome circuit，
也不决定 priority、并行批次或开始时间。

沿用已确认的线性布局：Memory → Entanglement → Measurement 从上到下对齐，
Reservoir 位于 Memory 右侧。

```python
from qec_schedule.qec import create_code
from qec_schedule.hardware import load_hardware_config, build_initial_state
from qec_schedule.lowering import GateLowerer

config = load_hardware_config("configs/hardware_default.yaml")
code = create_code()
state = build_initial_state(code, config)
plan = GateLowerer(config.timing).lower(code.syndrome_round(), state)
requests = plan.to_dict()
```

输入要求：idle 初始快照，每个 circuit qubit 都有映射且初始位于 Memory/Storage。
初始 site 作为该 atom 的 home site。输入对象不可变，lowering 不更新真实位置或时间。
内部仅沿合法参考门顺序计算每个 atom 的预计位置，供生成后续 requests 使用。

## 动作展开

| Physical gate | 实验请求 |
|---|---|
| H / X / Y / Z | 原地 SINGLE_QUBIT |
| CZ | 两个 atom 各自 PICKUP → MOVE → DROPOFF；ENTANGLE；各自 PICKUP → MOVE → DROPOFF 返回 home |
| CNOT(c,t) | H(t) → 上述 CZ 动作链 → H(t) |
| MEASURE_Z | PICKUP → MOVE 到 Measurement → DROPOFF → MEASURE |
| MEASURE_X | H → 上述 Z-basis measurement 动作链 |
| PREPARE | PREPARE，当前只支持准备到 0 |
| RESET | RESET 到 0；若不在 home，随后 PICKUP → MOVE → DROPOFF 返回 home |

单个 CZ 是 **13 个动作**，entangle 依赖两个入场 DROPOFF；physical gate completion
必须等两个返回 home 的 DROPOFF 都完成。列表中分开打印两条移动链不意味着强制串行：
两条入场链具有相同的外部依赖、互不依赖；实际并行受 AOD 模型和资源限制。

默认 Measurement 允许 RESET，所以测量后的 reset 在 Measurement 原地进行，随后返回。
仅测量、没有后继离场时，原子留在 Measurement。重复 Z 测量可原地进行。
如果后续单比特操作在当前 zone 不允许，先返回支持该操作的 home 再执行。
没有可执行该操作的 zone、没有可用 pair slot 或 measurement site 时明确报错。

## ExperimentalIR

`ExperimentalAction` 是不可变记录，包含：

- id、gate_id、action_type、atoms；
- start_time=None、duration（us）；
- sources、targets：与 atoms 逐项对应的 zone/site/position；
- dependencies：实验 action ID；
- required_resources：资源名与请求数量；
- metadata：physical gate、round/check、gate label、transport_id 等。

ActionType：PICKUP、MOVE、DROPOFF、SINGLE_QUBIT、ENTANGLE、MEASURE、PREPARE、RESET。
两原子操作需要逐原子 source/target，不能只保存一个公共位置。
只有 MOVE 改变位置；PICKUP 和 DROPOFF 分别发生在出发位与目标位。
MEASURE 动作的 `basis=Z` 表示实际 readout 基；MEASURE_X 的 H 基变换是独立 action。

`ExperimentalPlan` 提供 actions、gate_completion、reservations、home_sites、
planned_final_sites、actions_for_gate()、to_dict()。
gate_completion 必须引用对应 gate 的全部末端 action，防止 premature completion。
当前仅承诺请求结构合法，不保证任意硬件配置下存在可行或最优的执行调度。
planned_final_sites 是预计位置，不是经过模拟验证的最终 HardwareState。

## 依赖转换

构建前验证 PhysicalCircuitDAG，包括同 qubit 的依赖路径。
每个 gate 的入口 actions 继承其所有 physical predecessors 的 completion actions。
内部增加 pickup→move→dropoff、到达→gate、gate→返回等依赖。

不存在全局 circuit layer barrier，也不因为共享 pair slot 就在 compiler 中强加
两个独立 physical gates 的次序。资源竞争由后续 scheduler 根据 requests 处理。

## 资源与占用生命周期

action 资源使用命名约定：

- `atom_lock/<atom_id>`：防止同 atom 重叠操作；
- `device/aod`：transport 控制；
- `device/local_1q`、`device/rydberg`、`device/imaging`；
- `device/state_preparation`：PREPARE / RESET 的抽象设备占用。

这些是资源需求标识，不是已实现的 ResourceLock 或设备仿真。

`Reservation` 定义多动作之间持续保持的资源：在任意 acquire_before action 启动前
整体获取，在所有 release_after action 完成后释放。release_after 为空表示保持到 plan 结束。

1. Transport：从 PICKUP 开始前到 DROPOFF 结束后持续占用 AOD 和 atom，
   避免 pickup 后释放设备、其他不兼容移动插入。三个动作共享 transport_id。
2. CZ：pair slot、两个 site 和两个 zone 容量单位，在任意入场 pickup 前整体预留，
   直到两个 atom 都返回 home；这是保守的完整往返占用。
3. Measurement：site 和一个 zone 容量单位，从入场 pickup 前预留，
   保持到后续离场 dropoff；即使 MEASURE 已完成，原子仍占位。

同一 action 的资源若已由它所属的活动 reservation 持有，应复用而不是重复扣减。
未来 AOD planner 合并兼容 transport 时，还必须将共同的 AOD 设备预留合并为一份，
保留各 atom 的占用；不能把多个独立 AOD lease 误当成需要多台控制器。

home_sites 在本策略下专属于其初始 atom；初始不参与电路的 atom 占用应从
initial HardwareState 继承。lowering 排除初始已占用的目标 trap，后续 scheduler
还需执行 zone 容量、设备容量和整个 reservation 生命周期的约束。

## 默认策略与时长

`RoundRobinDestinations` 按配置顺序轮换可用 pair slots、measurement sites。
它只绑定地点，不优化 movement compatibility，也不代表 RESST priority。
通过 `DestinationPolicy` 可替换 pair()/measurement()，不需要更改 QEC compiler。
政策返回值必须来自已验证的候选目标。

`configs/hardware_default.yaml` 新增可选 timing，旧配置不含该段仍可读取：

| 参数 | 默认值 |
|---|---:|
| move_speed | 1 um/us |
| pickup/dropoff | 各 1 us |
| single_qubit / entangle | 各 1 us |
| prepare / reset | 各 1 us |
| measurement | 20 us |

MOVE duration = 欧氏距离 / move_speed。参数必须有限且大于零。
数值只是示例估计，尚未包含加速度、转移保真度、路径避碰或光束物理模型。
全 plan 的 duration 求和是累计动作耗时，**不能当作总实验执行时间**。

## 运行与验收

```powershell
.\.venv\Scripts\python.exe examples/demo_gate_lowering.py
.\.venv\Scripts\python.exe examples/demo_gate_lowering.py --primitive CNOT --rounds 3 --output-dir results/lowering_cnot
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

默认输出 `results/experimental_requests.json`，顶层 `scheduled=false`，
所有 start_time=null。控制台展示第一个 CZ、MEASURE_Z 和 RESET 的完整动作链。

默认 d=3 CZ 单轮：**104 个 physical gates → 440 个 experimental actions**：

| 动作 | 数量 |
|---|---:|
| PICKUP / MOVE / DROPOFF | 各 112 |
| ENTANGLE | 24 |
| SINGLE_QUBIT | 56 |
| PREPARE / RESET / MEASURE | 各 8 |

144 个 reservations：112 transport、24 pair、8 measurement。
一整轮包含 reset，因此所有参与计算的原子预计返回 home。
CNOT 输入同样生成 440 个动作；三轮生成 1320 个动作。

新增 11 项测试，累计 37 项。覆盖往返、测量占位、连续轮次、基变换、资源预留、
物理依赖继承、独立操作、时长、非法输入、可替换 code/placement policy。
另用独立的串行 endpoint replay 校验默认整轮的每个起止位置、占位和 zone 容量，
最终恢复初始布局；该验证不模拟连续路径或实际并行时序。

动作展开与占用生命周期验收方法如上。现已继续实现 [步骤 6：AOD compatibility 与 epoch 分组](aod_model.md)。
