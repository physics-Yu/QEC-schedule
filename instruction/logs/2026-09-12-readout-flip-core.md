# 4B读出记录翻转底座

2026-09-12。用户最新审批边界允许工程修复与测试迭代；本任务没有变更物理支撑、几何、读出时长或RESET模型。

## 变更

- `PhysicalGate`末尾追加strict-bool `readout_flip`；True只允许MEASURE/MZ，默认False通过专属serializer元数据省略，保留schema19旧canonical表示。
- 实际量子投影产生true bit，报告位再按固定标识XOR；conditions仅读reported，RESET仍作用于真实collapsed state。RNG消耗不变。
- 仅启用flip的measurement批次在完成trace增加measurement_true_results/readout_flips；checkpoint恢复审计全部历史plan的读出元数据，不仅检查最后plan。
- VisualRecorder仅为噪声批保存同名操作字段，真实位在完成前为空；frame.measurement_results仍为截至当前提交的reported bits。

完整接口与范围见[readout_flip_contract](../../docs/readout_flip_contract.md)。没有新增state字段、随机流、读出波形模型或隐含纠错。

## 实际验证

命令：`C:/python312/python.exe -m pytest -q tests/test_readout_flip.py tests/test_quantum_readout.py tests/test_batch_raman.py`

结果：57 passed in 4.62s，无skip。一次执行通过，未为写日志重复运行。覆盖Bell真实关联/报告翻转、RNG一致、RESET/条件、逐事件恢复、历史噪声字段篡改拒绝、无预读及保存的原GHZ2 schema19 checkpoint逐字恢复。

机器证据：[result.json](../../artifacts/qec-roadmap/step4B-core-tests/result.json)，包括实际命令/结果及受本任务管理文件的SHA256。

对root的viewer只读检查：其measurement_true_results/readout_flips按对象字段读取，与recording格式一致；只有operation.end<=当前时间且当前frame已有相同reported gate ID才展示投影审计，避免从完整operation记录泄露未来测量位。此检查不是浏览器动态验收。

## 未完成范围

本任务不运行完整4B物理实验。三轮+闭合轮协议、仅reported历史译码、工作台输入保留、正式物理重放与浏览器验收由主线程/其他agent另行完成并记录，不能以这57项核心通过冒充完整时域纠错通过。
