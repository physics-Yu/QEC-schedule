# Neutral-Atom FTQC Scheduling Simulator
## 基于 QEC 编译、AOD 原子移动、RESST 调度与动态可视化的资源估计平台

## 0. 项目目标

构建一个面向中性原子容错量子计算的**实验执行级调度模拟平台**。

本项目不是量子态模拟器，不计算真实 pulse waveform，也不模拟 Hamiltonian 演化。

系统关心的是：

> 一个 logical quantum program 在选定 QEC code 编码之后，究竟会导致哪些 physical atoms 在什么时候移动到哪里、什么时候接受 single-qubit gate、什么时候进入 entangling zone 完成 two-qubit gate、什么时候移动到 measurement zone 被测量，以及这些操作在有限实验资源约束下需要多少实际时间。

完整流程必须为：

\[
\boxed{
\text{Logical Program}
\rightarrow
\text{QEC Compiler}
\rightarrow
\text{Physical-Qubit Gate DAG}
\rightarrow
\text{Hardware Lowering}
\rightarrow
\text{RESST Scheduler}
\rightarrow
\text{Experimental Timeline}
\rightarrow
\text{Animation + Resource Report}
}
\]

项目最终核心输出不是最终量子态，而是：

1. atom-by-atom execution trace；
2. 完整实验 timeline；
3. AOD / laser / zone / readout 资源占用；
4. circuit parallelism 到 hardware parallelism 的损失；
5. 原子移动距离、移动次数与等待时间；
6. 动态动画：看到原子逐批移动、进入 entangling zone、接受 gate、离开、进入 measurement zone。

---

# 1. 核心设计原则

系统必须严格区分以下三个层次。

## Layer A：Logical Layer

描述：

```text
LogicalPrepare
LogicalH
LogicalX
LogicalZ
LogicalCNOT
LogicalMeasure
LogicalIdle
```

这一层完全不知道物理 atom、AOD、zone、laser。

例如：

```python
LogicalH(logical_qubit="L0")
LogicalCNOT(control="L0", target="L1")
LogicalMeasureZ(logical_qubit="L0")
```

---

## Layer B：QEC Physical Layer

根据具体 quantum error correcting code，将 logical operation 编译成 physical-qubit-level circuit。

例如：

```text
PREPARE ancilla_0
H ancilla_0
CZ data_0 ancilla_0
CZ data_1 ancilla_0
CZ data_2 ancilla_0
CZ data_3 ancilla_0
H ancilla_0
MEASURE ancilla_0
```

必须显式包含：

- data qubits；
- syndrome ancillas；
- syndrome extraction rounds；
- ancilla preparation；
- measurement；
- reset；
- logical operation 对 physical qubits 的展开。

这一层的输出不是实验动作，而是：

\[
\boxed{\text{physical gate dependency DAG}}
\]

---

## Layer C：Experimental Hardware Layer

将 abstract physical gate 转化为真正实验平台动作。

例如：

```text
CZ(q1,q2)
```

不能直接执行。

必须 lowering 成：

```text
AOD_PICKUP(q1,q2)
AOD_MOVE(q1,q2 -> entangling zone)
RYDBERG_ENTANGLE(q1,q2)
AOD_MOVE(q1,q2 -> storage)
AOD_DROPOFF(q1,q2)
```

Single-qubit gate：

```text
H(q1)
```

简化为：

```text
LOCAL_1Q(q1, H)
```

atom 默认原地不移动。

Measurement：

```text
MEASURE(q1)
```

转化为：

```text
AOD_PICKUP(q1)
AOD_MOVE(q1 -> measurement zone)
IMAGE(q1)
```

第一版不需要实现 pulse waveform，只需要产生一个具有 duration 和 resource requirement 的事件。

---

# 2. 系统总体架构

建议目录：

