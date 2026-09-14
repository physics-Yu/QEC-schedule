# 两逻辑位的受限时域纠错协议

2026-09-12，第四步4B。新增实现 `experiments/surface_qec_temporal.py`，复用已经验证的两patch制备及逐check抽取构造，未修改旧 `surface_qec.py`。本协议是明确限制的单事件模型，不是完整电路级容错或任意多错误译码。

## 物理门序列

34原子保持18data＋16专用ancilla：先执行旧协议的实际prepare抽取与反馈，制备逻辑|+⟩、|0⟩；再执行9对transversal CNOT，得到两逻辑GHZ。随后为round1、round2、round3、closing四轮完整X/Z稳定子抽取，最后执行静态经典条件纠正。

每轮16个MEASURE及16个RESET，连同prepare共 **80 MEASURE＋80 RESET**；全部轮实际执行的 **249 CZ** 包括prepare的48、四轮的192、逻辑CNOT的9。默认优化线路916槽，含331H、88X、88Z；X/Z中包含不成立时仍占1μs控制槽的候选条件纠正。单数据注入另有一个真实1μs Pauli门。理想报告位翻转是某个实际MEASURE的`readout_flip=true`，不会删掉光照、运输或量子投影。

每个轮入口是完整上一阶段退出的全局DAG屏障；选择的数据故障先等待所有前序阶段结束，接下来整个抽取轮等待该门。closing不允许声明故障，其运输、测量和复位仍属于真实物理成本，不是免费的经典真值检查。

## 支持的单事件集合

`fault=None`为无错误；否则只接受下列一个事件：

```
{"kind":"data", "round":1|2|3, "pauli":"X"|"Y"|"Z", "qubit_id":"Q000"..."Q017"}
{"kind":"readout", "round":1|2|3, "patch":0|1, "check_type":"X"|"Z", "check_index":0..3}
```

162个数据事件、48个报告位事件、1个无错误，共211个声明案例。相同稳定子作用的退化错误产生重复历史，去重后是187个支持的全局历史。制备、逻辑门、各抽取门、运输、RESET和closing保持理想；不包含门内hook故障、持续多轮随机噪声、损失、加热或任意多个独立事件。

报告位翻转只改变经典报告，量子态按真实投影结果坍缩；RESET作用于真实量子态。译码与条件控制使用报告位，不读取量子真值、故障参数或注入门ID。

## 全局64位检查与稀疏CSS反馈

`ROUNDS=('round1','round2','round3','closing')`。
`HISTORY_IDS`按round→check_type(X/Z)→patch→check_index排列64个ID，例如 `round2_X0_0`。prepare的16个随机制备结果不属于这64位。

固定支持集合由211个事件的Pauli/check反对易关系预先产生，所有输入共享同一集合，不按当前选定故障临时生成。先验证整个64位报告历史属于这一个联合集合，避免把两个分别合法的CSS局部历史误当作一个合法全局事件。缺少位报 `INCOMPLETE_SYNDROME_HISTORY`，非严格整数0/1报 `INVALID_SYNDROME_HISTORY`，完整但未支持报 **UNSUPPORTED_SYNDROME_HISTORY**。

每个patch、每种CSS分量使用四轮×四check的16位稀疏历史表；每个实际条件X/Z门检查恰好16个相等条件，门ID以 `TEMP_CORR_` 开头。全零和纯报告翻转等无需数据纠正的历史也显式属于支持集合，但不生成多余光门。`validate_history`只接收报告位，`decode`返回同一表给出的纠正。

在这个“最多一个事件＋末轮完全正确”的限定下，数据纠正的Pauli代表可由closing符号决定；前三轮用于核对报告历史的事件类型与时序是否属于支持集合。这不是通用最小权匹配译码，也不声称由此得到噪声阈值或对任意多事件的检测保证。多个故障若产生与受支持事件相同的历史，单靠历史不能鉴别；明确拒绝的是支持集合之外的历史。

root runner在64位全部提交后、以及任何 `TEMP_CORR_` 即将执行时调用全局检查，不能只执行四张独立CSS表。支持短线路编辑；若删去完整协议部分，摘要应显示history/protocol incomplete，不能因几何编译成功就宣称已完成此协议。

## API与显示

- `protocol(fault=None, optimize=True, reduce_edges=True)`：实际gates及readouts、stages、round_boundaries、noisy_rounds、closing_round、history_ids、noise_event等显示元数据。
- `experiment_input(fault=None, compiler='qec_temporal')`：可编辑输入。噪声元数据放在qec_protocol，不复用旧qec_fault字段；实际行为完全取决于门表。
- `validate_history(reported_bits)`：成功返回supported、history_bits、corrections；`decode(bits)`只返回纠正列表。
- `simulate_ideal(gates=None, seed=0, fault=None)`：执行实际静态线路、投影、RESET和条件，返回量子态与摘要；使用与物理core一致的一目标一RNG bit规则。
- `summarize(state)`：从真实trace收集applied条件纠正与真值投影，从state读取reported测量。corrections表示实际执行；decoded_corrections是译码建议，两者不混淆。

摘要包含true_measurement_results、reported_measurement_results、history_complete、history_supported、各轮完整性、measurement_protocol_complete、16个码稳定子、logical_xx/logical_zz和verified_logical_ghz2。真值来自trace的measurement_true_results；无翻转操作的真值等于报告。显示用真值不能进入译码。

## 验证范围

专项文件 `tests/test_surface_qec_temporal.py` 逐一执行211个真实理想量子线路，并用独立symplectic反对易公式核对每个真实/报告测量位；验证实际纠正、16码稳定子、逻辑XX/ZZ和ancilla复位。其他测试覆盖固定全局表、局部合法但全局非法的双事件历史、实际双报告翻转停止、轮入口全局依赖、80读出/RESET与249CZ、原始/优化门表等价及模型边界。

2026-09-12 首轮专项执行 `C:/python312/python.exe -m pytest tests/test_surface_qec_temporal.py -q --disable-warnings --maxfail=1`：**222 passed in 82.62s**。其中211个参数案例全部通过，没有物理协议失败或失败后重试。此结果是协议量子与边界验收，不计作完整运输编译或浏览器验收。

本文件不提供完整物理运行成绩。完整代表例须在量子与核心测试完成且源码冻结后，由主任务单独执行真实编译、独立重放与编辑动画验收；4C四patch尚未实施。
