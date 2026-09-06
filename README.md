# QEC-schedule

面向中性原子容错量子计算的调度模拟平台，按步骤实施。
当前已完成 **步骤 1–6**：LogicalIR、可替换的 QEC code 接口、
默认 d=3 rotated surface code、显式 syndrome extraction 电路，以及
PhysicalCircuitDAG 的依赖索引、动态 ready set 和执行状态推进；
已加入 Atom / Zone / HardwareState、YAML 硬件布局与静态二维绘图，
以及 physical gate 到 ExperimentalIR 的动作展开、预计时长与资源预留请求；
现已支持 AOD 同位移兼容性、tone/可达范围检查和 ready transports 的 epoch 分组。

## 快速运行

需要 Python **3.10+**。配置读取使用 PyYAML，绘图使用可选 Matplotlib extra。
本机默认 `python` 若仍是 3.7，请改用 Python 3.10+ 的解释器路径。

```powershell
python -m pip install -e ".[visualization]"
python examples/demo_code_topology.py
python examples/demo_syndrome_circuit.py
python examples/demo_syndrome_circuit.py --primitive CNOT --output results/syndrome_cnot.json
python examples/demo_syndrome_circuit.py --rounds 3 --output results/syndrome_three_rounds.json
python examples/demo_physical_dag.py
python examples/demo_hardware_layout.py
python examples/demo_gate_lowering.py
python examples/demo_aod_movement.py

$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

本机已建立 `.venv`，可用 `.\.venv\Scripts\python.exe` 替换上面的 `python`。
不需绘图时安装 `python -m pip install -e .`，运行硬件示例加 `--no-plot`。
输出 `results/` 属于可重新生成的验收产物，不纳入 Git；
GitHub Actions 上传布局 PNG 和状态 JSON 为可下载 artifact。

## 接口使用

```python
from qec_schedule.qec import create_code, default_registry

code = create_code()  # 默认 rotated_surface, distance=3, block_id=L0
circuit = code.syndrome_round(primitive="CZ", rounds=1)

from qec_schedule.compiler import PhysicalCircuitDAG
dag = PhysicalCircuitDAG(circuit)
first = dag.ready_operations()[0]
dag.start(first.id)
dag.complete(first.id)  # 后续硬件层应在对应实验动作真正结束后调用

# 可独立构造多个实例；未来替换编码不需要修改 hardware/scheduler。
other_block = create_code(block_id="L1")
# registry = default_registry()
# registry.register("my_code", MyCode)
# custom_code = registry.create("my_code", **parameters)
```

CSS code 继承 `CSSCode` 可复用 extraction；其他 code 继承 `QECCode` 自供电路。
QEC 层不包含 atom、AOD、zone、量子态或硬件时间；硬件层独立消费其 qubit 接口。
LogicalIR 当前只提供表达与校验，不包含逻辑门的容错编译。

## 验收和设计

- [步骤 1、2 验收说明](docs/acceptance_steps_1_2.md)
- [步骤 3：DAG 接口与验收](docs/dag.md)
- [步骤 4：硬件模型、静态图与验收](docs/hardware_model.md)
- [步骤 5：实验动作展开与验收](docs/gate_lowering.md)
- [步骤 6：AOD 兼容性与 movement epochs](docs/aod_model.md)
- [QEC 接口、默认拓扑和电路约定](docs/qec_interfaces.md)
- [完整平台规格](docs/NEUTRAL_ATOM_FTQC_PLATFORM_SPEC.md)

下一步是 RESST Task/Pool/Priority/ResourceLock；事件驱动调度、atom 动画和资源估计尚未实现。
