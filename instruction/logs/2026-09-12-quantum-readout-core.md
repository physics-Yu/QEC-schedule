# 2026-09-12：测量、复位和条件物理效应底座

授权：用户要求包含实际辅助原子测量和纠错的 GHZ2 QEC；本轮主任务分派此核心工作，覆盖旧文档的“不实施测量”历史范围。协议、工作台和实验成绩由同轮主交接另行汇总。

## 已实现

- `PhysicalGate` 新增 RESET、MZ 兼容别名以及 condition/depends_on；DAG 合并经典结果依赖、显式依赖、逐 qubit 依赖。
- 新 `hardware/readout.py` 要求目标位于 measurement zone、稳定并有启用支撑，拒绝交接/移动中的读出。批量 MEASUREMENT/RESET 允许不同 qubit 同时执行；默认500/100μs仅为项目假设。
- `simulation/quantum_effects.py` 把物理完成事件连接到理想稳定子引擎：实际投影、结果、非破坏性 measured 标记、RESET到|0⟩，实际CZ/HXYZ更新量子态。跟踪模式T明确拒绝。
- `SimulationState` 保存 opt-in quantum_state、measurement_results；schema19保存原始及运行中的量子态/RNG，预测、审计、实际执行一致。旧schema18及更早版本需重新编译。
- false 条件X/Z为1μs控制时隙，完成DAG但不打光、不改变量子态，资源CONTROL且Raman busy不增长。Recorder暴露applied与累计结果。
- DAG纯transition复用验证后的静态依赖结构；restore一次建立反向邻接；runtime直接比较不可变节点对象，避免重复大JSON序列化。没有减少校验内容。

接口与边界见 [quantum_readout_core.md](../../docs/quantum_readout_core.md)。

## 本轮验证

命令：

```
C:/python312/python.exe -m pytest tests/test_quantum_readout.py tests/test_batch_cz.py tests/test_runtime_prefix_cache.py tests/test_foundations.py tests/test_cz_prediction.py tests/test_m3.py -q --disable-warnings --maxfail=1
```

109 passed，102.14s。最终DAG对象相等优化之后重跑：

```
C:/python312/python.exe -m pytest tests/test_quantum_readout.py tests/test_runtime_prefix_cache.py -q --disable-warnings --maxfail=1
```

30 passed，2.15s。两组有重叠，不相加。专项11项包含Bell测量关联、真实batch CZ稳定子预期、MZ外拒绝且实时状态不变、读出/复位、条件真假、逐事件恢复、结果篡改、CONTROL资源、记录器和程序后RNG。

## 限制与下一步

没有读出噪声、损失、加热、测量串扰或实验波形模型；量子引擎是理想纯稳定子，非Clifford门不支持。单独底座通过不等于完整QEC实验通过。下一步由主任务运行含辅助原子的完整线路、独立量子终态验证、物理重放与可编辑浏览器验收，并报告实际耗时与失败。