```text
neutral-atom-ftqc/
│
├── AGENTS.md
├── README.md
├── pyproject.toml
│
├── configs/
│   ├── hardware_default.yaml
│   ├── surface_code_d3.yaml
│   └── scheduler_default.yaml
│
├── docs/
│   ├── architecture.md
│   ├── execution_model.md
│   ├── qec_compiler.md
│   ├── hardware_model.md
│   ├── aod_model.md
│   ├── resst_scheduler.md
│   └── visualization.md
│
├── src/
│   ├── logical/
│   │   ├── ir.py
│   │   └── program.py
│   ├── qec/
│   │   ├── code.py
│   │   ├── surface_code.py
│   │   ├── stabilizer.py
│   │   └── syndrome_circuit.py
│   ├── compiler/
│   │   ├── logical_to_qec.py
│   │   ├── physical_gate_ir.py
│   │   └── dag.py
│   ├── hardware/
│   │   ├── atom.py
│   │   ├── geometry.py
│   │   ├── zones.py
│   │   ├── resources.py
│   │   ├── aod.py
│   │   └── hardware_state.py
│   ├── lowering/
│   │   ├── experimental_ir.py
│   │   ├── gate_lowering.py
│   │   └── movement_planner.py
│   ├── scheduler/
│   │   ├── task.py
│   │   ├── pool.py
│   │   ├── resst.py
│   │   ├── priority.py
│   │   └── scheduler.py
│   ├── simulator/
│   │   ├── event.py
│   │   ├── engine.py
│   │   ├── trace.py
│   │   └── metrics.py
│   └── visualization/
│       ├── animation.py
│       ├── timeline.py
│       └── dashboard.py
│
├── examples/
│   ├── demo_surface_code_cycle.py
│   ├── demo_logical_measurement.py
│   └── demo_two_blocks.py
│
└── tests/
```

---

# 3. Phase 1：Logical IR

定义最小 logical instruction set：

```python
class LogicalInstruction:
    id
    logical_qubits
    dependencies
```

支持：

```text
LogicalPrepare0
LogicalPreparePlus

LogicalX
LogicalZ
LogicalH

LogicalCNOT

LogicalMeasureX
LogicalMeasureZ

LogicalIdle
```

第一版优先支持：

```text
LogicalPrepare0
LogicalIdle
LogicalH
LogicalMeasureZ
```

如果 LogicalCNOT 对 surface code 的 FT 实现过于复杂，可以在第一版标记为 experimental / simplified。

---

# 4. Phase 2：QEC Code Layer

第一版只实现：

\[
\boxed{\text{Rotated Surface Code}}
\]

先支持：

```text
distance = 3
```

以后支持：

```text
d = 3, 5, 7, ...
```

每个 code 必须定义：

```python
class QECCode:
    data_qubits()
    ancilla_qubits()

    x_stabilizers()
    z_stabilizers()

    logical_x()
    logical_z()

    syndrome_round()
```

其中 physical qubit 是抽象 qubit ID。

---

# 5. Syndrome Extraction 必须成为第一等公民

不要把 syndrome measurement 写成一个抽象指令：

```text
SYNDROME_ROUND
```

而必须展开。

例如一个 stabilizer：

\[
Z_1Z_2Z_3Z_4
\]

展开成：

```text
PREPARE ancilla

CZ(data1, ancilla)
CZ(data2, ancilla)
CZ(data3, ancilla)
CZ(data4, ancilla)

MEASURE ancilla
RESET ancilla
```

最终系统必须知道每个 syndrome ancilla 与哪些 data atoms 发生 interaction，以及 interaction ordering。

---

# 6. QECPhysicalIR

定义：

```python
PhysicalGate:
    id
    gate_type
    qubits
    predecessors
    successors
    metadata
```

gate type：

```text
PREPARE
RESET
H
X
Y
Z
CZ
CNOT
MEASURE_X
MEASURE_Z
```

推荐内部 two-qubit primitive 统一成 CZ，或至少允许 lowering 时统一。

---

# 7. 必须使用 DAG，而不是预先固定 circuit layer

保存：

\[
G=(V,E)
\]

其中：

\[
V=\text{physical operations}
\]

\[
E=\text{dependency constraints}
\]

scheduler 每次得到：

```python
ready_set = dag.ready_operations()
```

这表示 circuit 上理论允许并行的操作。

之后由 hardware scheduler 再决定实验平台实际上允许并行哪些。

---

# 8. Physical Qubit → Atom Mapping

定义：

```python
Atom:
    atom_id
    assigned_qubit
    atom_type
    position
    zone
    state
```

其中：

```text
atom_type:
    DATA
    ANCILLA
    RESERVOIR
```

state：

```text
IDLE
MOVING
GATING
MEASURING
LOST
```

不要存储 quantum state。

---

# 9. Hardware Geometry

第一版使用二维平面。

定义四类 zone：

```text
StorageZone
EntanglingZone
MeasurementZone
ReservoirZone
```

