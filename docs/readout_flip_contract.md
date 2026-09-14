# 固定读出记录翻转

2026-09-12，4B的受限读出通道。此扩展只描述显式指定的经典报告位错误，不模拟光场、读出保真度、加热、损失或复位错误。

## 输入与旧证据兼容

`PhysicalGate.readout_flip`是末尾追加的严格bool字段，默认False，只有MEASURE/MZ允许True；其他门和RESET不能启用。MEASURE的parameters仍为空，不把翻转标识解释成角度或概率。

字段有专属`omit_if_false`元数据。统一serializer只对明确选择该行为的字段省略False，既有其他默认字段仍全部保存。旧输入不含此字段时恢复为False，schema19不新增state字段，旧ideal circuit/DAG/trace/checkpoint的canonical表示不变。显式True进入线路、DAG、计划原点和checkpoint。

## 执行

每个MEASURE目标仍按操作gate_ids顺序消耗一个现有RNG bit，然后实际投影：

```
quantum_after, true_bit = quantum.measure_z(qubit, rng_bit)
reported_bit = true_bit XOR int(gate.readout_flip)
measurement_results[gate_id] = reported_bit
```

条件门和译码器只读measurement_results，即reported bits。不得根据flip配置、真值trace或量子期望值选择纠正。RESET仍投影并复位实际量子态，与之前报告位是否翻转无关。无新随机流，测量/复位时长和原子支撑、区域、资源约束不变。

当且仅当一个measurement operation内至少一项目标启用flip，完成trace增加：

- `measurement_true_results`：该批全部目标的真实投影位。
- `readout_flips`：该批全部目标的bool翻转标识。

既有measurement_results始终为报告位。理想操作不增加上述字段；开始事件没有投影真值。VisualRecorder仅对噪声批增加同名操作字段，完成之前true_results为空；frame的measurement_results仍仅包含截至该帧提交的报告位。

## 审计

独立物理/量子重放核验真实collapsed state、报告位、DAG与RNG。checkpoint恢复还按保存plan的operation来源逐条审计全部历史读出，包括早于最后一个plan的读出：报告位必须匹配已提交结果，true/flip字段须精确对应声明的固定翻转，并检查严格类型、完整键集及仅在完成时出现。理想读出不得新增这类字段。

恢复的真值审计属于验收工具；它不是运行时译码输入，也不改变真实投影。此底座本身不代表三轮时域协议或任何逻辑容错实验已经完成。

## 本轮检查

`python -m pytest -q tests/test_readout_flip.py tests/test_quantum_readout.py tests/test_batch_raman.py`

57项通过，4.62s，无skip。包含Bell真值关联与报告位翻转、RNG消耗一致、RESET与条件控制、逐事件checkpoint恢复、早期plan噪声trace篡改拒绝、记录器无预读，以及保存的原GHZ2 schema19正式checkpoint逐字恢复。未执行新的完整物理实验。
