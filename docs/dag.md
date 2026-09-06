# PhysicalCircuitDAG：步骤 3

## 模块边界

`compiler/dag.py` 将 QEC code 生成的 `PhysicalCircuit` 转成有向无环依赖图。
节点是 physical gates，边是必须遵守的操作次序。该模块不依赖任何具体 QEC code。

图中没有 atom 位置、硬件资源、task priority 或执行耗时。
`READY` 仅表示电路依赖满足；后续硬件调度器才决定是否有资源执行。
将来一个 physical gate 展开成多个实验动作时，应在其所有必要动作结束后，
调用该 gate 的 `complete()`。提前调用将错误释放后继依赖。

## 接口

```python
from qec_schedule.qec import create_code
from qec_schedule.compiler import PhysicalCircuitDAG

circuit = create_code().syndrome_round()
dag = PhysicalCircuitDAG(circuit)

ready = dag.ready_operations()               # tuple[PhysicalGate, ...]
selected = ready[0]
parents = dag.predecessors(selected.id)       # tuple[str, ...]
children = dag.successors(selected.id)
dag.start(selected.id)                       # READY -> RUNNING
dag.complete(selected.id)                    # RUNNING -> DONE
new_ready = dag.ready_operations()
```

其他接口：

- `start_operations(ids)`：原子性启动一组 ready gate；任一 ID 不合法时整组不变。
- `state(id)`：WAITING / READY / RUNNING / DONE。
- `running_operations()`、`completed_operations()`：当前运行或完成的 gate。
- `is_complete`：所有节点是否完成；空图立即完成。
- `gates`：只读的 ID → PhysicalGate 映射。
- `topological_order()`：稳定拓扑顺序，返回 ID 元组。
- `edge_count`：显式依赖边数，不包含传递闭包中的隐式边。
- `to_dict()`：静态拓扑 JSON，包含 predecessor 和 successor，执行期间保持不变。
- `PhysicalCircuitDAG(dag.circuit)`：创建独立执行实例，原图状态不受影响。

`PhysicalCircuit` 保留步骤 2 的契约：records 已按合法拓扑顺序排列。
外部 code 若提供无序记录，可使用 `PhysicalCircuitDAG.from_gates(qubits, gates)`。
该入口先检查引用和环，再稳定拓扑排序。拓扑排序只解决列表顺序，不创建新依赖。

未知 ID 抛出 `KeyError`；非法状态转换、重复启动、重复完成、重复 gate ID、
不存在的 qubit/predecessor、环，以及同 qubit 操作缺少顺序均抛出 `ValueError`。

## 依赖安全

同 qubit 上相邻的两个操作必须有依赖路径相连，可以是直接边，也可以是传递路径。
缺少路径时拒绝构建图，避免把 compiler 的遗漏当作可以并行执行。
不会根据输入列表偷偷增加边，也不会凭拓扑排序给本来无序的同 qubit 操作指定语义。

只有 predecessor 进入 DONE 才减少后继的未完成计数；RUNNING 不等于 DONE。
后继的所有依赖完成后立即变为 READY，因此不需要固定 circuit layers 或全局同步。
返回集合均按稳定拓扑顺序排列，便于复现；这不是硬件 priority 策略。

## 验收

使用 Python 3.10+，在项目根目录运行：

```powershell
python -m pip install -e ".[visualization]"
$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
python examples/demo_physical_dag.py
python examples/demo_physical_dag.py --primitive CNOT --output-dir results/dag_cnot
python examples/demo_physical_dag.py --rounds 3 --output-dir results/dag_three_rounds
```

默认 CZ 单轮应打印：

```text
Nodes: 104, edges: 111
Initially ready: 12
...
Completed: 104; ready: 0; running: 0
```

初始 ready 包括 8 个 ancilla PREPARE 和 4 个独立 data H。
data 已存在是步骤 2 的输入假设；CZ 分解前的独立 H 不依赖 ancilla PREPARE，
因此无需额外添加 preparation barrier。

输出：

- `results/physical_dag.json`：全部 gate、双向邻接和拓扑顺序。
- `results/dag_progress.json`：每次启动、单个完成、新 ready 与仍 running 的 gate ID。

演示每次启动当前 ready gate，再完成一个 running gate，立即重新查询 ready。
这里的完成顺序只用于验证状态，不表示实验时间、资源并行能力或最优调度。

本步骤新增 7 项测试，加上前两步共 15 项：

1. 分叉/汇合图的 predecessor、successor 和多依赖解锁。
2. 独立分支仍 running 时允许另一分支继续。
3. 非法状态转换、重复操作和批量启动失败的原子性。
4. 无序记录导入、环、缺失引用和重复 ID 拒绝。
5. 同 qubit 顺序缺失拒绝，合法传递依赖接受。
6. 空图、只读拓扑与独立重放。
7. Surface/repetition code 的 CZ/CNOT 三轮电路，随机选择启动/完成，
   对照独立依赖条件计算 ready set，并检查运行中的 gate 不共享 qubit。

步骤 3 已完成，现已继续实现 [步骤 4 的硬件模型与静态布局](hardware_model.md)。