所有 zone 都应具有：

```python
bounds
capacity
allowed_operations
```

---

# 10. ExperimentalIR

MVP 可以定义：

```python
MoveAction
SingleQubitAction
EntangleAction
MeasureAction
```

所有 action 必须拥有：

```python
id
atoms
start_time
duration
required_resources
source_zone
target_zone
dependencies
```

---

# 11. Gate Lowering

Physical：

```text
H(q1)
```

lower 为：

```text
SingleQubitAction(atom=a1)
```

Physical：

```text
CZ(q1,q2)
```

lower 为：

```text
MoveRequest(a1 -> entangling zone)
MoveRequest(a2 -> entangling zone)

EntangleRequest(a1,a2)

MoveRequest(a1 -> storage)
MoveRequest(a2 -> storage)
```

Measurement：

```text
MEASURE(q1)
```

lower 为：

```text
MoveRequest(a1 -> measurement zone)
MeasureRequest(a1)
```

---

# 12. AOD Movement Model

禁止把 AOD 简化成固定 atom capacity。

必须把它抽象成：

\[
\boxed{
\text{一组 movement requests 能否被同一个 AOD movement epoch 实现}
}
\]

定义：

```python
AODController:
    max_x_tones
    max_y_tones
    allowed_region
    allowed_primitives
```

MVP：

```text
TRANSLATE
```

必须实现。

第一版 compatibility：

> 如果若干 atoms 具有完全相同的 displacement vector，则认为它们可以在同一个 AOD epoch 内移动。

即：

\[
\Delta r_i=\Delta r_j
\]

则 compatible。

第二版再升级为 crossed-AOD model：

\[
r_{ij}(t)=
(x_i(t),y_j(t))
\]

并加入：

- x-line sharing；
- y-line sharing；
- line ordering；
- no crossing；
- max tone number；
- field of view；
- translate/stretch/compress compatibility。

---

# 13. MovementPlanner

输入：

```text
一批 MoveRequest
```

输出：

```text
AODMovementEpoch[]
```

这一模块必须和 scheduler 分离。

---

# 14. RESST Scheduler

采用 RESST 风格：

\[
\boxed{
\text{Task Pool}
+
\text{Dependency}
+
\text{Resource requirement}
+
\text{Priority}
+
\text{Dynamic ready state}
}
\]

Task pools：

```text
P_MOVE
P_1Q
P_ENTANGLE
P_MEASURE
P_REFILL
```

每个 task：

```python
Task:
    task_id
    task_type
    atoms
    dependencies
    required_resources
    priority_vector
    estimated_duration
    status
```

status：

```text
WAITING
READY
RUNNING
DONE
BLOCKED
```

---

# 15. Resource Model

资源至少包括：

```text
AODController
Local1QControl
RydbergLaser
EntanglingZone
MeasurementZone
ImagingSystem
```

AOD 使用 compatibility constraint。

Rydberg 使用 batch model：

```text
EntangleAction(
    pairs=[
        (q1,q2),
        (q3,q4),
        (q5,q6)
    ]
)
```

优化目标之一：

\[
\boxed{\text{maximize entangling batch size}}
\]

---

# 16. RESST Scheduling Loop

核心循环：

```python
while unfinished_tasks:

    update_ready_tasks()

    collect_ready_tasks_by_pool()

    generate_candidate_batches()

    test_resource_constraints()

    test_aod_compatibility()

    choose_tasks_by_priority()

    start_selected_tasks()

    advance_to_next_event()

    release_resources()

    update_hardware_state()

    record_trace()
```

必须做 event-driven simulator。

---

# 17. Hardware State

```python
HardwareState:
    current_time
    atoms
    zones
    resources
    running_tasks
```

---

# 18. Simulation Trace

```python
TraceEvent:
    event_id
    task_id
    type
    atoms
    start_time
    end_time
    source_position
    target_position
    zone
    resource
```

输出：

```text
results/run_001_trace.json
```

visualization 和 metrics 都必须基于 trace。

---

# 19. Visualization

最高优先级功能：

\[
\boxed{\text{看到 atom 真正在机器平面上移动}}
\]

第一版优先使用：

```text
matplotlib.animation.FuncAnimation
```

二维平面显示：

```text
Storage
Entangling
Measurement
Reservoir
```

必须区分：

```text
data atom
X ancilla
Z ancilla
reservoir atom
```

