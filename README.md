# QEC-schedule

面向中性原子容错量子计算的调度模拟平台，按步骤实施。
当前已完成 **步骤 1、2**：LogicalIR、可替换的 QEC code 接口、
默认 d=3 rotated surface code、显式 syndrome extraction 电路。

## 快速运行

需要 Python **3.10+**。运行与测试无第三方依赖。
本机默认 `python` 若仍是 3.7，请改用 Python 3.10+ 的解释器路径。

```powershell
python examples/demo_code_topology.py
python examples/demo_syndrome_circuit.py
python examples/demo_syndrome_circuit.py --primitive CNOT --output results/syndrome_cnot.json
python examples/demo_syndrome_circuit.py --rounds 3 --output results/syndrome_three_rounds.json

$env:PYTHONPATH = 'src'
python -m unittest discover -s tests -v
```

可选安装：`python -m pip install -e .`。
输出 `results/*.json` 属于可重新生成的验收产物，不纳入 Git。

## 接口使用

```python
from qec_schedule.qec import create_code, default_registry

code = create_code()  # 默认 rotated_surface, distance=3, block_id=L0
circuit = code.syndrome_round(primitive="CZ", rounds=1)

# 可独立构造多个实例；未来替换编码不需要修改 hardware/scheduler。
other_block = create_code(block_id="L1")
# registry = default_registry()
# registry.register("my_code", MyCode)
# custom_code = registry.create("my_code", **parameters)
```

CSS code 继承 `CSSCode` 可复用 extraction；其他 code 继承 `QECCode` 自供电路。
代码层不包含 atom、AOD、zone、量子态或硬件时间。
LogicalIR 当前只提供表达与校验，不包含逻辑门的容错编译。

## 验收和设计

- [步骤 1、2 验收说明](docs/acceptance_steps_1_2.md)
- [QEC 接口、默认拓扑和电路约定](docs/qec_interfaces.md)
- [完整平台规格](docs/NEUTRAL_ATOM_FTQC_PLATFORM_SPEC.md)

下一步是 PhysicalCircuitDAG；硬件调度、atom 动画和资源估计尚未实现。
