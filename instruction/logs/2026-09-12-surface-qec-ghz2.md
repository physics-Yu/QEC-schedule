# 两逻辑 surface GHZ 的测量与纠错实现

状态：COMPLETED（声明的理想读出、单数据错误恢复范围）。用户在前一轮范围审计后明确要求接入测量和稳定子，允许先从两个逻辑比特实现；这取代此前“只核验未授权扩展”的交接描述。

目标：18 数据原子 + 16 辅助原子，测量制备、逻辑 CNOT、可选实际 Pauli 注入、稳定子抽取、由真实读出决定的条件纠正，经原有物理 validator / Executor / recorder 回放。完整线路保留可编辑、编译入口。首版量子验收边界为理想 Clifford 与理想读出下的单数据 Pauli 错误，不宣称已覆盖门噪声、测量噪声或完整容错。

分工：物理研究 agent 实现独立 stabilizer 引擎与协议验证；scheduler agent 接入测量/复位/条件门和 checkpoint；acceptance agent 接入既有工作台与浏览器验收；主 agent 实现二维布局、物理读出运输及调度和端到端验证。

读出 500 μs、复位 100 μs 暂为显式模拟参数，不是通用硬件事实；1Q 光仍固定 1 μs。SLM / AOD 捕获闭包、正交通道、全部 CZ 作用对、单比特 5 μm 间距等既有硬条件保持。

## 完成结果

正式工作台 http://127.0.0.1:8781/?job=55831b7d3be24c56ada3cd4958460db2 ，PID28100；[完整实验记录](../../docs/surface_qec_experiment.md)。seed7，真实编辑Y(Q000)，481个门/控制槽、105CZ→33pulse（最大9并行），32测量＋32复位；189.438s编译，22055.9μs含归还。prepare随机syndrome触发Z(Q011)，final真实syndrome触发Z(Q000)+X(Q000)，16码checks和XX/ZZ全+1。184条件槽中181不打光，不虚报为光脉冲。

修复/实现文件：`quantum/stabilizer.py`、`experiments/surface_qec.py`、`experiments/qec_layout.py`、`simulation/qec.py`；核心domain/state/operation_program/checkpoint/readout及工作台/recorder/viewer。辅助capture闭包不放松，空AOD交点仍查；readout目的地按实际存在的锚原子找平移，修复稀疏形状不存在左下角时误判无容量。初始均匀offset规范化为None以保证独立origin与运行态精确一致。

性能：首轮完整DAG探针stage耗时明显，被主动停止；profile发现重复序列化主导。HH消去、阶段EXIT frontier和依赖传递约简均有等价测试；DAG运行节点不重建静态图，runtime直接比较不可变节点；序列化精确builtin快路径与仅不可变字符串sort-key缓存保留旧JSON逐字结果。没有删除物理验证。单stage cProfile观测25.8→7.1s（阶段优化不同且含profile开销），不当作整个compiler加速比。

## 本轮验证

- `python -m pytest tests/test_stabilizer_quantum.py tests/test_surface_qec_protocol.py -q`：74 PASS，含54单data错误、12种随机制备seed、HH/依赖可达等价、删check/恢复负例。
- core agent readout/batch/runtime_prefix/foundations/cz_prediction/M3：109 PASS；最后直接DAG相等优化后30项专项PASS，存在交叉不相加；详见[核心日志](2026-09-12-quantum-readout-core.md)。
- 工作台/QEC/旧patch输入专项44 PASS；真实JS handler测试故障增删、条件/依赖保留，旧large controls通过。
- root `tests/test_serializer_equivalence.py tests/test_qec_runner.py tests/test_qec_geometry.py`：5 PASS，含稀疏16辅助MZ往返、隔行4辅助捕获、16旁观辅助下真实9对CZ、H/MEASURE/RESET/条件执行和checkpoint与compiler-free replay。
- `examples/accept_qec_browser.py`：真实headless Edge手工编辑+编译一次，物理/关键帧32×各28.766/26.765s到终态；中途测量结果无预读、false条件不亮光、无页面异常，`changed_during_run=false`。
- `examples/verify_surface_qec.py artifacts/workbench-surface-qec/55831b7d3be24c56ada3cd4958460db2`：93plan纯Executor重放PASS，checkpoint逐字相同，481效果exactly once，所有原始SLM终态恢复；中间XX/ZZ=-1/-1，纠正后+1/+1。verification.json同步保存到正式browser目录。
- 未跑整个仓库所有测试，未重新生成历史schema18产物。当前schema19拒绝旧checkpoint，旧HTML仍可看、input可重编译。

## 产物与下一步

完整产物 `artifacts/surface-qec-ghz2/browser/`（输入、HTML、recording、trace、checkpoint、qec_result、verification、browser-acceptance及截图），worker原始目录 `artifacts/workbench-surface-qec/55831b7d3be24c56ada3cd4958460db2/`。旧8769及旧36data实验保持；新GUI编辑流程不覆盖用户门表。根目录旧input/progress是被停止的早期性能探针，正式成绩只看browser目录。

未完成：通用噪声/泄漏/测量错误、重复时域decoder、四逻辑带纠错GHZ、最优调度。下一可执行任务：固定此正确协议，评估辅助附带捕获后集中MZ读出与减少51轮装卸；在错误模型和decoder明确后再加连续纠错及四逻辑。单次理想测量纠正不得宣称全电路噪声容错。