MOVE 时必须插值，不允许 teleport。

1Q gate：atom 不移动，只高亮并显示 gate label。

ENTANGLE：在 entangling zone 内画 pair connection。

MEASURE：atom 位于 measurement zone，高亮并显示 M。

支持：

```text
Play
Pause
Restart
speed x1
speed x5
speed x20
```

---

# 20. Timeline Visualization

输出 Gantt-style timeline。

纵轴：

```text
AOD
1Q Laser
Rydberg Laser
Measurement
atom groups
```

横轴：

\[
t
\]

用于观察 resource contention。

---

# 21. Metrics

至少输出：

## 总时间

\[
T_{\rm total}
\]

## 分类时间

```text
Transport time
1Q time
Entangling time
Measurement time
Waiting time
```

## AOD

```text
number of AOD epochs
mean atoms per epoch
maximum atoms per epoch
total transport distance
mean transport distance
AOD busy fraction
```

## Rydberg

```text
number of entangling pulses
mean pairs per pulse
max pairs per pulse
Rydberg utilization
```

## Measurement

```text
measurement batches
mean atoms per batch
measurement utilization
```

---

# 22. Parallelism Metrics

记录：

\[
N_{\rm ready}
\]

和：

\[
N_{\rm executed}
\]

定义：

\[
P(t)=\frac{N_{\rm executed}}{N_{\rm ready}}
\]

用于衡量 QEC circuit 的理论 parallelism 有多少被真实硬件资源限制损失。

---

# 23. Resource Scaling Experiments

所有 hardware 参数必须通过 YAML 配置。

例如：

```yaml
aod:
  move_speed: 1.0
  max_x_tones: 20
  max_y_tones: 20

single_qubit:
  duration: 1.0

rydberg:
  duration: 1.0

measurement:
  duration: 20.0

zones:
  entangling_capacity_pairs: 20
  measurement_capacity: 100
```

未来 sweep：

```text
AOD capability
entangling-zone size
measurement capacity
laser availability
code distance
```

---

# 24. MVP Demo

第一版只完成：

\[
\boxed{
\text{distance-3 rotated surface-code syndrome cycle}
}
\]

要求：

1. 自动生成 d=3 code；
2. 创建 data atoms；
3. 创建 syndrome ancilla atoms；
4. 自动生成完整 stabilizer-measurement physical gate DAG；
5. 将 physical CZ/CNOT 转成 atom movement；
6. ancilla 或 data atom 按设定策略进入 entangling zone；
7. scheduler 根据 AOD compatibility 分批移动；
8. 进入 zone 后产生 entangling batch；
9. syndrome ancilla 移动到 measurement zone；
10. 完成 measurement；
11. 输出完整 timeline；
12. 输出 metrics；
13. 播放动画。

---

# 25. MVP 允许的简化

### AOD

只支持：

```text
same displacement -> same batch
```

### Entangling zone

只要求 pair occupies one predefined pair slot。

### Single-qubit gate

atom remains stationary，duration fixed。

### Measurement

move to measurement zone，wait fixed duration。

### Quantum state

完全不模拟。

### Decoder

第一版不实现。

### Noise

第一版不实现。

---

# 26. 后续阶段

## Phase 2A

真实 crossed-AOD model：

\[
r_{ij}=(x_i,y_j)
\]

加入：

```text
x/y tone
shared line
no crossing
line ordering
```

## Phase 2B

加入：

```text
TRANSLATE
STRETCH
COMPRESS
```

## Phase 2C

atom loss + reservoir refill：

```text
ATOM_LOST
REFILL_REQUEST
RESERVOIR_PICKUP
MOVE
REPLACE
```

## Phase 2D

接 Stim，用于 QEC/noise circuit 验证，但不负责 hardware scheduling。

## Phase 2E

decoder：

```text
measurement
    ↓
syndrome
    ↓
decoder
    ↓
Pauli frame
```

---

# 27. 模块边界

禁止：

1. QEC compiler 直接控制 atom position；
2. scheduler 自己生成 syndrome circuit；
3. visualizer 直接读取 QEC circuit 猜 atom movement；
4. hardware lowering 自己决定 task priority。

必须保持：

```text
Logical Compiler
    ↓
QEC Physical DAG

Hardware Lowering
    ↓
Experimental Requests

RESST Scheduler
    ↓
Scheduled Trace

Simulator
    ↓
State History

Visualizer
    ↓
Animation
```

---

# 28. Codex 实现任务拆分

按以下任务逐个 commit。

## Task 1
建立 LogicalIR、QECCode interface、RotatedSurfaceCode(d=3)。

验收：能够打印 qubit 和 stabilizer topology。

## Task 2
实现 syndrome circuit generation。

验收：输出每个 ancilla 与 data qubit 的 interaction sequence。

## Task 3
建立 PhysicalCircuitDAG。

验收：正确计算 predecessor、successor、ready_set。

## Task 4
实现 Atom、Zone、HardwareState。

验收：画出静态二维 atom array。

## Task 5
实现 ExperimentalIR 和 gate lowering。

验收：
- CZ → MOVE / ENTANGLE / MOVE
- MEASURE → MOVE / MEASURE

## Task 6
实现第一版 AOD movement compatibility。

规则：

```text
same displacement vector
```

可合并。

验收：10 个 atoms 同方向同距离移动应产生 1 个 AOD epoch。

## Task 7
实现 RESST task model：

```text
Task
Pool
Priority
ResourceLock
TaskState
```

## Task 8
实现 event-driven scheduler。

验收：能够自动生成 start_time / end_time。

## Task 9
运行完整 d=3 syndrome cycle。

输出：

```text
trace.json
metrics.json
```

## Task 10
实现二维 atom animation。

运行：

```bash
python examples/demo_surface_code_cycle.py
```

必须看到：

1. atoms 初始位于 storage；
2. 一批 atoms 移向 entangling zone；
3. entangling pairs 高亮；
4. atoms 离开；
5. 下一批进入；
6. syndrome ancillas 最终进入 measurement zone；
7. 完成 measurement。

## Task 11
实现 timeline。

输出：

```text
results/demo_timeline.png
```

## Task 12
加入 configurable hardware parameters，并做简单 sweep。

---

# 29. 测试要求

至少建立：

```text
test_surface_code_geometry.py
test_syndrome_generation.py
test_dag_dependencies.py
test_aod_compatibility.py
test_gate_lowering.py
test_resource_conflict.py
test_resst_scheduler.py
test_execution_trace.py
```

必须保证：

- 两个需要同一 exclusive resource 的 task 不会 overlap；
- 依赖未完成的 task 永远不能运行；
- AOD incompatible movement 不会错误合并。

---

# 30. 最终研究问题

本软件的核心研究问题是：

\[
\boxed{
\text{给定一个 FT quantum circuit，
在真实 neutral-atom hardware constraints 下，
实际执行成本是多少？}
}
\]

重点研究：

\[
\boxed{
\text{QEC code structure}
\rightarrow
\text{physical interaction graph}
\rightarrow
\text{atom transport requirement}
\rightarrow
\text{hardware parallelism}
\rightarrow
\text{execution time}
}
\]

以及：

\[
\boxed{
\text{哪些硬件资源真正成为 FTQC bottleneck？}
}
\]

最终应能够比较：

```text
不同 code
不同 code distance
不同 layout
不同 AOD capabilities
不同 zone architecture
不同 scheduler
```

并得到 architecture-level resource estimation。

---

# 31. 项目成功标准

给定：

```text
Logical Program
+
QEC Code
+
Hardware Configuration
```

系统能够自动生成：

```text
atom-by-atom execution schedule
```

并动态展示：

```text
atoms 被分批 pickup
atoms 移动
atoms 进入 entangling zone
2Q interactions
atoms 回到 storage
single-qubit operation 高亮
ancilla 进入 measurement zone
measurement
```

同时输出：

```text
total execution time
AOD utilization
Rydberg utilization
measurement utilization
movement distance
movement epochs
entangling batches
waiting time
parallelism loss
```

则第一阶段项目成功。

一句话定义整个项目：

\[
\boxed{
\textbf{将一个 logical fault-tolerant quantum program，
逐层编译成真实 neutral-atom 实验平台上的 atom-level execution trace，
并使用 RESST 对有限硬件资源进行动态调度和资源估计。}
}
\]

第一版优先保证：

\[
\boxed{
\text{完整链路 > 物理细节}
}
\]

先让：

```text
Logical
→ QEC
→ Physical gates
→ Atom movements
→ RESST
→ Animation
```

完整工作，再逐渐增加 AOD、loss、decoder、code family 等真实性。
